from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.auth import create_user
from app.money import round_cost
from app.db import (
    get_connection,
    get_model_implied_usd_per_1m_analysis,
    get_project_daily_implied_usd_per_1m_timeseries,
    init_db,
)
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
    expected_blended_d1 = round_cost(10.0 / 1_100_000 * 1_000_000)
    assert a_day1["usd_per_1m_blended"] == expected_blended_d1
    assert a_day1["usd_per_1m_input"] == expected_blended_d1
    assert a_day1["usd_per_1m_output"] == expected_blended_d1

    # Day2: cost 30, model-a 2.2M tokens, model-b 1.05M tokens
    a_day2 = next(d for d in by_name["model-a"]["daily"] if d["date"] == "2026-05-02")
    b_day2 = next(d for d in by_name["model-b"]["daily"] if d["date"] == "2026-05-02")
    a_alloc_d2 = 30.0 * (2_200_000 / 3_250_000)
    b_alloc_d2 = 30.0 * (1_050_000 / 3_250_000)
    assert a_day2["cost_usd_allocated"] == round_cost(a_alloc_d2)
    assert b_day2["cost_usd_allocated"] == round_cost(b_alloc_d2)
    assert a_day2["usd_per_1m_blended"] == round_cost(a_alloc_d2 / 2_200_000 * 1_000_000)

    st_a = by_name["model-a"]["stats"]["blended"]
    assert st_a["count"] == 2
    assert st_a["min"] == min(expected_blended_d1, a_day2["usd_per_1m_blended"])
    assert st_a["max"] == max(expected_blended_d1, a_day2["usd_per_1m_blended"])
    assert st_a["mean"] == round_cost((expected_blended_d1 + a_day2["usd_per_1m_blended"]) / 2)
    assert st_a["median"] == round_cost((expected_blended_d1 + a_day2["usd_per_1m_blended"]) / 2)


def test_project_daily_implied_usd_per_1m_timeseries(tmp_path):
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
        payload = get_project_daily_implied_usd_per_1m_timeseries(conn, "projM", currency="USD")
    finally:
        conn.close()

    assert payload["available"] is True
    by_date = {p["date"]: p for p in payload["points"]}
    d1 = by_date["2026-05-01"]
    assert abs(float(d1["usd_per_1m_input"]) - 10.0) < 1e-6
    assert abs(float(d1["usd_per_1m_output"]) - 100.0) < 1e-6
    d2 = by_date["2026-05-02"]
    assert abs(float(d2["usd_per_1m_input"]) - 10.0) < 1e-6
    assert abs(float(d2["usd_per_1m_output"]) - 120.0) < 1e-6

    st_in = payload["stats"]["input"]
    assert st_in["count"] == 2
    assert abs(st_in["min"] - 10.0) < 1e-9
    assert abs(st_in["max"] - 10.0) < 1e-9
    st_out = payload["stats"]["output"]
    assert st_out["count"] == 2
    assert abs(st_out["min"] - 100.0) < 1e-6
    assert abs(st_out["max"] - 120.0) < 1e-6
    assert abs(st_out["mean"] - 110.0) < 1e-6
    assert abs(st_out["median"] - 110.0) < 1e-6


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

    res_ip = client.get("/api/projects/projM/implied-unit-prices-timeseries?currency=USD")
    assert res_ip.status_code == 200
    ip = res_ip.json()
    assert ip["available"] is True
    assert len(ip["points"]) >= 1
    assert ip["stats"]["input"]["count"] == 1

    page = client.get("/tokens")
    assert page.status_code == 200
    assert "unitPriceSection" in page.text
    assert "impliedUnitPriceInputChart" in page.text


def test_implied_timeseries_follows_token_calendar_not_full_billing(tmp_path):
    """Billing may span months; implied series stays on token days (no March-only billing)."""
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projSpan"
    token_dir = project_dir / "token"
    token_dir.mkdir(parents=True)
    (project_dir / "cost.csv").write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-03-01","1.0","1.0","","USD"\n'
        '"2026-05-01","10.0","10.0","","USD"\n'
        '"2026-05-02","20.0","20.0","","USD"\n',
        encoding="utf-8",
    )
    (token_dir / "input-tokens.csv").write_text(
        '"Time","m"\n2026-05-01 10:00:00,1 Mil\n2026-05-02 10:00:00,1 Mil\n',
        encoding="utf-8",
    )
    (token_dir / "output-tokens.csv").write_text(
        '"Time","m"\n2026-05-01 10:00:00,100 K\n2026-05-02 10:00:00,100 K\n',
        encoding="utf-8",
    )
    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    ingest_token_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    conn = get_connection(db_path)
    try:
        payload = get_project_daily_implied_usd_per_1m_timeseries(conn, "projSpan", currency="USD")
    finally:
        conn.close()
    dates = [p["date"] for p in payload["points"]]
    assert dates == ["2026-05-01", "2026-05-02"]
    assert payload["from_date"] == "2026-05-01"
    assert payload["to_date"] == "2026-05-02"
    assert "2026-03-01" not in dates


def test_implied_timeseries_extends_through_billing_tail_without_tokens(tmp_path):
    """Trailing billing days after the last token row still appear (cost, null implied $/1M)."""
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projTail"
    token_dir = project_dir / "token"
    token_dir.mkdir(parents=True)
    (project_dir / "cost.csv").write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-05-01","10.0","10.0","","USD"\n'
        '"2026-05-02","20.0","20.0","","USD"\n'
        '"2026-05-03","5.0","5.0","","USD"\n',
        encoding="utf-8",
    )
    (token_dir / "input-tokens.csv").write_text(
        '"Time","m"\n2026-05-01 10:00:00,1 Mil\n2026-05-02 10:00:00,1 Mil\n',
        encoding="utf-8",
    )
    (token_dir / "output-tokens.csv").write_text(
        '"Time","m"\n2026-05-01 10:00:00,100 K\n2026-05-02 10:00:00,100 K\n',
        encoding="utf-8",
    )
    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    ingest_token_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    conn = get_connection(db_path)
    try:
        payload = get_project_daily_implied_usd_per_1m_timeseries(conn, "projTail", currency="USD")
    finally:
        conn.close()
    dates = [p["date"] for p in payload["points"]]
    assert dates == ["2026-05-01", "2026-05-02", "2026-05-03"]
    assert payload["to_date"] == "2026-05-03"
    d3 = next(p for p in payload["points"] if p["date"] == "2026-05-03")
    assert d3["usd_per_1m_input"] is None
    assert d3["usd_per_1m_output"] is None
    assert d3["cost_usd"] is not None
