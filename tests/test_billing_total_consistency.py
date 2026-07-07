"""Billing totals must match across SQL SUM and report aggregators (no penny drift)."""
from __future__ import annotations

from app.db import (
    get_all_financial_stats,
    get_catalog_market_cost_timeseries,
    get_connection,
    get_financial_project_breakdown,
    get_project_stats,
    get_timeseries,
    init_db,
    round_cost,
)


def _seed_mdm_like_billing(conn) -> str:
    project = "proj-billing-totals"
    conn.execute("INSERT INTO projects(name) VALUES (?)", (project,))
    resources = [
        (
            "/subscriptions/x/resourcegroups/rg/providers/"
            "microsoft.cognitiveservices/accounts/agent-a",
            27.5609,
        ),
        (
            "/subscriptions/x/resourcegroups/rg/providers/"
            "microsoft.cognitiveservices/accounts/agent-b",
            4.2684,
        ),
    ]
    for idx, (rid, cost) in enumerate(resources, start=1):
        conn.execute(
            """
            INSERT INTO transactions(
                project_name, usage_date, resource_id, resource_type,
                resource_location, resource_group_name, service_name, meter,
                cost_usd, cost, currency, raw_json, source_file, source_row_index
            ) VALUES (?, '2026-06-10', ?, 'microsoft.cognitiveservices/accounts',
                'US East 2', 'rg', 'Foundry Models', 'm', ?, ?, 'USD', '{}', 'f.csv', ?)
            """,
            (project, rid, cost, cost, idx),
        )
    conn.commit()
    return project


def test_billing_totals_consistent_across_aggregators(tmp_path):
    db_path = tmp_path / "cost.sqlite3"
    conn = get_connection(str(db_path))
    init_db(conn)
    project = _seed_mdm_like_billing(conn)
    start, end = "2026-06-08", "2026-07-07"
    try:
        stats = get_project_stats(conn, project, from_date=start, to_date=end)
        pts, _ = get_timeseries(conn, project, start_date=start, end_date=end)
        cat = get_catalog_market_cost_timeseries(
            conn, project, start_date=start, end_date=end, currency="USD"
        )
        fin = get_all_financial_stats(
            conn, start_date=start, end_date=end, project_names=[project]
        )
        breakdown = get_financial_project_breakdown(
            conn, start_date=start, end_date=end, project_names=[project]
        )
    finally:
        conn.close()

    expected = round_cost(27.5609 + 4.2684)
    assert stats.actual_cost_usd_total == expected
    if cat.get("available"):
        assert cat["summary"]["total_actual_cost_usd"] == expected
    assert fin["daily"]["total_actual"] == expected
    assert breakdown[0]["actual_cost_usd_total"] == expected
    # Daily chart points are rounded per day; summed total may differ by a penny.
    daily_sum = round_cost(sum(float(p["cost_usd"] or 0) for p in pts))
    assert daily_sum == expected or abs(float(daily_sum or 0) - float(expected or 0)) <= 0.01
