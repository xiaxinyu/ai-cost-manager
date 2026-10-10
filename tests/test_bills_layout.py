from __future__ import annotations

from pathlib import Path

from app.bills_layout import (
    discover_subprojects_on_disk,
    is_billing_csv_relpath,
    is_token_metric_csv_relpath,
    is_token_usage_csv_relpath,
    plan_date_layout_relpath,
    snapshot_date_from_relpath,
    subproject_from_filename,
    subproject_from_relpath,
    subproject_from_resource_id,
)
from app.ingest import discover_csv_files
from app.token_ingest import discover_token_csv_files, ingest_token_all
from app.db import get_connection, get_imported_token_totals, get_imported_token_totals_by_subproject, init_db


def test_subproject_from_relpath_nested_and_flat():
    assert subproject_from_relpath("RG-HK/token/coding-1/input-tokens-2026-7-7.csv") == "coding-1"
    assert subproject_from_relpath("RG-HK/performance/coding-1/model-requests-2026-7-7.csv") == "coding-1"
    assert subproject_from_relpath("RG-HK/token/input-tokens-2026-7-7.csv") == ""


def test_subproject_from_relpath_date_snapshot():
    assert (
        subproject_from_relpath(
            "RG-HK/2026-9-8/proj-mdm-coding-1-resource/input-tokens-2026-9-8.csv"
        )
        == "proj-mdm-coding-1-resource"
    )
    assert (
        subproject_from_relpath(
            "RG-HK/2026-9-8/proj-mdm-coding-1-resource/model-requests-2026-9-8.csv"
        )
        == "proj-mdm-coding-1-resource"
    )
    # Compat: kind dirs under date still parse.
    assert (
        subproject_from_relpath(
            "RG-HK/2026-9-8/proj-mdm-coding-1-resource/token/input-tokens-2026-9-8.csv"
        )
        == "proj-mdm-coding-1-resource"
    )
    assert snapshot_date_from_relpath("RG-HK/2026-9-8/cost-2026-9-8.csv") == "2026-9-8"
    assert is_billing_csv_relpath("RG-HK/2026-9-8/cost-2026-9-8.csv") is True
    assert is_billing_csv_relpath("RG-HK/2026-9-8/input-tokens-2026-9-8.csv") is False
    assert is_token_usage_csv_relpath(
        "RG-HK/2026-9-8/proj-a/input-tokens-2026-9-8.csv"
    )
    assert is_token_metric_csv_relpath(
        "RG-HK/2026-9-8/proj-a/model-requests-2026-9-8.csv"
    )


def test_plan_date_layout_relpath():
    assert plan_date_layout_relpath("RG-HK/cost-2026-9-8.csv") == "RG-HK/2026-9-8/cost-2026-9-8.csv"
    assert (
        plan_date_layout_relpath("RG-HK/token/coding-1/input-tokens-2026-7-7.csv")
        == "RG-HK/2026-7-7/coding-1/input-tokens-2026-7-7.csv"
    )
    assert (
        plan_date_layout_relpath(
            "RG-HK/2026-9-8/coding-1/token/input-tokens-2026-9-8.csv"
        )
        == "RG-HK/2026-9-8/coding-1/input-tokens-2026-9-8.csv"
    )
    assert plan_date_layout_relpath("RG-HK/2026-9-8/cost-2026-9-8.csv") is None
    assert plan_date_layout_relpath("RG-HK/2026-9-8/coding-1/input-tokens-2026-9-8.csv") is None
    assert plan_date_layout_relpath("RG-HK/token/coding-1/input-tokens.csv") is None


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


def test_grafana_raw_filenames_are_recognized():
    from app.bills_layout import (
        is_metric_csv_filename,
        is_token_usage_csv_filename,
        metric_name_from_filename,
        subproject_from_relpath,
    )

    assert is_token_usage_csv_filename(
        "Input Tokens-data-as-joinbyfield-2026-10-10 15_15_30.csv"
    )
    assert is_token_usage_csv_filename("Output Tokens-data-2026-10-10 15_21_09.csv")
    assert is_metric_csv_filename(
        "Token Cache Match Rate (OpenAI models)-data-as-joinbyfield-2026-10-10 15_15_09.csv"
    )
    assert is_metric_csv_filename(
        "Average Latency (Time to Last Byte)-data-as-joinbyfield-2026-10-10 15_13_58.csv"
    )
    assert is_metric_csv_filename("Model Requests-data-as-joinbyfield-2026-10-10 15_13_45.csv")
    assert metric_name_from_filename("Model Requests-data-x.csv") == "model_requests"
    assert (
        subproject_from_relpath(
            "RG-HK/2026-10-9/proj-mdm-coding-1-resource/"
            "Input Tokens-data-as-joinbyfield-2026-10-10 15_15_30.csv"
        )
        == "proj-mdm-coding-1-resource"
    )


def test_discover_subprojects_on_disk(tmp_path):
    project = tmp_path / "RG-HK-S56-MDM-Coding"
    (project / "token" / "coding-1").mkdir(parents=True)
    (project / "token" / "coding-2").mkdir(parents=True)
    (project / "performance" / "coding-1").mkdir(parents=True)
    assert discover_subprojects_on_disk(tmp_path, "RG-HK-S56-MDM-Coding") == ["coding-1", "coding-2"]


def test_discover_subprojects_on_disk_date_layout(tmp_path):
    project = tmp_path / "RG-HK"
    (project / "2026-9-8" / "coding-1").mkdir(parents=True)
    (project / "2026-9-8" / "coding-1" / "input-tokens-2026-9-8.csv").write_text("x\n", encoding="utf-8")
    (project / "2026-10-8" / "coding-2").mkdir(parents=True)
    (project / "2026-10-8" / "coding-2" / "model-requests-2026-10-8.csv").write_text("x\n", encoding="utf-8")
    assert discover_subprojects_on_disk(tmp_path, "RG-HK") == ["coding-1", "coding-2"]


def test_date_layout_billing_and_token_discovery(tmp_path):
    bills_dir = tmp_path / "bills"
    project = "RG-HK"
    date_dir = bills_dir / project / "2026-9-8"
    date_dir.mkdir(parents=True)
    (date_dir / "cost-2026-9-8.csv").write_text(
        "UsageDate,Cost\n2026-09-01,1.0\n",
        encoding="utf-8",
    )
    sub_dir = date_dir / "coding-1"
    sub_dir.mkdir(parents=True)
    (sub_dir / "input-tokens-2026-9-8.csv").write_text(
        '"Time","gpt-4o"\n2026-09-08 10:00:00,1 Mil\n',
        encoding="utf-8",
    )

    billing = discover_csv_files(bills_dir)
    assert len(billing) == 1
    assert billing[0][2] == "RG-HK/2026-9-8/cost-2026-9-8.csv"

    tokens = discover_token_csv_files(bills_dir)
    assert len(tokens) == 1
    assert tokens[0][2] == "RG-HK/2026-9-8/coding-1/input-tokens-2026-9-8.csv"
    assert tokens[0][3] == "coding-1"


def test_date_layout_token_ingest(tmp_path):
    bills_dir = tmp_path / "bills"
    project = "RG-HK"
    for sub, mil in (("coding-1", 1), ("coding-2", 2)):
        subdir = bills_dir / project / "2026-7-7" / sub
        subdir.mkdir(parents=True)
        (subdir / "input-tokens-2026-7-7.csv").write_text(
            '"Time","gpt-5.3-codex"\n'
            f"2026-07-07 10:00:00,{mil} Mil\n",
            encoding="utf-8",
        )

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
    finally:
        conn.close()


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
        breakdown = get_imported_token_totals_by_subproject(conn, project)
        assert len(breakdown) == 2
        by_name = {r["subproject_name"]: r for r in breakdown}
        assert by_name["coding-1"]["input_tokens"] == 1_000_000.0
        assert by_name["coding-2"]["input_tokens"] == 2_000_000.0
    finally:
        conn.close()


def test_token_timeseries_subproject_breakdown_api(tmp_path):
    from app.auth import create_user
    from app.main import create_app
    from fastapi.testclient import TestClient

    bills_dir = tmp_path / "bills"
    project = "proj-api"
    for sub, mil in (("alpha", 1), ("beta", 2)):
        subdir = bills_dir / project / "token" / sub
        subdir.mkdir(parents=True)
        (subdir / "input-tokens.csv").write_text(
            '"Time","gpt-4o"\n'
            f"2026-07-01 00:00:00,{mil} Mil\n",
            encoding="utf-8",
        )
        (subdir / "output-tokens.csv").write_text(
            '"Time","gpt-4o"\n'
            f"2026-07-01 00:00:00,{mil * 100} K\n",
            encoding="utf-8",
        )

    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_token_all(bills_dir=bills_dir, db_path=db_path)
    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)
    conn = get_connection(db_path)
    init_db(conn)
    create_user(conn, username="admin", password="admin12345", is_active=True)
    conn.close()
    client.post("/auth/login", data={"username": "admin", "password": "admin12345"})

    res = client.get(f"/api/projects/{project}/token-timeseries")
    assert res.status_code == 200
    payload = res.json()
    assert payload["token_data_source"] == "imported"
    bd = payload.get("subproject_breakdown") or []
    assert len(bd) == 2
    names = {r["subproject_name"] for r in bd}
    assert names == {"alpha", "beta"}
    alpha = next(r for r in bd if r["subproject_name"] == "alpha")
    assert alpha["input_tokens"] == 1_000_000.0
    assert alpha["output_tokens"] == 100_000.0

    filtered = client.get(f"/api/projects/{project}/token-timeseries?subproject=alpha")
    assert filtered.status_code == 200
    assert "subproject_breakdown" not in filtered.json()


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
