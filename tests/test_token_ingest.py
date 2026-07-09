from __future__ import annotations

import sqlite3
from pathlib import Path

from app.db import (
    get_imported_token_totals,
    get_imported_token_totals_by_subproject,
    get_connection,
    init_db,
    project_has_imported_tokens,
)
from app.token_ingest import (
    compare_token_csv_natural_keys,
    discover_token_csv_files,
    ingest_token_all,
    ingest_token_selected,
    infer_token_direction,
    iter_token_csv_points,
    list_missing_token_files,
    parse_token_quantity,
    verify_ingested_token_files,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MDM_PROJECT = "RG-HK-S56-MDM-Coding"
_MDM_TOKEN_DIR = _REPO_ROOT / "bills" / _MDM_PROJECT / "token"
_MDM_WINDOW = ("2026-06-29", "2026-07-05")
# Golden totals for _MDM_WINDOW — derived from bills/RG-HK-S56-MDM-Coding Grafana CSVs.
_MDM_SUBPROJECT_TOTALS: dict[str, tuple[float, float]] = {
    "proj-mdm-coding-1-resource": (23_315_500.0, 258_022.0),
    "proj-mdm-coding-2-resource": (8_702_200.0, 66_720.0),
    "proj-mdm-coding-3-resource": (71_006_000.0, 418_400.0),
    "proj-mdm-coding-4-resource": (112_520_000.0, 420_800.0),
    "proj-mdm-coding-5-resource": (47_628_000.0, 261_520.0),
    "proj-mdm-coding-6-resource": (210_110_000.0, 1_158_000.0),
}
_MDM_PROJECT_TOTALS = (473_281_700.0, 2_583_462.0)
_MDM_POINT_COUNT = 434
_MDM_FILE_COUNT = 12


def _mdm_fixture_available() -> bool:
    if not _MDM_TOKEN_DIR.is_dir():
        return False
    discovered = [
        rel
        for pn, _, rel, _ in discover_token_csv_files(_REPO_ROOT / "bills")
        if pn == _MDM_PROJECT
    ]
    return len(discovered) == _MDM_FILE_COUNT


def _mdm_token_file_rels() -> list[str]:
    return [
        rel
        for pn, _, rel, _ in discover_token_csv_files(_REPO_ROOT / "bills")
        if pn == _MDM_PROJECT
    ]


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

    input_15 = bills_dir / "input-tokens-2026-5-15.csv"
    if not input_15.is_file():
        return
    assert file_total("input-tokens-2026-5-15.csv", "gpt-5.3-codex") > 0
    output_15 = bills_dir / "output-tokens-2026-5-15.csv"
    if output_15.is_file():
        assert file_total("output-tokens-2026-5-15.csv", "gpt-5.3-codex") > 0


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


def test_token_natural_key_upsert_newer_file_wins(tmp_path):
    bills_dir = tmp_path / "bills"
    token_dir = bills_dir / "proj" / "token"
    token_dir.mkdir(parents=True)

    older = token_dir / "input-tokens-2026-5-15.csv"
    newer = token_dir / "input-tokens-2026-5-16.csv"
    import os

    older.write_text(
        '"Time","gpt-5.3-codex"\n'
        "2026-05-14 00:00:00,1 Mil\n",
        encoding="utf-8",
    )
    newer.write_text(
        '"Time","gpt-5.3-codex"\n'
        "2026-05-14 00:00:00,2 Mil\n",
        encoding="utf-8",
    )
    os.utime(older, (1_000_000, 1_000_000))
    os.utime(newer, (2_000_000, 2_000_000))

    db_path = tmp_path / "cost_mgmt.sqlite3"
    r = ingest_token_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    assert r.files_ingested == 2
    assert r.rows_replaced >= 1

    conn = get_connection(db_path)
    try:
        init_db(conn)
        row = conn.execute(
            """
            SELECT token_count, source_file
            FROM token_usage_points
            WHERE project_name = 'proj'
              AND subproject_name = ''
              AND token_direction = 'input'
              AND recorded_at = '2026-05-14 00:00:00'
              AND model_name = 'gpt-5.3-codex'
            """
        ).fetchone()
        assert row is not None
        assert float(row["token_count"]) == 2_000_000.0
        assert str(row["source_file"]).endswith("input-tokens-2026-5-16.csv")
    finally:
        conn.close()


def test_rg_mdm_coding_token_ingest_stats_and_dedup(tmp_path):
    """
    Regression fixture: bills/RG-HK-S56-MDM-Coding (6 subprojects × IN/OUT).

    Validates import parsing, natural-key storage, and SUM(token_count) stats.
    """
    if not _mdm_fixture_available():
        return

    bills_dir = _REPO_ROOT / "bills"
    db_path = tmp_path / "cost_mgmt.sqlite3"
    file_rels = _mdm_token_file_rels()

    expected_points = 0
    for pn, csv_path, rel, sub in discover_token_csv_files(bills_dir):
        if pn != _MDM_PROJECT:
            continue
        _, points, _ = iter_token_csv_points(
            csv_path, project_name=pn, file_path_rel=rel, subproject_name=sub
        )
        expected_points += len(points)
    assert expected_points == _MDM_POINT_COUNT

    r1 = ingest_token_selected(
        bills_dir=bills_dir,
        db_path=db_path,
        file_path_rels=file_rels,
        reimport_changed=False,
    )
    assert r1.files_ingested == _MDM_FILE_COUNT
    assert r1.verification_passed is True

    verify = verify_ingested_token_files(bills_dir, db_path, file_path_rels=file_rels)
    assert verify.fail_count == 0

    conn = get_connection(db_path)
    try:
        init_db(conn)
        assert project_has_imported_tokens(conn, _MDM_PROJECT)
        db_points = conn.execute(
            "SELECT COUNT(*) FROM token_usage_points WHERE project_name = ?",
            (_MDM_PROJECT,),
        ).fetchone()[0]
        assert db_points == _MDM_POINT_COUNT

        start, end = _MDM_WINDOW
        by_sub = {
            r["subproject_name"]: r
            for r in get_imported_token_totals_by_subproject(
                conn, _MDM_PROJECT, start_date=start, end_date=end
            )
        }
        assert set(by_sub) == set(_MDM_SUBPROJECT_TOTALS)
        for sub, (exp_in, exp_out) in _MDM_SUBPROJECT_TOTALS.items():
            assert float(by_sub[sub]["input_tokens"]) == exp_in
            assert float(by_sub[sub]["output_tokens"]) == exp_out

        proj_in, proj_out = get_imported_token_totals(
            conn, _MDM_PROJECT, start_date=start, end_date=end
        )
        assert proj_in == _MDM_PROJECT_TOTALS[0]
        assert proj_out == _MDM_PROJECT_TOTALS[1]
    finally:
        conn.close()

    r2 = ingest_token_selected(
        bills_dir=bills_dir,
        db_path=db_path,
        file_path_rels=file_rels,
        reimport_changed=False,
    )
    assert r2.files_skipped == _MDM_FILE_COUNT
    assert r2.files_ingested == 0


def test_rg_techlab_input_csv_no_exact_time_overlap():
    bills_dir = Path(__file__).resolve().parents[1] / "bills" / "rg-techlab-ai-coding" / "token"
    if not bills_dir.is_dir():
        return
    report = compare_token_csv_natural_keys(
        bills_dir / "input-tokens-2026-5-15.csv",
        bills_dir / "input-tokens-2026-5-16.csv",
    )
    assert report.exact_overlap_count == 0
    assert "2026-05-14" in report.calendar_date_overlap


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
