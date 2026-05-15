from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth import create_user
from app.db import get_connection, init_db, list_projects_with_imported_tokens
from app.main import create_app
from app.token_ingest import ingest_token_all


def _create_admin(db_path: str) -> None:
    conn = get_connection(db_path)
    try:
        init_db(conn)
        create_user(conn, username="admin", password="admin12345", is_active=True)
    finally:
        conn.close()


def _write_token_csvs(bills_dir, project: str) -> None:
    token_dir = bills_dir / project / "token"
    token_dir.mkdir(parents=True, exist_ok=True)
    (token_dir / "input-tokens.csv").write_text(
        '"Time","gpt-5.3-codex"\n2026-05-07 10:37:00,1 Mil\n',
        encoding="utf-8",
    )
    (token_dir / "output-tokens.csv").write_text(
        '"Time","gpt-5.3-codex"\n2026-05-07 10:37:00,100 K\n',
        encoding="utf-8",
    )


def test_projects_api_lists_token_capable_projects(tmp_path):
    bills_dir = tmp_path / "bills"
    _write_token_csvs(bills_dir, "rg-techlab-ai-coding")
    (bills_dir / "techlab-aiops-gpt5.1").mkdir(parents=True)
    (bills_dir / "techlab-aiops-gpt5.1" / "cost.csv").write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-05-07","5.0","5.0","","USD"\n',
        encoding="utf-8",
    )

    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_token_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)

    conn = get_connection(db_path)
    try:
        token_projects = list_projects_with_imported_tokens(conn)
    finally:
        conn.close()
    assert token_projects == ["rg-techlab-ai-coding"]

    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)
    _create_admin(str(db_path))
    client.post("/auth/login", data={"username": "admin", "password": "admin12345"})

    projects = client.get("/api/projects").json()
    assert "rg-techlab-ai-coding" in projects["projects"]
    assert projects["projects_with_imported_tokens"] == ["rg-techlab-ai-coding"]

    latest_token = client.get("/api/projects/latest-token").json()
    assert latest_token["project_name"] == "rg-techlab-ai-coding"

    no_tokens = client.get("/api/projects/techlab-aiops-gpt5.1/token-timeseries").json()
    assert no_tokens["token_data_source"] == "estimated"
    assert no_tokens["points"] == []

    with_tokens = client.get("/api/projects/rg-techlab-ai-coding/token-timeseries").json()
    assert with_tokens["token_data_source"] == "imported"
    assert with_tokens["points"][0]["estimated_input_tokens"] == 1_000_000.0
