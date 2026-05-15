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
    files_verified: int
    verification_passed: bool


def _verify_ingestion_for_file(
    conn,
    *,
    project_name: str,
    file_path_rel: str,
    checksum_sha256: str,
    expected_by_date: dict[str, dict[str, object]],
) -> None:
    """
    Strong correctness audit ("对数") for a single imported file:
    - compare per-usage_date row counts and cost_usd sums
    - compare total row count and cost_usd sum
    - compare ingested_files row_count and checksum_sha256
    """
    eps = 1e-6
    expected_dates = set(expected_by_date.keys())
    expected_total_rows = 0
    expected_total_cost_usd = 0.0
    expected_by_db: dict[str, dict[str, object]] = {}

    for d, agg in expected_by_date.items():
        cnt = int(agg["count"])
        cost_sum = float(agg["cost_sum"])
        expected_total_rows += cnt
        expected_total_cost_usd += cost_sum
        expected_by_db[d] = {"count": cnt, "cost_sum": cost_sum}

    rows_by_date = conn.execute(
        """
        SELECT
          usage_date,
          COUNT(*) AS cnt,
          COALESCE(SUM(cost_usd), 0) AS sum_cost_usd
        FROM transactions
        WHERE source_file = ?
        GROUP BY usage_date
        """,
        (file_path_rel,),
    ).fetchall()

    db_dates = {r["usage_date"] for r in rows_by_date}
    if db_dates != expected_dates:
        raise ValueError(
            f"Ingest audit date mismatch for {file_path_rel}: db_dates={sorted(db_dates)}, expected={sorted(expected_dates)}"
        )

    for r in rows_by_date:
        d = r["usage_date"]
        cnt = int(r["cnt"])
        sum_cost = float(r["sum_cost_usd"])
        exp = expected_by_db.get(d)
        if exp is None:
            raise ValueError(f"Ingest audit unexpected date in DB for {file_path_rel}: {d}")
        if cnt != exp["count"]:
            raise ValueError(
                f"Ingest audit row_count mismatch for {file_path_rel} date={d}: db={cnt}, expected={exp['count']}"
            )
        if abs(sum_cost - exp["cost_sum"]) > eps:
            raise ValueError(
                f"Ingest audit cost_usd sum mismatch for {file_path_rel} date={d}: db={sum_cost}, expected={exp['cost_sum']}"
            )

    total = conn.execute(
        """
        SELECT
          COUNT(*) AS cnt,
          COALESCE(SUM(cost_usd), 0) AS sum_cost_usd
        FROM transactions
        WHERE source_file = ?
        """,
        (file_path_rel,),
    ).fetchone()
    if int(total["cnt"]) != expected_total_rows:
        raise ValueError(
            f"Ingest audit total row_count mismatch for {file_path_rel}: db={int(total['cnt'])}, expected={expected_total_rows}"
        )
    if abs(float(total["sum_cost_usd"]) - expected_total_cost_usd) > eps:
        raise ValueError(
            f"Ingest audit total cost_usd sum mismatch for {file_path_rel}: db={float(total['sum_cost_usd'])}, expected={expected_total_cost_usd}"
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
    if int(ing["row_count"]) != expected_total_rows:
        raise ValueError(
            f"Ingest audit ingested_files row_count mismatch for {file_path_rel}: db={int(ing['row_count'])}, expected={expected_total_rows}"
        )


def _build_expected_by_date_from_csv(csv_path_abs: Path) -> dict[str, dict[str, object]]:
    """
    Parse CSV and build expected aggregates:
      - by UsageDate: {count, cost_sum}
    Rows with missing UsageDate are ignored (same as ingestion).
    """
    expected_by_date: dict[str, dict[str, object]] = {}
    with csv_path_abs.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            usage_date, _normalized_row, cost_usd, _cost = _extract_row(row)
            if usage_date is None:
                continue

            if usage_date not in expected_by_date:
                expected_by_date[usage_date] = {"count": 0, "cost_sum": 0.0}
            expected_by_date[usage_date]["count"] = int(expected_by_date[usage_date]["count"]) + 1
            expected_by_date[usage_date]["cost_sum"] = float(expected_by_date[usage_date]["cost_sum"]) + (
                float(cost_usd) if cost_usd is not None else 0.0
            )
    return expected_by_date


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
    Verify that data on disk (CSV) matches what was ingested into SQLite
    (row counts, cost sums, checksum, row_count in ingested_files).
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
                    expected_by_date = _build_expected_by_date_from_csv(csv_path_abs)
                    _verify_ingestion_for_file(
                        conn,
                        project_name=project_name,
                        file_path_rel=file_path_rel,
                        checksum_sha256=checksum,
                        expected_by_date=expected_by_date,
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
                expected_by_date = _build_expected_by_date_from_csv(csv_path_abs)
                _verify_ingestion_for_file(
                    conn,
                    project_name=project_name,
                    file_path_rel=file_path_rel,
                    checksum_sha256=checksum,
                    expected_by_date=expected_by_date,
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
        return None, normalized_row, None, None, None

    cost_usd = _to_float_or_none(normalized_row.get("CostUSD"))
    cost = _to_float_or_none(normalized_row.get("Cost"))

    return usage_date, normalized_row, cost_usd, cost


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


def ingest_all(
    bills_dir: str | os.PathLike[str],
    db_path: str | os.PathLike[str],
    *,
    reimport_changed: bool = False,
) -> IngestResult:
    ensure_parent_dir(db_path)
    conn = get_connection(db_path)
    init_db(conn)

    files = discover_csv_files(bills_dir)
    files_discovered = len(files)
    files_skipped = 0
    files_ingested = 0
    rows_ingested = 0
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

        if existing is not None:
            if not reimport_changed:
                files_skipped += 1
                continue
            checksum = _sha256_file(csv_path_abs)
            if str(existing["checksum_sha256"]) == checksum:
                files_skipped += 1
                continue
            # Re-import changed file: remove old rows then ingest again.
            conn.execute("SAVEPOINT ingest_file")
            conn.execute("DELETE FROM transactions WHERE source_file = ?", (file_path_rel,))
            conn.execute("DELETE FROM ingested_files WHERE file_path = ?", (file_path_rel,))
        else:
            checksum = _sha256_file(csv_path_abs)
            conn.execute("SAVEPOINT ingest_file")

        # Parse CSV and insert rows
        expected_by_date: dict[str, dict[str, object]] = {}
        with csv_path_abs.open("r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            raw_columns = reader.fieldnames or []
            to_insert: list[tuple] = []
            row_index = 0
            for row in reader:
                usage_date, normalized_row, cost_usd, cost = _extract_row(row)
                if usage_date is None:
                    row_index += 1
                    continue

                if usage_date not in expected_by_date:
                    expected_by_date[usage_date] = {"count": 0, "cost_sum": 0.0}
                expected_by_date[usage_date]["count"] = int(expected_by_date[usage_date]["count"]) + 1
                expected_by_date[usage_date]["cost_sum"] = float(expected_by_date[usage_date]["cost_sum"]) + (float(cost_usd) if cost_usd is not None else 0.0)

                raw_json = json.dumps(normalized_row, ensure_ascii=False)
                to_insert.append(
                    (
                        project_name,
                        usage_date,
                        normalized_row.get("ResourceId"),
                        normalized_row.get("ResourceType"),
                        normalized_row.get("ResourceLocation"),
                        normalized_row.get("ResourceGroupName"),
                        normalized_row.get("ServiceName"),
                        normalized_row.get("ServiceTier"),
                        normalized_row.get("Meter"),
                        cost_usd,
                        cost,
                        normalized_row.get("Currency"),
                        None,
                        raw_json,
                        file_path_rel,
                        row_index,
                    )
                )
                row_index += 1

        conn.executemany(
            """
            INSERT INTO transactions(
                project_name, usage_date,
                resource_id, resource_type, resource_location, resource_group_name,
                service_name, service_tier, meter,
                cost_usd, cost, currency, forecast_cost,
                raw_json, source_file, source_row_index
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            to_insert,
        )

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
                len(to_insert),
                csv_path_abs.stat().st_mtime,
                json.dumps(raw_columns, ensure_ascii=False),
            ),
        )

        # Audit ("对数") verification: parsed CSV totals must match DB rows for this source file.
        try:
            _verify_ingestion_for_file(
                conn,
                project_name=project_name,
                file_path_rel=file_path_rel,
                checksum_sha256=checksum,
                expected_by_date=expected_by_date,
            )
            conn.execute("RELEASE ingest_file")
            conn.commit()
            files_verified += 1
        except Exception:
            conn.execute("ROLLBACK TO ingest_file")
            conn.execute("RELEASE ingest_file")
            verification_passed = False
            raise

        files_ingested += 1
        rows_ingested += len(to_insert)

    conn.close()
    return IngestResult(
        projects_discovered=len(projects),
        files_discovered=files_discovered,
        files_skipped=files_skipped,
        files_ingested=files_ingested,
        rows_ingested=rows_ingested,
        files_verified=files_verified,
        verification_passed=verification_passed,
    )


def ingest_selected(
    bills_dir: str | os.PathLike[str],
    db_path: str | os.PathLike[str],
    *,
    file_path_rels: list[str],
    reimport_changed: bool = False,
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

        if existing is not None:
            if not reimport_changed:
                files_skipped += 1
                continue
            checksum = _sha256_file(csv_path_abs)
            if str(existing["checksum_sha256"]) == checksum:
                files_skipped += 1
                continue

            conn.execute("SAVEPOINT ingest_file")
            conn.execute("DELETE FROM transactions WHERE source_file = ?", (file_path_rel,))
            conn.execute("DELETE FROM ingested_files WHERE file_path = ?", (file_path_rel,))
        else:
            checksum = _sha256_file(csv_path_abs)
            conn.execute("SAVEPOINT ingest_file")

        expected_by_date: dict[str, dict[str, object]] = {}
        with csv_path_abs.open("r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            raw_columns = reader.fieldnames or []
            to_insert: list[tuple] = []
            row_index = 0
            for row in reader:
                usage_date, normalized_row, cost_usd, cost = _extract_row(row)
                if usage_date is None:
                    row_index += 1
                    continue

                if usage_date not in expected_by_date:
                    expected_by_date[usage_date] = {"count": 0, "cost_sum": 0.0}
                expected_by_date[usage_date]["count"] = int(expected_by_date[usage_date]["count"]) + 1
                expected_by_date[usage_date]["cost_sum"] = float(expected_by_date[usage_date]["cost_sum"]) + (
                    float(cost_usd) if cost_usd is not None else 0.0
                )

                raw_json = json.dumps(normalized_row, ensure_ascii=False)
                to_insert.append(
                    (
                        project_name,
                        usage_date,
                        normalized_row.get("ResourceId"),
                        normalized_row.get("ResourceType"),
                        normalized_row.get("ResourceLocation"),
                        normalized_row.get("ResourceGroupName"),
                        normalized_row.get("ServiceName"),
                        normalized_row.get("ServiceTier"),
                        normalized_row.get("Meter"),
                        cost_usd,
                        cost,
                        normalized_row.get("Currency"),
                        None,
                        raw_json,
                        file_path_rel,
                        row_index,
                    )
                )
                row_index += 1

        conn.executemany(
            """
            INSERT INTO transactions(
                project_name, usage_date,
                resource_id, resource_type, resource_location, resource_group_name,
                service_name, service_tier, meter,
                cost_usd, cost, currency, forecast_cost,
                raw_json, source_file, source_row_index
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            to_insert,
        )

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
                len(to_insert),
                csv_path_abs.stat().st_mtime,
                json.dumps(raw_columns, ensure_ascii=False),
            ),
        )
        try:
            _verify_ingestion_for_file(
                conn,
                project_name=project_name,
                file_path_rel=file_path_rel,
                checksum_sha256=checksum,
                expected_by_date=expected_by_date,
            )
            conn.execute("RELEASE ingest_file")
            conn.commit()
            files_verified += 1
        except Exception:
            conn.execute("ROLLBACK TO ingest_file")
            conn.execute("RELEASE ingest_file")
            verification_passed = False
            raise

        files_ingested += 1
        rows_ingested += len(to_insert)

    conn.close()
    return IngestResult(
        projects_discovered=len(projects),
        files_discovered=files_discovered,
        files_skipped=files_skipped,
        files_ingested=files_ingested,
        rows_ingested=rows_ingested,
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

