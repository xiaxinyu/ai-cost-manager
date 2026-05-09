from __future__ import annotations

import sqlite3

from app.ingest import ingest_all


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

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute("SELECT COUNT(*) FROM transactions")
        assert cur.fetchone()[0] == 2

        cur = conn.execute("SELECT COUNT(*) FROM ingested_files")
        assert cur.fetchone()[0] == 1

        r2 = ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
        assert r2.files_skipped == 1
        assert r2.files_ingested == 0

        cur = conn.execute("SELECT COUNT(*) FROM transactions")
        assert cur.fetchone()[0] == 2
    finally:
        conn.close()

