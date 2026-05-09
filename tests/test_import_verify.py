from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from app.auth import create_user
from app.db import init_db
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


def _login(client: TestClient) -> None:
    res = client.post("/auth/login", data={"username": "admin", "password": "admin12345"})
    assert res.status_code in {200, 303}


def test_verify_ingested_files_ok(tmp_path):
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projA"
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
    _create_admin(str(db_path))
    _login(client)

    res = client.get(
        "/api/import/verify-ingested-files",
        params={"file_path_rels": ["projA/2026-Mar-1.csv"]},
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["ok"] is True
    assert payload["pass_count"] == 1
    assert payload["fail_count"] == 0


def test_verify_ingested_files_detects_modified_csv(tmp_path):
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projA"
    project_dir.mkdir(parents=True, exist_ok=True)

    csv_path = project_dir / "2026-Mar-1.csv"
    csv_path.write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-03-01","1.0","1.0","","USD"\n',
        encoding="utf-8",
    )

    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)

    # Modify CSV content after ingest.
    csv_path.write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-03-01","2.0","2.0","","USD"\n',
        encoding="utf-8",
    )

    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)
    _create_admin(str(db_path))
    _login(client)

    res = client.get(
        "/api/import/verify-ingested-files",
        params={"file_path_rels": ["projA/2026-Mar-1.csv"]},
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["ok"] is False
    assert payload["fail_count"] == 1

