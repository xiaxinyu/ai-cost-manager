from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

from .meter_match import (
    aggregate_billing_rows,
    canonical_model_name,
    normalize_token_column,
    parse_foundry_meter,
    token_models_match,
)


SCHEMA_VERSION = 7

EXPECTED_CSV_COLUMNS = [
    "UsageDate",
    "ResourceId",
    "ResourceType",
    "ResourceLocation",
    "ResourceGroupName",
    "ServiceName",
    "ServiceTier",
    "Meter",
    "CostUSD",
    "Cost",
    "Currency",
]


def ensure_parent_dir(db_path: str | os.PathLike[str]) -> None:
    Path(db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def get_connection(db_path: str | os.PathLike[str]) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS ingested_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT NOT NULL,
            file_path TEXT NOT NULL UNIQUE,
            checksum_sha256 TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            row_count INTEGER NOT NULL,
            ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
            source_last_modified REAL,
            raw_columns TEXT
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT NOT NULL,
            usage_date TEXT NOT NULL, -- YYYY-MM-DD
            resource_id TEXT,
            resource_type TEXT,
            resource_location TEXT,
            resource_group_name TEXT,
            service_name TEXT,
            service_tier TEXT,
            meter TEXT,
            cost_usd NUMERIC,
            cost NUMERIC,
            currency TEXT,
            forecast_cost NUMERIC,
            raw_json TEXT NOT NULL,
            source_file TEXT NOT NULL,
            source_row_index INTEGER NOT NULL,
            ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(project_name, source_file, source_row_index)
        );

        CREATE INDEX IF NOT EXISTS idx_transactions_project_date
            ON transactions(project_name, usage_date);

        CREATE INDEX IF NOT EXISTS idx_ingested_files_project_name
            ON ingested_files(project_name);

        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS model_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            source_url TEXT NOT NULL,
            effective_date TEXT NOT NULL,
            retrieved_at_utc TEXT,
            vendor TEXT NOT NULL,
            platform TEXT NOT NULL,
            price_region TEXT NOT NULL,
            price_currency TEXT NOT NULL,
            model_series TEXT NOT NULL,
            model_name TEXT NOT NULL,
            context_bucket TEXT,
            deployment_scope TEXT,
            billing_mode TEXT NOT NULL,
            metric_name TEXT NOT NULL,
            amount NUMERIC NOT NULL,
            unit_quantity INTEGER NOT NULL,
            unit_name TEXT NOT NULL,
            unit_expression TEXT NOT NULL,
            notes TEXT,
            source_detail_json TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(
                source_id, effective_date, vendor, platform, price_region, price_currency,
                model_series, model_name, context_bucket,
                deployment_scope, billing_mode, metric_name
            )
        );

        CREATE INDEX IF NOT EXISTS idx_model_prices_filters
            ON model_prices(vendor, platform, model_series, price_currency, price_region);

        CREATE TABLE IF NOT EXISTS project_model_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT NOT NULL UNIQUE,
            model_name TEXT NOT NULL,
            api_version TEXT,
            azure_endpoint TEXT,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS price_source_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_key TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            reference_url TEXT NOT NULL DEFAULT '',
            api_url TEXT NOT NULL DEFAULT '',
            notes TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS ingested_token_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT NOT NULL,
            file_path TEXT NOT NULL UNIQUE,
            token_direction TEXT NOT NULL,
            checksum_sha256 TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            row_count INTEGER NOT NULL,
            ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
            source_last_modified REAL,
            raw_columns TEXT
        );

        CREATE TABLE IF NOT EXISTS token_usage_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            usage_date TEXT NOT NULL,
            model_name TEXT NOT NULL,
            token_direction TEXT NOT NULL,
            token_count REAL NOT NULL,
            source_file TEXT NOT NULL,
            source_row_index INTEGER NOT NULL,
            ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(project_name, source_file, source_row_index, model_name)
        );

        CREATE INDEX IF NOT EXISTS idx_token_usage_project_date
            ON token_usage_points(project_name, usage_date);

        CREATE INDEX IF NOT EXISTS idx_ingested_token_files_project_name
            ON ingested_token_files(project_name);
        """
    )
    conn.execute(
        """
        INSERT INTO meta(key, value)
        VALUES ('sqlite_version', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (sqlite3.sqlite_version,),
    )
    conn.execute(
        """
        INSERT INTO meta(key, value)
        VALUES ('schema_version', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (str(SCHEMA_VERSION),),
    )
    conn.commit()

    _migrate_billing_rows_if_needed(conn)
    _migrate_transactions_dedupe_billing_natural_key(conn)
    _migrate_model_prices_source_detail_json(conn)
    _ensure_price_source_catalog(conn)


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _migrate_billing_rows_if_needed(conn: sqlite3.Connection) -> None:
    """
    Migrate legacy `billing_rows` to `transactions` once, if needed.
    """
    if not _table_exists(conn, "billing_rows"):
        return

    # If already migrated, don't do it again.
    tx_cnt = conn.execute("SELECT COUNT(*) AS c FROM transactions").fetchone()["c"]
    if int(tx_cnt) > 0:
        return

    legacy_rows = conn.execute(
        """
        SELECT
          project_name, usage_date, currency, cost_usd, cost, forecast_cost,
          raw_json, source_file, source_row_index
        FROM billing_rows
        """
    ).fetchall()

    if not legacy_rows:
        return

    insert_rows = []
    for r in legacy_rows:
        raw = {}
        try:
            raw = json.loads(r["raw_json"]) if r["raw_json"] else {}
        except Exception:
            raw = {}

        insert_rows.append(
            (
                r["project_name"],
                r["usage_date"],
                raw.get("ResourceId"),
                raw.get("ResourceType"),
                raw.get("ResourceLocation"),
                raw.get("ResourceGroupName"),
                raw.get("ServiceName"),
                raw.get("ServiceTier"),
                raw.get("Meter"),
                r["cost_usd"],
                r["cost"],
                r["currency"],
                r["forecast_cost"],
                r["raw_json"],
                r["source_file"],
                r["source_row_index"],
            )
        )

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
        insert_rows,
    )
    conn.commit()


def _migrate_transactions_dedupe_billing_natural_key(conn: sqlite3.Connection) -> None:
    """
    One-time: collapse duplicate billing rows that share the same natural key
    (project_name, usage_date, resource_group_name, service_tier, meter), keeping the newest id.
    Enables cross-file upsert semantics (later import replaces earlier for the same meter line).
    """
    row = conn.execute("SELECT value FROM meta WHERE key = 'billing_natural_dedupe_v1'").fetchone()
    if row is not None and str(row["value"]).strip() == "1":
        return
    if not _table_exists(conn, "transactions"):
        return
    cnt = int(conn.execute("SELECT COUNT(*) AS c FROM transactions").fetchone()["c"])
    if cnt == 0:
        conn.execute(
            """
            INSERT INTO meta(key, value) VALUES ('billing_natural_dedupe_v1', '1')
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """
        )
        conn.commit()
        return

    conn.execute(
        """
        DELETE FROM transactions
        WHERE id NOT IN (
            SELECT MAX(id)
            FROM transactions
            GROUP BY
                project_name,
                usage_date,
                COALESCE(resource_group_name, ''),
                COALESCE(service_tier, ''),
                COALESCE(meter, '')
        )
        """
    )
    conn.execute(
        """
        INSERT INTO meta(key, value) VALUES ('billing_natural_dedupe_v1', '1')
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """
    )
    conn.commit()


def _migrate_model_prices_source_detail_json(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "model_prices"):
        return
    cols = {str(r["name"]) for r in conn.execute("PRAGMA table_info(model_prices)").fetchall()}
    if "source_detail_json" in cols:
        return
    conn.execute("ALTER TABLE model_prices ADD COLUMN source_detail_json TEXT")
    conn.commit()


PRICE_SOURCE_CATALOG_SEED: tuple[tuple[str, str, str, str, str, int], ...] = (
    (
        "microsoft_unit_price_api",
        "Microsoft unit price catalog (REST)",
        "https://azure.microsoft.com/en-us/pricing/details/azure-openai/",
        "https://prices.azure.com/api/retail/prices",
        "Used by Sync prices (Foundry Models + OpenAI filter). GPT-5.1 / GPT-5.2 marketing-page rows align with the "
        "\"GPT-5.1 + GPT-5.2 (Series…)\" scope plus an ARM region such as eastus2.",
        10,
    ),
    (
        "internal_billing_csv",
        "Project billing CSV exports",
        "",
        "",
        "Usage rows ingested from the configured bills directory (Import page).",
        20,
    ),
    (
        "model_price_csv",
        "Model price CSV (per-row source_url)",
        "",
        "",
        "Rows from price CSV files; each row can set source_url and source_id.",
        30,
    ),
)


def _ensure_price_source_catalog(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "price_source_catalog"):
        return
    cnt = int(conn.execute("SELECT COUNT(*) AS c FROM price_source_catalog").fetchone()["c"])
    if cnt > 0:
        return
    for sk, title, ref, api, notes, so in PRICE_SOURCE_CATALOG_SEED:
        conn.execute(
            """
            INSERT INTO price_source_catalog (source_key, title, reference_url, api_url, notes, sort_order)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (sk, title, ref, api, notes, so),
        )
    conn.commit()


def list_price_source_catalog(conn: sqlite3.Connection) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, source_key, title, reference_url, api_url, notes, sort_order, updated_at
        FROM price_source_catalog
        ORDER BY sort_order, id
        """
    ).fetchall()
    return [dict(r) for r in rows]


def update_price_source_catalog_row(
    conn: sqlite3.Connection,
    row_id: int,
    *,
    title: str | None = None,
    reference_url: str | None = None,
    api_url: str | None = None,
    notes: str | None = None,
) -> dict[str, object] | None:
    cur = conn.execute(
        "SELECT id, title, reference_url, api_url, notes FROM price_source_catalog WHERE id = ?",
        (row_id,),
    ).fetchone()
    if cur is None:
        return None
    t = title if title is not None else cur["title"]
    r = reference_url if reference_url is not None else cur["reference_url"]
    a = api_url if api_url is not None else cur["api_url"]
    n = notes if notes is not None else cur["notes"]
    conn.execute(
        """
        UPDATE price_source_catalog
        SET title = ?, reference_url = ?, api_url = ?, notes = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (t, r, a, n, row_id),
    )
    conn.commit()
    out = conn.execute(
        """
        SELECT id, source_key, title, reference_url, api_url, notes, sort_order, updated_at
        FROM price_source_catalog WHERE id = ?
        """,
        (row_id,),
    ).fetchone()
    return dict(out) if out else None


@dataclass(frozen=True)
class ProjectStats:
    project_name: str
    from_date: str | None
    to_date: str | None
    min_usage_date: str | None
    max_usage_date: str | None
    actual_cost_usd_total: float
    actual_days: int
    currency: str | None
    estimated_input_tokens: float | None
    estimated_output_tokens: float | None
    estimated_total_tokens: float | None
    token_estimate_model: str | None
    token_data_source: str | None = None


def _safe_float(x: object) -> float:
    if x is None:
        return 0.0
    return float(x)


def list_projects_with_imported_tokens(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT project_name
        FROM token_usage_points
        ORDER BY project_name ASC
        """
    ).fetchall()
    return [r["project_name"] for r in rows]


def list_projects(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT name AS project_name FROM projects
        UNION
        SELECT DISTINCT project_name FROM token_usage_points
        ORDER BY project_name
        """
    ).fetchall()
    return [r["project_name"] for r in rows]


def project_has_imported_tokens(conn: sqlite3.Connection, project_name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM token_usage_points
        WHERE project_name = ?
        LIMIT 1
        """,
        (project_name,),
    ).fetchone()
    return row is not None


def get_imported_token_totals(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[float, float]:
    where = ["project_name = ?"]
    params: list[object] = [project_name]
    if start_date:
        where.append("usage_date >= ?")
        params.append(start_date)
    if end_date:
        where.append("usage_date <= ?")
        params.append(end_date)
    where_sql = " AND ".join(where)
    row = conn.execute(
        f"""
        SELECT
            COALESCE(SUM(CASE WHEN token_direction = 'input' THEN token_count ELSE 0 END), 0) AS input_tokens,
            COALESCE(SUM(CASE WHEN token_direction = 'output' THEN token_count ELSE 0 END), 0) AS output_tokens
        FROM token_usage_points
        WHERE {where_sql}
        """,
        tuple(params),
    ).fetchone()
    return float(row["input_tokens"]), float(row["output_tokens"])


def get_imported_token_timeseries(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    granularity: str = "day",
) -> list[dict]:
    if granularity not in {"day", "month"}:
        raise ValueError("granularity must be 'day' or 'month'")
    date_expr = "usage_date" if granularity == "day" else "substr(usage_date, 1, 7)"
    where = ["project_name = ?"]
    params: list[object] = [project_name]
    if start_date:
        where.append("usage_date >= ?")
        params.append(start_date)
    if end_date:
        where.append("usage_date <= ?")
        params.append(end_date)
    where_sql = " AND ".join(where)
    rows = conn.execute(
        f"""
        SELECT
            {date_expr} AS date,
            COALESCE(SUM(CASE WHEN token_direction = 'input' THEN token_count ELSE 0 END), 0) AS input_tokens,
            COALESCE(SUM(CASE WHEN token_direction = 'output' THEN token_count ELSE 0 END), 0) AS output_tokens
        FROM token_usage_points
        WHERE {where_sql}
        GROUP BY {date_expr}
        ORDER BY date ASC
        """,
        tuple(params),
    ).fetchall()
    by_date: dict[str, tuple[float, float]] = {}
    for r in rows:
        in_tok = float(r["input_tokens"])
        out_tok = float(r["output_tokens"])
        by_date[str(r["date"])] = (in_tok, out_tok)

    if granularity == "day" and by_date:
        _, billing_max = _transaction_usage_bounds(
            conn,
            project_name,
            from_date=start_date,
            to_date=end_date,
            currency=None,
        )
        _extend_token_calendar_with_billing_tail(
            by_date,
            billing_max=billing_max,
            cap_end=end_date,
        )

    out: list[dict] = []
    for d in sorted(by_date.keys()):
        in_tok, out_tok = by_date[d]
        out.append(
            {
                "date": d,
                "estimated_input_tokens": in_tok,
                "estimated_output_tokens": out_tok,
                "estimated_total_tokens": in_tok + out_tok,
            }
        )
    return out


def get_imported_token_meta(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, object]:
    where = ["project_name = ?"]
    params: list[object] = [project_name]
    if start_date:
        where.append("usage_date >= ?")
        params.append(start_date)
    if end_date:
        where.append("usage_date <= ?")
        params.append(end_date)
    where_sql = " AND ".join(where)
    row = conn.execute(
        f"""
        SELECT
            MIN(usage_date) AS min_usage_date,
            MAX(usage_date) AS max_usage_date,
            COUNT(DISTINCT model_name) AS model_count,
            COUNT(DISTINCT usage_date) AS day_count
        FROM token_usage_points
        WHERE {where_sql}
        """,
        tuple(params),
    ).fetchone()
    models = conn.execute(
        f"""
        SELECT DISTINCT model_name
        FROM token_usage_points
        WHERE {where_sql}
        ORDER BY model_name ASC
        """,
        tuple(params),
    ).fetchall()
    canonical_models = sorted(
        {
            canonical_model_name(r["model_name"]) or str(r["model_name"])
            for r in models
        }
    )
    bill_min, bill_max = _transaction_usage_bounds(
        conn,
        project_name,
        from_date=start_date,
        to_date=end_date,
        currency=None,
    )
    return {
        "min_usage_date": _iso_date_min(row["min_usage_date"], bill_min),
        "max_usage_date": _iso_date_max(row["max_usage_date"], bill_max),
        "model_count": int(row["model_count"] or 0),
        "day_count": int(row["day_count"] or 0),
        "models": canonical_models,
    }


def get_imported_token_breakdown_by_model(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    where = ["project_name = ?"]
    params: list[object] = [project_name]
    if start_date:
        where.append("usage_date >= ?")
        params.append(start_date)
    if end_date:
        where.append("usage_date <= ?")
        params.append(end_date)
    where_sql = " AND ".join(where)
    rows = conn.execute(
        f"""
        SELECT
            model_name,
            token_direction,
            COALESCE(SUM(token_count), 0) AS token_count
        FROM token_usage_points
        WHERE {where_sql}
        GROUP BY model_name, token_direction
        ORDER BY token_count DESC, model_name ASC
        """,
        tuple(params),
    ).fetchall()
    grand = sum(float(r["token_count"]) for r in rows) or 0.0
    merged: dict[tuple[str, str], float] = {}
    for r in rows:
        model = canonical_model_name(r["model_name"]) or str(r["model_name"])
        direction = str(r["token_direction"])
        cnt = float(r["token_count"])
        key = (model, direction)
        merged[key] = merged.get(key, 0.0) + cnt
    out: list[dict] = []
    for (model, direction), cnt in sorted(
        merged.items(),
        key=lambda item: (-float(item[1]), item[0][0], item[0][1]),
    ):
        out.append(
            {
                "model_name": model,
                "token_direction": direction,
                "token_count": cnt,
                "share_pct": None if grand <= 0 else round(100.0 * cnt / grand, 2),
            }
        )
    return out


def get_imported_token_daily_by_model(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    currency: str | None = None,
) -> list[dict[str, object]]:
    """Per calendar day and model: input/output token totals (for ratio tables and charts)."""
    where = ["project_name = ?"]
    params: list[object] = [project_name]
    if start_date:
        where.append("usage_date >= ?")
        params.append(start_date)
    if end_date:
        where.append("usage_date <= ?")
        params.append(end_date)
    where_sql = " AND ".join(where)
    rows = conn.execute(
        f"""
        SELECT
            usage_date AS date,
            model_name,
            COALESCE(SUM(CASE WHEN token_direction = 'input' THEN token_count ELSE 0 END), 0) AS input_tokens,
            COALESCE(SUM(CASE WHEN token_direction = 'output' THEN token_count ELSE 0 END), 0) AS output_tokens
        FROM token_usage_points
        WHERE {where_sql}
        GROUP BY usage_date, model_name
        ORDER BY usage_date DESC, model_name ASC
        """,
        tuple(params),
    ).fetchall()
    merged: dict[tuple[str, str], dict[str, float]] = {}
    for r in rows:
        in_tok = float(r["input_tokens"])
        out_tok = float(r["output_tokens"])
        if in_tok <= 0 and out_tok <= 0:
            continue
        d = str(r["date"])
        model_name = canonical_model_name(r["model_name"]) or str(r["model_name"])
        key = (d, model_name)
        cur = merged.setdefault(key, {"input": 0.0, "output": 0.0})
        cur["input"] += in_tok
        cur["output"] += out_tok

    cost_rows = get_imported_token_daily_cost_by_model(
        conn,
        project_name,
        start_date=start_date,
        end_date=end_date,
        currency=currency,
    )
    cost_by_key = {
        (str(r["date"]), str(r["model_name"])): r
        for r in cost_rows
    }

    out: list[dict[str, object]] = []
    for (d, model_name), vals in sorted(
        merged.items(),
        key=lambda item: (item[0][0], item[0][1]),
        reverse=True,
    ):
        in_tok = float(vals["input"])
        out_tok = float(vals["output"])
        ratio: float | None = (out_tok / in_tok) if in_tok > 0 else None
        c = cost_by_key.get((d, model_name), {})
        in_cost = c.get("input_cost_usd", 0.0)
        out_cost = c.get("output_cost_usd", 0.0)
        total_cost = c.get("total_cost_usd", (float(in_cost) + float(out_cost)))
        out.append(
            {
                "date": d,
                "model_name": model_name,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "output_input_ratio": round(ratio, 6) if ratio is not None else None,
                "input_cost_usd": round(float(in_cost), 6),
                "output_cost_usd": round(float(out_cost), 6),
                "total_cost_usd": round(float(total_cost), 6),
                "allocation_method": c.get("allocation_method", "no_cost_overlap"),
            }
        )
    return out


def get_imported_token_daily_cost_by_model(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    currency: str | None = None,
) -> list[dict[str, object]]:
    """
    Per calendar day + model: split daily cost into input/output buckets.

    Priority:
    1) meter-matched split by direction from billing Meter parse
    2) proportional fallback by token share within model/day when meter split is unavailable
    """
    where = ["project_name = ?"]
    params: list[object] = [project_name]
    if start_date:
        where.append("usage_date >= ?")
        params.append(start_date)
    if end_date:
        where.append("usage_date <= ?")
        params.append(end_date)
    where_sql = " AND ".join(where)
    rows = conn.execute(
        f"""
        SELECT
            usage_date AS date,
            model_name,
            COALESCE(SUM(CASE WHEN token_direction = 'input' THEN token_count ELSE 0 END), 0) AS input_tokens,
            COALESCE(SUM(CASE WHEN token_direction = 'output' THEN token_count ELSE 0 END), 0) AS output_tokens
        FROM token_usage_points
        WHERE {where_sql}
        GROUP BY usage_date, model_name
        ORDER BY usage_date ASC, model_name ASC
        """,
        tuple(params),
    ).fetchall()
    if not rows:
        return []

    by_date_model: dict[str, dict[str, dict[str, float]]] = {}
    totals_by_date: dict[str, tuple[float, float]] = {}
    for r in rows:
        d = str(r["date"])
        m = canonical_model_name(r["model_name"]) or str(r["model_name"])
        in_tok = float(r["input_tokens"] or 0.0)
        out_tok = float(r["output_tokens"] or 0.0)
        if in_tok <= 0 and out_tok <= 0:
            continue
        cur = by_date_model.setdefault(d, {}).setdefault(m, {"input": 0.0, "output": 0.0})
        cur["input"] += in_tok
        cur["output"] += out_tok
        tin, tout = totals_by_date.get(d, (0.0, 0.0))
        totals_by_date[d] = (tin + in_tok, tout + out_tok)

    if not by_date_model:
        return []

    token_dates = sorted(by_date_model.keys())
    eff_start, eff_end = token_dates[0], token_dates[-1]
    cost_points, chosen_currency = get_timeseries(
        conn,
        project_name,
        start_date=eff_start,
        end_date=eff_end,
        granularity="day",
        currency=currency,
    )
    cost_by_date = {str(p["date"]): float(p["cost_usd"] or 0.0) for p in cost_points}
    billing_by_date_model = get_meter_billing_by_date_model(
        conn,
        project_name,
        start_date=eff_start,
        end_date=eff_end,
        currency=chosen_currency,
    )

    out: list[dict[str, object]] = []
    for d in sorted(by_date_model.keys(), reverse=True):
        daily_cost = float(cost_by_date.get(d, 0.0))
        models = by_date_model.get(d, {})
        total_tokens = sum((v["input"] + v["output"]) for v in models.values())
        day_billing = billing_by_date_model.get(d, {})
        for model_name in sorted(models.keys()):
            tok = models[model_name]
            in_tok = float(tok["input"])
            out_tok = float(tok["output"])
            model_total = in_tok + out_tok
            if model_total <= 0:
                continue

            bill = day_billing.get(model_name)
            if bill is None:
                for bk, bv in day_billing.items():
                    if token_models_match(bk, model_name):
                        bill = bv
                        break
            bill = bill or {}
            bill_in = float(bill.get("input", 0.0))
            bill_out = float(bill.get("output", 0.0))
            meter_total = bill_in + bill_out

            if meter_total > 0:
                in_cost = bill_in
                out_cost = bill_out
                allocation_method = "meter_matched"
            elif daily_cost > 0 and total_tokens > 0:
                allocated = daily_cost * (model_total / total_tokens)
                in_share = (in_tok / model_total) if model_total > 0 else 0.0
                out_share = (out_tok / model_total) if model_total > 0 else 0.0
                in_cost = allocated * in_share
                out_cost = allocated * out_share
                allocation_method = "proportional_by_daily_tokens"
            else:
                in_cost = 0.0
                out_cost = 0.0
                allocation_method = "no_cost_overlap"

            total_cost = in_cost + out_cost
            out.append(
                {
                    "date": d,
                    "model_name": model_name,
                    "input_cost_usd": round(in_cost, 6),
                    "output_cost_usd": round(out_cost, 6),
                    "total_cost_usd": round(total_cost, 6),
                    "allocation_method": allocation_method,
                }
            )
    return out


def get_imported_token_models_with_prices(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict[str, object]]:
    where = ["project_name = ?"]
    params: list[object] = [project_name]
    if start_date:
        where.append("usage_date >= ?")
        params.append(start_date)
    if end_date:
        where.append("usage_date <= ?")
        params.append(end_date)
    where_sql = " AND ".join(where)

    usage_rows = conn.execute(
        f"""
        SELECT
            model_name,
            COALESCE(SUM(CASE WHEN token_direction = 'input' THEN token_count ELSE 0 END), 0) AS input_tokens,
            COALESCE(SUM(CASE WHEN token_direction = 'output' THEN token_count ELSE 0 END), 0) AS output_tokens
        FROM token_usage_points
        WHERE {where_sql}
        GROUP BY model_name
        ORDER BY model_name ASC
        """,
        tuple(params),
    ).fetchall()

    if not usage_rows:
        return []

    price_rows = conn.execute(
        """
        SELECT
            model_name,
            metric_name,
            amount,
            price_currency,
            price_region,
            effective_date,
            retrieved_at_utc,
            unit_expression,
            id
        FROM model_prices
        WHERE billing_mode = 'standard'
          AND metric_name IN ('input', 'output')
          AND amount > 0
        ORDER BY
          CASE WHEN price_currency = 'USD' THEN 0 ELSE 1 END,
          effective_date DESC,
          retrieved_at_utc DESC,
          id DESC
        """
    ).fetchall()

    def _metric_pick(model_name: str, metric_name: str) -> sqlite3.Row | None:
        target = _norm_model_name(model_name)
        if not target:
            return None
        for r in price_rows:
            if str(r["metric_name"]) != metric_name:
                continue
            candidate = _norm_model_name(str(r["model_name"]))
            if not candidate:
                continue
            if candidate == target or target in candidate or candidate in target:
                return r
        return None

    usage_by_model: dict[str, dict[str, float]] = {}
    for r in usage_rows:
        model_name = canonical_model_name(r["model_name"]) or str(r["model_name"])
        item = usage_by_model.setdefault(model_name, {"input_tokens": 0.0, "output_tokens": 0.0})
        item["input_tokens"] += float(r["input_tokens"] or 0.0)
        item["output_tokens"] += float(r["output_tokens"] or 0.0)

    out: list[dict[str, object]] = []
    for model_name in sorted(usage_by_model.keys()):
        pin = _metric_pick(model_name, "input")
        pout = _metric_pick(model_name, "output")
        cur = None
        if pin and pin["price_currency"]:
            cur = str(pin["price_currency"])
        elif pout and pout["price_currency"]:
            cur = str(pout["price_currency"])

        out.append(
            {
                "model_name": model_name,
                "input_tokens": float(usage_by_model[model_name]["input_tokens"]),
                "output_tokens": float(usage_by_model[model_name]["output_tokens"]),
                "input_price_per_1m": None if pin is None else float(pin["amount"]),
                "output_price_per_1m": None if pout is None else float(pout["amount"]),
                "price_currency": cur or "USD",
                "input_price_unit": None if pin is None else pin["unit_expression"],
                "output_price_unit": None if pout is None else pout["unit_expression"],
                "price_region": (
                    str(pin["price_region"])
                    if pin is not None and pin["price_region"]
                    else (str(pout["price_region"]) if pout is not None and pout["price_region"] else None)
                ),
            }
        )
    return out


TOKENS_PER_MILLION = 1_000_000.0


def _float_stats(vals: list[float]) -> dict[str, float | int | None]:
    if not vals:
        return {"min": None, "max": None, "mean": None, "median": None, "count": 0}
    return {
        "min": float(min(vals)),
        "max": float(max(vals)),
        "mean": float(_mean(vals)),
        "median": float(_median(vals)),
        "count": len(vals),
    }


def _catalog_usd_per_1m_for_model_name(conn: sqlite3.Connection, model_name: str) -> dict[str, float | None]:
    target = _norm_model_name(model_name)
    if not target:
        return {"input": None, "output": None}
    rows = conn.execute(
        """
        SELECT model_name, metric_name, amount
        FROM model_prices
        WHERE price_currency = 'USD'
          AND billing_mode = 'standard'
          AND metric_name IN ('input', 'output')
          AND amount > 0
        """
    ).fetchall()
    matches = [
        r
        for r in rows
        if (
            _norm_model_name(r["model_name"]) == target
            or target in _norm_model_name(r["model_name"])
            or _norm_model_name(r["model_name"]) in target
        )
    ]
    input_prices = [float(r["amount"]) for r in matches if r["metric_name"] == "input"]
    output_prices = [float(r["amount"]) for r in matches if r["metric_name"] == "output"]
    return {
        "input": min(input_prices) if input_prices else None,
        "output": min(output_prices) if output_prices else None,
    }


def _billing_transaction_rows(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    currency: str | None = None,
) -> list[tuple[str, str, float]]:
    currency_filter = currency
    if currency_filter is None:
        currencies = get_available_currencies(conn, project_name)
        currency_filter = currencies[0] if currencies else None
    where = ["project_name = ?"]
    params: list[object] = [project_name]
    if start_date:
        where.append("usage_date >= ?")
        params.append(start_date)
    if end_date:
        where.append("usage_date <= ?")
        params.append(end_date)
    if currency_filter:
        where.append("currency = ?")
        params.append(currency_filter)
    where_sql = " AND ".join(where)
    rows = conn.execute(
        f"""
        SELECT usage_date, meter, COALESCE(cost_usd, 0) AS cost_usd
        FROM transactions
        WHERE {where_sql}
        """,
        tuple(params),
    ).fetchall()
    return [(str(r["usage_date"]), str(r["meter"] or ""), float(r["cost_usd"])) for r in rows]


def get_meter_billing_by_date_model(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    currency: str | None = None,
) -> dict[str, dict[str, dict[str, float]]]:
    """Sum ``CostUSD`` by calendar day and token model (from parsed ``Meter``)."""
    rows = _billing_transaction_rows(
        conn,
        project_name,
        start_date=start_date,
        end_date=end_date,
        currency=currency,
    )
    return aggregate_billing_rows(rows)


def get_project_meter_billing_by_direction_day(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    currency: str | None = None,
) -> dict[str, dict[str, float]]:
    """Project-level daily billing split into input/output buckets via meter parse."""
    by_date_model = get_meter_billing_by_date_model(
        conn,
        project_name,
        start_date=start_date,
        end_date=end_date,
        currency=currency,
    )
    out: dict[str, dict[str, float]] = {}
    for d, models in by_date_model.items():
        bill_in = sum(float(m.get("input", 0.0)) for m in models.values())
        bill_out = sum(float(m.get("output", 0.0)) for m in models.values())
        out[d] = {"input": bill_in, "output": bill_out, "total": bill_in + bill_out}
    return out


def get_billing_token_bridge(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    currency: str | None = None,
) -> dict[str, object]:
    """
    Diagnostics: how billing meters map to imported token model columns,
    and per-day overlap between meter-matched cost and token volume.
    """
    if not project_has_imported_tokens(conn, project_name):
        return {
            "available": False,
            "reason": "no_imported_tokens",
            "project": project_name,
        }

    bill_rows = _billing_transaction_rows(
        conn,
        project_name,
        start_date=start_date,
        end_date=end_date,
        currency=currency,
    )
    meter_stats: dict[str, dict[str, object]] = {}
    parsed_cost = 0.0
    total_cost = 0.0
    for usage_date, meter, cost in bill_rows:
        total_cost += cost
        parsed = parse_foundry_meter(meter)
        key = meter or ""
        st = meter_stats.setdefault(
            key,
            {
                "meter": meter,
                "parsed": parsed is not None,
                "token_model": parsed.token_model if parsed else None,
                "billing_direction": parsed.billing_direction if parsed else None,
                "cost_usd": 0.0,
                "row_count": 0,
            },
        )
        st["cost_usd"] = float(st["cost_usd"]) + cost
        st["row_count"] = int(st["row_count"]) + 1
        if parsed is not None:
            parsed_cost += cost

    billing_by_date_model = aggregate_billing_rows(bill_rows)
    token_daily = get_imported_token_daily_by_model(
        conn,
        project_name,
        start_date=start_date,
        end_date=end_date,
    )
    token_models = sorted({str(r["model_name"]) for r in token_daily})
    billing_models = sorted(
        {m for models in billing_by_date_model.values() for m in models.keys()}
    )

    token_norm = {normalize_token_column(m): m for m in token_models}
    billing_norm = {normalize_token_column(m): m for m in billing_models}
    token_only = [m for m in token_models if normalize_token_column(m) not in billing_norm]
    billing_only = [m for m in billing_models if normalize_token_column(m) not in token_norm]

    daily_bridge: list[dict[str, object]] = []
    dates = sorted(
        set(billing_by_date_model.keys())
        | {str(r["date"]) for r in token_daily}
    )
    for d in dates:
        for model in sorted(
            set(billing_by_date_model.get(d, {}).keys())
            | {
                str(r["model_name"])
                for r in token_daily
                if str(r["date"]) == d
            }
        ):
            bill = billing_by_date_model.get(d, {}).get(model, {})
            tok_row = next(
                (
                    r
                    for r in token_daily
                    if str(r["date"]) == d and token_models_match(str(r["model_name"]), model)
                ),
                None,
            )
            tin = float(tok_row["input_tokens"]) if tok_row else 0.0
            tout = float(tok_row["output_tokens"]) if tok_row else 0.0
            bin_c = float(bill.get("input", 0.0))
            bout_c = float(bill.get("output", 0.0))
            daily_bridge.append(
                {
                    "date": d,
                    "token_model": model,
                    "billing_input_usd": round(bin_c, 6),
                    "billing_output_usd": round(bout_c, 6),
                    "input_tokens": tin,
                    "output_tokens": tout,
                    "meter_matched": (bin_c > 0 or bout_c > 0)
                    and (tin > 0 or tout > 0),
                }
            )

    parse_rate = (parsed_cost / total_cost) if total_cost > 0 else 0.0
    return {
        "available": True,
        "project": project_name,
        "from_date": start_date,
        "to_date": end_date,
        "currency": currency,
        "rules": [
            {
                "rule_id": "foundry_v1",
                "description": "Azure Foundry meter → gpt-{version}[-{family}]",
            }
        ],
        "meter_summary": sorted(
            meter_stats.values(),
            key=lambda x: float(x["cost_usd"]),
            reverse=True,
        ),
        "parse_rate_by_cost": round(parse_rate, 4),
        "parsed_cost_usd": round(parsed_cost, 6),
        "total_cost_usd": round(total_cost, 6),
        "token_models": token_models,
        "billing_models": billing_models,
        "token_models_without_billing": token_only,
        "billing_models_without_tokens": billing_only,
        "daily": daily_bridge,
    }


def get_model_implied_usd_per_1m_analysis(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    currency: str | None = None,
) -> dict[str, object]:
    """
    Implied USD per 1M tokens per model per day.

    Primary: sum billing ``Meter`` rows matched to token CSV model columns
    (e.g. ``5.3 codex inp`` → ``gpt-5.3-codex`` input). Fallback when meters
    do not parse: proportional split of daily project cost by token share.
    """
    if not project_has_imported_tokens(conn, project_name):
        return {
            "available": False,
            "reason": "no_imported_tokens",
            "project": project_name,
            "currency": currency,
            "models": [],
        }

    where = ["project_name = ?"]
    params: list[object] = [project_name]
    if start_date:
        where.append("usage_date >= ?")
        params.append(start_date)
    if end_date:
        where.append("usage_date <= ?")
        params.append(end_date)
    where_sql = " AND ".join(where)
    token_rows = conn.execute(
        f"""
        SELECT
            usage_date,
            model_name,
            token_direction,
            COALESCE(SUM(token_count), 0) AS token_count
        FROM token_usage_points
        WHERE {where_sql}
        GROUP BY usage_date, model_name, token_direction
        """,
        tuple(params),
    ).fetchall()

    by_date_model: dict[str, dict[str, dict[str, float]]] = {}
    for r in token_rows:
        d = str(r["usage_date"])
        model = canonical_model_name(r["model_name"]) or str(r["model_name"])
        direction = str(r["token_direction"])
        by_date_model.setdefault(d, {}).setdefault(model, {"input": 0.0, "output": 0.0})
        if direction in {"input", "output"}:
            by_date_model[d][model][direction] += float(r["token_count"])

    if not by_date_model:
        return {
            "available": True,
            "project": project_name,
            "currency": currency,
            "from_date": start_date,
            "to_date": end_date,
            "unit_label": "USD per 1M tokens",
            "allocation_method": "proportional_by_daily_tokens",
            "models": [],
        }

    totals_by_date: dict[str, tuple[float, float]] = {}
    for d, models in by_date_model.items():
        tin = sum(float(m["input"]) for m in models.values())
        tout = sum(float(m["output"]) for m in models.values())
        totals_by_date[d] = (tin, tout)
    _, billing_max = _transaction_usage_bounds(
        conn,
        project_name,
        from_date=start_date,
        to_date=end_date,
        currency=currency,
    )
    _extend_token_calendar_with_billing_tail(
        totals_by_date,
        billing_max=billing_max,
        cap_end=end_date,
    )
    for d in totals_by_date:
        by_date_model.setdefault(d, {})

    token_dates = sorted(by_date_model.keys())
    eff_start, eff_end = token_dates[0], token_dates[-1]
    cost_points, chosen_currency = get_timeseries(
        conn,
        project_name,
        start_date=eff_start,
        end_date=eff_end,
        granularity="day",
        currency=currency,
    )
    cost_by_date = {str(p["date"]): float(p["cost_usd"]) for p in cost_points}
    billing_by_date_model = get_meter_billing_by_date_model(
        conn,
        project_name,
        start_date=eff_start,
        end_date=eff_end,
        currency=chosen_currency,
    )
    used_meter_match = False
    used_proportional = False

    model_daily: dict[str, list[dict[str, object]]] = {}
    models_seen: set[str] = set()
    for _d, models in by_date_model.items():
        for mn in models.keys():
            models_seen.add(mn)

    for usage_date in token_dates:
        daily_cost = cost_by_date.get(usage_date, 0.0)
        day_models = by_date_model.get(usage_date, {})
        if not day_models:
            continue

        total_tokens = 0.0
        for tok in day_models.values():
            total_tokens += tok["input"] + tok["output"]
        if total_tokens <= 0:
            continue

        day_billing = billing_by_date_model.get(usage_date, {})

        for model_name, tok in day_models.items():
            in_tok = tok["input"]
            out_tok = tok["output"]
            model_total = in_tok + out_tok
            if model_total <= 0:
                continue

            bill = day_billing.get(model_name)
            if bill is None:
                for bk, bv in day_billing.items():
                    if token_models_match(bk, model_name):
                        bill = bv
                        break
            bill = bill or {}
            bill_in = float(bill.get("input", 0.0))
            bill_out = float(bill.get("output", 0.0))
            meter_cost = bill_in + bill_out

            if meter_cost > 0:
                used_meter_match = True
                allocated_cost = meter_cost
                usd_per_1m_input = (
                    (bill_in / in_tok) * TOKENS_PER_MILLION if in_tok > 0 and bill_in > 0 else None
                )
                usd_per_1m_output = (
                    (bill_out / out_tok) * TOKENS_PER_MILLION
                    if out_tok > 0 and bill_out > 0
                    else None
                )
                alloc_method = "meter_matched"
            elif daily_cost > 0:
                used_proportional = True
                allocated_cost = daily_cost * (model_total / total_tokens)
                in_share = in_tok / model_total if model_total > 0 else 0.0
                out_share = out_tok / model_total if model_total > 0 else 0.0
                usd_per_1m_input = (
                    (allocated_cost * in_share / in_tok) * TOKENS_PER_MILLION
                    if in_tok > 0
                    else None
                )
                usd_per_1m_output = (
                    (allocated_cost * out_share / out_tok) * TOKENS_PER_MILLION
                    if out_tok > 0
                    else None
                )
                alloc_method = "proportional_by_daily_tokens"
            else:
                continue

            usd_per_1m_blended = (allocated_cost / model_total) * TOKENS_PER_MILLION

            model_daily.setdefault(model_name, []).append(
                {
                    "date": usage_date,
                    "cost_usd_allocated": round(allocated_cost, 6),
                    "input_tokens": in_tok,
                    "output_tokens": out_tok,
                    "total_tokens": model_total,
                    "usd_per_1m_input": (
                        round(usd_per_1m_input, 6) if usd_per_1m_input is not None else None
                    ),
                    "usd_per_1m_output": (
                        round(usd_per_1m_output, 6) if usd_per_1m_output is not None else None
                    ),
                    "usd_per_1m_blended": round(usd_per_1m_blended, 6),
                    "allocation_method": alloc_method,
                }
            )

    models_out: list[dict[str, object]] = []
    for model_name in sorted(models_seen):
        daily = model_daily.get(model_name, [])
        catalog = _catalog_usd_per_1m_for_model_name(conn, model_name)
        models_out.append(
            {
                "model_name": model_name,
                "catalog_usd_per_1m_input": catalog["input"],
                "catalog_usd_per_1m_output": catalog["output"],
                "daily": daily,
                "stats": {
                    "input": _float_stats(
                        [float(d["usd_per_1m_input"]) for d in daily if d["usd_per_1m_input"] is not None]
                    ),
                    "output": _float_stats(
                        [float(d["usd_per_1m_output"]) for d in daily if d["usd_per_1m_output"] is not None]
                    ),
                    "blended": _float_stats(
                        [float(d["usd_per_1m_blended"]) for d in daily if d["usd_per_1m_blended"] is not None]
                    ),
                },
            }
        )

    if used_meter_match and not used_proportional:
        top_method = "meter_matched"
    elif used_meter_match and used_proportional:
        top_method = "meter_matched_with_proportional_fallback"
    else:
        top_method = "proportional_by_daily_tokens"

    return {
        "available": True,
        "project": project_name,
        "currency": chosen_currency,
        "from_date": eff_start,
        "to_date": eff_end,
        "unit_label": "USD per 1M tokens",
        "allocation_method": top_method,
        "models": models_out,
    }


def get_project_daily_implied_usd_per_1m_timeseries(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    currency: str | None = None,
) -> dict[str, object]:
    """
    Project-level daily implied list price: full day bill ÷ (sum of imported tokens / 1M)
    separately for input and output directions.

    Same calendar-day billing row is compared against total input millions and total output
    millions (not additive; each series answers "if the whole bill were spread only over
    that direction's volume").

    Returned ``points`` are keyed on the **imported token calendar** (same ``start_date`` /
    ``end_date`` filters as the token aggregate), then extended **forward only** through
    any later billing days in that window so trailing bills still appear even when token
    CSVs stop early. Earlier billing-only history before the first token day is still
    excluded.
    """
    if not project_has_imported_tokens(conn, project_name):
        return {
            "available": False,
            "reason": "no_imported_tokens",
            "project": project_name,
            "currency": currency,
            "points": [],
            "stats": {
                "input": _float_stats([]),
                "output": _float_stats([]),
            },
        }

    where = ["project_name = ?"]
    params: list[object] = [project_name]
    if start_date:
        where.append("usage_date >= ?")
        params.append(start_date)
    if end_date:
        where.append("usage_date <= ?")
        params.append(end_date)
    where_sql = " AND ".join(where)
    agg_rows = conn.execute(
        f"""
        SELECT
            usage_date AS usage_date,
            COALESCE(SUM(CASE WHEN token_direction = 'input' THEN token_count ELSE 0 END), 0) AS input_tokens,
            COALESCE(SUM(CASE WHEN token_direction = 'output' THEN token_count ELSE 0 END), 0) AS output_tokens
        FROM token_usage_points
        WHERE {where_sql}
        GROUP BY usage_date
        """,
        tuple(params),
    ).fetchall()
    tokens_by_date: dict[str, tuple[float, float]] = {}
    for r in agg_rows:
        d = str(r["usage_date"])
        tin = float(r["input_tokens"] or 0.0)
        tout = float(r["output_tokens"] or 0.0)
        tokens_by_date[d] = (tin, tout)

    _, billing_max = _transaction_usage_bounds(
        conn,
        project_name,
        from_date=start_date,
        to_date=end_date,
        currency=currency,
    )
    _extend_token_calendar_with_billing_tail(
        tokens_by_date,
        billing_max=billing_max,
        cap_end=end_date,
    )

    token_dates_sorted = sorted(tokens_by_date.keys())
    if not token_dates_sorted:
        cur = currency or "USD"
        return {
            "available": True,
            "project": project_name,
            "currency": currency,
            "from_date": start_date,
            "to_date": end_date,
            "unit_label": f"{cur} per 1M tokens",
            "definition": "daily_cost / (sum_imported_tokens_in_direction / 1_000_000)",
            "points": [],
            "stats": {
                "input": _float_stats([]),
                "output": _float_stats([]),
            },
        }

    eff_start, eff_end = token_dates_sorted[0], token_dates_sorted[-1]
    cost_points, chosen_currency = get_timeseries(
        conn,
        project_name,
        start_date=eff_start,
        end_date=eff_end,
        granularity="day",
        currency=currency,
    )
    cost_by_date: dict[str, float | None] = {}
    for p in cost_points:
        d = str(p["date"])
        raw = p.get("cost_usd")
        cost_by_date[d] = float(raw) if raw is not None else None

    meter_by_day = get_project_meter_billing_by_direction_day(
        conn,
        project_name,
        start_date=eff_start,
        end_date=eff_end,
        currency=chosen_currency,
    )

    points: list[dict[str, object]] = []
    input_vals: list[float] = []
    output_vals: list[float] = []

    for d in token_dates_sorted:
        raw_cost = cost_by_date.get(d)
        cost = float(raw_cost) if raw_cost is not None else None
        meter_day = meter_by_day.get(d, {})
        cost_in = float(meter_day.get("input", 0.0))
        cost_out = float(meter_day.get("output", 0.0))
        meter_total = float(meter_day.get("total", 0.0))

        tin, tout = tokens_by_date.get(d, (0.0, 0.0))
        has_tokens = tin > 0 or tout > 0

        usd_in: float | None = None
        usd_out: float | None = None
        display_cost = meter_total if meter_total > 0 else cost
        if cost_in > 0 and tin > 0:
            usd_in = (cost_in / tin) * TOKENS_PER_MILLION
            input_vals.append(usd_in)
        elif cost is not None and cost > 0 and tin > 0:
            usd_in = (cost / tin) * TOKENS_PER_MILLION
            input_vals.append(usd_in)
        if cost_out > 0 and tout > 0:
            usd_out = (cost_out / tout) * TOKENS_PER_MILLION
            output_vals.append(usd_out)
        elif cost is not None and cost > 0 and tout > 0:
            usd_out = (cost / tout) * TOKENS_PER_MILLION
            output_vals.append(usd_out)

        points.append(
            {
                "date": d,
                "cost_usd": round(display_cost, 6) if display_cost is not None else None,
                "input_tokens": tin if has_tokens else None,
                "output_tokens": tout if has_tokens else None,
                "usd_per_1m_input": round(usd_in, 6) if usd_in is not None else None,
                "usd_per_1m_output": round(usd_out, 6) if usd_out is not None else None,
            }
        )

    cur = chosen_currency or "USD"
    return {
        "available": True,
        "project": project_name,
        "currency": chosen_currency,
        "from_date": eff_start,
        "to_date": eff_end,
        "unit_label": f"{cur} per 1M tokens",
        "definition": "daily_cost / (sum_imported_tokens_in_direction / 1_000_000)",
        "points": points,
        "stats": {
            "input": _float_stats(input_vals),
            "output": _float_stats(output_vals),
        },
    }


def _imported_token_periods(
    conn: sqlite3.Connection,
    *,
    project_name: str,
    granularity: str,
    start_date: str | None,
    end_date: str | None,
) -> list[str]:
    date_expr = "usage_date" if granularity == "day" else "substr(usage_date, 1, 7)"
    where = ["project_name = ?"]
    params: list[object] = [project_name]
    if start_date:
        where.append("usage_date >= ?")
        params.append(start_date)
    if end_date:
        where.append("usage_date <= ?")
        params.append(end_date)
    where_sql = " AND ".join(where)
    rows = conn.execute(
        f"""
        SELECT DISTINCT {date_expr} AS period
        FROM token_usage_points
        WHERE {where_sql}
        ORDER BY period ASC
        """,
        tuple(params),
    ).fetchall()
    return [str(r["period"]) for r in rows]


def _aggregate_imported_tokens_into_period(
    conn: sqlite3.Connection,
    *,
    project_name: str,
    granularity: str,
    start_date: str | None,
    end_date: str | None,
    per_period: dict[str, dict[str, object]],
    period_set: set[str],
) -> None:
    date_expr = "usage_date" if granularity == "day" else "substr(usage_date, 1, 7)"
    where = ["project_name = ?"]
    params: list[object] = [project_name]
    if start_date:
        where.append("usage_date >= ?")
        params.append(start_date)
    if end_date:
        where.append("usage_date <= ?")
        params.append(end_date)
    where_sql = " AND ".join(where)
    rows = conn.execute(
        f"""
        SELECT
            {date_expr} AS period,
            COALESCE(SUM(CASE WHEN token_direction = 'input' THEN token_count ELSE 0 END), 0) AS input_tokens,
            COALESCE(SUM(CASE WHEN token_direction = 'output' THEN token_count ELSE 0 END), 0) AS output_tokens
        FROM token_usage_points
        WHERE {where_sql}
        GROUP BY {date_expr}
        ORDER BY period ASC
        """,
        tuple(params),
    ).fetchall()
    for r in rows:
        period = str(r["period"])
        if period not in period_set:
            period_set.add(period)
            per_period[period] = {"input": 0.0, "output": 0.0, "has": False}
        in_tok = float(r["input_tokens"])
        out_tok = float(r["output_tokens"])
        per_period[period]["input"] = _safe_float(per_period[period]["input"]) + in_tok
        per_period[period]["output"] = _safe_float(per_period[period]["output"]) + out_tok
        if in_tok > 0 or out_tok > 0:
            per_period[period]["has"] = True


def upsert_project_model_config(
    conn: sqlite3.Connection,
    *,
    project_name: str,
    model_name: str,
    api_version: str | None,
    azure_endpoint: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO project_model_configs(
            project_name, model_name, api_version, azure_endpoint, updated_at
        ) VALUES (?, ?, ?, ?, datetime('now'))
        ON CONFLICT(project_name) DO UPDATE SET
            model_name = excluded.model_name,
            api_version = excluded.api_version,
            azure_endpoint = excluded.azure_endpoint,
            updated_at = datetime('now')
        """,
        (project_name, model_name, api_version, azure_endpoint),
    )
    conn.commit()


def get_project_model_config(conn: sqlite3.Connection, project_name: str) -> dict | None:
    row = conn.execute(
        """
        SELECT project_name, model_name, api_version, azure_endpoint, updated_at
        FROM project_model_configs
        WHERE project_name = ?
        """,
        (project_name,),
    ).fetchone()
    if row is None:
        return None
    return {
        "project_name": row["project_name"],
        "model_name": row["model_name"],
        "api_version": row["api_version"],
        "azure_endpoint": row["azure_endpoint"],
        "updated_at": row["updated_at"],
    }


def _norm_model_name(v: str | None) -> str:
    return normalize_token_column(canonical_model_name(v))


def _get_project_token_price_model(
    conn: sqlite3.Connection, *, project_name: str
) -> dict[str, object] | None:
    cfg = get_project_model_config(conn, project_name)
    if not cfg:
        return None

    target = _norm_model_name(cfg["model_name"])
    if not target:
        return None

    rows = conn.execute(
        """
        SELECT model_name, metric_name, amount, price_region
        FROM model_prices
        WHERE price_currency = 'USD'
          AND billing_mode = 'standard'
          AND metric_name IN ('input', 'output')
          AND amount > 0
        """
    ).fetchall()
    matches = [
        r
        for r in rows
        if (
            _norm_model_name(r["model_name"]) == target
            or target in _norm_model_name(r["model_name"])
            or _norm_model_name(r["model_name"]) in target
        )
    ]
    if not matches:
        return None

    input_prices = [float(r["amount"]) for r in matches if r["metric_name"] == "input"]
    output_prices = [float(r["amount"]) for r in matches if r["metric_name"] == "output"]
    if not input_prices or not output_prices:
        return None

    # Conservative estimate: use min standard prices found for configured model.
    regions = sorted({str(r["price_region"]) for r in matches if r["price_region"]})
    return {
        "model_name": cfg["model_name"],
        "input_price": min(input_prices),
        "output_price": min(output_prices),
        # Might be multiple regions if multiple price entries exist for the same model.
        # Keep it fully visible for the dashboard (frontend can wrap/scroll if needed).
        "price_region": ", ".join(regions) if regions else None,
    }


def _estimate_tokens_from_price(
    *,
    cost_usd: float,
    input_price: float,
    output_price: float,
) -> dict[str, float] | None:
    if cost_usd <= 0 or input_price <= 0 or output_price <= 0:
        return None
    return {
        "estimated_input_tokens": (cost_usd / input_price) * 1_000_000.0,
        "estimated_output_tokens": (cost_usd / output_price) * 1_000_000.0,
    }


def _estimate_tokens_by_cost(
    conn: sqlite3.Connection, *, project_name: str, total_cost_usd: float
) -> dict | None:
    if total_cost_usd <= 0:
        return None
    price_model = _get_project_token_price_model(conn, project_name=project_name)
    if not price_model:
        return None
    token_est = _estimate_tokens_from_price(
        cost_usd=total_cost_usd,
        input_price=float(price_model["input_price"]),
        output_price=float(price_model["output_price"]),
    )
    if token_est is None:
        return None
    return {
        "model_name": price_model["model_name"],
        **token_est,
    }


def ensure_project(conn: sqlite3.Connection, project_name: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO projects(name) VALUES (?)",
        (project_name,),
    )


def get_available_currencies(conn: sqlite3.Connection, project_name: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT currency, COUNT(*) AS cnt
        FROM transactions
        WHERE project_name = ? AND currency IS NOT NULL
        GROUP BY currency
        ORDER BY cnt DESC, currency ASC
        """,
        (project_name,),
    ).fetchall()
    return [r["currency"] for r in rows]


def _iso_date_min(*dates: str | None) -> str | None:
    vals = [d for d in dates if d]
    return min(vals) if vals else None


def _iso_date_max(*dates: str | None) -> str | None:
    vals = [d for d in dates if d]
    return max(vals) if vals else None


def _transaction_usage_bounds(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    currency: str | None = None,
) -> tuple[str | None, str | None]:
    """Min/max ``usage_date`` in ``transactions`` for the project (optional filters)."""
    currency_filter = currency
    if currency_filter is None:
        currencies = get_available_currencies(conn, project_name)
        currency_filter = currencies[0] if currencies else None
    where = ["project_name = ?"]
    params: list[object] = [project_name]
    if from_date:
        where.append("usage_date >= ?")
        params.append(from_date)
    if to_date:
        where.append("usage_date <= ?")
        params.append(to_date)
    if currency_filter:
        where.append("currency = ?")
        params.append(currency_filter)
    where_sql = " AND ".join(where)
    row = conn.execute(
        f"""
        SELECT MIN(usage_date) AS mn, MAX(usage_date) AS mx
        FROM transactions
        WHERE {where_sql}
        """,
        tuple(params),
    ).fetchone()
    return row["mn"], row["mx"]


def _extend_token_calendar_with_billing_tail(
    tokens_by_date: dict[str, tuple[float, float]],
    *,
    billing_max: str | None,
    cap_end: str | None = None,
    max_new_days: int = 366,
) -> None:
    """Append zero-token ISO days after the last token day through ``billing_max`` (capped).

    Only extends **forward** from the latest key already in ``tokens_by_date``; does not
    pull in earlier billing-only history (keeps series anchored on imported usage).
    """
    if not tokens_by_date or not billing_max:
        return
    last_t = max(tokens_by_date.keys())
    eff_end = billing_max
    if cap_end and cap_end < eff_end:
        eff_end = cap_end
    if eff_end <= last_t:
        return
    d = date.fromisoformat(last_t)
    end_d = date.fromisoformat(eff_end)
    added = 0
    while d < end_d and added < max_new_days:
        d += timedelta(days=1)
        ds = d.isoformat()
        if ds not in tokens_by_date:
            tokens_by_date[ds] = (0.0, 0.0)
            added += 1


def get_project_stats(
    conn: sqlite3.Connection,
    project_name: str,
    from_date: str | None = None,
    to_date: str | None = None,
    currency: str | None = None,
) -> ProjectStats:
    currency_filter = currency
    if currency_filter is None:
        currencies = get_available_currencies(conn, project_name)
        currency_filter = currencies[0] if currencies else None

    where = ["project_name = ?"]
    params: list[object] = [project_name]
    if from_date:
        where.append("usage_date >= ?")
        params.append(from_date)
    if to_date:
        where.append("usage_date <= ?")
        params.append(to_date)
    if currency_filter:
        where.append("currency = ?")
        params.append(currency_filter)

    where_sql = " AND ".join(where)
    row = conn.execute(
        f"""
        SELECT
            MIN(usage_date) AS min_usage_date,
            MAX(usage_date) AS max_usage_date,
            COALESCE(SUM(cost_usd), 0) AS actual_cost_usd_total,
            COUNT(DISTINCT CASE WHEN cost_usd IS NOT NULL THEN usage_date END) AS actual_days
        FROM transactions
        WHERE {where_sql}
        """,
        tuple(params),
    ).fetchone()

    total_cost_usd = _safe_float(row["actual_cost_usd_total"])

    if project_has_imported_tokens(conn, project_name):
        in_tok, out_tok = get_imported_token_totals(
            conn, project_name, start_date=from_date, end_date=to_date
        )
        token_row = conn.execute(
            """
            SELECT MIN(usage_date) AS min_usage_date, MAX(usage_date) AS max_usage_date
            FROM token_usage_points
            WHERE project_name = ?
            """
            + (" AND usage_date >= ?" if from_date else "")
            + (" AND usage_date <= ?" if to_date else ""),
            tuple(
                [project_name]
                + ([from_date] if from_date else [])
                + ([to_date] if to_date else [])
            ),
        ).fetchone()
        return ProjectStats(
            project_name=project_name,
            from_date=from_date,
            to_date=to_date,
            min_usage_date=_iso_date_min(
                token_row["min_usage_date"], row["min_usage_date"]
            ),
            max_usage_date=_iso_date_max(
                token_row["max_usage_date"], row["max_usage_date"]
            ),
            actual_cost_usd_total=total_cost_usd,
            actual_days=int(row["actual_days"]),
            currency=currency_filter,
            estimated_input_tokens=in_tok,
            estimated_output_tokens=out_tok,
            estimated_total_tokens=in_tok + out_tok,
            token_estimate_model=None,
            token_data_source="imported",
        )

    token_estimate = _estimate_tokens_by_cost(
        conn, project_name=project_name, total_cost_usd=total_cost_usd
    ) or {}

    return ProjectStats(
        project_name=project_name,
        from_date=from_date,
        to_date=to_date,
        min_usage_date=row["min_usage_date"],
        max_usage_date=row["max_usage_date"],
        actual_cost_usd_total=total_cost_usd,
        actual_days=int(row["actual_days"]),
        currency=currency_filter,
        estimated_input_tokens=token_estimate.get("estimated_input_tokens"),
        estimated_output_tokens=token_estimate.get("estimated_output_tokens"),
        estimated_total_tokens=(
            None
            if token_estimate.get("estimated_input_tokens") is None
            or token_estimate.get("estimated_output_tokens") is None
            else float(token_estimate["estimated_input_tokens"]) + float(token_estimate["estimated_output_tokens"])
        ),
        token_estimate_model=token_estimate.get("model_name"),
        token_data_source="estimated" if token_estimate else None,
    )


def get_timeseries(
    conn: sqlite3.Connection,
    project_name: str,
    start_date: str | None = None,
    end_date: str | None = None,
    granularity: str = "day",
    currency: str | None = None,
) -> tuple[list[dict], str | None]:
    if granularity not in {"day", "month"}:
        raise ValueError("granularity must be 'day' or 'month'")

    date_expr = "usage_date" if granularity == "day" else "substr(usage_date, 1, 7)"

    currency_filter = currency
    if currency_filter is None:
        currencies = get_available_currencies(conn, project_name)
        currency_filter = currencies[0] if currencies else None

    where = ["project_name = ?"]
    params: list[object] = [project_name]
    if start_date:
        where.append("usage_date >= ?")
        params.append(start_date)
    if end_date:
        where.append("usage_date <= ?")
        params.append(end_date)
    if currency_filter:
        where.append("currency = ?")
        params.append(currency_filter)

    where_sql = " AND ".join(where)
    rows = conn.execute(
        f"""
        SELECT
            {date_expr} AS period,
            COALESCE(SUM(cost_usd), 0) AS actual_cost_usd_total
        FROM transactions
        WHERE {where_sql}
        GROUP BY {date_expr}
        ORDER BY period ASC
        """,
        tuple(params),
    ).fetchall()

    points = [
        {
            "date": r["period"],
            "cost_usd": float(r["actual_cost_usd_total"]),
        }
        for r in rows
    ]
    return points, currency_filter


def get_cost_forecast_baseline(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    window_days: int = 28,
    currency: str | None = None,
) -> dict[str, Any]:
    """
    Calendar-window average daily CostUSD for simple cost extrapolation.

    Uses the last ``window_days`` calendar days ending at MAX(usage_date) for the project,
    filling missing days with 0. Suitable for "pizza team scale" multipliers on the client.
    """
    wd = max(7, min(90, int(window_days)))
    cfg_row = get_project_model_config(conn, project_name)
    team_model: dict[str, Any] | None = None
    if cfg_row:
        team_model = {
            "model_name": cfg_row["model_name"],
            "api_version": cfg_row["api_version"],
            "has_endpoint": bool(cfg_row.get("azure_endpoint")),
            "updated_at": cfg_row.get("updated_at"),
        }

    row = conn.execute(
        "SELECT MAX(usage_date) AS mx FROM transactions WHERE project_name = ?",
        (project_name,),
    ).fetchone()
    end_s = row["mx"] if row else None
    if not end_s:
        return {
            "ok": False,
            "reason": "no_transactions",
            "project": project_name,
            "team_model": team_model,
        }

    end_d = date.fromisoformat(str(end_s))
    start_d = end_d - timedelta(days=wd - 1)
    start_s = start_d.isoformat()
    end_s_str = str(end_s)

    points, chosen_currency = get_timeseries(
        conn,
        project_name,
        start_date=start_s,
        end_date=end_s_str,
        granularity="day",
        currency=currency,
    )
    by_date = {str(p["date"]): float(p["cost_usd"] or 0.0) for p in points}
    total = 0.0
    d = start_d
    for _ in range(wd):
        total += float(by_date.get(d.isoformat(), 0.0) or 0.0)
        d += timedelta(days=1)

    baseline = total / float(wd) if wd else 0.0
    return {
        "ok": True,
        "project": project_name,
        "currency": chosen_currency,
        "window_days": wd,
        "window_start": start_s,
        "window_end": end_s_str,
        "window_total_usd": round(total, 6),
        "baseline_usd_per_day": round(baseline, 6),
        "team_model": team_model,
        "method": f"sum(daily_cost_usd)/{wd}_calendar_days_inclusive",
        "notes_zh": (
            "外推金额 = 上表「日均基线」× 时间天数 × 披萨倍率；基线来自账单 CostUSD，不是单价公式。"
            "主力模型在 Tokens 页配置，便于在 Model Prices 对照目录价做 sanity check。"
            "「披萨」= 团队规模倍率（1≈基线用量，2≈约 2×）。仅供内部规划，非财务承诺。"
        ),
    }


def get_token_timeseries(
    conn: sqlite3.Connection,
    project_name: str,
    start_date: str | None = None,
    end_date: str | None = None,
    granularity: str = "day",
    currency: str | None = None,
) -> tuple[list[dict], str | None, str | None, str | None, str | None]:
    if project_has_imported_tokens(conn, project_name):
        imported = get_imported_token_timeseries(
            conn,
            project_name,
            start_date=start_date,
            end_date=end_date,
            granularity=granularity,
        )
        rows: list[dict] = []
        for p in imported:
            rows.append(
                {
                    "date": p["date"],
                    "estimated_input_tokens": p["estimated_input_tokens"],
                    "estimated_output_tokens": p["estimated_output_tokens"],
                    "estimated_total_tokens": p["estimated_total_tokens"],
                }
            )
        return rows, None, None, None, "imported"

    points, chosen_currency = get_timeseries(
        conn,
        project_name,
        start_date=start_date,
        end_date=end_date,
        granularity=granularity,
        currency=currency,
    )
    price_model = _get_project_token_price_model(conn, project_name=project_name)
    if not price_model:
        return (
            [
                {
                    "date": p["date"],
                    "cost_usd": p["cost_usd"],
                    "estimated_input_tokens": None,
                    "estimated_output_tokens": None,
                    "estimated_total_tokens": None,
                }
                for p in points
            ],
            chosen_currency,
            None,
            None,
            "estimated",
        )

    input_price = float(price_model["input_price"])
    output_price = float(price_model["output_price"])
    rows: list[dict] = []
    for p in points:
        token_est = _estimate_tokens_from_price(
            cost_usd=_safe_float(p["cost_usd"]),
            input_price=input_price,
            output_price=output_price,
        )
        in_tok = token_est["estimated_input_tokens"] if token_est else None
        out_tok = token_est["estimated_output_tokens"] if token_est else None
        rows.append(
            {
                "date": p["date"],
                "cost_usd": p["cost_usd"],
                "estimated_input_tokens": in_tok,
                "estimated_output_tokens": out_tok,
                "estimated_total_tokens": None if in_tok is None or out_tok is None else in_tok + out_tok,
            }
        )
    return rows, chosen_currency, str(price_model["model_name"]), price_model.get("price_region"), "estimated"


def _project_where(project_names: list[str] | None) -> tuple[str, list[object]]:
    """
    Build a safe `project_name IN (...)` SQL fragment.

    If project_names is None/empty => no filtering.
    """
    if not project_names:
        return "1=1", []
    placeholders = ",".join(["?"] * len(project_names))
    return f"project_name IN ({placeholders})", list(project_names)


def get_all_currencies(
    conn: sqlite3.Connection,
    start_date: str | None = None,
    end_date: str | None = None,
    project_names: list[str] | None = None,
) -> list[str]:
    where = ["currency IS NOT NULL"]
    params: list[object] = []

    project_sql, project_params = _project_where(project_names)
    if project_sql != "1=1":
        where.append(project_sql)
        params.extend(project_params)

    if start_date:
        where.append("usage_date >= ?")
        params.append(start_date)
    if end_date:
        where.append("usage_date <= ?")
        params.append(end_date)

    where_sql = " AND ".join(where)
    rows = conn.execute(
        f"""
        SELECT currency, COUNT(*) AS cnt
        FROM transactions
        WHERE {where_sql}
        GROUP BY currency
        ORDER BY cnt DESC, currency ASC
        """,
        tuple(params),
    ).fetchall()
    return [r["currency"] for r in rows]


def get_all_timeseries(
    conn: sqlite3.Connection,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    granularity: str = "day",
    currency: str | None = None,
    project_names: list[str] | None = None,
) -> tuple[list[dict], str | None]:
    if granularity not in {"day", "month"}:
        raise ValueError("granularity must be 'day' or 'month'")

    date_expr = "usage_date" if granularity == "day" else "substr(usage_date, 1, 7)"

    currency_filter = currency
    if currency_filter is None:
        currencies = get_all_currencies(
            conn,
            start_date=start_date,
            end_date=end_date,
            project_names=project_names,
        )
        currency_filter = currencies[0] if currencies else None

    where = []
    params: list[object] = []

    project_sql, project_params = _project_where(project_names)
    if project_sql != "1=1":
        where.append(project_sql)
        params.extend(project_params)

    if currency_filter:
        where.append("currency = ?")
        params.append(currency_filter)
    if start_date:
        where.append("usage_date >= ?")
        params.append(start_date)
    if end_date:
        where.append("usage_date <= ?")
        params.append(end_date)

    where_sql = " AND ".join(where) if where else "1=1"

    rows = conn.execute(
        f"""
        SELECT
            {date_expr} AS period,
            COALESCE(SUM(cost_usd), 0) AS actual_cost_usd_total
        FROM transactions
        WHERE {where_sql}
        GROUP BY {date_expr}
        ORDER BY period ASC
        """,
        tuple(params),
    ).fetchall()

    points = [
        {
            "date": r["period"],
            "cost_usd": float(r["actual_cost_usd_total"]),
        }
        for r in rows
    ]
    return points, currency_filter


def get_all_token_timeseries(
    conn: sqlite3.Connection,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    granularity: str = "day",
    currency: str | None = None,
    project_names: list[str] | None = None,
) -> tuple[list[dict], str | None, str | None, str | None]:
    """
    Aggregate token totals (input/output/total) for the same scope as all-financial reports.

    Uses imported token CSV data when available per project; otherwise falls back to
    cost-based estimates from linked model prices.
    """
    if granularity not in {"day", "month"}:
        raise ValueError("granularity must be 'day' or 'month'")

    date_expr = "usage_date" if granularity == "day" else "substr(usage_date, 1, 7)"

    cost_points, chosen_currency = get_all_timeseries(
        conn,
        start_date=start_date,
        end_date=end_date,
        granularity=granularity,
        currency=currency,
        project_names=project_names,
    )
    periods = [p["date"] for p in cost_points]
    period_set = set(periods)

    scoped_projects = project_names if project_names else list_projects(conn)
    for pn in scoped_projects:
        if not project_has_imported_tokens(conn, pn):
            continue
        for period in _imported_token_periods(
            conn,
            project_name=pn,
            granularity=granularity,
            start_date=start_date,
            end_date=end_date,
        ):
            if period not in period_set:
                periods.append(period)
                period_set.add(period)
    periods.sort()

    per_period: dict[str, dict[str, object]] = {
        d: {"input": 0.0, "output": 0.0, "has": False} for d in periods
    }

    token_models: set[str] = set()
    token_regions: set[str] = set()
    imported_projects = 0
    estimated_projects = 0

    for pn in scoped_projects:
        if project_has_imported_tokens(conn, pn):
            imported_projects += 1
            meta = get_imported_token_meta(
                conn, pn, start_date=start_date, end_date=end_date
            )
            for m in meta.get("models") or []:
                token_models.add(str(m))
            _aggregate_imported_tokens_into_period(
                conn,
                project_name=pn,
                granularity=granularity,
                start_date=start_date,
                end_date=end_date,
                per_period=per_period,
                period_set=period_set,
            )
            continue

        price_model = _get_project_token_price_model(conn, project_name=pn)
        if not price_model:
            continue
        estimated_projects += 1

        model_name = price_model.get("model_name")
        if model_name:
            token_models.add(str(model_name))

        region = price_model.get("price_region")
        if region:
            token_regions.add(str(region))

        input_price = float(price_model["input_price"])
        output_price = float(price_model["output_price"])

        where = ["project_name = ?"]
        params: list[object] = [pn]
        if chosen_currency:
            where.append("currency = ?")
            params.append(chosen_currency)
        if start_date:
            where.append("usage_date >= ?")
            params.append(start_date)
        if end_date:
            where.append("usage_date <= ?")
            params.append(end_date)

        where_sql = " AND ".join(where)
        rows = conn.execute(
            f"""
            SELECT
                {date_expr} AS period,
                COALESCE(SUM(cost_usd), 0) AS actual_cost_usd_total
            FROM transactions
            WHERE {where_sql}
            GROUP BY {date_expr}
            ORDER BY period ASC
            """,
            tuple(params),
        ).fetchall()

        for r in rows:
            period = str(r["period"])
            if period not in period_set:
                period_set.add(period)
                periods.append(period)
                per_period[period] = {"input": 0.0, "output": 0.0, "has": False}

            cost_usd = _safe_float(r["actual_cost_usd_total"])
            token_est = _estimate_tokens_from_price(
                cost_usd=cost_usd,
                input_price=input_price,
                output_price=output_price,
            )
            if token_est is None:
                continue

            in_tok = _safe_float(token_est["estimated_input_tokens"])
            out_tok = _safe_float(token_est["estimated_output_tokens"])

            per_period[period]["input"] = _safe_float(per_period[period]["input"]) + in_tok
            per_period[period]["output"] = _safe_float(per_period[period]["output"]) + out_tok
            per_period[period]["has"] = True

    periods.sort()

    def display_single_or_multiple(vals: set[str]) -> str | None:
        vals = {v for v in vals if v}
        if not vals:
            return None
        if len(vals) == 1:
            return next(iter(vals))
        return f"Multiple ({len(vals)})"

    model_display = display_single_or_multiple(token_models)
    region_display = display_single_or_multiple(token_regions)

    if imported_projects and estimated_projects:
        token_data_source = "mixed"
    elif imported_projects:
        token_data_source = "imported"
    elif estimated_projects:
        token_data_source = "estimated"
    else:
        token_data_source = None

    points: list[dict] = []
    for d in periods:
        entry = per_period.get(d, {"has": False, "input": 0.0, "output": 0.0})
        if not entry.get("has"):
            points.append(
                {
                    "date": d,
                    "estimated_input_tokens": None,
                    "estimated_output_tokens": None,
                    "estimated_total_tokens": None,
                }
            )
        else:
            in_tok = float(entry["input"])
            out_tok = float(entry["output"])
            points.append(
                {
                    "date": d,
                    "estimated_input_tokens": in_tok,
                    "estimated_output_tokens": out_tok,
                    "estimated_total_tokens": in_tok + out_tok,
                }
            )

    return points, model_display, region_display, token_data_source


def verify_all_financial_consistency(
    conn: sqlite3.Connection,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    currency: str | None = None,
    project_names: list[str] | None = None,
    mode: str = "deep",
) -> dict:
    """
    Verification mechanism to ensure `/api/reports/all-financial` results are consistent with
    per-project dashboard calculations (sum across projects must match aggregated report).

    Returns a structured { ok, checks[] } payload.
    """
    mode = (mode or "deep").strip().lower()
    if mode not in {"quick", "deep"}:
        raise ValueError("mode must be 'quick' or 'deep'")

    # Baseline from report-scoped computations.
    stats = get_all_financial_stats(
        conn,
        start_date=start_date,
        end_date=end_date,
        currency=currency,
        project_names=project_names,
    )
    chosen_currency = stats.get("currency")
    daily_points = stats.get("daily_points") or []
    monthly_points = stats.get("monthly_points") or []

    token_daily_points, token_model_display, token_region_display, _ = get_all_token_timeseries(
        conn,
        start_date=start_date,
        end_date=end_date,
        granularity="day",
        currency=chosen_currency,
        project_names=project_names,
    )
    token_monthly_points, _, _, _ = get_all_token_timeseries(
        conn,
        start_date=start_date,
        end_date=end_date,
        granularity="month",
        currency=chosen_currency,
        project_names=project_names,
    )

    scoped_projects = project_names if project_names else list_projects(conn)

    report_dates_day = [p["date"] for p in daily_points]
    report_dates_month = [p["date"] for p in monthly_points]
    day_set = set(report_dates_day)
    month_set = set(report_dates_month)

    # Compute sum across per-project endpoints' underlying functions.
    cost_day_sum: dict[str, float] = {d: 0.0 for d in report_dates_day}
    cost_month_sum: dict[str, float] = {d: 0.0 for d in report_dates_month}

    token_day_has: dict[str, bool] = {d: False for d in report_dates_day}
    token_day_input_sum: dict[str, float] = {d: 0.0 for d in report_dates_day}
    token_day_output_sum: dict[str, float] = {d: 0.0 for d in report_dates_day}

    token_month_has: dict[str, bool] = {d: False for d in report_dates_month}
    token_month_input_sum: dict[str, float] = {d: 0.0 for d in report_dates_month}
    token_month_output_sum: dict[str, float] = {d: 0.0 for d in report_dates_month}

    token_models: set[str] = set()
    token_regions: set[str] = set()

    for pn in scoped_projects:
        # Cost points
        dp, _ = get_timeseries(
            conn,
            project_name=pn,
            start_date=start_date,
            end_date=end_date,
            granularity="day",
            currency=chosen_currency,
        )
        for p in dp:
            if p["date"] in day_set:
                cost_day_sum[p["date"]] += float(p["cost_usd"] or 0.0)

        mp, _ = get_timeseries(
            conn,
            project_name=pn,
            start_date=start_date,
            end_date=end_date,
            granularity="month",
            currency=chosen_currency,
        )
        for p in mp:
            if p["date"] in month_set:
                cost_month_sum[p["date"]] += float(p["cost_usd"] or 0.0)

        # Token points
        tp_day, _, _, _, _ = get_token_timeseries(
            conn,
            project_name=pn,
            start_date=start_date,
            end_date=end_date,
            granularity="day",
            currency=chosen_currency,
        )
        for p in tp_day:
            d = p["date"]
            if d not in day_set:
                continue
            in_tok = p.get("estimated_input_tokens")
            out_tok = p.get("estimated_output_tokens")
            if in_tok is None or out_tok is None:
                continue
            token_day_has[d] = True
            token_day_input_sum[d] += float(in_tok)
            token_day_output_sum[d] += float(out_tok)

        tp_month, _, _, _, _ = get_token_timeseries(
            conn,
            project_name=pn,
            start_date=start_date,
            end_date=end_date,
            granularity="month",
            currency=chosen_currency,
        )
        for p in tp_month:
            d = p["date"]
            if d not in month_set:
                continue
            in_tok = p.get("estimated_input_tokens")
            out_tok = p.get("estimated_output_tokens")
            if in_tok is None or out_tok is None:
                continue
            token_month_has[d] = True
            token_month_input_sum[d] += float(in_tok)
            token_month_output_sum[d] += float(out_tok)

        price_model = _get_project_token_price_model(conn, project_name=pn)
        if price_model:
            if price_model.get("model_name"):
                token_models.add(str(price_model["model_name"]))
            if price_model.get("price_region"):
                token_regions.add(str(price_model["price_region"]))

    def display_single_or_multiple(vals: set[str]) -> str | None:
        vals = {v for v in vals if v}
        if not vals:
            return None
        if len(vals) == 1:
            return next(iter(vals))
        return f"Multiple ({len(vals)})"

    expected_model_display = display_single_or_multiple(token_models)
    expected_region_display = display_single_or_multiple(token_regions)

    eps_cost = 1e-6
    eps_tokens = 1e-3

    checks: list[dict] = []

    def add_check(name: str, ok: bool, details: str = "") -> None:
        checks.append({"name": name, "pass": bool(ok), "details": details})

    # Quick mode: totals only.
    if mode == "quick":
        report_cost_day_total = sum(p["cost_usd"] for p in daily_points)
        report_cost_month_total = sum(p["cost_usd"] for p in monthly_points)

        computed_cost_day_total = sum(cost_day_sum.values())
        computed_cost_month_total = sum(cost_month_sum.values())

        add_check(
            "cost_daily_total_matches",
            abs(report_cost_day_total - computed_cost_day_total) <= eps_cost,
            f"report={report_cost_day_total}, computed={computed_cost_day_total}",
        )
        add_check(
            "cost_monthly_total_matches",
            abs(report_cost_month_total - computed_cost_month_total) <= eps_cost,
            f"report={report_cost_month_total}, computed={computed_cost_month_total}",
        )

        report_token = stats.get("token_estimate") or {}
        report_est_input_total = float(report_token.get("estimated_input_tokens_total") or 0.0)
        report_est_output_total = float(report_token.get("estimated_output_tokens_total") or 0.0)
        computed_est_input_total = sum(v for d, v in token_day_input_sum.items() if token_day_has[d])
        computed_est_output_total = sum(v for d, v in token_day_output_sum.items() if token_day_has[d])

        add_check(
            "token_totals_input_matches",
            abs(report_est_input_total - computed_est_input_total) <= eps_tokens,
            f"report={report_est_input_total}, computed={computed_est_input_total}",
        )
        add_check(
            "token_totals_output_matches",
            abs(report_est_output_total - computed_est_output_total) <= eps_tokens,
            f"report={report_est_output_total}, computed={computed_est_output_total}",
        )
    else:
        # Deep mode: per-period points must match.
        for i, p in enumerate(daily_points):
            d = p["date"]
            computed_cost = cost_day_sum.get(d, 0.0)
            report_cost = float(p["cost_usd"] or 0.0)
            add_check(
                f"cost_daily_point_matches:{d}",
                abs(report_cost - computed_cost) <= eps_cost,
                f"report={report_cost}, computed={computed_cost}",
            )

            tp = token_daily_points[i] if i < len(token_daily_points) else None
            if tp is None or tp.get("date") != d:
                add_check(f"token_daily_point_alignment:{d}", False, "token points mismatch")
                continue

            if not token_day_has[d]:
                add_check(f"token_daily_point_none:{d}", tp.get("estimated_input_tokens") is None and tp.get("estimated_output_tokens") is None)
                continue

            report_in = tp.get("estimated_input_tokens")
            report_out = tp.get("estimated_output_tokens")
            computed_in = token_day_input_sum[d]
            computed_out = token_day_output_sum[d]

            add_check(
                f"token_daily_point_input_matches:{d}",
                report_in is not None and abs(float(report_in) - computed_in) <= eps_tokens,
                f"report={report_in}, computed={computed_in}",
            )
            add_check(
                f"token_daily_point_output_matches:{d}",
                report_out is not None and abs(float(report_out) - computed_out) <= eps_tokens,
                f"report={report_out}, computed={computed_out}",
            )

        for i, p in enumerate(monthly_points):
            d = p["date"]
            computed_cost = cost_month_sum.get(d, 0.0)
            report_cost = float(p["cost_usd"] or 0.0)
            add_check(
                f"cost_monthly_point_matches:{d}",
                abs(report_cost - computed_cost) <= eps_cost,
                f"report={report_cost}, computed={computed_cost}",
            )

            tp = token_monthly_points[i] if i < len(token_monthly_points) else None
            if tp is None or tp.get("date") != d:
                add_check(f"token_monthly_point_alignment:{d}", False, "token points mismatch")
                continue

            if not token_month_has[d]:
                add_check(f"token_monthly_point_none:{d}", tp.get("estimated_input_tokens") is None and tp.get("estimated_output_tokens") is None)
                continue

            report_in = tp.get("estimated_input_tokens")
            report_out = tp.get("estimated_output_tokens")
            computed_in = token_month_input_sum[d]
            computed_out = token_month_output_sum[d]

            add_check(
                f"token_monthly_point_input_matches:{d}",
                report_in is not None and abs(float(report_in) - computed_in) <= eps_tokens,
                f"report={report_in}, computed={computed_in}",
            )
            add_check(
                f"token_monthly_point_output_matches:{d}",
                report_out is not None and abs(float(report_out) - computed_out) <= eps_tokens,
                f"report={report_out}, computed={computed_out}",
            )

    add_check(
        "token_estimate_model_display_matches",
        (token_model_display == expected_model_display),
        f"report={token_model_display}, expected={expected_model_display}",
    )
    add_check(
        "token_estimate_region_display_matches",
        (token_region_display == expected_region_display),
        f"report={token_region_display}, expected={expected_region_display}",
    )

    ok = all(c.get("pass") for c in checks)
    failed = [c["name"] for c in checks if not c.get("pass")]

    return {
        "ok": ok,
        "mode": mode,
        "checks": checks,
        "failed_checks": failed[:20],  # cap details
        "failed_count": len(failed),
        "currency": chosen_currency,
    }


def _mean(vals: list[float]) -> float:
    if not vals:
        return 0.0
    return sum(vals) / len(vals)


def _median(vals: list[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    return (s[mid - 1] + s[mid]) / 2.0


def _variance(vals: list[float]) -> float:
    if not vals:
        return 0.0
    m = _mean(vals)
    # population variance; good for dashboard/audit summaries
    return _mean([x * x for x in vals]) - m * m


def get_financial_project_breakdown(
    conn: sqlite3.Connection,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    currency: str | None = None,
    project_names: list[str] | None = None,
) -> list[dict]:
    """
    Per-project cost in the same scope as all-financial reports, plus token estimates
    when a project has an associated model and matching rows in `model_prices`.
    """
    _, chosen_currency = get_all_timeseries(
        conn,
        start_date=start_date,
        end_date=end_date,
        granularity="day",
        currency=currency,
        project_names=project_names,
    )
    if chosen_currency is None:
        return []

    where: list[str] = []
    params: list[object] = []
    project_sql, project_params = _project_where(project_names)
    if project_sql != "1=1":
        where.append(project_sql)
        params.extend(project_params)
    where.append("currency = ?")
    params.append(chosen_currency)
    if start_date:
        where.append("usage_date >= ?")
        params.append(start_date)
    if end_date:
        where.append("usage_date <= ?")
        params.append(end_date)
    where_sql = " AND ".join(where)

    rows = conn.execute(
        f"""
        SELECT
            project_name,
            COALESCE(SUM(cost_usd), 0) AS cost_usd_total,
            COUNT(DISTINCT CASE WHEN cost_usd IS NOT NULL THEN usage_date END) AS actual_days
        FROM transactions
        WHERE {where_sql}
        GROUP BY project_name
        HAVING COALESCE(SUM(cost_usd), 0) > 0
        ORDER BY cost_usd_total DESC
        """,
        tuple(params),
    ).fetchall()

    out: list[dict] = []
    for r in rows:
        pn = r["project_name"]
        total = _safe_float(r["cost_usd_total"])
        te = _estimate_tokens_by_cost(conn, project_name=pn, total_cost_usd=total) or {}
        cfg = get_project_model_config(conn, pn)
        configured = (cfg or {}).get("model_name")
        out.append(
            {
                "project_name": pn,
                "actual_cost_usd_total": total,
                "actual_days": int(r["actual_days"]),
                "currency": chosen_currency,
                "model_configured": bool(configured),
                "configured_model_name": configured,
                "estimated_input_tokens": te.get("estimated_input_tokens"),
                "estimated_output_tokens": te.get("estimated_output_tokens"),
                "token_estimate_model": te.get("model_name"),
            }
        )
    return out


def get_all_financial_stats(
    conn: sqlite3.Connection,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    currency: str | None = None,
    project_names: list[str] | None = None,
) -> dict:
    daily_points, chosen_currency = get_all_timeseries(
        conn,
        start_date=start_date,
        end_date=end_date,
        granularity="day",
        currency=currency,
        project_names=project_names,
    )
    monthly_points, _ = get_all_timeseries(
        conn,
        start_date=start_date,
        end_date=end_date,
        granularity="month",
        currency=chosen_currency,
        project_names=project_names,
    )

    daily_actual = [p["cost_usd"] for p in daily_points]
    monthly_actual = [p["cost_usd"] for p in monthly_points]

    estimated_input_tokens_total = 0.0
    estimated_output_tokens_total = 0.0
    projects_with_token_estimate = 0
    scoped_projects = project_names if project_names else list_projects(conn)
    for project_name in scoped_projects:
        pstats = get_project_stats(
            conn,
            project_name,
            from_date=start_date,
            to_date=end_date,
            currency=chosen_currency,
        )
        if pstats.estimated_input_tokens is None or pstats.estimated_output_tokens is None:
            continue
        estimated_input_tokens_total += pstats.estimated_input_tokens
        estimated_output_tokens_total += pstats.estimated_output_tokens
        projects_with_token_estimate += 1

    return {
        "currency": chosen_currency,
        "daily": {
            "count_days": len(daily_points),
            "total_actual": sum(daily_actual),
            "avg_actual": _mean(daily_actual),
            "median_actual": _median(daily_actual),
            "var_actual": _variance(daily_actual),
        },
        "monthly": {
            "count_months": len(monthly_points),
            "avg_actual": _mean(monthly_actual),
            "median_actual": _median(monthly_actual),
            "var_actual": _variance(monthly_actual),
        },
        "token_estimate": {
            "projects_with_estimate": projects_with_token_estimate,
            "estimated_input_tokens_total": estimated_input_tokens_total,
            "estimated_output_tokens_total": estimated_output_tokens_total,
        },
        "project_breakdown": get_financial_project_breakdown(
            conn,
            start_date=start_date,
            end_date=end_date,
            currency=currency,
            project_names=project_names,
        ),
        "daily_points": daily_points,
        "monthly_points": monthly_points,
    }


def get_rows(
    conn: sqlite3.Connection,
    project_name: str,
    start_date: str | None = None,
    end_date: str | None = None,
    currency: str | None = None,
    page: int = 1,
    page_size: int = 50,
    mode: str = "simple",
) -> dict:
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    mode = mode.strip().lower()
    if mode not in {"simple", "full"}:
        raise ValueError("mode must be 'simple' or 'full'")

    where = ["project_name = ?"]
    params: list[object] = [project_name]
    if start_date:
        where.append("usage_date >= ?")
        params.append(start_date)
    if end_date:
        where.append("usage_date <= ?")
        params.append(end_date)
    if currency:
        where.append("currency = ?")
        params.append(currency)

    where_sql = " AND ".join(where)

    total = conn.execute(
        f"""
        SELECT COUNT(*) AS total
        FROM transactions
        WHERE {where_sql}
        """,
        tuple(params),
    ).fetchone()["total"]

    offset = (page - 1) * page_size
    if mode == "simple":
        price_model = _get_project_token_price_model(conn, project_name=project_name)
        input_price = float(price_model["input_price"]) if price_model else None
        output_price = float(price_model["output_price"]) if price_model else None
        model_name = str(price_model["model_name"]) if price_model else None
        rows = conn.execute(
            f"""
            SELECT
                usage_date, currency, cost_usd, cost, source_file, source_row_index
                FROM transactions
            WHERE {where_sql}
            ORDER BY usage_date DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            tuple([*params, page_size, offset]),
        ).fetchall()
        parsed_rows: list[dict] = []
        for r in rows:
            cost_usd = None if r["cost_usd"] is None else float(r["cost_usd"])
            token_est = (
                None
                if input_price is None or output_price is None
                else _estimate_tokens_from_price(
                    cost_usd=0.0 if cost_usd is None else cost_usd,
                    input_price=input_price,
                    output_price=output_price,
                )
            )
            in_tok = None if token_est is None else token_est["estimated_input_tokens"]
            out_tok = None if token_est is None else token_est["estimated_output_tokens"]
            parsed_rows.append(
                {
                    "usage_date": r["usage_date"],
                    "currency": r["currency"],
                    "cost_usd": cost_usd,
                    "cost": None if r["cost"] is None else float(r["cost"]),
                    "estimated_input_tokens": in_tok,
                    "estimated_output_tokens": out_tok,
                    "estimated_total_tokens": None if in_tok is None or out_tok is None else in_tok + out_tok,
                    "token_estimate_model": model_name,
                    "source_file": r["source_file"],
                    "source_row_index": r["source_row_index"],
                }
            )

        return {
            "total": int(total),
            "page": page,
            "page_size": page_size,
            "mode": "simple",
            "rows": parsed_rows,
        }

    # Full mode: return all CSV columns (from raw_json) + source reference.
    rows = conn.execute(
        f"""
        SELECT
            usage_date, currency, cost_usd, cost,
            raw_json, source_file, source_row_index
            FROM transactions
        WHERE {where_sql}
        ORDER BY usage_date DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        tuple([*params, page_size, offset]),
    ).fetchall()

    columns: list[str] = EXPECTED_CSV_COLUMNS
    parsed_rows: list[dict] = []
    for r in rows:
        fields_raw = json.loads(r["raw_json"]) if r["raw_json"] else {}
        fields = {col: fields_raw.get(col) for col in EXPECTED_CSV_COLUMNS}
        parsed_rows.append(
            {
                "usage_date": r["usage_date"],
                "currency": r["currency"],
                "cost_usd": None if r["cost_usd"] is None else float(r["cost_usd"]),
                "cost": None if r["cost"] is None else float(r["cost"]),
                "fields": fields,
                "source_file": r["source_file"],
                "source_row_index": r["source_row_index"],
            }
        )

    return {
        "total": int(total),
        "page": page,
        "page_size": page_size,
        "mode": "full",
        "columns": columns,
        "rows": parsed_rows,
    }


def replace_model_prices(conn: sqlite3.Connection, rows: Iterable[tuple]) -> int:
    """
    Replace all model price rows with the provided normalized tuples.
    """
    conn.execute("DELETE FROM model_prices")
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
        list(rows),
    )
    conn.commit()
    c = conn.execute("SELECT COUNT(*) AS c FROM model_prices").fetchone()["c"]
    return int(c)


def clear_all_model_prices(conn: sqlite3.Connection) -> int:
    """Delete every row in model_prices. Returns how many rows were removed."""
    cur = conn.execute("DELETE FROM model_prices")
    conn.commit()
    return int(cur.rowcount or 0)


# Typical `model_series` strings from Microsoft catalog sync (`azure_retail_prices.normalize_retail_item`),
# merged into filter options so GPT-5.x families appear before matching rows exist in SQLite.
_KNOWN_RETAIL_MODEL_SERIES_HINTS: tuple[str, ...] = (
    "GPT-5.5 Series",
    "GPT-5.4 Series",
    "GPT-5.3 Series",
    "GPT-5.2 Series",
    "GPT-5.1 Series",
    "GPT-5.1 Codex Series",
    "GPT-4o Series",
    "GPT-5 mini Series",
    "GPT-5 nano Series",
)


def get_model_price_filter_options(conn: sqlite3.Connection) -> dict[str, list[str]]:
    def _list_values(col: str) -> list[str]:
        q = f"SELECT DISTINCT {col} AS v FROM model_prices WHERE {col} IS NOT NULL AND {col} != '' ORDER BY {col}"
        rows = conn.execute(q).fetchall()
        return [r["v"] for r in rows]

    series_from_db = _list_values("model_series")
    model_series = sorted(set(series_from_db) | set(_KNOWN_RETAIL_MODEL_SERIES_HINTS))

    return {
        "vendors": _list_values("vendor"),
        "platforms": _list_values("platform"),
        "model_series": model_series,
        "currencies": _list_values("price_currency"),
        "regions": _list_values("price_region"),
    }


def get_model_prices_meta(conn: sqlite3.Connection) -> dict[str, object]:
    total = int(conn.execute("SELECT COUNT(*) AS c FROM model_prices").fetchone()["c"])
    src_rows = conn.execute(
        """
        SELECT
            source_id,
            COUNT(*) AS row_count,
            MAX(retrieved_at_utc) AS last_retrieved_at_utc
        FROM model_prices
        GROUP BY source_id
        ORDER BY source_id
        """
    ).fetchall()
    return {
        "total_rows": total,
        "sources": [
            {
                "source_id": r["source_id"],
                "row_count": int(r["row_count"]),
                "last_retrieved_at_utc": r["last_retrieved_at_utc"],
            }
            for r in src_rows
        ],
        "price_source_catalog": list_price_source_catalog(conn),
    }


def get_model_prices(
    conn: sqlite3.Connection,
    *,
    vendor: str | None = None,
    platform: str | None = None,
    model_series: str | None = None,
    page: int = 1,
    page_size: int = 100,
) -> tuple[list[dict], int]:
    where = ["1=1"]
    params: list[object] = []

    if vendor:
        where.append("vendor = ?")
        params.append(vendor)
    if platform:
        where.append("platform = ?")
        params.append(platform)
    if model_series:
        where.append("model_series = ?")
        params.append(model_series)

    where_sql = " AND ".join(where)
    page = max(1, int(page))
    page_size = min(500, max(1, int(page_size)))
    offset = (page - 1) * page_size

    total = int(
        conn.execute(
            f"SELECT COUNT(*) AS c FROM model_prices WHERE {where_sql}",
            tuple(params),
        ).fetchone()["c"]
    )

    rows = conn.execute(
        f"""
        SELECT
            id,
            source_id, source_url, effective_date, retrieved_at_utc,
            vendor, platform, price_region, price_currency,
            model_series, model_name, context_bucket, deployment_scope,
            billing_mode, metric_name, amount,
            unit_quantity, unit_name, unit_expression, notes
        FROM model_prices
        WHERE {where_sql}
        ORDER BY
            vendor, platform, model_series, model_name,
            COALESCE(context_bucket, ''), COALESCE(deployment_scope, ''),
            billing_mode, metric_name
        LIMIT ? OFFSET ?
        """
        ,
        tuple([*params, page_size, offset]),
    ).fetchall()

    out = [
        {
            "id": int(r["id"]),
            "source_id": r["source_id"],
            "source_url": r["source_url"],
            "effective_date": r["effective_date"],
            "retrieved_at_utc": r["retrieved_at_utc"],
            "vendor": r["vendor"],
            "platform": r["platform"],
            "price_region": r["price_region"],
            "price_currency": r["price_currency"],
            "model_series": r["model_series"],
            "model_name": r["model_name"],
            "context_bucket": r["context_bucket"],
            "deployment_scope": r["deployment_scope"],
            "billing_mode": r["billing_mode"],
            "metric_name": r["metric_name"],
            "amount": float(r["amount"]),
            "unit_quantity": int(r["unit_quantity"]),
            "unit_name": r["unit_name"],
            "unit_expression": r["unit_expression"],
            "notes": r["notes"],
        }
        for r in rows
    ]
    return out, total


_FORECAST_METRICS: tuple[str, ...] = ("input", "cached_input", "output")


def list_forecast_model_catalog(conn: sqlite3.Connection) -> list[dict[str, str]]:
    """Distinct models from the full ``model_prices`` table (any vendor / platform)."""
    rows = conn.execute(
        """
        SELECT DISTINCT
            trim(vendor) AS v,
            trim(platform) AS p,
            trim(model_series) AS ms,
            trim(model_name) AS mn
        FROM model_prices
        WHERE model_series IS NOT NULL AND trim(model_series) != ''
          AND model_name IS NOT NULL AND trim(model_name) != ''
          AND vendor IS NOT NULL AND trim(vendor) != ''
          AND platform IS NOT NULL AND trim(platform) != ''
        ORDER BY v COLLATE NOCASE, p COLLATE NOCASE, ms COLLATE NOCASE, mn COLLATE NOCASE
        """
    ).fetchall()
    return [
        {"vendor": str(r["v"]), "platform": str(r["p"]), "model_series": str(r["ms"]), "model_name": str(r["mn"])}
        for r in rows
    ]


def _forecast_norm_compact(s: str | None) -> str:
    return (s or "").strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def _forecast_region_matches(row_region: str | None, want: str | None) -> bool:
    """Empty ``want`` = accept any region (first match wins in caller ordering)."""
    if not want or not str(want).strip():
        return True
    rr = _forecast_norm_compact(row_region)
    w = _forecast_norm_compact(want)
    if not rr:
        return False
    return rr == w


def _forecast_scope_matches(row_scope: str | None, want: str | None) -> bool:
    w = (want or "global").strip().lower()
    r = (row_scope or "").strip().lower()
    if w == "global":
        return r in ("", "global")
    return r == w


def get_forecast_model_unit_prices(
    conn: sqlite3.Connection,
    *,
    vendor: str,
    platform: str,
    model_series: str,
    model_name: str,
    price_region: str | None = None,
    deployment_scope: str | None = "global",
    billing_mode: str = "standard",
) -> dict[str, Any]:
    """
    Latest catalog unit prices for ``input`` / ``cached_input`` / ``output`` meters
    (amount / unit_quantity = price per token in listed currency).
    """
    vn = (vendor or "").strip()
    pl = (platform or "").strip()
    ms = (model_series or "").strip()
    mn = (model_name or "").strip()
    if not vn or not pl or not ms or not mn:
        return {
            "ok": False,
            "reason": "missing_model",
            "notes_zh": "请提供 vendor、platform、model_series 与 model_name。",
        }

    bm = (billing_mode or "standard").strip()
    rows = conn.execute(
        """
        SELECT metric_name, amount, unit_quantity, price_currency, price_region,
               deployment_scope, effective_date, retrieved_at_utc
        FROM model_prices
        WHERE lower(trim(vendor)) = lower(trim(?))
          AND lower(trim(platform)) = lower(trim(?))
          AND lower(trim(model_series)) = lower(trim(?))
          AND lower(trim(model_name)) = lower(trim(?))
          AND lower(trim(coalesce(billing_mode, ''))) = lower(trim(?))
          AND metric_name IN ('input', 'cached_input', 'output')
        ORDER BY effective_date DESC, retrieved_at_utc DESC
        """,
        (vn, pl, ms, mn, bm),
    ).fetchall()

    picked: dict[str, dict[str, Any]] = {}
    chosen_region: str | None = None
    chosen_currency: str | None = None
    for r in rows:
        if not _forecast_region_matches(r["price_region"], price_region):
            continue
        if not _forecast_scope_matches(r["deployment_scope"], deployment_scope):
            continue
        m = str(r["metric_name"] or "")
        if m in picked:
            continue
        uq = int(r["unit_quantity"] or 0)
        if uq <= 0:
            continue
        amt = float(r["amount"] or 0.0)
        per_token = amt / float(uq)
        picked[m] = {
            "amount_catalog": amt,
            "unit_quantity": uq,
            "per_token": per_token,
            "price_currency": str(r["price_currency"] or "USD"),
        }
        if chosen_region is None:
            chosen_region = str(r["price_region"] or "")
        if chosen_currency is None:
            chosen_currency = str(r["price_currency"] or "USD")

    if "input" not in picked and "output" not in picked:
        return {
            "ok": False,
            "reason": "no_prices",
            "vendor": vn,
            "platform": pl,
            "model_series": ms,
            "model_name": mn,
            "notes_zh": "目录中没有匹配的单价行。请在 Model Prices 核对 vendor/平台/区域/部署范围/计费模式，或改用「任意区域」。",
        }

    def per_1m(key: str) -> float | None:
        x = picked.get(key)
        if not x:
            return None
        return float(x["per_token"]) * 1_000_000.0

    cur = chosen_currency or "USD"
    dsp = (deployment_scope or "global").strip().lower() or "global"
    return {
        "ok": True,
        "vendor": vn,
        "platform": pl,
        "model_series": ms,
        "model_name": mn,
        "price_region": chosen_region,
        "deployment_scope": dsp,
        "billing_mode": bm,
        "currency": cur,
        "usd_per_1m_tokens": {
            "input": per_1m("input"),
            "cached_input": per_1m("cached_input"),
            "output": per_1m("output"),
        },
        "per_token": {k: float(v["per_token"]) for k, v in picked.items()},
        "missing_metrics": [m for m in _FORECAST_METRICS if m not in picked],
        "notes_zh": (
            "单价来自 Model Prices 全表（所选 vendor / 平台 / 区域 / 部署 / 计费模式）。"
            "Forecast 页「每日用量」以百万 tokens（1M）为单位填写；总成本 = Σ(实际日 token × 单价) × 团队倍率 × 天数。"
            "未出现在目录中的计量项按 0 单价计。仅供内部估算，最终以账单与合同为准。"
        ),
    }


def get_model_price_by_id(conn: sqlite3.Connection, price_id: int) -> dict | None:
    r = conn.execute(
        """
        SELECT
            id,
            source_id, source_url, effective_date, retrieved_at_utc,
            vendor, platform, price_region, price_currency,
            model_series, model_name, context_bucket, deployment_scope,
            billing_mode, metric_name, amount,
            unit_quantity, unit_name, unit_expression, notes, source_detail_json
        FROM model_prices
        WHERE id = ?
        """,
        (price_id,),
    ).fetchone()
    if r is None:
        return None
    detail: dict | None = None
    raw = r["source_detail_json"]
    if raw:
        try:
            detail = json.loads(raw)
        except Exception:
            detail = {"parse_error": True, "raw": raw}
    return {
        "id": int(r["id"]),
        "source_id": r["source_id"],
        "source_url": r["source_url"],
        "effective_date": r["effective_date"],
        "retrieved_at_utc": r["retrieved_at_utc"],
        "vendor": r["vendor"],
        "platform": r["platform"],
        "price_region": r["price_region"],
        "price_currency": r["price_currency"],
        "model_series": r["model_series"],
        "model_name": r["model_name"],
        "context_bucket": r["context_bucket"],
        "deployment_scope": r["deployment_scope"],
        "billing_mode": r["billing_mode"],
        "metric_name": r["metric_name"],
        "amount": float(r["amount"]),
        "unit_quantity": int(r["unit_quantity"]),
        "unit_name": r["unit_name"],
        "unit_expression": r["unit_expression"],
        "notes": r["notes"],
        "source_detail": detail,
    }
