from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth import create_user
from app.db import init_db, get_connection
from app.main import create_app


def _create_admin(db_path: str) -> None:
    conn = get_connection(db_path)
    try:
        init_db(conn)
        create_user(conn, username="admin", password="admin12345", is_active=True)
    finally:
        conn.close()


def test_import_api_billing_and_token_together(tmp_path):
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "rg-techlab-ai-coding"
    token_dir = project_dir / "token"
    token_dir.mkdir(parents=True)

    (project_dir / "2026-May.csv").write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-05-07","10.0","10.0","","USD"\n',
        encoding="utf-8",
    )
    (token_dir / "input-tokens.csv").write_text(
        '"Time","gpt-5.3-codex"\n2026-05-07 10:37:00,1 Mil\n',
        encoding="utf-8",
    )
    (token_dir / "output-tokens.csv").write_text(
        '"Time","gpt-5.3-codex"\n2026-05-07 10:37:00,100 K\n',
        encoding="utf-8",
    )

    db_path = tmp_path / "cost_mgmt.sqlite3"
    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)
    _create_admin(str(db_path))

    login = client.post("/auth/login", data={"username": "admin", "password": "admin12345"})
    assert login.status_code in {200, 303}

    res = client.get("/api/import/missing-files")
    assert res.status_code == 200
    data = res.json()
    assert data["missing_count"] == 3
    assert data["missing_billing_count"] == 1
    assert data["missing_token_count"] == 2

    res = client.post("/api/import/run", json={"reimport_changed": False})
    assert res.status_code == 200
    run = res.json()
    assert run["verification_passed"] is True
    assert run["billing_files_ingested"] == 1
    assert run["token_files_ingested"] == 2

    stats = client.get("/api/projects/rg-techlab-ai-coding/stats").json()
    assert stats["token_data_source"] == "imported"
    assert stats["estimated_input_tokens"] == 1_000_000.0
    assert stats["estimated_output_tokens"] == 100_000.0

    series = client.get("/api/projects/rg-techlab-ai-coding/token-timeseries").json()
    assert series["token_data_source"] == "imported"
    assert series["points"][0]["estimated_input_tokens"] == 1_000_000.0
    assert len(series.get("breakdown_by_model") or []) >= 1
    daily = series.get("daily_by_model") or []
    assert len(daily) >= 1
    assert daily[0]["model_name"]
    assert daily[0]["input_tokens"] > 0
    assert series.get("import_meta", {}).get("model_count") >= 1

    report = client.get("/api/reports/all-financial?project_names=rg-techlab-ai-coding").json()
    assert report["token_data_source"] == "imported"
    assert report["token_daily_points"][0]["estimated_input_tokens"] == 1_000_000.0

    projects = client.get("/api/projects").json()
    assert "rg-techlab-ai-coding" in projects["projects_with_imported_tokens"]

    latest_token = client.get("/api/projects/latest-token").json()
    assert latest_token["project_name"] == "rg-techlab-ai-coding"
