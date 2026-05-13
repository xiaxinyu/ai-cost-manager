from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth import create_user
from app.ingest import ingest_all
from app.main import create_app
from app.db import upsert_project_model_config


def test_api_project_flow(tmp_path):
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projB"
    project_dir.mkdir(parents=True, exist_ok=True)

    csv_path = project_dir / "2026-Mar-1.csv"
    csv_path.write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-03-01","1.0","1.0","","USD"\n'
        '"2026-03-02","","","0.5","USD"\n',
        encoding="utf-8",
    )

    db_path = tmp_path / "cost_mgmt.sqlite3"

    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)

    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)

    # Create admin user and login (API is protected).
    # Create admin in DB (use a separate connection in tests).
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        create_user(conn, username="admin", password="admin12345", is_active=True)
    finally:
        conn.close()

    res = client.post("/auth/login", data={"username": "admin", "password": "admin12345"})
    assert res.status_code in {200, 303}

    res = client.get("/api/projects")
    assert res.status_code == 200
    data = res.json()
    assert data["projects"] == ["projB"]

    res = client.get("/api/projects/projB/stats")
    assert res.status_code == 200
    stats = res.json()
    assert stats["project"] == "projB"
    assert stats["currency"] == "USD"
    assert stats["actual_cost_usd_total"] == 1.0
    assert stats["actual_days"] == 1

    res = client.get("/api/projects/projB/timeseries?granularity=day")
    assert res.status_code == 200
    ts = res.json()
    assert ts["project"] == "projB"
    assert ts["currency"] == "USD"
    assert len(ts["points"]) == 2
    assert ts["points"][0]["date"] == "2026-03-01"
    assert ts["points"][0]["cost_usd"] == 1.0

    res = client.get("/api/projects/projB/forecast-baseline?window_days=28")
    assert res.status_code == 200
    fb = res.json()
    assert fb["ok"] is True
    assert fb["project"] == "projB"
    assert fb["window_days"] == 28
    assert fb["currency"] == "USD"
    assert fb["baseline_usd_per_day"] > 0
    assert "notes_zh" in fb
    assert "team_model" in fb

    res = client.get("/api/projects/projB/rows?page=1&page_size=10")
    assert res.status_code == 200
    rows = res.json()
    assert rows["total"] == 2
    assert rows["rows"][0]["usage_date"] == "2026-03-02"

    # Full/complex mode: show all CSV fields from `raw_json`.
    res_full = client.get("/api/projects/projB/rows?page=1&page_size=10&mode=full")
    assert res_full.status_code == 200
    data_full = res_full.json()
    assert data_full["mode"] == "full"
    assert "UsageDate" in data_full["columns"]
    assert "CostUSD" in data_full["columns"]
    assert len(data_full["rows"]) == 2
    assert data_full["rows"][0]["fields"]["UsageDate"] == "2026-03-02"

    latest = client.get("/api/projects/latest").json()
    assert latest["project_name"] == "projB"


def test_api_token_timeseries_and_rows_estimated_tokens(tmp_path):
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projToken"
    project_dir.mkdir(parents=True, exist_ok=True)

    csv_path = project_dir / "2026-Apr.csv"
    csv_path.write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-04-01","1.0","1.0","","USD"\n'
        '"2026-04-02","2.0","2.0","","USD"\n',
        encoding="utf-8",
    )

    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)

    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)

    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        create_user(conn, username="admin", password="admin12345", is_active=True)
        upsert_project_model_config(
            conn,
            project_name="projToken",
            model_name="GPT-5.3 Codex",
            api_version=None,
            azure_endpoint=None,
        )
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
                "input",
                2.0,
                1_000_000,
                "tokens",
                "USD/1M tokens",
                None,
                None,
            ),
        )
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
                "output",
                4.0,
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

    res = client.post("/auth/login", data={"username": "admin", "password": "admin12345"})
    assert res.status_code in {200, 303}

    ts = client.get("/api/projects/projToken/token-timeseries?start_date=2026-04-01&end_date=2026-04-01")
    assert ts.status_code == 200
    payload = ts.json()
    assert payload["token_estimate_model"] == "GPT-5.3 Codex"
    assert len(payload["points"]) == 1
    p0 = payload["points"][0]
    assert p0["date"] == "2026-04-01"
    assert p0["cost_usd"] == 1.0
    assert p0["estimated_input_tokens"] == 500000.0
    assert p0["estimated_output_tokens"] == 250000.0
    assert p0["estimated_total_tokens"] == 750000.0

    stats = client.get("/api/projects/projToken/stats?currency=USD")
    assert stats.status_code == 200
    stats_data = stats.json()
    assert stats_data["estimated_input_tokens"] == 1500000.0
    assert stats_data["estimated_output_tokens"] == 750000.0
    assert stats_data["estimated_total_tokens"] == 2250000.0

    rows = client.get("/api/projects/projToken/rows?page=1&page_size=10&mode=simple")
    assert rows.status_code == 200
    rows_data = rows.json()
    assert rows_data["rows"][0]["usage_date"] == "2026-04-02"
    assert rows_data["rows"][0]["estimated_total_tokens"] == 1500000.0
