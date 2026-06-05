from __future__ import annotations

import sqlite3

from app.db import init_db
from app.import_listing import (
    _ingested_at_epoch,
    count_all_ingested_files,
    list_all_ingested_files,
)
from app.token_metric_ingest import ingest_token_metric_all
from app.token_ingest import ingest_token_all
from app.ingest import ingest_all


def test_list_all_ingested_files_unified_count(tmp_path):
    bills_dir = tmp_path / "bills"
    p = bills_dir / "projA"
    (p / "token").mkdir(parents=True)
    (p / "performance").mkdir(parents=True)

    (p / "2026.csv").write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-01-01","1.0","1.0","","USD"\n',
        encoding="utf-8",
    )
    (p / "token" / "input-tokens-2026-6-4.csv").write_text(
        '"Time","gpt-4o"\n2026-06-01 00:00:00,100\n',
        encoding="utf-8",
    )
    (p / "token" / "cache-match-rate-2026-6-4.csv").write_text(
        '"Time","gpt-4o"\n2026-06-01 00:00:00,1%\n',
        encoding="utf-8",
    )

    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=True)
    ingest_token_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=True)
    ingest_token_metric_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=True)

    counts = count_all_ingested_files(db_path)
    assert counts["billing"] == 1
    assert counts["token"] == 1  # only input file; cache-match is metric
    assert counts["token_metric"] == 1
    assert counts["total"] == 3

    files = list_all_ingested_files(db_path, limit=5000)
    assert len(files) == 3
    kinds = {f["file_kind"] for f in files}
    assert kinds == {"billing", "token", "token_metric"}
    for f in files:
        assert f["ingested_at_epoch"] is not None
        assert f["ingested_at_epoch"] > 0


def test_ingested_at_epoch_parses_sqlite_utc():
    epoch = _ingested_at_epoch("2026-06-05 07:57:12")
    assert epoch is not None
    from datetime import datetime, timezone

    assert datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S") == "2026-06-05 07:57:12"


def test_list_all_ingested_files_pagination(tmp_path):
    bills_dir = tmp_path / "bills"
    p = bills_dir / "projA"
    p.mkdir(parents=True)
    db_path = tmp_path / "cost_mgmt.sqlite3"

    for i in range(5):
        (p / f"2026-{i}.csv").write_text(
            '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
            f'"2026-01-0{i + 1}","1.0","1.0","","USD"\n',
            encoding="utf-8",
        )
    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=True)

    page1 = list_all_ingested_files(db_path, limit=2, offset=0)
    page2 = list_all_ingested_files(db_path, limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 2
    assert page1[0]["ingested_at"] >= page1[1]["ingested_at"]
    paths = {f["file_path_rel"] for f in page1 + page2}
    assert len(paths) == 4
