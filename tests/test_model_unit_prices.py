from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from app.auth import create_user
from app.db import get_connection, get_model_implied_usd_per_1m_analysis, init_db
from app.ingest import ingest_all
from app.main import create_app
from app.token_ingest import ingest_token_all


def _create_admin(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        init_db(conn)
        create_user(conn, username="admin", password="admin12345", is_active=True)
    finally:
        conn.close()


def test_model_implied_usd_per_1m_daily_stats(tmp_path):
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projM"
    token_dir = project_dir / "token"
    token_dir.mkdir(parents=True)

    (project_dir / "cost.csv").write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-05-01","10.0","10.0","","USD"\n'
        '"2026-05-02","30.0","30.0","","USD"\n',
        encoding="utf-8",
    )
    (token_dir / "input-tokens.csv").write_text(
        '"Time","model-a","model-b"\n'
        "2026-05-01 10:00:00,1 Mil,0\n"
        "2026-05-02 10:00:00,2 Mil,1 Mil\n",
        encoding="utf-8",
    )
    (token_dir / "output-tokens.csv").write_text(
        '"Time","model-a","model-b"\n'
        "2026-05-01 10:00:00,100 K,0\n"
        "2026-05-02 10:00:00,200 K,50 K\n",
        encoding="utf-8",
    )

    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    ingest_token_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)

    conn = get_connection(db_path)
    try:
        payload = get_model_implied_usd_per_1m_analysis(conn, "projM", currency="USD")
    finally:
        conn.close()

    assert payload["available"] is True
    by_name = {m["model_name"]: m for m in payload["models"]}
    assert "model-a" in by_name and "model-b" in by_name

    # Day1: cost 10, model-a 1M in + 100K out (only model with tokens) => $10 / 1.1M tokens
    a_day1 = next(d for d in by_name["model-a"]["daily"] if d["date"] == "2026-05-01")
    expected_blended_d1 = 10.0 / 1_100_000 * 1_000_000
    assert abs(a_day1["usd_per_1m_blended"] - expected_blended_d1) < 1e-6
    assert abs(a_day1["usd_per_1m_input"] - expected_blended_d1) < 1e-6
    assert abs(a_day1["usd_per_1m_output"] - expected_blended_d1) < 1e-6

    # Day2: cost 30, model-a 2.2M tokens, model-b 1.05M tokens
    a_day2 = next(d for d in by_name["model-a"]["daily"] if d["date"] == "2026-05-02")
    b_day2 = next(d for d in by_name["model-b"]["daily"] if d["date"] == "2026-05-02")
    a_alloc_d2 = 30.0 * (2_200_000 / 3_250_000)
    b_alloc_d2 = 30.0 * (1_050_000 / 3_250_000)
    assert abs(a_day2["cost_usd_allocated"] - a_alloc_d2) < 1e-4
    assert abs(b_day2["cost_usd_allocated"] - b_alloc_d2) < 1e-4
    assert abs(a_day2["usd_per_1m_blended"] - (a_alloc_d2 / 2_200_000 * 1_000_000)) < 1e-6

    st_a = by_name["model-a"]["stats"]["blended"]
    assert st_a["count"] == 2
    assert st_a["min"] == min(expected_blended_d1, a_day2["usd_per_1m_blended"])
    assert st_a["max"] == max(expected_blended_d1, a_day2["usd_per_1m_blended"])
    assert abs(st_a["mean"] - (expected_blended_d1 + a_day2["usd_per_1m_blended"]) / 2) < 1e-6
    assert abs(st_a["median"] - (expected_blended_d1 + a_day2["usd_per_1m_blended"]) / 2) < 1e-6


def test_model_unit_prices_api(tmp_path):
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projM"
    token_dir = project_dir / "token"
    token_dir.mkdir(parents=True)
    (project_dir / "cost.csv").write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-05-01","5.0","5.0","","USD"\n',
        encoding="utf-8",
    )
    (token_dir / "input-tokens.csv").write_text(
        '"Time","gpt-x"\n2026-05-01 10:00:00,1 Mil\n',
        encoding="utf-8",
    )
    (token_dir / "output-tokens.csv").write_text(
        '"Time","gpt-x"\n2026-05-01 10:00:00,50 K\n',
        encoding="utf-8",
    )

    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    ingest_token_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)

    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)
    _create_admin(str(db_path))
    client.post("/auth/login", data={"username": "admin", "password": "admin12345"})

    res = client.get("/api/projects/projM/model-unit-prices?currency=USD")
    assert res.status_code == 200
    data = res.json()
    assert data["available"] is True
    assert len(data["models"]) == 1
    assert data["models"][0]["stats"]["blended"]["count"] == 1

    page = client.get("/")
    assert page.status_code == 200
    assert "modelUnitPriceSection" in page.text
