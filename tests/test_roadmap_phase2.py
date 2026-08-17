"""Phase 2/3 roadmap API contracts: budget, tags, anomalies, allocation stubs."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import create_user
from app.db import (
    init_db,
    set_subproject_tag,
    upsert_project_monthly_budget,
)
from app.main import create_app


def _admin_client(tmp_path: Path) -> tuple[TestClient, Path]:
    bills_dir = tmp_path / "bills"
    bills_dir.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "cost_mgmt.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        init_db(conn)
        create_user(conn, username="admin", password="admin12345", is_active=True)
        conn.execute("INSERT OR IGNORE INTO projects(name) VALUES ('demo')")
        for i, (d, cost) in enumerate([
            ("2024-02-01", 10.0),
            ("2024-02-02", 12.0),
            ("2024-02-03", 9.0),
            ("2024-02-04", 11.0),
            ("2024-02-05", 10.5),
            ("2024-02-06", 9.5),
            ("2024-02-07", 11.5),
            ("2024-02-08", 200.0),  # strong outlier > 2σ
        ]):
            conn.execute(
                """
                INSERT INTO transactions(
                  project_name, usage_date, cost_usd, cost, currency, raw_json,
                  source_file, source_row_index
                ) VALUES ('demo', ?, ?, ?, 'USD', '{}', ?, ?)
                """,
                (d, cost, cost, "/tmp/demo/bill.csv", i),
            )
        upsert_project_monthly_budget(conn, "demo", "202402", 50.0)
        set_subproject_tag(
            conn, project_name="demo", subproject_name="team-a", tag="growth"
        )
        conn.commit()
    finally:
        conn.close()
    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)
    login = client.post("/auth/login", data={"username": "admin", "password": "admin12345"})
    assert login.status_code in {200, 303}
    return client, db_path


def test_budget_and_anomaly_and_tags(tmp_path: Path) -> None:
    client, db_path = _admin_client(tmp_path)
    stats = client.get(
        "/api/projects/demo/stats",
        params={"from_date": "2024-02-01", "to_date": "2024-02-08"},
    )
    assert stats.status_code == 200
    body = stats.json()
    assert body["budget_usd"] == 50.0
    assert body["budget_yyyymm"] == "202402"

    budget = client.get("/api/projects/demo/budget", params={"yyyymm": "202402"})
    assert budget.status_code == 200
    assert budget.json()["budget_usd"] == 50.0
    assert budget.json()["editable"] is False

    anomalies = client.get(
        "/api/projects/demo/anomalies",
        params={"start_date": "2024-02-01", "end_date": "2024-02-08", "detect": True},
    )
    assert anomalies.status_code == 200
    payload = anomalies.json()
    events = payload["events"] or payload["detected_now"]
    assert any(e["usage_date"] == "2024-02-08" for e in events)

    tags = client.get("/api/tags", params={"project": "demo"})
    assert tags.status_code == 200
    assert any(t["tag"] == "growth" for t in tags.json()["tags"])

    by_user = client.get("/api/reports/allocation-by-user")
    assert by_user.status_code == 200
    assert by_user.json()["available"] is False
    assert by_user.json()["reason"] == "missing_fields"


def test_phase2_ui_contracts(tmp_path: Path) -> None:
    client, _ = _admin_client(tmp_path)
    cost = client.get("/")
    assert 'id="costBudgetProgress"' in cost.text
    assert 'id="costModelViewBarBtn"' in cost.text
    assert 'id="costModelBarChart"' in cost.text

    tokens = client.get("/tokens")
    assert 'id="tokenDataAsOf"' in tokens.text
    assert "performance/" in tokens.text
    assert "Native charts" in tokens.text

    reports = client.get("/reports")
    assert 'id="reportAllocTabUser"' in reports.text
    assert 'id="reportAllocTabDept"' in reports.text
    assert 'id="reportAllocTabTag"' in reports.text
    assert 'id="verifyResult"' in reports.text

    estimate = client.get("/estimate")
    assert "estimateNav" in estimate.text
