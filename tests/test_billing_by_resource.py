from __future__ import annotations

from app.db import get_connection, get_project_billing_by_resource, init_db, round_cost


def test_billing_by_resource_groups_resource_and_service(tmp_path):
    db_path = tmp_path / "cost.sqlite3"
    conn = get_connection(str(db_path))
    init_db(conn)
    rid = (
        "/subscriptions/x/resourcegroups/rg-a/providers/"
        "microsoft.cognitiveservices/accounts/my-agent"
    )
    pe = (
        "/subscriptions/x/resourcegroups/rg-a/providers/"
        "microsoft.network/privateendpoints/pe-1"
    )
    try:
        conn.execute("INSERT INTO projects(name) VALUES ('projR')")
        conn.executemany(
            """
            INSERT INTO transactions(
                project_name, usage_date, resource_id, resource_type,
                resource_location, resource_group_name, service_name, meter,
                cost_usd, cost, currency, raw_json, source_file, source_row_index
            ) VALUES (?, '2026-06-01', ?, ?, 'US East 2', 'rg-a', ?, 'm', ?, ?, 'USD', '{}', 'f.csv', ?)
            """,
            [
                ("projR", rid, "microsoft.cognitiveservices/accounts", "Foundry Models", 50.0, 50.0, 1),
                ("projR", rid, "microsoft.cognitiveservices/accounts", "Microsoft Defender for Cloud", 10.0, 10.0, 2),
                ("projR", pe, "microsoft.network/privateendpoints", "Virtual Network", 5.0, 5.0, 3),
            ],
        )
        conn.commit()
        payload = get_project_billing_by_resource(
            conn, "projR", start_date="2026-06-01", end_date="2026-06-01", currency="USD"
        )
    finally:
        conn.close()

    assert payload["available"] is True
    assert payload["total_cost_usd"] == round_cost(65.0)
    assert payload["row_count"] == 3
    rows = payload["rows"]
    assert rows[0]["resource_name"] == "my-agent"
    assert rows[0]["service_name"] == "Foundry Models"
    assert rows[0]["cost_usd"] == round_cost(50.0)
    names = {r["resource_name"] for r in rows}
    assert names == {"my-agent", "pe-1"}
    assert sum(float(r["cost_usd"] or 0) for r in rows) == 65.0
