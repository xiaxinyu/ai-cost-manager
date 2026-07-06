from __future__ import annotations

from app.db import get_catalog_market_cost_timeseries, get_connection, init_db, round_cost


def test_billing_other_rows_reconcile_to_total(tmp_path):
    db_path = tmp_path / "cost.sqlite3"
    conn = get_connection(str(db_path))
    init_db(conn)
    try:
        conn.execute(
            "INSERT INTO projects(name) VALUES ('projA'), ('projB')"
        )
        conn.executemany(
            """
            INSERT INTO transactions(
                project_name, usage_date, service_name, meter, cost_usd, cost, currency,
                raw_json, source_file, source_row_index
            ) VALUES (?, ?, ?, ?, ?, ?, 'USD', '{}', 'f.csv', ?)
            """,
            [
                ("projA", "2026-06-01", "Foundry Models", "5.4 inp Gl 1M Tokens", 50.0, 50.0, 1),
                ("projA", "2026-06-01", "Foundry Models", "5.4 opt Gl 1M Tokens", 25.0, 25.0, 2),
                ("projA", "2026-06-01", "Microsoft Defender for Cloud", "Standard Tokens", 10.0, 10.0, 3),
                ("projA", "2026-06-01", "Virtual Network", "Peering", 5.0, 5.0, 4),
            ],
        )
        conn.executemany(
            """
            INSERT INTO token_usage_points(
                project_name, recorded_at, usage_date, model_name, token_direction,
                token_count, source_file, source_row_index
            ) VALUES (?, '2026-06-01 10:00:00', ?, ?, ?, ?, 't.csv', ?)
            """,
            [
                ("projA", "2026-06-01", "gpt-5.4", "input", 1_000_000, 1),
                ("projA", "2026-06-01", "gpt-5.4", "output", 500_000, 2),
            ],
        )
        conn.commit()

        payload = get_catalog_market_cost_timeseries(
            conn, "projA", start_date="2026-06-01", end_date="2026-06-01", currency="USD"
        )
    finally:
        conn.close()

    assert payload["available"] is True
    summary = payload["summary"]
    others = payload.get("billing_other_rows") or []
    model_total = sum(float(m["actual_cost_usd"] or 0) for m in payload["model_summary"])
    other_total = sum(float(o["actual_cost_usd"] or 0) for o in others)
    billing_total = float(summary["total_actual_cost_usd"] or 0)

    assert billing_total == round_cost(90.0)
    assert abs(model_total + other_total - billing_total) < 0.02
    assert any("Defender" in str(o["model_name"]) for o in others)
    assert any("Foundry" in str(o["model_name"]) for o in others) or other_total >= 15.0
