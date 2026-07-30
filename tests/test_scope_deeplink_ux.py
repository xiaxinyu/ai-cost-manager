"""Template contracts for Cost ↔ Tokens scope deep-links and UX affordances."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import create_user
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


def test_cost_tokens_reports_scope_deeplink_contracts(tmp_path: Path) -> None:
    bills_dir = tmp_path / "bills"
    bills_dir.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "cost_mgmt.sqlite3"
    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)
    _create_admin(str(db_path))
    login = client.post("/auth/login", data={"username": "admin", "password": "admin12345"})
    assert login.status_code in {200, 303}

    cost = client.get("/")
    assert cost.status_code == 200
    assert "scope-url.js" in cost.text
    assert 'id="openInTokensLink"' in cost.text
    assert 'id="exportScopeBtn"' in cost.text
    assert 'id="runRateProjection"' in cost.text
    assert 'id="costSelectionHint"' in cost.text
    assert "Negative variance = OpEx below list" in cost.text
    assert "Month at run-rate" in cost.text
    assert "clearDashboardSelection" in cost.text
    assert "AppScopeUrl" in cost.text
    assert "tokensHrefForModel" in cost.text
    assert "applyCostDaySelection" in cost.text

    tokens = client.get("/tokens")
    assert tokens.status_code == 200
    assert "scope-url.js" in tokens.text
    assert 'id="openInCostLink"' in tokens.text
    assert 'id="outInRatioKpi"' in tokens.text
    assert 'id="costPer1kRequestsKpi"' in tokens.text
    assert 'id="tokenSelectionHint"' in tokens.text
    assert "Open in Cost" in tokens.text
    assert "Import token CSVs" in tokens.text

    reports = client.get("/reports")
    assert reports.status_code == 200
    assert "Negative variance = OpEx below list" in reports.text
    assert "applyDailyChartLedgerSelection" in reports.text
    assert "is-navActive" in reports.text or "bindReportJumpNavActive" in reports.text


def test_scope_url_static_asset_served(tmp_path: Path) -> None:
    bills_dir = tmp_path / "bills"
    bills_dir.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "cost_mgmt.sqlite3"
    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)
    res = client.get("/static/js/scope-url.js")
    assert res.status_code == 200
    body = res.text
    assert "AppScopeUrl" in body
    assert "replaceState" in body
    assert "subproject" in body
    assert "model" in body
