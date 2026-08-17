"""Period compare + data freshness API/UI contracts."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import create_user
from app.db import compute_period_compare, get_data_as_of_utc, init_db
from app.main import create_app


def _create_admin(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        init_db(conn)
        create_user(conn, username="admin", password="admin12345", is_active=True)
    finally:
        conn.close()


def _seed_billing(db_path: str, project: str = "demo") -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        init_db(conn)
        conn.execute("INSERT OR IGNORE INTO projects(name) VALUES (?)", (project,))
        # Two equal 3-day windows: prev 2024-01-01..03 cost 30; curr 2024-01-04..06 cost 60
        rows = [
            ("2024-01-01", 10.0),
            ("2024-01-02", 10.0),
            ("2024-01-03", 10.0),
            ("2024-01-04", 20.0),
            ("2024-01-05", 20.0),
            ("2024-01-06", 20.0),
        ]
        for i, (d, cost) in enumerate(rows):
            conn.execute(
                """
                INSERT INTO transactions(
                  project_name, usage_date, cost_usd, cost, currency, raw_json,
                  source_file, source_row_index
                ) VALUES (?, ?, ?, ?, 'USD', '{}', ?, ?)
                """,
                (project, d, cost, cost, f"/tmp/{project}/bill.csv", i),
            )
        conn.execute(
            """
            INSERT INTO ingested_files(
              project_name, file_path, checksum_sha256, schema_version, row_count,
              ingested_at, source_last_modified
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project,
                f"/tmp/{project}/bill.csv",
                "abc",
                1,
                6,
                "2024-01-07 12:30:00",
                1_704_628_200.0,  # ~2024-01-07
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_compute_period_compare_mom() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "t.sqlite3")
        _seed_billing(db_path)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            init_db(conn)
            cmp = compute_period_compare(
                conn,
                "demo",
                start="2024-01-04",
                end="2024-01-06",
                currency="USD",
            )
            assert cmp["prev_start"] == "2024-01-01"
            assert cmp["prev_end"] == "2024-01-03"
            assert float(cmp["actual_cost_usd_total"]) == 30.0
            assert cmp["delta_pct"] == 100.0
            assert cmp["avg_daily_delta_pct"] == 100.0
            assert cmp["mode"] == "prior_period"
            assert cmp["label"] == "上期"
            assert get_data_as_of_utc(conn, "demo") is not None
        finally:
            conn.close()


def test_compute_period_compare_prior_month() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "t.sqlite3")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            init_db(conn)
            conn.execute("INSERT OR IGNORE INTO projects(name) VALUES ('demo')")
            # Feb full month vs Jan full month
            rows = []
            for day in range(1, 32):
                rows.append((f"2024-01-{day:02d}", 10.0))
            for day in range(1, 30):
                rows.append((f"2024-02-{day:02d}", 20.0))
            for i, (d, cost) in enumerate(rows):
                conn.execute(
                    """
                    INSERT INTO transactions(
                      project_name, usage_date, cost_usd, cost, currency, raw_json,
                      source_file, source_row_index
                    ) VALUES ('demo', ?, ?, ?, 'USD', '{}', ?, ?)
                    """,
                    (d, cost, cost, "/tmp/demo/month.csv", i),
                )
            conn.commit()
            cmp = compute_period_compare(
                conn,
                "demo",
                start="2024-02-01",
                end="2024-02-29",
                currency="USD",
            )
            assert cmp["mode"] == "prior_month"
            assert cmp["label"] == "上月"
            assert cmp["prev_start"] == "2024-01-01"
            assert cmp["prev_end"] == "2024-01-31"
            # Feb: 29*20=580, Jan: 31*10=310 → +87.1%
            assert cmp["delta_pct"] == 87.1
        finally:
            conn.close()


def test_stats_api_includes_period_compare_and_data_as_of(tmp_path: Path) -> None:
    bills_dir = tmp_path / "bills"
    bills_dir.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "cost_mgmt.sqlite3"
    _create_admin(str(db_path))
    _seed_billing(str(db_path))
    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)
    login = client.post("/auth/login", data={"username": "admin", "password": "admin12345"})
    assert login.status_code in {200, 303}

    res = client.get(
        "/api/projects/demo/stats",
        params={"from_date": "2024-01-04", "to_date": "2024-01-06", "currency": "USD"},
    )
    assert res.status_code == 200
    body = res.json()
    assert "period_compare" in body
    assert body["period_compare"]["prev_start"] == "2024-01-01"
    assert body["period_compare"]["delta_pct"] == 100.0
    assert body["period_compare"]["mode"] == "prior_period"
    assert body["period_compare"]["label"] == "上期"
    assert "data_as_of_utc" in body
    assert body["data_as_of_utc"]


def test_ui_contract_period_compare_and_savings_ids(tmp_path: Path) -> None:
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
    assert 'id="costSavingsBanner"' in cost.text
    assert 'id="actualCostPeriodCompare"' in cost.text
    assert 'id="avgDailyCostPeriodCompare"' in cost.text
    assert 'class="sub kpiDelta"' in cost.text
    assert 'id="costDataAsOf"' in cost.text

    tokens = client.get("/tokens")
    assert tokens.status_code == 200
    assert 'id="totalTokensPeriodCompare"' in tokens.text
    assert 'id="tokenDataAsOf"' in tokens.text

    reports = client.get("/reports")
    assert reports.status_code == 200
    assert 'id="reportDataAsOf"' in reports.text
