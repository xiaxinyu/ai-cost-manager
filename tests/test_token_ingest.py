from __future__ import annotations

import sqlite3
from pathlib import Path

from app.token_ingest import (
    discover_token_csv_files,
    ingest_token_all,
    infer_token_direction,
    list_missing_token_files,
    parse_token_quantity,
)
from app.db import get_imported_token_totals, get_connection, init_db, project_has_imported_tokens


def test_parse_token_quantity():
    assert parse_token_quantity("46.2 K") == 46_200.0
    assert parse_token_quantity("46.2K") == 46_200.0
    assert parse_token_quantity("935 K") == 935_000.0
    assert parse_token_quantity("3.91 Mil") == 3_910_000.0
    assert parse_token_quantity("3.91Mil") == 3_910_000.0
    assert parse_token_quantity("24.2 mil") == 24_200_000.0
    assert parse_token_quantity("1.5 M") == 1_500_000.0
    assert parse_token_quantity("2M") == 2_000_000.0
    assert parse_token_quantity("0") == 0.0
    assert parse_token_quantity("191 K") == 191_000.0
    assert parse_token_quantity("123") == 123.0


def test_parse_token_quantity_fixture_files():
    bills_dir = Path(__file__).resolve().parents[1] / "bills" / "rg-techlab-ai-coding" / "token"
    if not bills_dir.is_dir():
        return

    import csv

    def file_total(name: str, model: str) -> float:
        path = bills_dir / name
        total = 0.0
        with path.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                for key, val in row.items():
                    if key and key.strip().strip('"') == model:
                        total += parse_token_quantity(val)
        return total

    assert file_total("input-tokens.csv", "gpt-5.3-codex") == 521_227_000.0
    assert file_total("input-tokens.csv", "gpt-5.4") == 224_000.0
    assert file_total("output-tokens.csv", "gpt-5.3-codex") == 2_592_930.0


def test_infer_token_direction_from_filename():
    assert infer_token_direction("input-tokens.csv") == "input"
    assert infer_token_direction("Output Tokens-data.csv") == "output"


def test_token_ingest_grafana_csv(tmp_path):
    bills_dir = tmp_path / "bills"
    token_dir = bills_dir / "rg-techlab-ai-coding" / "token"
    token_dir.mkdir(parents=True)

    (token_dir / "input-tokens.csv").write_text(
        '"Time","gpt-5.3-codex","gpt-5.4"\n'
        "2026-05-07 10:37:00,3.91 Mil,0\n"
        "2026-05-07 16:37:00,24.2 Mil,0\n",
        encoding="utf-8",
    )
    (token_dir / "output-tokens.csv").write_text(
        '"Time","gpt-5.3-codex","gpt-5.4"\n'
        "2026-05-07 10:37:00,46.2 K,0\n"
        "2026-05-07 16:37:00,123 K,0\n",
        encoding="utf-8",
    )

    discovered = discover_token_csv_files(bills_dir)
    assert len(discovered) == 2

    db_path = tmp_path / "cost_mgmt.sqlite3"
    r1 = ingest_token_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    assert r1.files_ingested == 2
    assert r1.rows_ingested > 0
    assert r1.verification_passed is True

    missing = list_missing_token_files(bills_dir=bills_dir, db_path=db_path)
    assert missing == []

    conn = get_connection(db_path)
    try:
        init_db(conn)
        assert project_has_imported_tokens(conn, "rg-techlab-ai-coding")
        in_tok, out_tok = get_imported_token_totals(conn, "rg-techlab-ai-coding")
        assert in_tok == 28_110_000.0
        assert out_tok == 169_200.0
    finally:
        conn.close()

    r2 = ingest_token_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    assert r2.files_skipped == 2
    assert r2.files_ingested == 0


def test_billing_ingest_ignores_token_subdirectory(tmp_path):
    from app.ingest import discover_csv_files, ingest_all

    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projA"
    token_dir = project_dir / "token"
    token_dir.mkdir(parents=True)
    project_dir.mkdir(parents=True, exist_ok=True)

    (project_dir / "bill.csv").write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-03-01","1.0","1.0","","USD"\n',
        encoding="utf-8",
    )
    (token_dir / "input.csv").write_text(
        '"Time","gpt-5.3-codex"\n2026-05-07 10:37:00,1 K\n',
        encoding="utf-8",
    )

    billing_files = discover_csv_files(bills_dir)
    assert len(billing_files) == 1
    assert billing_files[0][2] == "projA/bill.csv"

    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM token_usage_points").fetchone()[0] == 0
    finally:
        conn.close()
