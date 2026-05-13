from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .db import get_connection, init_db, replace_model_prices


@dataclass(frozen=True)
class PriceImportResult:
    source_csv: str
    rows_read: int
    rows_imported: int


def _read_price_csv_rows(csv_path: str) -> tuple[list[tuple], set[str]]:
    p = Path(csv_path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"price csv not found: {p}")

    rows: list[tuple] = []
    source_ids: set[str] = set()
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            sid = (r.get("source_id") or "").strip()
            if sid:
                source_ids.add(sid)
            rows.append(
                (
                    sid,
                    (r.get("source_url") or "").strip(),
                    (r.get("effective_date") or "").strip(),
                    (r.get("retrieved_at_utc") or "").strip() or None,
                    (r.get("vendor") or "").strip(),
                    (r.get("platform") or "").strip(),
                    (r.get("price_region") or "").strip(),
                    (r.get("price_currency") or "").strip(),
                    (r.get("model_series") or "").strip(),
                    (r.get("model_name") or "").strip(),
                    (r.get("context_bucket") or "").strip() or None,
                    (r.get("deployment_scope") or "").strip() or None,
                    (r.get("billing_mode") or "").strip(),
                    (r.get("metric_name") or "").strip(),
                    float(r.get("amount") or 0.0),
                    int(float(r.get("unit_quantity") or 0)),
                    (r.get("unit_name") or "").strip(),
                    (r.get("unit_expression") or "").strip(),
                    (r.get("notes") or "").strip() or None,
                    (r.get("source_detail_json") or "").strip() or None,
                )
            )
    return rows, source_ids


def import_price_csv(*, db_path: str, csv_path: str) -> PriceImportResult:
    p = Path(csv_path).expanduser().resolve()
    rows, _ = _read_price_csv_rows(str(p))

    conn = get_connection(db_path)
    try:
        init_db(conn)
        imported = replace_model_prices(conn, rows)
    finally:
        conn.close()

    return PriceImportResult(source_csv=str(p), rows_read=len(rows), rows_imported=imported)


def import_price_csv_merge(*, db_path: str, csv_path: str) -> PriceImportResult:
    """
    Delete existing rows whose ``source_id`` appears in the CSV, then insert all CSV rows.

    Keeps other ``source_id`` values (for example retail sync under ``azure_retail_prices_api``).
    """
    p = Path(csv_path).expanduser().resolve()
    rows, source_ids = _read_price_csv_rows(str(p))
    if not source_ids:
        raise ValueError("CSV must set non-empty source_id on at least one row for merge import")

    conn = get_connection(db_path)
    try:
        init_db(conn)
        for sid in sorted(source_ids):
            conn.execute("DELETE FROM model_prices WHERE source_id = ?", (sid,))
        conn.executemany(
            """
            INSERT INTO model_prices(
                source_id, source_url, effective_date, retrieved_at_utc,
                vendor, platform, price_region, price_currency,
                model_series, model_name, context_bucket, deployment_scope,
                billing_mode, metric_name, amount,
                unit_quantity, unit_name, unit_expression, notes, source_detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return PriceImportResult(source_csv=str(p), rows_read=len(rows), rows_imported=len(rows))
