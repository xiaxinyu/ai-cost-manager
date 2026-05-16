from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth import create_user
from app.db import (
    get_connection,
    get_imported_token_daily_by_model,
    init_db,
    sum_transaction_cost_usd_for_model_day,
)
from app.main import create_app


def _seed_token_day(
    conn,
    *,
    project: str,
    usage_date: str,
    model: str,
    input_tokens: float,
    output_tokens: float,
    row_base: int = 1,
) -> None:
    conn.execute(
        """
        INSERT INTO token_usage_points(
            project_name, recorded_at, usage_date, model_name, token_direction,
            token_count, source_file, source_row_index
        ) VALUES (?, ?, ?, ?, 'input', ?, ?, ?)
        """,
        (
            project,
            f"{usage_date} 10:00:00",
            usage_date,
            model,
            input_tokens,
            f"token/input-{usage_date}-{model}.csv",
            row_base,
        ),
    )
    conn.execute(
        """
        INSERT INTO token_usage_points(
            project_name, recorded_at, usage_date, model_name, token_direction,
            token_count, source_file, source_row_index
        ) VALUES (?, ?, ?, ?, 'output', ?, ?, ?)
        """,
        (
            project,
            f"{usage_date} 10:00:00",
            usage_date,
            model,
            output_tokens,
            f"token/output-{usage_date}-{model}.csv",
            row_base,
        ),
    )


def _seed_tx(
    conn,
    *,
    project: str,
    usage_date: str,
    meter: str,
    cost_usd: float,
    row_index: int,
) -> None:
    conn.execute(
        """
        INSERT INTO transactions(
            project_name, usage_date, meter, cost_usd, cost, currency,
            raw_json, source_file, source_row_index
        ) VALUES (?, ?, ?, ?, ?, 'USD', '{}', 'billing/cost.csv', ?)
        """,
        (project, usage_date, meter, cost_usd, cost_usd, row_index),
    )


def test_transaction_meter_matching_sums_cost_by_model_date_direction(tmp_path):
    db_path = tmp_path / "cost_mgmt.sqlite3"
    conn = get_connection(db_path)
    try:
        init_db(conn)
        _seed_token_day(
            conn,
            project="projTx",
            usage_date="2026-05-12",
            model="gpt-5.3-codex",
            input_tokens=2_000_000.0,
            output_tokens=200_000.0,
        )
        _seed_token_day(
            conn,
            project="projTx",
            usage_date="2026-05-12",
            model="gpt-5.4",
            input_tokens=1_000_000.0,
            output_tokens=50_000.0,
        )
        _seed_token_day(
            conn,
            project="projTx",
            usage_date="2026-05-07",
            model="gpt-5.3-codex",
            input_tokens=41_210_000.0,
            output_tokens=259_300.0,
        )
        # gpt-5.3-codex
        _seed_tx(conn, project="projTx", usage_date="2026-05-12", meter="5.3 codex inp Gl 1M Tokens", cost_usd=10.0, row_index=1)
        _seed_tx(conn, project="projTx", usage_date="2026-05-12", meter="5.3 codex cd inp Gl 1M Tokens", cost_usd=5.0, row_index=2)
        _seed_tx(conn, project="projTx", usage_date="2026-05-12", meter="5.3 codex opt Gl 1M Tokens", cost_usd=4.0, row_index=3)
        # gpt-5.4
        _seed_tx(conn, project="projTx", usage_date="2026-05-12", meter="5.4 inp Gl 1M Tokens", cost_usd=0.05, row_index=4)
        _seed_tx(conn, project="projTx", usage_date="2026-05-12", meter="5.4 opt Gl 1M Tokens", cost_usd=0.02, row_index=5)
        _seed_tx(
            conn,
            project="projTx",
            usage_date="2026-05-07",
            meter="5.3 codex inp Gl 1M Tokens",
            cost_usd=10.077865,
            row_index=6,
        )
        _seed_tx(
            conn,
            project="projTx",
            usage_date="2026-05-07",
            meter="5.3 codex cd inp Gl 1M Tokens",
            cost_usd=5.05283072,
            row_index=7,
        )
        _seed_tx(
            conn,
            project="projTx",
            usage_date="2026-05-07",
            meter="5.3 codex opt Gl 1M Tokens",
            cost_usd=3.294704,
            row_index=8,
        )
        conn.commit()

        assert abs(
            sum_transaction_cost_usd_for_model_day(
                conn,
                "projTx",
                usage_date="2026-05-07",
                token_model="gpt-5.3-codex",
                token_direction="input",
                currency="USD",
            )
            - 15.13069572
        ) < 1e-4
        assert abs(
            sum_transaction_cost_usd_for_model_day(
                conn,
                "projTx",
                usage_date="2026-05-07",
                token_model="gpt-5.3-codex",
                token_direction="output",
                currency="USD",
            )
            - 3.294704
        ) < 1e-4

        out = get_imported_token_daily_by_model(conn, "projTx", currency="USD")
        by_key = {(str(r["date"]), str(r["model_name"])): r for r in out}
        c53 = by_key[("2026-05-12", "gpt-5.3-codex")]
        c54 = by_key[("2026-05-12", "gpt-5.4")]
        assert c53["allocation_method"] == "meter_matched"
        assert abs(float(c53["input_cost_usd"]) - 15.0) < 1e-6
        assert abs(float(c53["output_cost_usd"]) - 4.0) < 1e-6
        assert abs(float(c53["total_cost_usd"]) - 19.0) < 1e-6
        assert c54["allocation_method"] == "meter_matched"
        assert abs(float(c54["input_cost_usd"]) - 0.05) < 1e-6
        assert abs(float(c54["output_cost_usd"]) - 0.02) < 1e-6
        assert abs(float(c54["total_cost_usd"]) - 0.07) < 1e-6
        d57 = by_key[("2026-05-07", "gpt-5.3-codex")]
        assert d57["allocation_method"] == "meter_matched"
        assert float(d57["input_cost_usd"]) == 15.13
        assert float(d57["output_cost_usd"]) == 3.29
    finally:
        conn.close()


def test_token_timeseries_api_returns_daily_cost_columns_from_transactions(tmp_path):
    db_path = tmp_path / "cost_mgmt.sqlite3"
    conn = get_connection(db_path)
    try:
        init_db(conn)
        create_user(conn, username="admin", password="admin12345", is_active=True)
        _seed_token_day(
            conn,
            project="projApi",
            usage_date="2026-05-14",
            model="gpt-5.3-codex",
            input_tokens=1_000_000.0,
            output_tokens=100_000.0,
        )
        _seed_tx(conn, project="projApi", usage_date="2026-05-14", meter="5.3 codex inp", cost_usd=12.0, row_index=1)
        _seed_tx(conn, project="projApi", usage_date="2026-05-14", meter="5.3 codex opt", cost_usd=3.0, row_index=2)
        conn.commit()
    finally:
        conn.close()

    app = create_app(db_path=str(db_path), bills_dir=str(tmp_path / "bills"), auto_ingest=False)
    client = TestClient(app)
    login = client.post("/auth/login", data={"username": "admin", "password": "admin12345"})
    assert login.status_code in {200, 303}
    res = client.get("/api/projects/projApi/token-timeseries?start_date=2026-05-14&end_date=2026-05-14&currency=USD")
    assert res.status_code == 200
    rows = (res.json().get("daily_by_model") or [])
    assert len(rows) == 1
    row = rows[0]
    assert row["model_name"] == "gpt-5.3-codex"
    assert abs(float(row["input_cost_usd"]) - 12.0) < 1e-6
    assert abs(float(row["output_cost_usd"]) - 3.0) < 1e-6
    assert abs(float(row["total_cost_usd"]) - 15.0) < 1e-6
    assert row["allocation_method"] == "meter_matched"
