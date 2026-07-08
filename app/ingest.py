from __future__ import annotations

import csv
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .db import SCHEMA_VERSION, EXPECTED_CSV_COLUMNS, ensure_parent_dir, get_connection, init_db, ensure_project


@dataclass(frozen=True)
class IngestResult:
    projects_discovered: int
    files_discovered: int
    files_skipped: int
    files_ingested: int
    rows_ingested: int
    rows_inserted: int
    rows_updated: int
    files_verified: int
    verification_passed: bool


def _verify_billing_merge_csv(
    conn,
    *,
    project_name: str,
    file_path_rel: str,
    checksum_sha256: str,
    csv_path_abs: Path,
    expected_row_count: int,
) -> None:
    """
    Post-ingest audit for billing CSVs merged by natural key
    (UsageDate + ResourceId + ResourceGroupName + ServiceTier + Meter within project_name).

    - Every non-empty CSV row must resolve to a DB row with matching cost_usd.
    - Duplicate keys in the same file: merge preserves Actual when a later row is forecast-only.
    - ingested_files row_count must match CSV data row count.
    """
    eps = 1e-6
    last_cost_by_key: dict[tuple[str, str, str, str, str], float | None] = {}
    csv_data_rows = 0
    with csv_path_abs.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            usage_date, normalized_row, cost_usd, _cost = _extract_row(row)
            if usage_date is None:
                continue
            csv_data_rows += 1
            key = _billing_natural_key_tuple(usage_date, normalized_row)
            last_cost_by_key[key] = _merge_billing_cost_usd(
                last_cost_by_key.get(key),
                cost_usd,
            )

    if csv_data_rows != expected_row_count:
        raise ValueError(
            f"Ingest audit CSV row count mismatch for {file_path_rel}: parsed={csv_data_rows}, expected={expected_row_count}"
        )

    for key, exp_c in last_cost_by_key.items():
        usage_date, resource_id, rg, tier, meter = key
        r = conn.execute(
            """
            SELECT cost_usd
            FROM transactions
            WHERE project_name = ?
              AND usage_date = ?
              AND COALESCE(resource_id, '') = ?
              AND COALESCE(resource_group_name, '') = ?
              AND COALESCE(service_tier, '') = ?
              AND COALESCE(meter, '') = ?
            LIMIT 1
            """,
            (project_name, usage_date, resource_id, rg, tier, meter),
        ).fetchone()
        if r is None:
            raise ValueError(
                f"Ingest audit missing DB row for natural key after ingest: {file_path_rel} {key!r}"
            )
        db_c = float(r["cost_usd"]) if r["cost_usd"] is not None else None
        if exp_c is None and db_c is None:
            continue
        if exp_c is None or db_c is None:
            raise ValueError(
                f"Ingest audit cost_usd mismatch for {file_path_rel} key={key!r}: db={db_c}, expected={exp_c}"
            )
        if abs(db_c - exp_c) > eps:
            raise ValueError(
                f"Ingest audit cost_usd mismatch for {file_path_rel} key={key!r}: db={db_c}, expected={exp_c}"
            )

    ing = conn.execute(
        """
        SELECT checksum_sha256, row_count
        FROM ingested_files
        WHERE file_path = ?
        """,
        (file_path_rel,),
    ).fetchone()
    if ing is None:
        raise ValueError(f"Ingest audit missing ingested_files row for {file_path_rel}")
    if str(ing["checksum_sha256"]) != str(checksum_sha256):
        raise ValueError(
            f"Ingest audit checksum mismatch for {file_path_rel}: db={ing['checksum_sha256']}, expected={checksum_sha256}"
        )
    if int(ing["row_count"]) != expected_row_count:
        raise ValueError(
            f"Ingest audit ingested_files row_count mismatch for {file_path_rel}: db={int(ing['row_count'])}, expected={expected_row_count}"
        )


def _count_billing_csv_data_rows(csv_path_abs: Path) -> int:
    n = 0
    with csv_path_abs.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            usage_date, _norm, _c1, _c2 = _extract_row(row)
            if usage_date is None:
                continue
            n += 1
    return n


@dataclass(frozen=True)
class IngestVerifyResultItem:
    file_path_rel: str
    pass_check: bool
    error: str | None = None


@dataclass(frozen=True)
class IngestVerifyResult:
    limit: int
    items: list[IngestVerifyResultItem]

    @property
    def pass_count(self) -> int:
        return sum(1 for x in self.items if x.pass_check)

    @property
    def fail_count(self) -> int:
        return sum(1 for x in self.items if not x.pass_check)


def verify_ingested_files(
    bills_dir: str | os.PathLike[str],
    db_path: str | os.PathLike[str],
    *,
    limit: int = 50,
    file_path_rels: list[str] | None = None,
) -> IngestVerifyResult:
    """
    Verify that data on disk (CSV) matches SQLite for each ingested billing file:
    natural key rows (UsageDate + ResourceId + ResourceGroupName + ServiceTier + Meter per project),
    checksum, and ingested_files.row_count.
    """
    bills_path = Path(bills_dir).expanduser().resolve()

    conn = get_connection(db_path)
    init_db(conn)
    try:
        if file_path_rels:
            # Verify the exact list of ingested files (in the same order as requested).
            items: list[IngestVerifyResultItem] = []
            for file_path_rel in file_path_rels:
                ing = conn.execute(
                    """
                    SELECT project_name, file_path, checksum_sha256, row_count
                    FROM ingested_files
                    WHERE file_path = ?
                    """,
                    (file_path_rel,),
                ).fetchone()
                if ing is None:
                    items.append(
                        IngestVerifyResultItem(
                            file_path_rel=file_path_rel,
                            pass_check=False,
                            error="Ingest record not found for file_path_rel",
                        )
                    )
                    continue

                project_name = ing["project_name"]
                try:
                    csv_path_abs = (bills_path / file_path_rel).expanduser().resolve()
                    if not csv_path_abs.exists():
                        raise FileNotFoundError(f"Missing CSV file for {file_path_rel}")

                    checksum = _sha256_file(csv_path_abs)
                    rc = _count_billing_csv_data_rows(csv_path_abs)
                    _verify_billing_merge_csv(
                        conn,
                        project_name=project_name,
                        file_path_rel=file_path_rel,
                        checksum_sha256=checksum,
                        csv_path_abs=csv_path_abs,
                        expected_row_count=rc,
                    )
                    items.append(IngestVerifyResultItem(file_path_rel=file_path_rel, pass_check=True, error=None))
                except Exception as e:
                    items.append(IngestVerifyResultItem(file_path_rel=file_path_rel, pass_check=False, error=str(e)))

            return IngestVerifyResult(limit=len(file_path_rels), items=items)

        # Default behavior: verify the latest N ingested files.
        limit = max(1, min(int(limit), 200))
        rows = conn.execute(
            """
            SELECT project_name, file_path, checksum_sha256, row_count
            FROM ingested_files
            ORDER BY ingested_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        items: list[IngestVerifyResultItem] = []
        for r in rows:
            project_name = r["project_name"]
            file_path_rel = r["file_path"]

            try:
                csv_path_abs = (bills_path / file_path_rel).expanduser().resolve()
                if not csv_path_abs.exists():
                    raise FileNotFoundError(f"Missing CSV file for {file_path_rel}")

                checksum = _sha256_file(csv_path_abs)
                rc = _count_billing_csv_data_rows(csv_path_abs)
                _verify_billing_merge_csv(
                    conn,
                    project_name=project_name,
                    file_path_rel=file_path_rel,
                    checksum_sha256=checksum,
                    csv_path_abs=csv_path_abs,
                    expected_row_count=rc,
                )
                items.append(IngestVerifyResultItem(file_path_rel=file_path_rel, pass_check=True, error=None))
            except Exception as e:
                items.append(
                    IngestVerifyResultItem(
                        file_path_rel=file_path_rel,
                        pass_check=False,
                        error=str(e),
                    )
                )

        return IngestVerifyResult(limit=limit, items=items)
    finally:
        conn.close()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalize_key(k: str) -> str:
    return k.strip().strip("\ufeff").strip('"').strip("'").lower().replace(" ", "_")


def _csv_field(row: dict[str, Any], column: str) -> str | None:
    normalized = {_normalize_key(k): v for k, v in row.items()}
    return _trim_optional_str(normalized.get(_normalize_key(column)))


def _to_float_or_none(val: Any) -> float | None:
    if val is None:
        return None
    s = str(val).strip()
    if s == "" or s.lower() in {"null", "none"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _trim_optional_str(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    if s == "" or s.lower() in {"null", "none"}:
        return None
    return s


def _extract_row(
    fields: dict[str, Any],
) -> tuple[str | None, dict[str, str | None], float | None, float | None]:
    """
    Returns:
      - usage_date: CSV UsageDate as trimmed string (or None)
      - normalized_row: keys match EXPECTED_CSV_COLUMNS with trimmed strings (or None)
      - parsed numeric: cost_usd, cost
    """
    normalized = {_normalize_key(k): v for k, v in fields.items()}

    normalized_row: dict[str, str | None] = {}
    for expected_col in EXPECTED_CSV_COLUMNS:
        raw_val = normalized.get(_normalize_key(expected_col))
        normalized_row[expected_col] = _trim_optional_str(raw_val)

    usage_date = normalized_row.get("UsageDate")
    if usage_date is None:
        return None, normalized_row, None, None

    cost_usd = _to_float_or_none(normalized_row.get("CostUSD"))
    cost = _to_float_or_none(normalized_row.get("Cost"))

    return usage_date, normalized_row, cost_usd, cost


def _to_forecast_or_none(val: Any) -> float | None:
    return _to_float_or_none(val)


def _merge_billing_cost_usd(
    existing: float | None,
    incoming: float | None,
) -> float | None:
    """
    Merge CostUSD for rows sharing a billing natural key.

    Forecast-only trailing rows (empty CostUSD) must not erase an earlier Actual
    row for the same UsageDate + resource dimensions within one CSV export.
    """
    if incoming is not None:
        return incoming
    return existing


def _merge_billing_forecast_cost(
    existing: float | None,
    incoming: float | None,
) -> float | None:
    if incoming is not None:
        return incoming
    return existing


_TX_INSERT = """
INSERT INTO transactions(
    project_name, usage_date,
    resource_id, resource_type, resource_location, resource_group_name,
    service_name, service_tier, meter,
    cost_usd, cost, currency, forecast_cost,
    raw_json, source_file, source_row_index
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_TX_UPDATE = """
UPDATE transactions SET
    project_name = ?,
    usage_date = ?,
    resource_id = ?,
    resource_type = ?,
    resource_location = ?,
    resource_group_name = ?,
    service_name = ?,
    service_tier = ?,
    meter = ?,
    cost_usd = ?,
    cost = ?,
    currency = ?,
    forecast_cost = ?,
    raw_json = ?,
    source_file = ?,
    source_row_index = ?,
    ingested_at = datetime('now')
WHERE id = ?
"""


def _coalesce_billing_dim(val: Any) -> str:
    s = _trim_optional_str(val)
    return s if s is not None else ""


def _billing_natural_key_tuple(usage_date: str, normalized_row: dict[str, str | None]) -> tuple[str, str, str, str, str]:
    return (
        usage_date,
        _coalesce_billing_dim(normalized_row.get("ResourceId")),
        _coalesce_billing_dim(normalized_row.get("ResourceGroupName")),
        _coalesce_billing_dim(normalized_row.get("ServiceTier")),
        _coalesce_billing_dim(normalized_row.get("Meter")),
    )


def _find_tx_by_natural_key(
    conn,
    project_name: str,
    usage_date: str,
    resource_id: str,
    rg: str,
    tier: str,
    meter: str,
) -> int | None:
    row = conn.execute(
        """
        SELECT id FROM transactions
        WHERE project_name = ?
          AND usage_date = ?
          AND COALESCE(resource_id, '') = ?
          AND COALESCE(resource_group_name, '') = ?
          AND COALESCE(service_tier, '') = ?
          AND COALESCE(meter, '') = ?
        LIMIT 1
        """,
        (project_name, usage_date, resource_id, rg, tier, meter),
    ).fetchone()
    return int(row["id"]) if row else None


def _find_tx_by_file_slot(conn, project_name: str, file_path_rel: str, source_row_index: int) -> int | None:
    row = conn.execute(
        """
        SELECT id FROM transactions
        WHERE project_name = ? AND source_file = ? AND source_row_index = ?
        LIMIT 1
        """,
        (project_name, file_path_rel, source_row_index),
    ).fetchone()
    return int(row["id"]) if row else None


def _upsert_one_billing_row(
    conn,
    *,
    project_name: str,
    file_path_rel: str,
    source_row_index: int,
    usage_date: str,
    normalized_row: dict[str, str | None],
    cost_usd: float | None,
    cost: float | None,
    forecast_cost: float | None,
    raw_json: str,
) -> str:
    """
    Upsert by natural key (UsageDate + ResourceId + ResourceGroupName + ServiceTier + Meter) within project;
    same-file (source_file, source_row_index) wins over stale slots when both collide.
    Returns 'insert' or 'update'.
    """
    _usage_date, resource_k, rg_k, tier_k, meter_k = _billing_natural_key_tuple(usage_date, normalized_row)

    kid = _find_tx_by_natural_key(
        conn, project_name, usage_date, resource_k, rg_k, tier_k, meter_k
    )
    rid = _find_tx_by_file_slot(conn, project_name, file_path_rel, source_row_index)

    existing_cost_usd: float | None = None
    existing_cost: float | None = None
    existing_forecast: float | None = None
    if kid is not None:
        existing_row = conn.execute(
            "SELECT cost_usd, cost, forecast_cost FROM transactions WHERE id = ?",
            (kid,),
        ).fetchone()
        if existing_row is not None:
            existing_cost_usd = _to_float_or_none(existing_row["cost_usd"])
            existing_cost = _to_float_or_none(existing_row["cost"])
            existing_forecast = _to_float_or_none(existing_row["forecast_cost"])

    merged_cost_usd = _merge_billing_cost_usd(existing_cost_usd, cost_usd)
    merged_cost = _merge_billing_cost_usd(existing_cost, cost)
    merged_forecast = _merge_billing_forecast_cost(existing_forecast, forecast_cost)

    tup = (
        project_name,
        usage_date,
        normalized_row.get("ResourceId"),
        normalized_row.get("ResourceType"),
        normalized_row.get("ResourceLocation"),
        normalized_row.get("ResourceGroupName"),
        normalized_row.get("ServiceName"),
        normalized_row.get("ServiceTier"),
        normalized_row.get("Meter"),
        merged_cost_usd,
        merged_cost,
        normalized_row.get("Currency"),
        merged_forecast,
        raw_json,
        file_path_rel,
        source_row_index,
    )

    if kid is not None and rid is not None and kid != rid:
        conn.execute("DELETE FROM transactions WHERE id = ?", (rid,))
        conn.execute(_TX_UPDATE, tup + (kid,))
        return "update"
    if kid is not None:
        conn.execute(_TX_UPDATE, tup + (kid,))
        return "update"
    if rid is not None:
        conn.execute(_TX_UPDATE, tup + (rid,))
        return "update"
    conn.execute(_TX_INSERT, tup)
    return "insert"


def _ingest_billing_csv_rows(
    conn,
    *,
    project_name: str,
    file_path_rel: str,
    csv_path_abs: Path,
) -> tuple[int, int]:
    file_ins = 0
    file_upd = 0
    with csv_path_abs.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        row_index = 0
        for row in reader:
            usage_date, normalized_row, cost_usd, cost = _extract_row(row)
            if usage_date is None:
                row_index += 1
                continue

            raw_json = json.dumps(normalized_row, ensure_ascii=False)
            forecast_cost = _to_forecast_or_none(
                _csv_field(row, "ForecastCost"),
            )
            op = _upsert_one_billing_row(
                conn,
                project_name=project_name,
                file_path_rel=file_path_rel,
                source_row_index=row_index,
                usage_date=usage_date,
                normalized_row=normalized_row,
                cost_usd=cost_usd,
                cost=cost,
                forecast_cost=forecast_cost,
                raw_json=raw_json,
            )
            if op == "insert":
                file_ins += 1
            else:
                file_upd += 1
            row_index += 1
    return file_ins, file_upd


def _finalize_billing_file_ingest(
    conn,
    *,
    project_name: str,
    file_path_rel: str,
    checksum: str,
    data_rows: int,
    csv_path_abs: Path,
    raw_columns: list[str],
) -> None:
    conn.execute(
        """
        INSERT INTO ingested_files(
            project_name, file_path, checksum_sha256, schema_version,
            row_count, source_last_modified, raw_columns
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_name,
            file_path_rel,
            checksum,
            SCHEMA_VERSION,
            data_rows,
            csv_path_abs.stat().st_mtime,
            json.dumps(raw_columns, ensure_ascii=False),
        ),
    )
    try:
        _verify_billing_merge_csv(
            conn,
            project_name=project_name,
            file_path_rel=file_path_rel,
            checksum_sha256=checksum,
            csv_path_abs=csv_path_abs,
            expected_row_count=data_rows,
        )
        conn.execute("RELEASE ingest_file")
        conn.commit()
    except Exception:
        conn.execute("ROLLBACK TO ingest_file")
        conn.execute("RELEASE ingest_file")
        raise


def discover_csv_files(bills_dir: str | os.PathLike[str]) -> list[tuple[str, Path, str]]:
    """
    Returns list of (project_name, csv_path_abs, file_path_rel).
    file_path_rel format: <project>/<filename>.csv
    """
    bills_path = Path(bills_dir).expanduser().resolve()
    if not bills_path.exists():
        return []

    results: list[tuple[str, Path, str]] = []
    for project_dir in sorted(bills_path.glob("*")):
        if not project_dir.is_dir():
            continue
        project_name = project_dir.name
        # Do not treat the dedicated model price directory as a billing project.
        if project_name.strip().lower() in {"price", "prices"}:
            continue
        for csv_path in sorted(project_dir.glob("*.csv")):
            rel_path = str(csv_path.relative_to(bills_path))
            results.append((project_name, csv_path, rel_path))
    return results


def _billing_reimport_should_skip(
    *,
    existing,
    csv_path_abs: Path,
    reimport_changed: bool,
    reimport_force: bool,
) -> bool:
    if existing is None:
        return False
    if not reimport_changed and not reimport_force:
        return True
    if reimport_force:
        return False
    checksum = _sha256_file(csv_path_abs)
    return str(existing["checksum_sha256"]) == checksum


def _billing_clear_file_slot_for_reimport(
    conn,
    *,
    project_name: str,
    file_path_rel: str,
) -> None:
    conn.execute("DELETE FROM ingested_files WHERE file_path = ?", (file_path_rel,))
    conn.execute(
        "DELETE FROM transactions WHERE project_name = ? AND source_file = ?",
        (project_name, file_path_rel),
    )


def ingest_all(
    bills_dir: str | os.PathLike[str],
    db_path: str | os.PathLike[str],
    *,
    reimport_changed: bool = False,
    reimport_force: bool = False,
) -> IngestResult:
    ensure_parent_dir(db_path)
    conn = get_connection(db_path)
    init_db(conn)

    files = discover_csv_files(bills_dir)
    files_discovered = len(files)
    files_skipped = 0
    files_ingested = 0
    rows_ingested = 0
    rows_inserted = 0
    rows_updated = 0
    files_verified = 0
    verification_passed = True

    projects = set()

    for project_name, csv_path_abs, file_path_rel in files:
        projects.add(project_name)
        ensure_project(conn, project_name)
        existing = conn.execute(
            "SELECT checksum_sha256 FROM ingested_files WHERE file_path = ?",
            (file_path_rel,),
        ).fetchone()

        if _billing_reimport_should_skip(
            existing=existing,
            csv_path_abs=csv_path_abs,
            reimport_changed=reimport_changed,
            reimport_force=reimport_force,
        ):
            files_skipped += 1
            continue

        conn.execute("SAVEPOINT ingest_file")
        if existing is not None:
            _billing_clear_file_slot_for_reimport(
                conn,
                project_name=project_name,
                file_path_rel=file_path_rel,
            )
        else:
            _sha256_file(csv_path_abs)

        file_ins, file_upd = _ingest_billing_csv_rows(
            conn,
            project_name=project_name,
            file_path_rel=file_path_rel,
            csv_path_abs=csv_path_abs,
        )
        data_rows = file_ins + file_upd
        checksum = _sha256_file(csv_path_abs)
        with csv_path_abs.open("r", newline="", encoding="utf-8-sig") as f:
            raw_columns = csv.DictReader(f).fieldnames or []

        try:
            _finalize_billing_file_ingest(
                conn,
                project_name=project_name,
                file_path_rel=file_path_rel,
                checksum=checksum,
                data_rows=data_rows,
                csv_path_abs=csv_path_abs,
                raw_columns=list(raw_columns or []),
            )
        except Exception:
            verification_passed = False
            raise

        files_ingested += 1
        rows_ingested += data_rows
        rows_inserted += file_ins
        rows_updated += file_upd
        files_verified += 1

    conn.close()
    return IngestResult(
        projects_discovered=len(projects),
        files_discovered=files_discovered,
        files_skipped=files_skipped,
        files_ingested=files_ingested,
        rows_ingested=rows_ingested,
        rows_inserted=rows_inserted,
        rows_updated=rows_updated,
        files_verified=files_verified,
        verification_passed=verification_passed,
    )


def ingest_selected(
    bills_dir: str | os.PathLike[str],
    db_path: str | os.PathLike[str],
    *,
    file_path_rels: list[str],
    reimport_changed: bool = False,
    reimport_force: bool = False,
) -> IngestResult:
    """
    Ingest only the specified bills files (by `file_path_rel` = <project>/<filename>.csv).
    """
    file_set = {str(x) for x in file_path_rels}
    ensure_parent_dir(db_path)
    conn = get_connection(db_path)
    init_db(conn)

    files = discover_csv_files(bills_dir)
    selected = [f for f in files if f[2] in file_set]

    files_discovered = len(selected)
    files_skipped = 0
    files_ingested = 0
    rows_ingested = 0
    rows_inserted = 0
    rows_updated = 0
    files_verified = 0
    verification_passed = True

    projects = set()
    for project_name, csv_path_abs, file_path_rel in selected:
        projects.add(project_name)
        ensure_project(conn, project_name)

        existing = conn.execute(
            "SELECT checksum_sha256 FROM ingested_files WHERE file_path = ?",
            (file_path_rel,),
        ).fetchone()

        if _billing_reimport_should_skip(
            existing=existing,
            csv_path_abs=csv_path_abs,
            reimport_changed=reimport_changed,
            reimport_force=reimport_force,
        ):
            files_skipped += 1
            continue

        conn.execute("SAVEPOINT ingest_file")
        if existing is not None:
            _billing_clear_file_slot_for_reimport(
                conn,
                project_name=project_name,
                file_path_rel=file_path_rel,
            )
        else:
            _sha256_file(csv_path_abs)

        file_ins, file_upd = _ingest_billing_csv_rows(
            conn,
            project_name=project_name,
            file_path_rel=file_path_rel,
            csv_path_abs=csv_path_abs,
        )
        data_rows = file_ins + file_upd
        checksum = _sha256_file(csv_path_abs)
        with csv_path_abs.open("r", newline="", encoding="utf-8-sig") as f:
            raw_columns = csv.DictReader(f).fieldnames or []

        try:
            _finalize_billing_file_ingest(
                conn,
                project_name=project_name,
                file_path_rel=file_path_rel,
                checksum=checksum,
                data_rows=data_rows,
                csv_path_abs=csv_path_abs,
                raw_columns=list(raw_columns or []),
            )
        except Exception:
            verification_passed = False
            raise

        files_ingested += 1
        rows_ingested += data_rows
        rows_inserted += file_ins
        rows_updated += file_upd
        files_verified += 1

    conn.close()
    return IngestResult(
        projects_discovered=len(projects),
        files_discovered=files_discovered,
        files_skipped=files_skipped,
        files_ingested=files_ingested,
        rows_ingested=rows_ingested,
        rows_inserted=rows_inserted,
        rows_updated=rows_updated,
        files_verified=files_verified,
        verification_passed=verification_passed,
    )


def list_missing_files(
    bills_dir: str | os.PathLike[str],
    db_path: str | os.PathLike[str],
) -> list[dict[str, object]]:
    """
    Return local CSV files under bills/<project> that are not yet ingested.

    Output items:
      - project_name
      - file_path_rel (format: <project>/<filename>.csv relative to bills/)
      - source_last_modified (mtime)
    """
    conn = get_connection(db_path)
    try:
        init_db(conn)
        bills_path = Path(bills_dir).expanduser().resolve()
        if not bills_path.exists():
            return []

        existing = conn.execute("SELECT file_path FROM ingested_files").fetchall()
        ingested_paths = {r["file_path"] for r in existing}

        files = discover_csv_files(bills_dir)
        missing: list[dict[str, object]] = []
        for project_name, csv_path_abs, file_path_rel in files:
            if file_path_rel in ingested_paths:
                continue
            missing.append(
                {
                    "project_name": project_name,
                    "file_path_rel": file_path_rel,
                    "file_kind": "billing",
                    "source_last_modified": float(csv_path_abs.stat().st_mtime),
                }
            )
        # Sort by mtime desc to show recent bills first.
        missing.sort(key=lambda x: x["source_last_modified"], reverse=True)
        return missing
    finally:
        conn.close()


def list_ingested_files(
    db_path: str | os.PathLike[str],
    *,
    limit: int = 50,
) -> list[dict[str, object]]:
    """
    List files already ingested into the DB.
    """
    limit = max(1, min(int(limit), 200))
    conn = get_connection(db_path)
    try:
        init_db(conn)
        rows = conn.execute(
            """
            SELECT
                project_name,
                file_path,
                row_count,
                ingested_at,
                source_last_modified
            FROM ingested_files
            ORDER BY ingested_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        return [
            {
                "project_name": r["project_name"],
                "file_path_rel": r["file_path"],
                "file_kind": "billing",
                "row_count": int(r["row_count"]),
                "ingested_at": r["ingested_at"],
                "source_last_modified": r["source_last_modified"],
            }
            for r in rows
        ]
    finally:
        conn.close()

