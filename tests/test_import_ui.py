from __future__ import annotations

from fastapi.testclient import TestClient

import sqlite3

from app.auth import create_user
from app.db import init_db
from app.main import create_app


def _create_admin(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        init_db(conn)
        create_user(conn, username="admin", password="admin12345", is_active=True)
    finally:
        conn.close()


def test_import_missing_files_flow(tmp_path):
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projC"
    project_dir.mkdir(parents=True, exist_ok=True)

    csv_path = project_dir / "2026-Mar-1.csv"
    csv_path.write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-03-01","1.0","1.0","","USD"\n'
        '"2026-03-02","","","0.5","USD"\n',
        encoding="utf-8",
    )

    db_path = tmp_path / "cost_mgmt.sqlite3"

    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)

    _create_admin(str(db_path))

    res = client.post("/auth/login", data={"username": "admin", "password": "admin12345"})
    assert res.status_code in {200, 303}

    res = client.get("/api/import/missing-files")
    assert res.status_code == 200
    data = res.json()
    assert data["missing_count"] == 1
    assert data["missing_files"][0]["file_path_rel"] == "projC/2026-Mar-1.csv"

    res = client.post("/api/import/run", json={"reimport_changed": False})
    assert res.status_code == 200
    run_data = res.json()
    assert run_data["files_ingested"] == 1
    assert run_data["rows_ingested"] == 2

    res = client.get("/api/import/missing-files")
    assert res.status_code == 200
    data2 = res.json()
    assert data2["missing_count"] == 0

    res = client.get("/api/projects")
    assert res.status_code == 200
    assert res.json()["projects"] == ["projC"]

    res = client.get("/api/projects/projC/stats")
    assert res.status_code == 200
    stats = res.json()
    assert stats["actual_cost_usd_total"] == 1.0


def test_import_selected_files_flow(tmp_path):
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projC"
    project_dir.mkdir(parents=True, exist_ok=True)

    csv_path_a = project_dir / "2026-a.csv"
    csv_path_a.write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-03-01","1.0","1.0","","USD"\n',
        encoding="utf-8",
    )

    csv_path_b = project_dir / "2026-b.csv"
    csv_path_b.write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-03-02","2.0","2.0","","USD"\n',
        encoding="utf-8",
    )

    db_path = tmp_path / "cost_mgmt.sqlite3"

    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)

    _create_admin(str(db_path))

    res = client.post("/auth/login", data={"username": "admin", "password": "admin12345"})
    assert res.status_code in {200, 303}

    res = client.get("/api/import/missing-files")
    assert res.status_code == 200
    data = res.json()
    assert data["missing_count"] == 2

    # Import only A.
    res = client.post(
        "/api/import/run",
        json={"reimport_changed": False, "file_path_rels": ["projC/2026-a.csv"]},
    )
    assert res.status_code == 200
    run_data = res.json()
    assert run_data["files_ingested"] == 1
    assert run_data["rows_ingested"] == 1

    res = client.get("/api/import/missing-files")
    assert res.status_code == 200
    data2 = res.json()
    assert data2["missing_count"] == 1
    assert data2["missing_files"][0]["file_path_rel"] == "projC/2026-b.csv"

    # Stats reflect only A (cost_usd=1.0)
    res = client.get("/api/projects/projC/stats")
    assert res.status_code == 200
    stats = res.json()
    assert stats["actual_cost_usd_total"] == 1.0

