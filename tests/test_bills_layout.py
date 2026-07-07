from __future__ import annotations

from pathlib import Path

from app.bills_layout import (
    discover_subprojects_on_disk,
    subproject_from_filename,
    subproject_from_relpath,
    subproject_from_resource_id,
)
from app.token_ingest import discover_token_csv_files, ingest_token_all
from app.db import get_connection, get_imported_token_totals, init_db


def test_subproject_from_relpath_nested_and_flat():
    assert subproject_from_relpath("RG-HK/token/coding-1/input-tokens-2026-7-7.csv") == "coding-1"
    assert subproject_from_relpath("RG-HK/performance/coding-1/model-requests-2026-7-7.csv") == "coding-1"
    assert subproject_from_relpath("RG-HK/token/input-tokens-2026-7-7.csv") == ""


def test_subproject_from_legacy_filename_slug():
    assert subproject_from_filename("input-tokens-coding-1-2026-7-7.csv") == "coding-1"
    assert subproject_from_filename("model-requests-coding-1-2026-7-7.csv") == "coding-1"
    assert subproject_from_filename("input-tokens-2026-7-7.csv") == ""


def test_subproject_from_resource_id():
    rid = (
        "/subscriptions/x/resourcegroups/rg-a/providers/"
        "microsoft.cognitiveservices/accounts/proj-mdm-coding-1-resource"
    )
    assert subproject_from_resource_id(rid) == "proj-mdm-coding-1-resource"
    assert subproject_from_resource_id("") == ""
    assert subproject_from_resource_id(None) == ""


def test_is_token_usage_csv_filename_strict():
    from app.bills_layout import is_token_usage_csv_filename

    assert is_token_usage_csv_filename("input-tokens-2026-7-7.csv") is True
    assert is_token_usage_csv_filename("output-tokens-2026-7-7.csv") is True
    assert is_token_usage_csv_filename("model-requests-2026-7-7.csv") is False
    assert is_token_usage_csv_filename("cache-match-rate-2026-7-7.csv") is False
    assert is_token_usage_csv_filename("my-input-output-debug.csv") is False


def test_discover_subprojects_on_disk(tmp_path):
    project = tmp_path / "RG-HK-S56-MDM-Coding"
    (project / "token" / "coding-1").mkdir(parents=True)
    (project / "token" / "coding-2").mkdir(parents=True)
    (project / "performance" / "coding-1").mkdir(parents=True)
    assert discover_subprojects_on_disk(tmp_path, "RG-HK-S56-MDM-Coding") == ["coding-1", "coding-2"]


def test_nested_token_ingest_keeps_subprojects_separate(tmp_path):
    bills_dir = tmp_path / "bills"
    project = "RG-HK-S56-MDM-Coding"
    for sub in ("coding-1", "coding-2"):
        subdir = bills_dir / project / "token" / sub
        subdir.mkdir(parents=True)
        (subdir / "input-tokens-2026-7-7.csv").write_text(
            '"Time","gpt-5.3-codex"\n'
            f"2026-07-07 10:00:00,{1 if sub == 'coding-1' else 2} Mil\n",
            encoding="utf-8",
        )

    discovered = discover_token_csv_files(bills_dir)
    assert len(discovered) == 2
    assert {row[3] for row in discovered} == {"coding-1", "coding-2"}

    db_path = tmp_path / "cost_mgmt.sqlite3"
    result = ingest_token_all(bills_dir=bills_dir, db_path=db_path)
    assert result.files_ingested == 2
    assert result.verification_passed is True

    conn = get_connection(db_path)
    try:
        init_db(conn)
        in1, _ = get_imported_token_totals(conn, project, subproject_name="coding-1")
        in2, _ = get_imported_token_totals(conn, project, subproject_name="coding-2")
        assert in1 == 1_000_000.0
        assert in2 == 2_000_000.0
        in_all, _ = get_imported_token_totals(conn, project)
        assert in_all == 3_000_000.0
    finally:
        conn.close()


def test_project_stats_respects_subproject_filter(tmp_path):
    from app.db import get_project_stats

    bills_dir = tmp_path / "bills"
    project = "proj-sub"
    for sub, mil in (("alpha", 1), ("beta", 3)):
        subdir = bills_dir / project / "token" / sub
        subdir.mkdir(parents=True)
        (subdir / "input-tokens.csv").write_text(
            '"Time","gpt-4o"\n'
            f"2026-07-01 00:00:00,{mil} Mil\n",
            encoding="utf-8",
        )

    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_token_all(bills_dir=bills_dir, db_path=db_path)

    conn = get_connection(db_path)
    try:
        init_db(conn)
        alpha_stats = get_project_stats(conn, project, subproject_name="alpha")
        beta_stats = get_project_stats(conn, project, subproject_name="beta")
        all_stats = get_project_stats(conn, project)
        assert alpha_stats.estimated_input_tokens == 1_000_000.0
        assert beta_stats.estimated_input_tokens == 3_000_000.0
        assert all_stats.estimated_input_tokens == 4_000_000.0
    finally:
        conn.close()


def test_list_subprojects_includes_billing_resources(tmp_path):
    from app.db import list_subprojects_for_project

    db_path = tmp_path / "cost.sqlite3"
    conn = get_connection(db_path)
    init_db(conn)
    rid = (
        "/subscriptions/x/resourcegroups/rg-a/providers/"
        "microsoft.cognitiveservices/accounts/proj-mdm-coding-3-resource"
    )
    try:
        conn.execute("INSERT INTO projects(name) VALUES ('proj-bill')")
        conn.execute(
            """
            INSERT INTO transactions(
                project_name, usage_date, resource_id, resource_type,
                resource_location, resource_group_name, service_name, meter,
                cost_usd, cost, currency, raw_json, source_file, source_row_index
            ) VALUES ('proj-bill', '2026-06-01', ?, 'microsoft.cognitiveservices/accounts',
                'US East 2', 'rg-a', 'Foundry Models', 'm', 1.0, 1.0, 'USD', '{}', 'f.csv', 1)
            """,
            (rid,),
        )
        conn.commit()
        subs = list_subprojects_for_project(conn, "proj-bill")
    finally:
        conn.close()

    assert "proj-mdm-coding-3-resource" in subs


def test_project_stats_billing_subproject_filter(tmp_path):
    from app.db import get_project_stats

    db_path = tmp_path / "cost.sqlite3"
    conn = get_connection(db_path)
    init_db(conn)
    rid_a = (
        "/subscriptions/x/resourcegroups/rg-a/providers/"
        "microsoft.cognitiveservices/accounts/agent-a"
    )
    rid_b = (
        "/subscriptions/x/resourcegroups/rg-a/providers/"
        "microsoft.cognitiveservices/accounts/agent-b"
    )
    try:
        conn.execute("INSERT INTO projects(name) VALUES ('proj-cost')")
        conn.executemany(
            """
            INSERT INTO transactions(
                project_name, usage_date, resource_id, resource_type,
                resource_location, resource_group_name, service_name, meter,
                cost_usd, cost, currency, raw_json, source_file, source_row_index
            ) VALUES (?, '2026-06-01', ?, 'microsoft.cognitiveservices/accounts',
                'US East 2', 'rg-a', 'Foundry Models', 'm', ?, ?, 'USD', '{}', 'f.csv', ?)
            """,
            [
                ("proj-cost", rid_a, 30.0, 30.0, 1),
                ("proj-cost", rid_b, 20.0, 20.0, 2),
            ],
        )
        conn.commit()
        all_stats = get_project_stats(conn, "proj-cost")
        a_stats = get_project_stats(conn, "proj-cost", subproject_name="agent-a")
    finally:
        conn.close()

    assert all_stats.actual_cost_usd_total == 50.0
    assert a_stats.actual_cost_usd_total == 30.0
