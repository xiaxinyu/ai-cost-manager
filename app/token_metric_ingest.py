from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .db import SCHEMA_VERSION, ensure_parent_dir, ensure_project, get_connection, init_db
from .ingest import _sha256_file

_METRIC_UPSERT_SQL = """
INSERT INTO token_metric_points(
    project_name, recorded_at, usage_date, model_name, metric_name,
    metric_value, metric_unit, source_file, source_row_index
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(project_name, metric_name, recorded_at, model_name)
DO UPDATE SET
    usage_date = excluded.usage_date,
    metric_value = excluded.metric_value,
    metric_unit = excluded.metric_unit,
    source_file = excluded.source_file,
    source_row_index = excluded.source_row_index,
    ingested_at = datetime('now')
"""


@dataclass(frozen=True)
class TokenMetricIngestResult:
    projects_discovered: int
    files_discovered: int
    files_skipped: int
    files_ingested: int
    rows_ingested: int
    rows_replaced: int
    files_verified: int
    files_failed: int
    verification_passed: bool
    errors: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class TokenMetricIngestVerifyResultItem:
    file_path_rel: str
    pass_check: bool
    error: str | None = None


@dataclass(frozen=True)
class TokenMetricIngestVerifyResult:
    limit: int
    items: list[TokenMetricIngestVerifyResultItem]

    @property
    def pass_count(self) -> int:
        return sum(1 for x in self.items if x.pass_check)

    @property
    def fail_count(self) -> int:
        return sum(1 for x in self.items if not x.pass_check)


def _normalize_key(k: str) -> str:
    return k.strip().strip("\ufeff").strip('"').strip("'").lower().replace(" ", "_")


def _normalize_model_name(raw: str) -> str:
    return raw.strip().strip('"').strip("'")


def _parse_recorded_at(raw_time: str) -> tuple[str, str]:
    s = raw_time.strip().strip('"')
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(s, fmt)
            recorded_at = dt.strftime("%Y-%m-%d %H:%M:%S")
            return recorded_at, dt.date().isoformat()
        except ValueError:
            continue
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s, s[:10]
    raise ValueError(f"Cannot parse Time value: {raw_time!r}")


_PCT_RE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*%\s*$")
_LAT_RE = re.compile(
    r"^\s*([+-]?\d+(?:\.\d+)?)\s*(ms|s|mins?|minutes?|hrs?|hours?)\s*$",
    re.IGNORECASE,
)

_COUNT_SUFFIX_MULTIPLIERS: dict[str, float] = {
    "k": 1_000.0,
    "mil": 1_000_000.0,
    "m": 1_000_000.0,
}

_COUNT_QTY_RE = re.compile(
    r"^\s*([+-]?\d+(?:\.\d+)?)\s*(Mil|mil|MIL|K|k|M|m)?\s*$",
    re.IGNORECASE,
)


def _parse_metric_value(raw: Any, *, metric_name: str) -> tuple[float, str]:
    s = str(raw).strip().strip('"').strip("'")
    if not s or s.lower() in {"null", "none", "-", "nan"}:
        return 0.0, "count"

    m = _PCT_RE.match(s)
    if m:
        return float(m.group(1)), "pct"

    m = _LAT_RE.match(s)
    if m:
        v = float(m.group(1))
        unit = m.group(2).lower().rstrip(".")
        if unit == "s":
            return v * 1000.0, "ms"
        if unit in {"min", "mins", "minute", "minutes"}:
            return v * 60_000.0, "ms"
        if unit in {"h", "hr", "hrs", "hour", "hours"}:
            return v * 3_600_000.0, "ms"
        return v, "ms"

    # Count-like values (e.g. "3.61 K", "935 K", plain integer)
    s2 = s.replace(",", "").strip()
    m2 = _COUNT_QTY_RE.match(s2)
    if m2:
        num = float(m2.group(1))
        suffix_raw = m2.group(2) or ""
        suffix = suffix_raw.lower().rstrip(".")
        if not suffix:
            return num, "count"
        mult = _COUNT_SUFFIX_MULTIPLIERS.get(suffix)
        if mult is not None:
            return num * mult, "count"

    try:
        return float(s2), "count"
    except ValueError as e:
        raise ValueError(f"Cannot parse metric value for {metric_name}: {raw!r}") from e


def _file_sort_key(csv_path: Path) -> tuple[float, str]:
    try:
        mtime = float(csv_path.stat().st_mtime)
    except OSError:
        mtime = 0.0
    return (mtime, csv_path.name)


def _infer_metric_from_filename(name: str) -> str | None:
    low = name.lower()
    if low.startswith("cache-match-rate-"):
        return "cache_match_rate"
    if low.startswith("avg-latency-"):
        return "avg_latency"
    if low.startswith("model-requests-"):
        return "model_requests"
    return None


def discover_token_metric_csv_files(bills_dir: str | os.PathLike[str]) -> list[tuple[str, Path, str, str]]:
    """
    Returns list of (project_name, csv_path_abs, file_path_rel, metric_name), oldest file first.

    file_path_rel formats:
    - <project>/token/<filename>.csv (cache-match-rate-*.csv)
    - <project>/performance/<filename>.csv (avg-latency-*.csv, model-requests-*.csv)
    """
    bills_path = Path(bills_dir).expanduser().resolve()
    if not bills_path.exists():
        return []

    results: list[tuple[str, Path, str, str]] = []
    for project_dir in sorted(bills_path.glob("*")):
        if not project_dir.is_dir():
            continue
        project_name = project_dir.name
        if project_name.strip().lower() in {"price", "prices"}:
            continue

        for subdir in ("token", "performance"):
            d = project_dir / subdir
            if not d.is_dir():
                continue
            for csv_path in sorted(d.glob("*.csv"), key=_file_sort_key):
                metric = _infer_metric_from_filename(csv_path.name)
                if metric is None:
                    continue
                rel_path = str(csv_path.relative_to(bills_path))
                results.append((project_name, csv_path, rel_path, metric))
    return results


def iter_token_metric_csv_points(
    csv_path_abs: Path, *, project_name: str, file_path_rel: str, metric_name: str
) -> tuple[list[dict[str, object]], list[str]]:
    points: list[dict[str, object]] = []
    with csv_path_abs.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        raw_columns = reader.fieldnames or []
        model_cols = [c for c in raw_columns if _normalize_key(c) != "time"]

        for row_index, row in enumerate(reader):
            normalized = {_normalize_key(k): (v if v is not None else "") for k, v in row.items()}
            raw_time = normalized.get("time", "").strip()
            if not raw_time:
                continue
            recorded_at, usage_date = _parse_recorded_at(raw_time)

            for col in model_cols:
                col_key = _normalize_key(col)
                raw_val = normalized.get(col_key, "")
                if raw_val is None or str(raw_val).strip() == "":
                    continue
                model_name = _normalize_model_name(col)
                v, unit = _parse_metric_value(raw_val, metric_name=metric_name)
                points.append(
                    {
                        "project_name": project_name,
                        "recorded_at": recorded_at,
                        "usage_date": usage_date,
                        "model_name": model_name,
                        "metric_name": metric_name,
                        "metric_value": v,
                        "metric_unit": unit,
                        "source_file": file_path_rel,
                        "source_row_index": row_index,
                    }
                )
    return points, list(raw_columns)


def _delete_stale_keys_for_source_file(
    conn,
    *,
    file_path_rel: str,
    new_keys: set[tuple[str, str, str, str]],
) -> int:
    old_rows = conn.execute(
        """
        SELECT project_name, metric_name, recorded_at, model_name
        FROM token_metric_points
        WHERE source_file = ?
        """,
        (file_path_rel,),
    ).fetchall()
    removed = 0
    for r in old_rows:
        key = (
            str(r["project_name"]),
            str(r["metric_name"]),
            str(r["recorded_at"]),
            str(r["model_name"]),
        )
        if key in new_keys:
            continue
        conn.execute(
            """
            DELETE FROM token_metric_points
            WHERE project_name = ?
              AND metric_name = ?
              AND recorded_at = ?
              AND model_name = ?
            """,
            key,
        )
        removed += 1
    return removed


def _ingest_one_token_metric_file(
    conn,
    *,
    project_name: str,
    csv_path_abs: Path,
    file_path_rel: str,
    metric_name: str,
    reimport_changed: bool,
) -> tuple[int, int, bool]:
    conn.execute("SAVEPOINT ingest_token_metric_file")
    checksum = _sha256_file(csv_path_abs)

    existing = conn.execute(
        "SELECT checksum_sha256 FROM ingested_token_metric_files WHERE file_path = ?",
        (file_path_rel,),
    ).fetchone()
    if existing is not None and not reimport_changed:
        conn.execute("RELEASE ingest_token_metric_file")
        return (0, 0, False)
    if existing is not None and reimport_changed and str(existing["checksum_sha256"]) == checksum:
        conn.execute("RELEASE ingest_token_metric_file")
        return (0, 0, False)

    points, raw_columns = iter_token_metric_csv_points(
        csv_path_abs,
        project_name=project_name,
        file_path_rel=file_path_rel,
        metric_name=metric_name,
    )
    new_keys = {
        (str(p["project_name"]), str(p["metric_name"]), str(p["recorded_at"]), str(p["model_name"])) for p in points
    }

    replaced = 0
    if existing is not None:
        replaced += _delete_stale_keys_for_source_file(conn, file_path_rel=file_path_rel, new_keys=new_keys)
        conn.execute("DELETE FROM ingested_token_metric_files WHERE file_path = ?", (file_path_rel,))

    # count replacements due to conflicts (best-effort)
    rows_before = conn.execute(
        "SELECT COUNT(*) AS c FROM token_metric_points WHERE source_file = ?",
        (file_path_rel,),
    ).fetchone()["c"]

    to_insert = [
        (
            p["project_name"],
            p["recorded_at"],
            p["usage_date"],
            p["model_name"],
            p["metric_name"],
            float(p["metric_value"]),
            p["metric_unit"],
            p["source_file"],
            int(p["source_row_index"]),
        )
        for p in points
    ]
    conn.executemany(_METRIC_UPSERT_SQL, to_insert)

    rows_after = conn.execute(
        "SELECT COUNT(*) AS c FROM token_metric_points WHERE source_file = ?",
        (file_path_rel,),
    ).fetchone()["c"]
    replaced += max(0, int(rows_before) - int(rows_after))

    data_row_count = len({int(p["source_row_index"]) for p in points})
    conn.execute(
        """
        INSERT INTO ingested_token_metric_files(
            project_name, file_path, metric_name, checksum_sha256, schema_version,
            row_count, source_last_modified, raw_columns
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_name,
            file_path_rel,
            metric_name,
            checksum,
            SCHEMA_VERSION,
            data_row_count,
            csv_path_abs.stat().st_mtime,
            json.dumps(raw_columns, ensure_ascii=False),
        ),
    )

    try:
        # Lightweight verify: ensure we can find at least one row for the source file after ingest.
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM token_metric_points WHERE source_file = ?",
            (file_path_rel,),
        ).fetchone()
        if int(row["c"]) <= 0 and data_row_count > 0:
            raise ValueError("Token metric ingest audit: no rows found after ingest")
        conn.execute("RELEASE ingest_token_metric_file")
        conn.commit()
    except Exception:
        conn.execute("ROLLBACK TO ingest_token_metric_file")
        conn.execute("RELEASE ingest_token_metric_file")
        raise

    return len(points), replaced, True


def ingest_token_metric_all(
    bills_dir: str | os.PathLike[str],
    db_path: str | os.PathLike[str],
    *,
    reimport_changed: bool = False,
) -> TokenMetricIngestResult:
    return ingest_token_metric_selected(
        bills_dir=bills_dir, db_path=db_path, file_path_rels=None, reimport_changed=reimport_changed
    )


def ingest_token_metric_selected(
    bills_dir: str | os.PathLike[str],
    db_path: str | os.PathLike[str],
    *,
    file_path_rels: list[str] | None,
    reimport_changed: bool = False,
) -> TokenMetricIngestResult:
    ensure_parent_dir(db_path)
    conn = get_connection(db_path)
    try:
        init_db(conn)

        files = discover_token_metric_csv_files(bills_dir)
        if file_path_rels is not None:
            file_set = {str(x) for x in file_path_rels}
            files = [f for f in files if f[2] in file_set]

        files_discovered = len(files)
        files_skipped = 0
        files_ingested = 0
        rows_ingested = 0
        rows_replaced = 0
        files_verified = 0
        files_failed = 0
        verification_passed = True
        errors: list[tuple[str, str]] = []
        projects: set[str] = set()

        for project_name, csv_path_abs, file_path_rel, metric_name in files:
            projects.add(project_name)
            ensure_project(conn, project_name)

            existing = conn.execute(
                "SELECT checksum_sha256 FROM ingested_token_metric_files WHERE file_path = ?",
                (file_path_rel,),
            ).fetchone()
            if existing is not None and not reimport_changed:
                files_skipped += 1
                continue
            if existing is not None and reimport_changed:
                checksum = _sha256_file(csv_path_abs)
                if str(existing["checksum_sha256"]) == checksum:
                    files_skipped += 1
                    continue

            try:
                row_count, replaced, ingested = _ingest_one_token_metric_file(
                    conn,
                    project_name=project_name,
                    csv_path_abs=csv_path_abs,
                    file_path_rel=file_path_rel,
                    metric_name=metric_name,
                    reimport_changed=reimport_changed,
                )
            except Exception as e:
                verification_passed = False
                files_failed += 1
                errors.append((file_path_rel, str(e)))
                continue

            if not ingested:
                files_skipped += 1
                continue

            files_ingested += 1
            rows_ingested += row_count
            rows_replaced += replaced
            files_verified += 1

        return TokenMetricIngestResult(
            projects_discovered=len(projects),
            files_discovered=files_discovered,
            files_skipped=files_skipped,
            files_ingested=files_ingested,
            rows_ingested=rows_ingested,
            rows_replaced=rows_replaced,
            files_verified=files_verified,
            files_failed=files_failed,
            verification_passed=verification_passed,
            errors=tuple(errors),
        )
    finally:
        conn.close()


def list_missing_token_metric_files(
    bills_dir: str | os.PathLike[str],
    db_path: str | os.PathLike[str],
) -> list[dict[str, object]]:
    conn = get_connection(db_path)
    try:
        init_db(conn)
        bills_path = Path(bills_dir).expanduser().resolve()
        if not bills_path.exists():
            return []
        existing = conn.execute("SELECT file_path FROM ingested_token_metric_files").fetchall()
        ingested_paths = {r["file_path"] for r in existing}

        missing: list[dict[str, object]] = []
        for project_name, csv_path_abs, file_path_rel, metric_name in discover_token_metric_csv_files(bills_dir):
            if file_path_rel in ingested_paths:
                continue
            missing.append(
                {
                    "project_name": project_name,
                    "file_path_rel": file_path_rel,
                    "file_kind": "token_metric",
                    "metric_name": metric_name,
                    "source_last_modified": float(csv_path_abs.stat().st_mtime),
                }
            )
        missing.sort(key=lambda x: float(x["source_last_modified"] or 0), reverse=True)
        return missing
    finally:
        conn.close()


def list_ingested_token_metric_files(
    db_path: str | os.PathLike[str],
    *,
    limit: int = 50,
) -> list[dict[str, object]]:
    limit = max(1, min(int(limit), 200))
    conn = get_connection(db_path)
    try:
        init_db(conn)
        rows = conn.execute(
            """
            SELECT
                project_name,
                file_path,
                metric_name,
                row_count,
                ingested_at,
                source_last_modified
            FROM ingested_token_metric_files
            ORDER BY ingested_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            {
                "project_name": r["project_name"],
                "file_path_rel": r["file_path"],
                "file_kind": "token_metric",
                "metric_name": r["metric_name"],
                "row_count": int(r["row_count"]),
                "ingested_at": r["ingested_at"],
                "source_last_modified": r["source_last_modified"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def verify_ingested_token_metric_files(
    bills_dir: str | os.PathLike[str],
    db_path: str | os.PathLike[str],
    *,
    limit: int = 50,
    file_path_rels: list[str] | None = None,
) -> TokenMetricIngestVerifyResult:
    bills_path = Path(bills_dir).expanduser().resolve()
    conn = get_connection(db_path)
    init_db(conn)
    try:
        if file_path_rels:
            items: list[TokenMetricIngestVerifyResultItem] = []
            for file_path_rel in file_path_rels:
                ing = conn.execute(
                    """
                    SELECT project_name, file_path, checksum_sha256, metric_name
                    FROM ingested_token_metric_files
                    WHERE file_path = ?
                    """,
                    (file_path_rel,),
                ).fetchone()
                if ing is None:
                    items.append(
                        TokenMetricIngestVerifyResultItem(
                            file_path_rel=file_path_rel,
                            pass_check=False,
                            error="Ingest record not found for file_path_rel",
                        )
                    )
                    continue
                try:
                    csv_path_abs = (bills_path / file_path_rel).expanduser().resolve()
                    if not csv_path_abs.exists():
                        raise FileNotFoundError(f"Missing CSV file for {file_path_rel}")
                    checksum = _sha256_file(csv_path_abs)
                    if str(ing["checksum_sha256"]) != str(checksum):
                        raise ValueError("Checksum mismatch")
                    # Ensure at least 1 point exists for this file
                    row = conn.execute(
                        "SELECT COUNT(*) AS c FROM token_metric_points WHERE source_file = ?",
                        (file_path_rel,),
                    ).fetchone()
                    if int(row["c"]) <= 0:
                        raise ValueError("No DB rows found for metric file")
                    items.append(TokenMetricIngestVerifyResultItem(file_path_rel=file_path_rel, pass_check=True))
                except Exception as e:
                    items.append(
                        TokenMetricIngestVerifyResultItem(file_path_rel=file_path_rel, pass_check=False, error=str(e))
                    )
            return TokenMetricIngestVerifyResult(limit=len(file_path_rels), items=items)

        limit = max(1, min(int(limit), 200))
        rows = conn.execute(
            """
            SELECT project_name, file_path, checksum_sha256, metric_name
            FROM ingested_token_metric_files
            ORDER BY ingested_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        items: list[TokenMetricIngestVerifyResultItem] = []
        for r in rows:
            file_path_rel = str(r["file_path"])
            try:
                csv_path_abs = (bills_path / file_path_rel).expanduser().resolve()
                if not csv_path_abs.exists():
                    raise FileNotFoundError(f"Missing CSV file for {file_path_rel}")
                checksum = _sha256_file(csv_path_abs)
                if str(r["checksum_sha256"]) != str(checksum):
                    raise ValueError("Checksum mismatch")
                items.append(TokenMetricIngestVerifyResultItem(file_path_rel=file_path_rel, pass_check=True))
            except Exception as e:
                items.append(TokenMetricIngestVerifyResultItem(file_path_rel=file_path_rel, pass_check=False, error=str(e)))
        return TokenMetricIngestVerifyResult(limit=limit, items=items)
    finally:
        conn.close()

