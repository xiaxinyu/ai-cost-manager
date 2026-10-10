from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.migrate_bills_to_date_layout import apply_file_moves, build_migration_plan, rewrite_db_paths


def test_migrate_plan_and_apply(tmp_path):
    bills = tmp_path / "bills"
    project = bills / "RG-HK"
    (project / "token" / "coding-1").mkdir(parents=True)
    (project / "performance" / "coding-1").mkdir(parents=True)
    (project / "cost-2026-9-8.csv").write_text("a\n", encoding="utf-8")
    (project / "token" / "coding-1" / "input-tokens-2026-9-8.csv").write_text("b\n", encoding="utf-8")
    (project / "performance" / "coding-1" / "model-requests-2026-9-8.csv").write_text("c\n", encoding="utf-8")
    # Flat token (no subproject)
    (project / "token" / "output-tokens-2026-7-7.csv").write_text("d\n", encoding="utf-8")

    plan, skipped = build_migration_plan(bills)
    assert skipped == []
    mapping = {p["old"]: p["new"] for p in plan}
    assert mapping["RG-HK/cost-2026-9-8.csv"] == "RG-HK/2026-9-8/cost-2026-9-8.csv"
    assert (
        mapping["RG-HK/token/coding-1/input-tokens-2026-9-8.csv"]
        == "RG-HK/2026-9-8/coding-1/input-tokens-2026-9-8.csv"
    )
    assert mapping["RG-HK/token/output-tokens-2026-7-7.csv"] == "RG-HK/2026-7-7/output-tokens-2026-7-7.csv"

    apply_file_moves(bills, plan)
    assert (bills / "RG-HK/2026-9-8/cost-2026-9-8.csv").is_file()
    assert (bills / "RG-HK/2026-9-8/coding-1/input-tokens-2026-9-8.csv").is_file()
    assert (bills / "RG-HK/2026-7-7/output-tokens-2026-7-7.csv").is_file()


def test_migrate_flattens_kind_dirs_under_date(tmp_path):
    bills = tmp_path / "bills"
    src = bills / "RG-HK" / "2026-8-3" / "coding-1" / "token"
    src.mkdir(parents=True)
    (src / "input-tokens-2026-8-3.csv").write_text("b\n", encoding="utf-8")
    perf = bills / "RG-HK" / "2026-8-3" / "coding-1" / "performance"
    perf.mkdir(parents=True)
    (perf / "model-requests-2026-8-3.csv").write_text("c\n", encoding="utf-8")

    plan, skipped = build_migration_plan(bills)
    assert skipped == []
    mapping = {p["old"]: p["new"] for p in plan}
    assert (
        mapping["RG-HK/2026-8-3/coding-1/token/input-tokens-2026-8-3.csv"]
        == "RG-HK/2026-8-3/coding-1/input-tokens-2026-8-3.csv"
    )
    assert (
        mapping["RG-HK/2026-8-3/coding-1/performance/model-requests-2026-8-3.csv"]
        == "RG-HK/2026-8-3/coding-1/model-requests-2026-8-3.csv"
    )
    apply_file_moves(bills, plan)
    assert (bills / "RG-HK/2026-8-3/coding-1/input-tokens-2026-8-3.csv").is_file()
    assert (bills / "RG-HK/2026-8-3/coding-1/model-requests-2026-8-3.csv").is_file()


def test_rewrite_db_paths(tmp_path):
    db_path = tmp_path / "db.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE ingested_files (file_path TEXT)"
    )
    conn.execute(
        "CREATE TABLE transactions (source_file TEXT)"
    )
    conn.execute("INSERT INTO ingested_files VALUES ('RG-HK/cost-2026-9-8.csv')")
    conn.execute("INSERT INTO transactions VALUES ('RG-HK/cost-2026-9-8.csv')")
    conn.commit()
    conn.close()

    counts = rewrite_db_paths(
        db_path,
        {"RG-HK/cost-2026-9-8.csv": "RG-HK/2026-9-8/cost-2026-9-8.csv"},
    )
    assert counts["ingested_files.file_path"] == 1
    assert counts["transactions.source_file"] == 1

    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT file_path FROM ingested_files").fetchone()[0] == (
        "RG-HK/2026-9-8/cost-2026-9-8.csv"
    )
    conn.close()
