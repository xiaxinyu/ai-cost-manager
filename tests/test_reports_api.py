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


def test_all_financial_report_stats(tmp_path):
    bills_dir = tmp_path / "bills"

    # Two projects to validate "all projects" aggregation.
    p1 = bills_dir / "projA"
    p2 = bills_dir / "projB"
    p1.mkdir(parents=True, exist_ok=True)
    p2.mkdir(parents=True, exist_ok=True)

    # Day1: projA=1, projB=2 => sum=3
    # Day2: projA=3, projB missing => sum=3
    (p1 / "2026.csv").write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-01-01","1.0","1.0","","USD"\n'
        '"2026-01-02","3.0","3.0","","USD"\n',
        encoding="utf-8",
    )
    (p2 / "2026.csv").write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-01-01","2.0","2.0","","USD"\n',
        encoding="utf-8",
    )

    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)

    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)

    _create_admin(str(db_path))
    client.post("/auth/login", data={"username": "admin", "password": "admin12345"})

    res = client.get("/api/reports/all-financial?currency=USD")
    assert res.status_code == 200
    payload = res.json()
    assert payload["currency_options"]
    assert payload["currency"] == "USD"
    assert "project_breakdown" in payload
    pb = payload["project_breakdown"]
    assert isinstance(pb, list) and len(pb) == 2
    by_name = {r["project_name"]: r for r in pb}
    assert by_name["projA"]["actual_cost_usd_total"] == 4.0
    assert by_name["projB"]["actual_cost_usd_total"] == 2.0

    daily = payload["daily"]
    # daily points are summed per day, so values are [3, 3]
    assert daily["count_days"] == 2
    assert daily["total_actual"] == 6.0
    assert daily["avg_actual"] == 3.0
    assert daily["median_actual"] == 3.0
    assert daily["var_actual"] == 0.0

    monthly = payload["monthly"]
    assert monthly["count_months"] == 1
    assert monthly["avg_actual"] == 6.0 / 1.0

    # Validate project filtering (single project scope).
    res2 = client.get("/api/reports/all-financial?currency=USD&project_names=projA")
    assert res2.status_code == 200
    payload2 = res2.json()
    assert len(payload2["project_breakdown"]) == 1
    assert payload2["project_breakdown"][0]["project_name"] == "projA"
    assert payload2["project_breakdown"][0]["actual_cost_usd_total"] == 4.0
    daily2 = payload2["daily"]
    # projA has Day1=1, Day2=3 => total=4, avg=2, median=2, variance=1 (population variance)
    assert daily2["count_days"] == 2
    assert daily2["total_actual"] == 4.0
    assert daily2["avg_actual"] == 2.0
    assert daily2["median_actual"] == 2.0
    assert daily2["var_actual"] == 1.0

    # Token estimates time series (may be null when no project model config exists)
    assert "token_daily_points" in payload
    assert "token_monthly_points" in payload
    assert "token_estimate_model_display" in payload
    assert "token_estimate_region_display" in payload

    assert len(payload["token_daily_points"]) == daily["count_days"]
    assert len(payload["token_monthly_points"]) == monthly["count_months"]

    td0 = payload["token_daily_points"][0]
    assert "estimated_input_tokens" in td0
    assert "estimated_output_tokens" in td0
    assert "estimated_total_tokens" in td0
    assert all(p["estimated_total_tokens"] is None for p in payload["token_daily_points"])

    # Verify consistency between report-scoped aggregation and per-project dashboard calculations.
    ver = client.get("/api/verify/reports-all-financial-consistency?currency=USD&mode=deep")
    assert ver.status_code == 200
    ver_payload = ver.json()
    assert ver_payload["ok"] is True
    assert ver_payload["failed_count"] == 0


def test_reports_page_layout_without_token_forecast(tmp_path):
    bills_dir = tmp_path / "bills"
    bills_dir.mkdir(parents=True)
    db_path = tmp_path / "cost_mgmt.sqlite3"
    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)
    _create_admin(str(db_path))
    client.post("/auth/login", data={"username": "admin", "password": "admin12345"})

    page = client.get("/reports")
    assert page.status_code == 200
    assert "tokenForecastChart" not in page.text
    assert "Token Forecast (7d)" not in page.text
    assert "chartGrid3" in page.text
    assert "tokenReportSection" in page.text

