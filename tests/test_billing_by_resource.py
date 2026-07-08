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


def test_billing_by_resource_subproject_filter(tmp_path):
    db_path = tmp_path / "cost.sqlite3"
    conn = get_connection(str(db_path))
    init_db(conn)
    rid_a = (
        "/subscriptions/x/resourcegroups/rg-a/providers/"
        "microsoft.cognitiveservices/accounts/proj-mdm-coding-1-resource"
    )
    rid_b = (
        "/subscriptions/x/resourcegroups/rg-a/providers/"
        "microsoft.cognitiveservices/accounts/proj-mdm-coding-2-resource"
    )
    try:
        conn.execute("INSERT INTO projects(name) VALUES ('projR')")
        conn.executemany(
            """
            INSERT INTO transactions(
                project_name, usage_date, resource_id, resource_type,
                resource_location, resource_group_name, service_name, meter,
                cost_usd, cost, currency, raw_json, source_file, source_row_index
            ) VALUES (?, '2026-06-01', ?, ?, 'US East 2', 'rg-a', 'Foundry Models', 'm', ?, ?, 'USD', '{}', 'f.csv', ?)
            """,
            [
                ("projR", rid_a, "microsoft.cognitiveservices/accounts", 40.0, 40.0, 1),
                ("projR", rid_b, "microsoft.cognitiveservices/accounts", 25.0, 25.0, 2),
            ],
        )
        conn.commit()
        all_payload = get_project_billing_by_resource(
            conn, "projR", start_date="2026-06-01", end_date="2026-06-01", currency="USD"
        )
        sub_payload = get_project_billing_by_resource(
            conn,
            "projR",
            start_date="2026-06-01",
            end_date="2026-06-01",
            currency="USD",
            subproject_name="proj-mdm-coding-1-resource",
        )
    finally:
        conn.close()

    assert all_payload["total_cost_usd"] == round_cost(65.0)
    assert sub_payload["total_cost_usd"] == round_cost(40.0)
    assert sub_payload["subproject"] == "proj-mdm-coding-1-resource"
    assert len(sub_payload["rows"]) == 1
    assert sub_payload["rows"][0]["resource_name"] == "proj-mdm-coding-1-resource"


def test_daily_cost_by_resource_series(tmp_path):
    db_path = tmp_path / "cost.sqlite3"
    conn = get_connection(str(db_path))
    init_db(conn)
    rid_a = (
        "/subscriptions/x/resourcegroups/rg-a/providers/"
        "microsoft.cognitiveservices/accounts/proj-mdm-coding-1-resource"
    )
    rid_b = (
        "/subscriptions/x/resourcegroups/rg-a/providers/"
        "microsoft.cognitiveservices/accounts/proj-mdm-coding-2-resource"
    )
    try:
        from app.db import get_project_daily_cost_by_resource

        conn.execute("INSERT INTO projects(name) VALUES ('projR')")
        conn.executemany(
            """
            INSERT INTO transactions(
                project_name, usage_date, resource_id, resource_type,
                resource_location, resource_group_name, service_name, meter,
                cost_usd, cost, currency, raw_json, source_file, source_row_index
            ) VALUES (?, ?, ?, ?, 'US East 2', 'rg-a', 'Foundry Models', 'm', ?, ?, 'USD', '{}', 'f.csv', ?)
            """,
            [
                ("projR", "2026-06-01", rid_a, "microsoft.cognitiveservices/accounts", 40.0, 40.0, 1),
                ("projR", "2026-06-01", rid_b, "microsoft.cognitiveservices/accounts", 25.0, 25.0, 2),
                ("projR", "2026-06-02", rid_a, "microsoft.cognitiveservices/accounts", 10.0, 10.0, 3),
            ],
        )
        conn.commit()
        payload = get_project_daily_cost_by_resource(
            conn, "projR", start_date="2026-06-01", end_date="2026-06-02", currency="USD"
        )
    finally:
        conn.close()

    assert payload["available"] is True
    assert payload["resource_count"] == 2
    series = payload["series"]
    assert len(series) == 2
    names = {s["resource_name"] for s in series}
    assert names == {"proj-mdm-coding-1-resource", "proj-mdm-coding-2-resource"}
    by_name = {s["resource_name"]: s["points"] for s in series}
    day1_a = next(p for p in by_name["proj-mdm-coding-1-resource"] if p["date"] == "2026-06-01")
    assert day1_a["cost_usd"] == round_cost(40.0)
    day2_a = next(p for p in by_name["proj-mdm-coding-1-resource"] if p["date"] == "2026-06-02")
    assert day2_a["cost_usd"] == round_cost(10.0)


def test_financial_daily_cost_by_segment_resource_mode(tmp_path):
    db_path = tmp_path / "cost.sqlite3"
    conn = get_connection(str(db_path))
    init_db(conn)
    rid_a = (
        "/subscriptions/x/resourcegroups/rg-a/providers/"
        "microsoft.cognitiveservices/accounts/proj-mdm-coding-1-resource"
    )
    rid_b = (
        "/subscriptions/x/resourcegroups/rg-a/providers/"
        "microsoft.cognitiveservices/accounts/proj-mdm-coding-2-resource"
    )
    try:
        from app.db import get_financial_daily_cost_by_segment

        conn.execute("INSERT INTO projects(name) VALUES ('projR')")
        conn.executemany(
            """
            INSERT INTO transactions(
                project_name, usage_date, resource_id, resource_type,
                resource_location, resource_group_name, service_name, meter,
                cost_usd, cost, currency, raw_json, source_file, source_row_index
            ) VALUES (?, ?, ?, ?, 'US East 2', 'rg-a', 'Foundry Models', 'm', ?, ?, 'USD', '{}', 'f.csv', ?)
            """,
            [
                ("projR", "2026-06-01", rid_a, "microsoft.cognitiveservices/accounts", 40.0, 40.0, 1),
                ("projR", "2026-06-01", rid_b, "microsoft.cognitiveservices/accounts", 25.0, 25.0, 2),
                ("projR", "2026-06-02", rid_a, "microsoft.cognitiveservices/accounts", 10.0, 10.0, 3),
            ],
        )
        conn.commit()
        payload = get_financial_daily_cost_by_segment(
            conn,
            start_date="2026-06-01",
            end_date="2026-06-02",
            currency="USD",
            project_names=["projR"],
        )
    finally:
        conn.close()

    assert payload["available"] is True
    assert payload["segment_mode"] == "resource"
    assert payload["resource_count"] == 2
    names = {s["resource_name"] for s in payload["series"]}
    assert names == {"proj-mdm-coding-1-resource", "proj-mdm-coding-2-resource"}


def test_financial_daily_cost_by_segment_project_mode(tmp_path):
    db_path = tmp_path / "cost.sqlite3"
    conn = get_connection(str(db_path))
    init_db(conn)
    try:
        from app.db import get_financial_daily_cost_by_segment

        conn.executemany("INSERT INTO projects(name) VALUES (?)", [("projA",), ("projB",)])
        conn.executemany(
            """
            INSERT INTO transactions(
                project_name, usage_date, resource_id, resource_type,
                resource_location, resource_group_name, service_name, meter,
                cost_usd, cost, currency, raw_json, source_file, source_row_index
            ) VALUES (?, ?, 'rid', 'microsoft.cognitiveservices/accounts', 'US East 2', 'rg-a', 'Foundry Models', 'm', ?, ?, 'USD', '{}', 'f.csv', ?)
            """,
            [
                ("projA", "2026-06-01", 30.0, 30.0, 1),
                ("projB", "2026-06-01", 20.0, 20.0, 2),
                ("projA", "2026-06-02", 15.0, 15.0, 3),
            ],
        )
        conn.commit()
        payload = get_financial_daily_cost_by_segment(
            conn,
            start_date="2026-06-01",
            end_date="2026-06-02",
            currency="USD",
            project_names=["projA", "projB"],
        )
    finally:
        conn.close()

    assert payload["available"] is True
    assert payload["segment_mode"] == "project"
    assert payload["resource_count"] == 2
    names = {s["resource_name"] for s in payload["series"]}
    assert names == {"projA", "projB"}
