from __future__ import annotations

import sqlite3

from app.ingest import ingest_all, ingest_selected


def test_ingest_excludes_price_directory(tmp_path):
    bills_dir = tmp_path / "bills"
    # Billing project (should be ingested)
    billing_dir = bills_dir / "projA"
    billing_dir.mkdir(parents=True, exist_ok=True)
    (billing_dir / "2026-Mar-1.csv").write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-03-01","1.0","1.0","","USD"\n',
        encoding="utf-8",
    )

    # Model price directory (must be excluded)
    price_dir = bills_dir / "price"
    price_dir.mkdir(parents=True, exist_ok=True)
    (price_dir / "ignore.csv").write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-03-02","2.0","2.0","","USD"\n',
        encoding="utf-8",
    )

    db_path = tmp_path / "cost_mgmt.sqlite3"
    r = ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    assert r.files_ingested == 1


def test_ingest_skips_already_read_files(tmp_path):
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projA"
    project_dir.mkdir(parents=True, exist_ok=True)

    csv_path = project_dir / "2026-Mar-1.csv"
    csv_path.write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-03-01","1.0","1.0","","USD"\n'
        '"2026-03-02","","","0.5","USD"\n',
        encoding="utf-8",
    )

    db_path = tmp_path / "cost_mgmt.sqlite3"

    r1 = ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    assert r1.projects_discovered == 1
    assert r1.files_discovered == 1
    assert r1.files_ingested == 1
    assert r1.files_skipped == 0
    assert r1.rows_ingested == 2
    assert r1.rows_inserted == 2 and r1.rows_updated == 0

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute("SELECT COUNT(*) FROM transactions")
        assert cur.fetchone()[0] == 2

        cur = conn.execute("SELECT COUNT(*) FROM ingested_files")
        assert cur.fetchone()[0] == 1

        r2 = ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
        assert r2.files_skipped == 1
        assert r2.files_ingested == 0
        assert r2.rows_inserted == 0 and r2.rows_updated == 0

        cur = conn.execute("SELECT COUNT(*) FROM transactions")
        assert cur.fetchone()[0] == 2
    finally:
        conn.close()


def test_billing_natural_key_upsert_across_files(tmp_path):
    """Same resource + UsageDate+RG+Tier+Meter in a later file replaces the earlier row."""
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projX"
    project_dir.mkdir(parents=True, exist_ok=True)
    rid = "/subscriptions/x/resourcegroups/rg1/providers/microsoft.cognitiveservices/accounts/res-a"
    hdr = (
        '"UsageDate","ResourceId","ResourceGroupName","ServiceTier","Meter",'
        '"CostUSD","Cost","Currency"\n'
    )
    (project_dir / "first.csv").write_text(
        hdr + f'"2026-04-01","{rid}","rg1","tier1","meter1","1.0","1.0","USD"\n',
        encoding="utf-8",
    )
    (project_dir / "second.csv").write_text(
        hdr + f'"2026-04-01","{rid}","rg1","tier1","meter1","9.0","9.0","USD"\n',
        encoding="utf-8",
    )
    db_path = tmp_path / "cost_mgmt.sqlite3"
    r1 = ingest_selected(
        bills_dir=bills_dir,
        db_path=db_path,
        file_path_rels=["projX/first.csv"],
        reimport_changed=True,
    )
    assert r1.rows_inserted == 1 and r1.rows_updated == 0
    r2 = ingest_selected(
        bills_dir=bills_dir,
        db_path=db_path,
        file_path_rels=["projX/second.csv"],
        reimport_changed=True,
    )
    assert r2.rows_inserted == 0 and r2.rows_updated == 1

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
        row = conn.execute("SELECT cost_usd, source_file FROM transactions").fetchone()
        assert float(row[0]) == 9.0
        assert row[1] == "projX/second.csv"
    finally:
        conn.close()


def test_billing_natural_key_distinct_resources_same_meter(tmp_path):
    """Multiple Cognitive Services resources on the same day/meter stay separate rows."""
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projMdm"
    project_dir.mkdir(parents=True, exist_ok=True)
    rid1 = (
        "/subscriptions/x/resourcegroups/rg-hk-s56-mdm-coding/providers/"
        "microsoft.cognitiveservices/accounts/proj-mdm-coding-1-resource"
    )
    rid2 = (
        "/subscriptions/x/resourcegroups/rg-hk-s56-mdm-coding/providers/"
        "microsoft.cognitiveservices/accounts/proj-mdm-coding-6-resource"
    )
    hdr = (
        '"UsageDate","ResourceId","ResourceGroupName","ServiceTier","Meter",'
        '"CostUSD","Cost","Currency"\n'
    )
    (project_dir / "day.csv").write_text(
        hdr
        + f'"2026-07-01","{rid1}","rg-hk-s56-mdm-coding","Azure OpenAI GPT5",'
        '"5.3 codex inp Gl 1M Tokens","1.20","1.20","USD"\n'
        + f'"2026-07-01","{rid2}","rg-hk-s56-mdm-coding","Azure OpenAI GPT5",'
        '"5.3 codex inp Gl 1M Tokens","4.09","4.09","USD"\n',
        encoding="utf-8",
    )
    db_path = tmp_path / "cost_mgmt.sqlite3"
    r = ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    assert r.rows_inserted == 2

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2
        total = conn.execute("SELECT SUM(cost_usd) FROM transactions").fetchone()[0]
        assert abs(float(total) - 5.29) < 1e-6
    finally:
        conn.close()

