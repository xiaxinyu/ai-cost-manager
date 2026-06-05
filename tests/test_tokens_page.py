from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from app.auth import create_user
from app.db import init_db, upsert_project_model_config
from app.ingest import ingest_all
from app.main import create_app


def _create_admin(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        init_db(conn)
        create_user(conn, username="admin", password="admin12345", is_active=True)
    finally:
        conn.close()


def _add_token_price_model(db_path: str, project_name: str = "projToken") -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        upsert_project_model_config(
            conn,
            project_name=project_name,
            model_name="GPT-5.3 Codex",
            api_version=None,
            azure_endpoint=None,
        )
        for metric_name, amount in (("input", 2.0), ("output", 4.0)):
            conn.execute(
                """
                INSERT INTO model_prices(
                    source_id, source_url, effective_date, retrieved_at_utc,
                    vendor, platform, price_region, price_currency,
                    model_series, model_name, context_bucket, deployment_scope,
                    billing_mode, metric_name, amount,
                    unit_quantity, unit_name, unit_expression, notes, source_detail_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "src",
                    "https://example.com",
                    "2026-04-01",
                    "2026-04-01T00:00:00Z",
                    "Microsoft",
                    "azure-openai",
                    "East US",
                    "USD",
                    "GPT-5.3",
                    "GPT-5.3 Codex",
                    None,
                    "global",
                    "standard",
                    metric_name,
                    amount,
                    1_000_000,
                    "tokens",
                    "USD/1M tokens",
                    None,
                    None,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def test_tokens_page_redirect_and_access(tmp_path):
    bills_dir = tmp_path / "bills"
    bills_dir.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "cost_mgmt.sqlite3"

    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)

    res = client.get("/tokens", follow_redirects=False)
    assert res.status_code in {302, 303, 307}
    assert "/login" in (res.headers.get("location") or "")

    _create_admin(str(db_path))
    login = client.post("/auth/login", data={"username": "admin", "password": "admin12345"})
    assert login.status_code in {200, 303}

    page = client.get("/tokens")
    assert page.status_code == 200
    assert "Token Operations" in page.text
    assert "noImportHint" in page.text
    assert 'id="tokenStartDateInput"' in page.text
    assert 'id="dailyPageSizeSelect"' in page.text
    assert 'id="dailyPrevBtn"' in page.text
    assert 'id="dataStatusBar"' in page.text
    assert 'id="tableRowBadge"' in page.text
    assert "/static/js/money.js" in page.text
    assert "/static/js/pages/tokens.js" in page.text
    assert "tokenAnalysisFlow" in page.text
    assert "flowBlock" in page.text
    assert "filterCard" in page.text
    assert "date-range-picker.js" in page.text
    assert "dateRangePicker" in page.text
    assert 'src="/static/js/pages/tokens.js?v=' in page.text
    assert 'href="/tokens"' in page.text
    assert "flowStep" in page.text
    assert "costTypeLegend" in page.text


def test_login_to_token_workspace_e2e_smoke(tmp_path):
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projToken"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "2026-Apr.csv").write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-04-01","1.0","1.0","","USD"\n'
        '"2026-04-02","2.0","2.0","","USD"\n',
        encoding="utf-8",
    )

    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    _create_admin(str(db_path))
    _add_token_price_model(str(db_path))

    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)

    login = client.post("/auth/login", data={"username": "admin", "password": "admin12345"})
    assert login.status_code in {200, 303}

    for path, marker in (
        ("/", "Cost"),
        ("/tokens", "Token Operations"),
        ("/reports", "Financial Report Center"),
        ("/prices", "Model Price Viewer"),
        ("/import", "Billing &amp; Token Import"),
    ):
        page = client.get(path)
        assert page.status_code == 200
        assert marker in page.text
        assert 'href="/tokens"' in page.text

    stats = client.get("/api/projects/projToken/stats?currency=USD").json()
    assert stats["token_data_source"] == "estimated"
    assert stats["estimated_input_tokens"] == 1_500_000.0
    assert stats["estimated_output_tokens"] == 750_000.0
    assert stats["estimated_total_tokens"] == 2_250_000.0

    series = client.get("/api/projects/projToken/token-timeseries?currency=USD").json()
    assert series["token_estimate_model"] == "GPT-5.3 Codex"
    assert series["token_estimate_region"] == "East US"
    assert series["points"][0]["estimated_total_tokens"] == 750_000.0
