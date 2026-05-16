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

# Grafana token CSV units: K/thousand, Mil/M/million (see parse_token_quantity).
_TOKEN_SUFFIX_MULTIPLIERS: dict[str, float] = {
    "k": 1_000.0,
    "mil": 1_000_000.0,
    "m": 1_000_000.0,
}

# Match "3.91 Mil", "46.2K", "935 K", plain integers. Put Mil before M in alternation.
_TOKEN_QTY_RE = re.compile(
    r"^\s*([+-]?\d+(?:\.\d+)?)\s*(Mil|mil|MIL|K|k|M|m)?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TokenIngestResult:
    projects_discovered: int
    files_discovered: int
    files_skipped: int
    files_ingested: int
    rows_ingested: int
    files_verified: int
    verification_passed: bool


@dataclass(frozen=True)
class TokenIngestVerifyResultItem:
    file_path_rel: str
    pass_check: bool
    error: str | None = None


@dataclass(frozen=True)
class TokenIngestVerifyResult:
    limit: int
    items: list[TokenIngestVerifyResultItem]

    @property
    def pass_count(self) -> int:
        return sum(1 for x in self.items if x.pass_check)

    @property
    def fail_count(self) -> int:
        return sum(1 for x in self.items if not x.pass_check)


def parse_token_quantity(val: Any) -> float:
    """
    Parse Grafana-style token counts to raw token integers as float.

    Supported suffixes (case-insensitive):
    - K -> × 1,000
    - Mil, M -> × 1,000,000
    Plain numbers are treated as already in token units.
    """
    s = str(val).strip().strip('"').strip("'").replace(",", "").replace("\u00a0", " ")
    if not s or s.lower() in {"0", "null", "none", "-", "nan"}:
        return 0.0
    m = _TOKEN_QTY_RE.match(s)
    if not m:
        try:
            return float(s)
        except ValueError as e:
            raise ValueError(f"Cannot parse token quantity: {val!r}") from e
    num = float(m.group(1))
    suffix_raw = m.group(2) or ""
    suffix = suffix_raw.lower().rstrip(".")
    if not suffix:
        return num
    mult = _TOKEN_SUFFIX_MULTIPLIERS.get(suffix)
    if mult is None:
        raise ValueError(f"Unknown token quantity suffix {suffix_raw!r} in {val!r}")
    return num * mult


def infer_token_direction(filename: str) -> str:
    low = filename.lower()
    if "input" in low:
        return "input"
    if "output" in low:
        return "output"
    raise ValueError(f"Cannot infer token direction from filename (expected 'input' or 'output'): {filename}")


def _normalize_key(k: str) -> str:
    return k.strip().strip("\ufeff").strip('"').strip("'").lower().replace(" ", "_")


def _parse_recorded_at(raw_time: str) -> tuple[str, str]:
    s = raw_time.strip().strip('"')
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(s, fmt)
            return s, dt.date().isoformat()
        except ValueError:
            continue
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s, s[:10]
    raise ValueError(f"Cannot parse Time value: {raw_time!r}")


def discover_token_csv_files(bills_dir: str | os.PathLike[str]) -> list[tuple[str, Path, str]]:
    """
    Returns list of (project_name, csv_path_abs, file_path_rel).
    file_path_rel format: <project>/token/<filename>.csv
    """
    bills_path = Path(bills_dir).expanduser().resolve()
    if not bills_path.exists():
        return []

    results: list[tuple[str, Path, str]] = []
    for project_dir in sorted(bills_path.glob("*")):
        if not project_dir.is_dir():
            continue
        project_name = project_dir.name
        if project_name.strip().lower() in {"price", "prices"}:
            continue
        token_dir = project_dir / "token"
        if not token_dir.is_dir():
            continue
        for csv_path in sorted(token_dir.glob("*.csv")):
            rel_path = str(csv_path.relative_to(bills_path))
            results.append((project_name, csv_path, rel_path))
    return results


def _build_expected_from_token_csv(
    csv_path_abs: Path, *, token_direction: str
) -> dict[str, dict[str, object]]:
    expected_by_date: dict[str, dict[str, object]] = {}
    with csv_path_abs.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        model_cols = [_normalize_key(c) for c in fieldnames if _normalize_key(c) != "time"]
        for _row_index, row in enumerate(reader):
            normalized = {_normalize_key(k): (v if v is not None else "") for k, v in row.items()}
            raw_time = normalized.get("time", "").strip()
            if not raw_time:
                continue
            _, usage_date = _parse_recorded_at(raw_time)
            row_total = 0.0
            for col in model_cols:
                raw_val = normalized.get(col, "")
                if raw_val is None or str(raw_val).strip() == "":
                    continue
                row_total += parse_token_quantity(raw_val)
            if usage_date not in expected_by_date:
                expected_by_date[usage_date] = {"count": 0, "token_sum": 0.0}
            expected_by_date[usage_date]["count"] = int(expected_by_date[usage_date]["count"]) + 1
            expected_by_date[usage_date]["token_sum"] = float(expected_by_date[usage_date]["token_sum"]) + row_total
    return expected_by_date


def _verify_token_ingestion_for_file(
    conn,
    *,
    file_path_rel: str,
    checksum_sha256: str,
    token_direction: str,
    expected_by_date: dict[str, dict[str, object]],
) -> None:
    eps = 1e-3
    expected_dates = set(expected_by_date.keys())
    expected_total_rows = sum(int(v["count"]) for v in expected_by_date.values())
    expected_total_tokens = sum(float(v["token_sum"]) for v in expected_by_date.values())

    rows_by_date = conn.execute(
        """
        SELECT
          usage_date,
          COUNT(DISTINCT source_row_index) AS cnt,
          COALESCE(SUM(token_count), 0) AS sum_tokens
        FROM token_usage_points
        WHERE source_file = ? AND token_direction = ?
        GROUP BY usage_date
        """,
        (file_path_rel, token_direction),
    ).fetchall()

    db_dates = {r["usage_date"] for r in rows_by_date}
    if db_dates != expected_dates:
        raise ValueError(
            f"Token ingest audit date mismatch for {file_path_rel}: db_dates={sorted(db_dates)}, expected={sorted(expected_dates)}"
        )

    for r in rows_by_date:
        d = r["usage_date"]
        exp = expected_by_date.get(d)
        if exp is None:
            raise ValueError(f"Token ingest audit unexpected date in DB for {file_path_rel}: {d}")
        if int(r["cnt"]) != int(exp["count"]):
            raise ValueError(
                f"Token ingest audit row_count mismatch for {file_path_rel} date={d}: db={int(r['cnt'])}, expected={exp['count']}"
            )
        if abs(float(r["sum_tokens"]) - float(exp["token_sum"])) > eps:
            raise ValueError(
                f"Token ingest audit token sum mismatch for {file_path_rel} date={d}: db={float(r['sum_tokens'])}, expected={exp['token_sum']}"
            )

    total = conn.execute(
        """
        SELECT
          COUNT(DISTINCT source_row_index) AS cnt,
          COALESCE(SUM(token_count), 0) AS sum_tokens
        FROM token_usage_points
        WHERE source_file = ? AND token_direction = ?
        """,
        (file_path_rel, token_direction),
    ).fetchone()
    if int(total["cnt"]) != expected_total_rows:
        raise ValueError(
            f"Token ingest audit total row_count mismatch for {file_path_rel}: db={int(total['cnt'])}, expected={expected_total_rows}"
        )
    if abs(float(total["sum_tokens"]) - expected_total_tokens) > eps:
        raise ValueError(
            f"Token ingest audit total token sum mismatch for {file_path_rel}: db={float(total['sum_tokens'])}, expected={expected_total_tokens}"
        )

    ing = conn.execute(
        """
        SELECT checksum_sha256, row_count
        FROM ingested_token_files
        WHERE file_path = ?
        """,
        (file_path_rel,),
    ).fetchone()
    if ing is None:
        raise ValueError(f"Token ingest audit missing ingested_token_files row for {file_path_rel}")
    if str(ing["checksum_sha256"]) != str(checksum_sha256):
        raise ValueError(
            f"Token ingest audit checksum mismatch for {file_path_rel}: db={ing['checksum_sha256']}, expected={checksum_sha256}"
        )
    if int(ing["row_count"]) != expected_total_rows:
        raise ValueError(
            f"Token ingest audit ingested_token_files row_count mismatch for {file_path_rel}: db={int(ing['row_count'])}, expected={expected_total_rows}"
        )


def _ingest_one_token_file(
    conn,
    *,
    project_name: str,
    csv_path_abs: Path,
    file_path_rel: str,
    reimport_changed: bool,
) -> tuple[int, bool]:
    token_direction = infer_token_direction(csv_path_abs.name)
    existing = conn.execute(
        "SELECT checksum_sha256 FROM ingested_token_files WHERE file_path = ?",
        (file_path_rel,),
    ).fetchone()

    if existing is not None:
        if not reimport_changed:
            return 0, False
        checksum = _sha256_file(csv_path_abs)
        if str(existing["checksum_sha256"]) == checksum:
            return 0, False
        conn.execute("SAVEPOINT ingest_token_file")
        conn.execute(
            "DELETE FROM token_usage_points WHERE source_file = ?",
            (file_path_rel,),
        )
        conn.execute("DELETE FROM ingested_token_files WHERE file_path = ?", (file_path_rel,))
    else:
        checksum = _sha256_file(csv_path_abs)
        conn.execute("SAVEPOINT ingest_token_file")

    expected_by_date: dict[str, dict[str, object]] = {}
    to_insert: list[tuple] = []
    data_row_count = 0

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
            row_total = 0.0
            for col in model_cols:
                col_key = _normalize_key(col)
                raw_val = normalized.get(col_key, "")
                if raw_val is None or str(raw_val).strip() == "":
                    continue
                token_count = parse_token_quantity(raw_val)
                row_total += token_count
                to_insert.append(
                    (
                        project_name,
                        recorded_at,
                        usage_date,
                        col.strip().strip('"'),
                        token_direction,
                        token_count,
                        file_path_rel,
                        row_index,
                    )
                )

            if usage_date not in expected_by_date:
                expected_by_date[usage_date] = {"count": 0, "token_sum": 0.0}
            expected_by_date[usage_date]["count"] = int(expected_by_date[usage_date]["count"]) + 1
            expected_by_date[usage_date]["token_sum"] = float(expected_by_date[usage_date]["token_sum"]) + row_total
            data_row_count += 1

    conn.executemany(
        """
        INSERT INTO token_usage_points(
            project_name, recorded_at, usage_date, model_name, token_direction,
            token_count, source_file, source_row_index
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        to_insert,
    )

    conn.execute(
        """
        INSERT INTO ingested_token_files(
            project_name, file_path, token_direction, checksum_sha256, schema_version,
            row_count, source_last_modified, raw_columns
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_name,
            file_path_rel,
            token_direction,
            checksum,
            SCHEMA_VERSION,
            data_row_count,
            csv_path_abs.stat().st_mtime,
            json.dumps(raw_columns, ensure_ascii=False),
        ),
    )

    try:
        _verify_token_ingestion_for_file(
            conn,
            file_path_rel=file_path_rel,
            checksum_sha256=checksum,
            token_direction=token_direction,
            expected_by_date=expected_by_date,
        )
        conn.execute("RELEASE ingest_token_file")
        conn.commit()
    except Exception:
        conn.execute("ROLLBACK TO ingest_token_file")
        conn.execute("RELEASE ingest_token_file")
        raise

    return len(to_insert), True


def ingest_token_all(
    bills_dir: str | os.PathLike[str],
    db_path: str | os.PathLike[str],
    *,
    reimport_changed: bool = False,
) -> TokenIngestResult:
    return ingest_token_selected(
        bills_dir=bills_dir,
        db_path=db_path,
        file_path_rels=None,
        reimport_changed=reimport_changed,
    )


def ingest_token_selected(
    bills_dir: str | os.PathLike[str],
    db_path: str | os.PathLike[str],
    *,
    file_path_rels: list[str] | None,
    reimport_changed: bool = False,
) -> TokenIngestResult:
    ensure_parent_dir(db_path)
    conn = get_connection(db_path)
    init_db(conn)

    files = discover_token_csv_files(bills_dir)
    if file_path_rels is not None:
        file_set = {str(x) for x in file_path_rels}
        files = [f for f in files if f[2] in file_set]

    files_discovered = len(files)
    files_skipped = 0
    files_ingested = 0
    rows_ingested = 0
    files_verified = 0
    verification_passed = True
    projects: set[str] = set()

    for project_name, csv_path_abs, file_path_rel in files:
        projects.add(project_name)
        ensure_project(conn, project_name)

        existing = conn.execute(
            "SELECT checksum_sha256 FROM ingested_token_files WHERE file_path = ?",
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
            row_count, ingested = _ingest_one_token_file(
                conn,
                project_name=project_name,
                csv_path_abs=csv_path_abs,
                file_path_rel=file_path_rel,
                reimport_changed=reimport_changed,
            )
        except Exception:
            verification_passed = False
            raise

        if not ingested:
            files_skipped += 1
            continue

        files_ingested += 1
        rows_ingested += row_count
        files_verified += 1

    conn.close()
    return TokenIngestResult(
        projects_discovered=len(projects),
        files_discovered=files_discovered,
        files_skipped=files_skipped,
        files_ingested=files_ingested,
        rows_ingested=rows_ingested,
        files_verified=files_verified,
        verification_passed=verification_passed,
    )


def list_missing_token_files(
    bills_dir: str | os.PathLike[str],
    db_path: str | os.PathLike[str],
) -> list[dict[str, object]]:
    conn = get_connection(db_path)
    try:
        init_db(conn)
        bills_path = Path(bills_dir).expanduser().resolve()
        if not bills_path.exists():
            return []

        existing = conn.execute("SELECT file_path FROM ingested_token_files").fetchall()
        ingested_paths = {r["file_path"] for r in existing}

        missing: list[dict[str, object]] = []
        for project_name, csv_path_abs, file_path_rel in discover_token_csv_files(bills_dir):
            if file_path_rel in ingested_paths:
                continue
            try:
                direction = infer_token_direction(csv_path_abs.name)
            except ValueError:
                direction = None
            missing.append(
                {
                    "project_name": project_name,
                    "file_path_rel": file_path_rel,
                    "file_kind": "token",
                    "token_direction": direction,
                    "source_last_modified": float(csv_path_abs.stat().st_mtime),
                }
            )
        missing.sort(key=lambda x: x["source_last_modified"], reverse=True)
        return missing
    finally:
        conn.close()


def list_ingested_token_files(
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
                token_direction,
                row_count,
                ingested_at,
                source_last_modified
            FROM ingested_token_files
            ORDER BY ingested_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            {
                "project_name": r["project_name"],
                "file_path_rel": r["file_path"],
                "file_kind": "token",
                "token_direction": r["token_direction"],
                "row_count": int(r["row_count"]),
                "ingested_at": r["ingested_at"],
                "source_last_modified": r["source_last_modified"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def verify_ingested_token_files(
    bills_dir: str | os.PathLike[str],
    db_path: str | os.PathLike[str],
    *,
    limit: int = 50,
    file_path_rels: list[str] | None = None,
) -> TokenIngestVerifyResult:
    bills_path = Path(bills_dir).expanduser().resolve()
    conn = get_connection(db_path)
    init_db(conn)
    try:
        if file_path_rels:
            items: list[TokenIngestVerifyResultItem] = []
            for file_path_rel in file_path_rels:
                ing = conn.execute(
                    """
                    SELECT project_name, file_path, checksum_sha256, token_direction
                    FROM ingested_token_files
                    WHERE file_path = ?
                    """,
                    (file_path_rel,),
                ).fetchone()
                if ing is None:
                    items.append(
                        TokenIngestVerifyResultItem(
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
                    expected_by_date = _build_expected_from_token_csv(
                        csv_path_abs, token_direction=str(ing["token_direction"])
                    )
                    _verify_token_ingestion_for_file(
                        conn,
                        file_path_rel=file_path_rel,
                        checksum_sha256=checksum,
                        token_direction=str(ing["token_direction"]),
                        expected_by_date=expected_by_date,
                    )
                    items.append(TokenIngestVerifyResultItem(file_path_rel=file_path_rel, pass_check=True, error=None))
                except Exception as e:
                    items.append(
                        TokenIngestVerifyResultItem(file_path_rel=file_path_rel, pass_check=False, error=str(e))
                    )
            return TokenIngestVerifyResult(limit=len(file_path_rels), items=items)

        limit = max(1, min(int(limit), 200))
        rows = conn.execute(
            """
            SELECT project_name, file_path, checksum_sha256, token_direction
            FROM ingested_token_files
            ORDER BY ingested_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        items = []
        for r in rows:
            file_path_rel = r["file_path"]
            try:
                csv_path_abs = (bills_path / file_path_rel).expanduser().resolve()
                if not csv_path_abs.exists():
                    raise FileNotFoundError(f"Missing CSV file for {file_path_rel}")
                checksum = _sha256_file(csv_path_abs)
                expected_by_date = _build_expected_from_token_csv(
                    csv_path_abs, token_direction=str(r["token_direction"])
                )
                _verify_token_ingestion_for_file(
                    conn,
                    file_path_rel=file_path_rel,
                    checksum_sha256=checksum,
                    token_direction=str(r["token_direction"]),
                    expected_by_date=expected_by_date,
                )
                items.append(TokenIngestVerifyResultItem(file_path_rel=file_path_rel, pass_check=True, error=None))
            except Exception as e:
                items.append(
                    TokenIngestVerifyResultItem(file_path_rel=file_path_rel, pass_check=False, error=str(e))
                )
        return TokenIngestVerifyResult(limit=limit, items=items)
    finally:
        conn.close()
