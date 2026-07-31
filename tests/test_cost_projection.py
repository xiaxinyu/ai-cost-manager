"""Tests for Cost projection calculator (unit rates × daily tokens)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import create_user
from app.cost_projection import project_daily_cost
from app.db import init_db
from app.main import create_app


def _create_admin(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        init_db(conn)
        create_user(conn, username="admin", password="admin12345", is_active=True)
    finally:
        conn.close()


def test_project_daily_cost_horizons() -> None:
    # Market-style: in 1.75 / out 14.00 · 2M in + 200k out per day
    proj = project_daily_cost(
        rate_in_per_1m=1.75,
        rate_out_per_1m=14.0,
        input_tokens_per_day=2_000_000,
        output_tokens_per_day=200_000,
    )
    assert proj is not None
    assert proj["day_input"] == 3.5  # 2 * 1.75
    assert proj["day_output"] == 2.8  # 0.2 * 14
    assert proj["day"] == 6.3
    assert proj["days_7"] == 44.1
    assert proj["days_30"] == 189.0
    assert proj["days_365"] == 2299.5


def test_project_daily_cost_opex_effective_example() -> None:
    # OpEx effective deepseek-like: 0.50 / 2.82
    proj = project_daily_cost(
        rate_in_per_1m=0.5,
        rate_out_per_1m=2.82,
        input_tokens_per_day=1_000_000,
        output_tokens_per_day=100_000,
    )
    assert proj is not None
    assert proj["day"] == 0.78  # 0.5 + 0.282 → rounded
    assert proj["days_30"] == 23.46  # unrounded daily × 30, then round


def test_project_daily_cost_requires_inputs() -> None:
    assert (
        project_daily_cost(
            rate_in_per_1m=None,
            rate_out_per_1m=None,
            input_tokens_per_day=1_000_000,
            output_tokens_per_day=1,
        )
        is None
    )
    assert (
        project_daily_cost(
            rate_in_per_1m=1.0,
            rate_out_per_1m=2.0,
            input_tokens_per_day=0,
            output_tokens_per_day=0,
        )
        is None
    )


def test_project_daily_cost_team_size_scales() -> None:
    one = project_daily_cost(
        rate_in_per_1m=1.0,
        rate_out_per_1m=2.0,
        input_tokens_per_day=1_000_000,
        output_tokens_per_day=500_000,
        team_size=1,
    )
    five = project_daily_cost(
        rate_in_per_1m=1.0,
        rate_out_per_1m=2.0,
        input_tokens_per_day=1_000_000,
        output_tokens_per_day=500_000,
        team_size=5,
    )
    assert one is not None and five is not None
    assert one["day"] == 2.0  # 1 + 1
    assert five["day"] == 10.0
    assert five["days_30"] == 300.0
    assert five["team_size"] == 5


def test_estimate_page_ui_and_nav(tmp_path: Path) -> None:
    bills_dir = tmp_path / "bills"
    bills_dir.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "cost_mgmt.sqlite3"
    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)
    _create_admin(str(db_path))
    login = client.post("/auth/login", data={"username": "admin", "password": "admin12345"})
    assert login.status_code in {200, 303}

    page = client.get("/estimate")
    assert page.status_code == 200
    assert "Estimate" in page.text
    assert 'id="estimateForm"' in page.text
    assert 'id="projModelSelect"' in page.text
    assert 'id="projTeamSizeSelect"' in page.text
    assert 'id="projTeamSizeCustom"' in page.text
    assert 'id="projRateSource"' not in page.text
    assert 'id="projRateIn"' not in page.text
    assert 'id="projRateOut"' not in page.text
    assert 'id="projInputTokens"' in page.text
    assert 'id="projOutputTokens"' in page.text
    assert ">1 person<" in page.text
    assert ">3 people<" in page.text
    assert ">5 people<" in page.text
    assert ">10 people<" in page.text
    assert "Custom…" in page.text
    assert 'id="estimateMarketRates"' in page.text
    assert 'id="estimateOpexRates"' in page.text
    assert 'id="estimateKpiDayMarket"' in page.text
    assert 'id="estimateKpiDayOpex"' in page.text
    assert 'id="reportCostProjectionTable"' in page.text
    assert "cost-projection.js" in page.text
    assert "/static/js/pages/estimate.js" in page.text
    assert "365 days" in page.text
    assert "Δ OpEx−Market" in page.text
    assert 'href="/estimate"' in page.text

    reports = client.get("/reports")
    assert reports.status_code == 200
    assert 'id="reportOpenEstimateLink"' in reports.text
    assert 'href="/estimate"' in reports.text
    assert "cost-projection.js" not in reports.text

    asset = client.get("/static/js/cost-projection.js")
    assert asset.status_code == 200
    assert "projectDailyCost" in asset.text
    assert "days_365" in asset.text


def test_estimate_page_requires_login(tmp_path: Path) -> None:
    bills_dir = tmp_path / "bills"
    bills_dir.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "cost_mgmt.sqlite3"
    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)
    res = client.get("/estimate", follow_redirects=False)
    assert res.status_code in {302, 303, 307}
    assert "/login" in (res.headers.get("location") or "")
