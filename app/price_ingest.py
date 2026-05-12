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


def import_price_csv(*, db_path: str, csv_path: str) -> PriceImportResult:
    p = Path(csv_path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"price csv not found: {p}")

    rows: list[tuple] = []
    rows_read = 0
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows_read += 1
            rows.append(
                (
                    (r.get("source_id") or "").strip(),
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

    conn = get_connection(db_path)
    try:
        init_db(conn)
        imported = replace_model_prices(conn, rows)
    finally:
        conn.close()

    return PriceImportResult(source_csv=str(p), rows_read=rows_read, rows_imported=imported)
