from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .cost_pipeline import cost_debug_enabled, log_cost_step, summarize_daily_cost_rows
from .money import round_cost
from .meter_match import (
    aggregate_billing_rows,
    canonical_model_name,
    meter_matches_model_direction,
    normalize_token_column,
    parse_foundry_meter,
    sum_meter_costs,
    token_models_match,
)


SCHEMA_VERSION = 12

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


def _sort_rows_by_date_desc(
    rows: list[dict[str, object]],
    *,
    date_key: str = "date",
    tie_key: str = "model_name",
) -> None:
    """Stable sort: newest date first, then tie_key ascending."""
    rows.sort(key=lambda r: str(r.get(tie_key) or ""))
    rows.sort(key=lambda r: str(r.get(date_key) or ""), reverse=True)


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
            subproject_name TEXT NOT NULL DEFAULT '',
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
            subproject_name TEXT NOT NULL DEFAULT '',
            recorded_at TEXT NOT NULL,
            usage_date TEXT NOT NULL,
            model_name TEXT NOT NULL,
            token_direction TEXT NOT NULL,
            token_count REAL NOT NULL,
            source_file TEXT NOT NULL,
            source_row_index INTEGER NOT NULL,
            ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(project_name, subproject_name, token_direction, recorded_at, model_name)
        );

        CREATE INDEX IF NOT EXISTS idx_token_usage_project_date
            ON token_usage_points(project_name, usage_date);

        CREATE INDEX IF NOT EXISTS idx_token_usage_natural
            ON token_usage_points(project_name, subproject_name, token_direction, recorded_at, model_name);

        CREATE INDEX IF NOT EXISTS idx_ingested_token_files_project_name
            ON ingested_token_files(project_name);

        CREATE TABLE IF NOT EXISTS ingested_token_metric_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT NOT NULL,
            subproject_name TEXT NOT NULL DEFAULT '',
            file_path TEXT NOT NULL UNIQUE,
            metric_name TEXT NOT NULL,
            checksum_sha256 TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            row_count INTEGER NOT NULL,
            ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
            source_last_modified REAL,
            raw_columns TEXT
        );

        CREATE TABLE IF NOT EXISTS token_metric_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT NOT NULL,
            subproject_name TEXT NOT NULL DEFAULT '',
            recorded_at TEXT NOT NULL,
            usage_date TEXT NOT NULL,
            model_name TEXT NOT NULL,
            metric_name TEXT NOT NULL,
            metric_value REAL NOT NULL,
            metric_unit TEXT NOT NULL,
            source_file TEXT NOT NULL,
            source_row_index INTEGER NOT NULL,
            ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(project_name, subproject_name, metric_name, recorded_at, model_name)
        );

        CREATE INDEX IF NOT EXISTS idx_token_metric_project_date
            ON token_metric_points(project_name, usage_date);

        CREATE INDEX IF NOT EXISTS idx_token_metric_natural
            ON token_metric_points(project_name, subproject_name, metric_name, recorded_at, model_name);

        CREATE INDEX IF NOT EXISTS idx_ingested_token_metric_files_project_name
            ON ingested_token_metric_files(project_name);

        CREATE TABLE IF NOT EXISTS project_monthly_budgets (
            project_name TEXT NOT NULL,
            yyyymm TEXT NOT NULL,
            budget_usd NUMERIC NOT NULL,
            PRIMARY KEY (project_name, yyyymm)
        );

        CREATE TABLE IF NOT EXISTS subproject_tags (
            project_name TEXT NOT NULL,
            subproject_name TEXT NOT NULL,
            tag TEXT NOT NULL,
            PRIMARY KEY (project_name, subproject_name, tag)
        );

        CREATE TABLE IF NOT EXISTS anomaly_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT NOT NULL,
            usage_date TEXT NOT NULL,
            metric TEXT NOT NULL,
            value REAL,
            mean REAL,
            stddev REAL,
            z_score REAL,
            detected_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (project_name, usage_date, metric)
        );

        CREATE INDEX IF NOT EXISTS idx_anomaly_events_project_date
            ON anomaly_events(project_name, usage_date);
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
    _migrate_billing_natural_key_v2(conn)
    _migrate_token_usage_natural_key(conn)
    _migrate_token_subproject_v1(conn)
    _migrate_model_prices_source_detail_json(conn)
    _ensure_price_source_catalog(conn)
    _ensure_roadmap_tables_v12(conn)


def _ensure_roadmap_tables_v12(conn: sqlite3.Connection) -> None:
    """Additive tables for budget / tags / anomaly (schema v12)."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS project_monthly_budgets (
            project_name TEXT NOT NULL,
            yyyymm TEXT NOT NULL,
            budget_usd NUMERIC NOT NULL,
            PRIMARY KEY (project_name, yyyymm)
        );
        CREATE TABLE IF NOT EXISTS subproject_tags (
            project_name TEXT NOT NULL,
            subproject_name TEXT NOT NULL,
            tag TEXT NOT NULL,
            PRIMARY KEY (project_name, subproject_name, tag)
        );
        CREATE TABLE IF NOT EXISTS anomaly_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT NOT NULL,
            usage_date TEXT NOT NULL,
            metric TEXT NOT NULL,
            value REAL,
            mean REAL,
            stddev REAL,
            z_score REAL,
            detected_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (project_name, usage_date, metric)
        );
        CREATE INDEX IF NOT EXISTS idx_anomaly_events_project_date
            ON anomaly_events(project_name, usage_date);
        """
    )
    conn.commit()


def get_project_monthly_budget(
    conn: sqlite3.Connection,
    project_name: str,
    yyyymm: str,
) -> float | None:
    row = conn.execute(
        """
        SELECT budget_usd FROM project_monthly_budgets
        WHERE project_name = ? AND yyyymm = ?
        """,
        (project_name, yyyymm),
    ).fetchone()
    if not row:
        return None
    return round_cost(_safe_float(row["budget_usd"]))


def upsert_project_monthly_budget(
    conn: sqlite3.Connection,
    project_name: str,
    yyyymm: str,
    budget_usd: float,
) -> None:
    conn.execute(
        """
        INSERT INTO project_monthly_budgets(project_name, yyyymm, budget_usd)
        VALUES (?, ?, ?)
        ON CONFLICT(project_name, yyyymm) DO UPDATE SET budget_usd = excluded.budget_usd
        """,
        (project_name, yyyymm, float(budget_usd)),
    )
    conn.commit()


def list_subproject_tags(
    conn: sqlite3.Connection,
    project_name: str | None = None,
) -> list[dict[str, str]]:
    where = ""
    params: tuple[object, ...] = ()
    if project_name:
        where = " WHERE project_name = ?"
        params = (project_name,)
    rows = conn.execute(
        f"""
        SELECT project_name, subproject_name, tag
        FROM subproject_tags{where}
        ORDER BY project_name, tag, subproject_name
        """,
        params,
    ).fetchall()
    return [
        {
            "project_name": r["project_name"],
            "subproject_name": r["subproject_name"],
            "tag": r["tag"],
        }
        for r in rows
    ]


def set_subproject_tag(
    conn: sqlite3.Connection,
    *,
    project_name: str,
    subproject_name: str,
    tag: str,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO subproject_tags(project_name, subproject_name, tag)
        VALUES (?, ?, ?)
        """,
        (project_name, subproject_name, tag),
    )
    conn.commit()


def delete_subproject_tag(
    conn: sqlite3.Connection,
    *,
    project_name: str,
    subproject_name: str,
    tag: str,
) -> None:
    conn.execute(
        """
        DELETE FROM subproject_tags
        WHERE project_name = ? AND subproject_name = ? AND tag = ?
        """,
        (project_name, subproject_name, tag),
    )
    conn.commit()


def detect_and_store_daily_cost_anomalies(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    currency: str | None = None,
    z_threshold: float = 2.0,
) -> list[dict[str, Any]]:
    """Detect ±2σ daily cost outliers and upsert into anomaly_events."""
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
    rows = conn.execute(
        f"""
        SELECT usage_date AS d, COALESCE(SUM(cost_usd), 0) AS cost_usd
        FROM transactions
        WHERE {' AND '.join(where)}
        GROUP BY usage_date
        ORDER BY usage_date
        """,
        tuple(params),
    ).fetchall()
    values = [float(r["cost_usd"] or 0) for r in rows]
    if len(values) < 3:
        return []
    mean = sum(values) / len(values)
    # Sample stddev so a single spike can exceed ±2σ with small n.
    denom = max(len(values) - 1, 1)
    var = sum((v - mean) ** 2 for v in values) / denom
    std = var ** 0.5
    if std <= 0:
        return []
    out: list[dict[str, Any]] = []
    for r, v in zip(rows, values):
        z = (v - mean) / std
        if abs(z) <= z_threshold:
            continue
        conn.execute(
            """
            INSERT INTO anomaly_events(
              project_name, usage_date, metric, value, mean, stddev, z_score
            ) VALUES (?, ?, 'daily_cost_usd', ?, ?, ?, ?)
            ON CONFLICT(project_name, usage_date, metric) DO UPDATE SET
              value = excluded.value,
              mean = excluded.mean,
              stddev = excluded.stddev,
              z_score = excluded.z_score,
              detected_at = datetime('now')
            """,
            (project_name, r["d"], v, mean, std, z),
        )
        out.append(
            {
                "project_name": project_name,
                "usage_date": r["d"],
                "metric": "daily_cost_usd",
                "value": round_cost(v),
                "mean": round_cost(mean),
                "stddev": round_cost(std),
                "z_score": round(z, 2),
            }
        )
    conn.commit()
    return out


def allocation_by_user_or_department(
    conn: sqlite3.Connection,
    *,
    dimension: str,
    project_names: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Stub until billing/token CSVs expose stable user/department fields."""
    _ = (conn, project_names, start_date, end_date)
    dim = (dimension or "").strip().lower()
    if dim not in {"user", "department"}:
        dim = "user"
    return {
        "available": False,
        "dimension": dim,
        "reason": "missing_fields",
        "message": (
            f"By {dim} allocation requires stable '{dim}' fields in billing or token CSVs "
            "(or a mapping table). No such fields are present yet."
        ),
        "rows": [],
    }


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


def _migrate_billing_natural_key_v2(conn: sqlite3.Connection) -> None:
    """
    Billing natural key now includes resource_id so multiple Cognitive Services
    accounts in one RG (subprojects) do not overwrite each other on ingest.
    Clears billing ingest state once so CSVs are re-imported under the new key.
    """
    row = conn.execute("SELECT value FROM meta WHERE key = 'billing_natural_key_v2'").fetchone()
    if row is not None and str(row["value"]).strip() == "1":
        return
    if not _table_exists(conn, "transactions"):
        conn.execute(
            """
            INSERT INTO meta(key, value) VALUES ('billing_natural_key_v2', '1')
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """
        )
        conn.commit()
        return

    conn.execute("DELETE FROM transactions")
    if _table_exists(conn, "ingested_files"):
        conn.execute("DELETE FROM ingested_files")
    conn.execute(
        """
        INSERT INTO meta(key, value) VALUES ('billing_natural_key_v2', '1')
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """
    )
    conn.commit()


def _migrate_token_usage_natural_key(conn: sqlite3.Connection) -> None:
    """
    One-time: dedupe token rows by (project, direction, recorded_at, model) and replace
    the old per-file row index unique constraint with a natural key for cross-file upsert.
    """
    row = conn.execute("SELECT value FROM meta WHERE key = 'token_natural_key_v1'").fetchone()
    if row is not None and str(row["value"]).strip() == "1":
        return
    if not _table_exists(conn, "token_usage_points"):
        conn.execute(
            """
            INSERT INTO meta(key, value) VALUES ('token_natural_key_v1', '1')
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """
        )
        conn.commit()
        return

    conn.executescript(
        """
        CREATE TABLE token_usage_points_new (
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
            UNIQUE(project_name, token_direction, recorded_at, model_name)
        );

        INSERT INTO token_usage_points_new(
            project_name, recorded_at, usage_date, model_name, token_direction,
            token_count, source_file, source_row_index, ingested_at
        )
        SELECT
            project_name, recorded_at, usage_date, model_name, token_direction,
            token_count, source_file, source_row_index, ingested_at
        FROM token_usage_points
        WHERE id IN (
            SELECT MAX(id)
            FROM token_usage_points
            GROUP BY project_name, token_direction, recorded_at, model_name
        );

        DROP TABLE token_usage_points;
        ALTER TABLE token_usage_points_new RENAME TO token_usage_points;

        CREATE INDEX IF NOT EXISTS idx_token_usage_project_date
            ON token_usage_points(project_name, usage_date);
        CREATE INDEX IF NOT EXISTS idx_token_usage_natural
            ON token_usage_points(project_name, token_direction, recorded_at, model_name);
        """
    )
    conn.execute(
        """
        INSERT INTO meta(key, value) VALUES ('token_natural_key_v1', '1')
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """
    )
    conn.commit()


def _column_names(conn: sqlite3.Connection, table_name: str) -> set[str]:
    if not _table_exists(conn, table_name):
        return set()
    return {str(r["name"]) for r in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _append_subproject_filter(
    where: list[str],
    params: list[object],
    subproject_name: str | None,
) -> None:
    """When subproject_name is set, restrict queries to that subfolder scope."""
    if subproject_name is None:
        return
    where.append("subproject_name = ?")
    params.append(str(subproject_name))


def _append_billing_subproject_filter(
    where: list[str],
    params: list[object],
    subproject_name: str | None,
) -> None:
    """Restrict billing transactions to rows whose ResourceId ends with the subproject slug."""
    if subproject_name is None:
        return
    slug = str(subproject_name).strip()
    if not slug:
        return
    where.append(
        "(COALESCE(resource_id, '') LIKE ? OR LOWER(COALESCE(resource_id, '')) = LOWER(?))"
    )
    params.append(f"%/{slug}")
    params.append(slug)


def _sum_billing_cost_usd(
    conn: sqlite3.Connection,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    currency: str | None = None,
    project_name: str | None = None,
    project_names: list[str] | None = None,
    subproject_name: str | None = None,
) -> float:
    """Authoritative billing total: one SQL SUM(cost_usd), then round once (matches Azure CSV totals)."""
    where: list[str] = []
    params: list[object] = []

    if project_name is not None:
        where.append("project_name = ?")
        params.append(project_name)
    else:
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
    if currency:
        where.append("currency = ?")
        params.append(currency)
    _append_billing_subproject_filter(where, params, subproject_name)

    where_sql = " AND ".join(where) if where else "1=1"
    row = conn.execute(
        f"SELECT COALESCE(SUM(cost_usd), 0) AS total FROM transactions WHERE {where_sql}",
        tuple(params),
    ).fetchone()
    return float(row["total"] or 0.0)


def _backfill_subproject_from_source_file(
    conn: sqlite3.Connection,
    *,
    table_name: str,
    path_column: str,
) -> None:
    from .bills_layout import subproject_from_relpath

    rows = conn.execute(f"SELECT id, {path_column} FROM {table_name}").fetchall()
    for row in rows:
        subproject = subproject_from_relpath(str(row[path_column]))
        conn.execute(
            f"UPDATE {table_name} SET subproject_name = ? WHERE id = ?",
            (subproject, int(row["id"])),
        )


def _migrate_token_subproject_v1(conn: sqlite3.Connection) -> None:
    """
    Add subproject_name to token ingest tables and extend natural keys so nested
    bills/<project>/token/<subproject>/ layouts do not collide.
    """
    row = conn.execute("SELECT value FROM meta WHERE key = 'token_subproject_v1'").fetchone()
    if row is not None and str(row["value"]).strip() == "1":
        return

    for table_name in ("ingested_token_files", "ingested_token_metric_files"):
        cols = _column_names(conn, table_name)
        if cols and "subproject_name" not in cols:
            conn.execute(
                f"ALTER TABLE {table_name} ADD COLUMN subproject_name TEXT NOT NULL DEFAULT ''"
            )

    if _table_exists(conn, "token_usage_points") and "subproject_name" not in _column_names(
        conn, "token_usage_points"
    ):
        conn.executescript(
            """
            CREATE TABLE token_usage_points_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT NOT NULL,
                subproject_name TEXT NOT NULL DEFAULT '',
                recorded_at TEXT NOT NULL,
                usage_date TEXT NOT NULL,
                model_name TEXT NOT NULL,
                token_direction TEXT NOT NULL,
                token_count REAL NOT NULL,
                source_file TEXT NOT NULL,
                source_row_index INTEGER NOT NULL,
                ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(project_name, subproject_name, token_direction, recorded_at, model_name)
            );

            INSERT INTO token_usage_points_new(
                id, project_name, subproject_name, recorded_at, usage_date, model_name,
                token_direction, token_count, source_file, source_row_index, ingested_at
            )
            SELECT
                id, project_name, '', recorded_at, usage_date, model_name,
                token_direction, token_count, source_file, source_row_index, ingested_at
            FROM token_usage_points
            WHERE id IN (
                SELECT MAX(id)
                FROM token_usage_points
                GROUP BY project_name, token_direction, recorded_at, model_name
            );

            DROP TABLE token_usage_points;
            ALTER TABLE token_usage_points_new RENAME TO token_usage_points;

            CREATE INDEX IF NOT EXISTS idx_token_usage_project_date
                ON token_usage_points(project_name, usage_date);
            CREATE INDEX IF NOT EXISTS idx_token_usage_natural
                ON token_usage_points(project_name, subproject_name, token_direction, recorded_at, model_name);
            """
        )
        _backfill_subproject_from_source_file(conn, table_name="token_usage_points", path_column="source_file")

    if _table_exists(conn, "token_metric_points") and "subproject_name" not in _column_names(
        conn, "token_metric_points"
    ):
        conn.executescript(
            """
            CREATE TABLE token_metric_points_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT NOT NULL,
                subproject_name TEXT NOT NULL DEFAULT '',
                recorded_at TEXT NOT NULL,
                usage_date TEXT NOT NULL,
                model_name TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                metric_value REAL NOT NULL,
                metric_unit TEXT NOT NULL,
                source_file TEXT NOT NULL,
                source_row_index INTEGER NOT NULL,
                ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(project_name, subproject_name, metric_name, recorded_at, model_name)
            );

            INSERT INTO token_metric_points_new(
                id, project_name, subproject_name, recorded_at, usage_date, model_name,
                metric_name, metric_value, metric_unit, source_file, source_row_index, ingested_at
            )
            SELECT
                id, project_name, '', recorded_at, usage_date, model_name,
                metric_name, metric_value, metric_unit, source_file, source_row_index, ingested_at
            FROM token_metric_points
            WHERE id IN (
                SELECT MAX(id)
                FROM token_metric_points
                GROUP BY project_name, metric_name, recorded_at, model_name
            );

            DROP TABLE token_metric_points;
            ALTER TABLE token_metric_points_new RENAME TO token_metric_points;

            CREATE INDEX IF NOT EXISTS idx_token_metric_project_date
                ON token_metric_points(project_name, usage_date);
            CREATE INDEX IF NOT EXISTS idx_token_metric_natural
                ON token_metric_points(project_name, subproject_name, metric_name, recorded_at, model_name);
            """
        )
        _backfill_subproject_from_source_file(conn, table_name="token_metric_points", path_column="source_file")

    for table_name, path_column in (
        ("ingested_token_files", "file_path"),
        ("ingested_token_metric_files", "file_path"),
    ):
        if _table_exists(conn, table_name) and "subproject_name" in _column_names(conn, table_name):
            _backfill_subproject_from_source_file(conn, table_name=table_name, path_column=path_column)

    conn.execute(
        """
        INSERT INTO meta(key, value) VALUES ('token_subproject_v1', '1')
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
        "azure_foundry_deepseek_pricing",
        "Azure Foundry Models — DeepSeek (marketing)",
        "https://azure.microsoft.com/en-us/pricing/details/ai-foundry-models/deepseek/",
        "",
        "Serverless DeepSeek language model rows from the Foundry Models pricing page (USD per 1M tokens).",
        15,
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
    for sk, title, ref, api, notes, so in PRICE_SOURCE_CATALOG_SEED:
        conn.execute(
            """
            INSERT INTO price_source_catalog (source_key, title, reference_url, api_url, notes, sort_order)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_key) DO NOTHING
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


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _delta_pct(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    cur = float(current)
    prev = float(previous)
    if prev == 0.0:
        if cur == 0.0:
            return 0.0
        return None
    return round(((cur - prev) / abs(prev)) * 100.0, 1)


def _last_day_of_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1) - timedelta(days=1)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)


def _is_full_calendar_month(start_d: date, end_d: date) -> bool:
    return start_d.day == 1 and end_d == _last_day_of_month(start_d)


def _prior_compare_window(
    start_d: date, end_d: date
) -> tuple[date, date, str, str]:
    """Return (prev_start, prev_end, mode, label).

    - Full calendar month → prior calendar month (mode=prior_month, label=上月)
    - Otherwise → equal-length window ending the day before start
      (mode=prior_period, label=上期)
    """
    if _is_full_calendar_month(start_d, end_d):
        prev_end = start_d - timedelta(days=1)
        prev_start = date(prev_end.year, prev_end.month, 1)
        return prev_start, prev_end, "prior_month", "上月"

    span_days = (end_d - start_d).days
    prev_end = start_d - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span_days)
    return prev_start, prev_end, "prior_period", "上期"


def compute_period_compare(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    start: str | None,
    end: str | None,
    currency: str | None = None,
    subproject_name: str | None = None,
) -> dict[str, Any]:
    """Compare current [start, end] to the prior window (上月 or 上期).

    Prior window:
    - if [start, end] is a full calendar month → previous calendar month
    - else → equal-length period ending at start−1
    """
    empty: dict[str, Any] = {
        "mode": None,
        "label": None,
        "prev_start": None,
        "prev_end": None,
        "actual_cost_usd_total": None,
        "actual_days": None,
        "delta_pct": None,
        "avg_daily_delta_pct": None,
        "estimated_total_tokens": None,
        "token_delta_pct": None,
    }
    start_d = _parse_iso_date(start)
    end_d = _parse_iso_date(end)
    if start_d is None or end_d is None or end_d < start_d:
        return empty

    prev_start, prev_end, mode, label = _prior_compare_window(start_d, end_d)

    current = get_project_stats(
        conn,
        project_name,
        from_date=start_d.isoformat(),
        to_date=end_d.isoformat(),
        currency=currency,
        subproject_name=subproject_name,
    )
    previous = get_project_stats(
        conn,
        project_name,
        from_date=prev_start.isoformat(),
        to_date=prev_end.isoformat(),
        currency=currency,
        subproject_name=subproject_name,
    )
    return {
        "mode": mode,
        "label": label,
        "prev_start": prev_start.isoformat(),
        "prev_end": prev_end.isoformat(),
        "actual_cost_usd_total": previous.actual_cost_usd_total,
        "actual_days": previous.actual_days,
        "delta_pct": _delta_pct(current.actual_cost_usd_total, previous.actual_cost_usd_total),
        "avg_daily_delta_pct": _delta_pct(
            (
                (current.actual_cost_usd_total / current.actual_days)
                if current.actual_days > 0
                else None
            ),
            (
                (previous.actual_cost_usd_total / previous.actual_days)
                if previous.actual_days > 0
                else None
            ),
        ),
        "estimated_total_tokens": previous.estimated_total_tokens,
        "token_delta_pct": _delta_pct(
            current.estimated_total_tokens, previous.estimated_total_tokens
        ),
    }


def _timestamp_candidate_to_utc(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_data_as_of_utc(
    conn: sqlite3.Connection,
    project_name: str | None = None,
) -> str | None:
    """Latest billing/token ingest freshness as ISO8601 UTC."""
    tables = (
        "ingested_files",
        "ingested_token_files",
        "ingested_token_metric_files",
    )
    latest: datetime | None = None
    for table in tables:
        if not _table_exists(conn, table):
            continue
        where = ""
        params: tuple[object, ...] = ()
        if project_name:
            where = " WHERE project_name = ?"
            params = (project_name,)
        rows = conn.execute(
            f"SELECT ingested_at, source_last_modified FROM {table}{where}",
            params,
        ).fetchall()
        for row in rows:
            for key in ("ingested_at", "source_last_modified"):
                cand = _timestamp_candidate_to_utc(row[key])
                if cand is not None and (latest is None or cand > latest):
                    latest = cand
    if latest is None:
        return None
    return latest.strftime("%Y-%m-%dT%H:%M:%SZ")


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
        UNION
        SELECT DISTINCT project_name FROM transactions
        ORDER BY project_name
        """
    ).fetchall()
    return [r["project_name"] for r in rows]


def list_token_models_for_project(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    subproject_name: str | None = None,
) -> list[str]:
    where = ["project_name = ?"]
    params: list[object] = [project_name]
    _append_subproject_filter(where, params, subproject_name)
    where_sql = " AND ".join(where)
    rows = conn.execute(
        f"""
        SELECT DISTINCT model_name
        FROM token_usage_points
        WHERE {where_sql}
        ORDER BY model_name ASC
        """,
        tuple(params),
    ).fetchall()
    return [str(r["model_name"]) for r in rows if r["model_name"]]


def list_subprojects_for_project(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    bills_dir: str | os.PathLike[str] | None = None,
) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT subproject_name
        FROM token_usage_points
        WHERE project_name = ? AND subproject_name != ''
        UNION
        SELECT DISTINCT subproject_name
        FROM token_metric_points
        WHERE project_name = ? AND subproject_name != ''
        UNION
        SELECT DISTINCT subproject_name
        FROM ingested_token_files
        WHERE project_name = ? AND subproject_name != ''
        UNION
        SELECT DISTINCT subproject_name
        FROM ingested_token_metric_files
        WHERE project_name = ? AND subproject_name != ''
        ORDER BY subproject_name ASC
        """,
        (project_name, project_name, project_name, project_name),
    ).fetchall()
    found = {str(r["subproject_name"]) for r in rows if r["subproject_name"]}
    from .bills_layout import discover_subprojects_on_disk, subproject_from_resource_id

    billing_rows = conn.execute(
        """
        SELECT DISTINCT resource_id
        FROM transactions
        WHERE project_name = ? AND COALESCE(TRIM(resource_id), '') != ''
        """,
        (project_name,),
    ).fetchall()
    for row in billing_rows:
        slug = subproject_from_resource_id(row["resource_id"])
        if slug:
            found.add(slug)
    if bills_dir is not None:
        found.update(discover_subprojects_on_disk(bills_dir, project_name))
    return sorted(found)


def _pick_primary_token_model(models: list[str], project_name: str) -> str:
    """Choose a display / config primary model from imported token columns."""
    unique = sorted({str(m).strip() for m in models if m})
    if not unique:
        return ""

    for m in unique:
        ml = m.lower()
        if ml == "gpt-4o" or ml.startswith("gpt-4o-"):
            return m

    folder_match = re.search(r"gpt-?(\d+(?:\.\d+)?)", project_name, re.IGNORECASE)
    if folder_match:
        ver = folder_match.group(1)
        needle = f"gpt-{ver}".lower()
        for m in unique:
            ml = m.lower()
            if ml == needle or ml.startswith(needle + "-"):
                return m

    return unique[0]


def ensure_project_model_config_from_tokens(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    overwrite: bool = False,
) -> str | None:
    """
    Seed ``project_model_configs`` from imported token CSV model columns when missing.

    Returns the primary model name if a config row exists or was created.
    """
    if not overwrite and get_project_model_config(conn, project_name) is not None:
        cfg = get_project_model_config(conn, project_name)
        return str(cfg["model_name"]) if cfg else None

    models = list_token_models_for_project(conn, project_name)
    primary = _pick_primary_token_model(models, project_name)
    if not primary:
        return None

    upsert_project_model_config(
        conn,
        project_name=project_name,
        model_name=primary,
        api_version=None,
        azure_endpoint=None,
    )
    return primary


def sync_missing_project_model_configs(conn: sqlite3.Connection) -> int:
    """Backfill configs for projects that have token imports but no config row."""
    rows = conn.execute(
        """
        SELECT DISTINCT t.project_name
        FROM token_usage_points t
        LEFT JOIN project_model_configs c ON c.project_name = t.project_name
        WHERE c.project_name IS NULL
        ORDER BY t.project_name
        """
    ).fetchall()
    n = 0
    for r in rows:
        if ensure_project_model_config_from_tokens(conn, str(r["project_name"])):
            n += 1
    return n


def list_project_details(conn: sqlite3.Connection) -> list[dict[str, object]]:
    """Project folder ids with primary (configured) and token (imported) model names."""
    sync_missing_project_model_configs(conn)
    out: list[dict[str, object]] = []
    for name in list_projects(conn):
        cfg = get_project_model_config(conn, name)
        token_models = list_token_models_for_project(conn, name)
        primary = str(cfg["model_name"]) if cfg and cfg.get("model_name") else None
        if not primary and token_models:
            primary = _pick_primary_token_model(token_models, name)
        label = name
        if primary:
            label = f"{name} · {primary}"
        elif token_models:
            label = f"{name} · {token_models[0]}"
        out.append(
            {
                "name": name,
                "primary_model": primary,
                "token_models": token_models,
                "display_label": label,
            }
        )
    return out


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
    subproject_name: str | None = None,
) -> tuple[float, float]:
    where = ["project_name = ?"]
    params: list[object] = [project_name]
    _append_subproject_filter(where, params, subproject_name)
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


def get_imported_token_totals_by_subproject(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    """Per-subproject input/output token totals for segment cards (Tokens page)."""
    where = ["project_name = ?", "COALESCE(TRIM(subproject_name), '') != ''"]
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
            subproject_name,
            COALESCE(SUM(CASE WHEN token_direction = 'input' THEN token_count ELSE 0 END), 0) AS input_tokens,
            COALESCE(SUM(CASE WHEN token_direction = 'output' THEN token_count ELSE 0 END), 0) AS output_tokens
        FROM token_usage_points
        WHERE {where_sql}
        GROUP BY subproject_name
        HAVING input_tokens > 0 OR output_tokens > 0
        ORDER BY (input_tokens + output_tokens) DESC, subproject_name ASC
        """,
        tuple(params),
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        in_tok = float(r["input_tokens"])
        out_tok = float(r["output_tokens"])
        out.append(
            {
                "subproject_name": str(r["subproject_name"]),
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "total_tokens": in_tok + out_tok,
            }
        )
    return out


def get_imported_token_timeseries(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    granularity: str = "day",
    subproject_name: str | None = None,
) -> list[dict]:
    if granularity not in {"day", "month"}:
        raise ValueError("granularity must be 'day' or 'month'")
    date_expr = "usage_date" if granularity == "day" else "substr(usage_date, 1, 7)"
    where = ["project_name = ?"]
    params: list[object] = [project_name]
    _append_subproject_filter(where, params, subproject_name)
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
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "total_tokens": in_tok + out_tok,
            }
        )
    return out


def get_imported_token_meta(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    subproject_name: str | None = None,
) -> dict[str, object]:
    where = ["project_name = ?"]
    params: list[object] = [project_name]
    _append_subproject_filter(where, params, subproject_name)
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
    subproject_name: str | None = None,
) -> list[dict]:
    where = ["project_name = ?"]
    params: list[object] = [project_name]
    _append_subproject_filter(where, params, subproject_name)
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
    subproject_name: str | None = None,
) -> list[dict[str, object]]:
    """Per calendar day and model: input/output token totals (for ratio tables and charts)."""
    where = ["project_name = ?"]
    params: list[object] = [project_name]
    _append_subproject_filter(where, params, subproject_name)
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
        subproject_name=subproject_name,
    )
    cost_by_key: dict[tuple[str, str], dict[str, object]] = {}
    for r in cost_rows:
        d = str(r["date"])
        m = str(r["model_name"])
        cost_by_key[(d, m)] = r

    def _lookup_cost(date: str, model_name: str) -> dict[str, object]:
        direct = cost_by_key.get((date, model_name))
        if direct is not None:
            return direct
        for (d, m), row in cost_by_key.items():
            if d == date and token_models_match(m, model_name):
                return row
        return {}

    out: list[dict[str, object]] = []
    for (d, model_name), vals in sorted(
        merged.items(),
        key=lambda item: (item[0][0], item[0][1]),
        reverse=True,
    ):
        in_tok = float(vals["input"])
        out_tok = float(vals["output"])
        ratio: float | None = (out_tok / in_tok) if in_tok > 0 else None
        c = _lookup_cost(d, model_name)
        method = str(c.get("allocation_method") or "no_meter_match")
        in_raw = c.get("input_cost_usd")
        out_raw = c.get("output_cost_usd")
        total_raw = c.get("total_cost_usd")
        has_cost = method in {"meter_matched", "meter_matched_partial"}
        usd_per_1m_input: float | None = None
        usd_per_1m_output: float | None = None
        if has_cost and in_raw is not None and in_tok > 0 and float(in_raw) > 0:
            usd_per_1m_input = round_cost((float(in_raw) / in_tok) * TOKENS_PER_MILLION)
        if has_cost and out_raw is not None and out_tok > 0 and float(out_raw) > 0:
            usd_per_1m_output = round_cost((float(out_raw) / out_tok) * TOKENS_PER_MILLION)
        out.append(
            {
                "date": d,
                "model_name": model_name,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "output_input_ratio": round(ratio, 6) if ratio is not None else None,
                "input_cost_usd": (
                    round_cost(float(in_raw))
                    if has_cost and in_raw is not None
                    else None
                ),
                "output_cost_usd": (
                    round_cost(float(out_raw))
                    if has_cost and out_raw is not None
                    else None
                ),
                "total_cost_usd": (
                    round_cost(float(total_raw))
                    if has_cost and total_raw is not None
                    else None
                ),
                "usd_per_1m_input": usd_per_1m_input,
                "usd_per_1m_output": usd_per_1m_output,
                "allocation_method": method,
            }
        )
    return out


def sum_transaction_cost_usd_for_model_day(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    usage_date: str,
    token_model: str,
    token_direction: str,
    currency: str | None = None,
    subproject_name: str | None = None,
) -> float:
    """
    Sum ``transactions.cost_usd`` for one calendar day, token model column, and direction.

    Matching uses ``Meter`` text (e.g. ``5.3 codex inp``, ``5.4 opt``) against the
    canonical token model name (e.g. ``gpt-5.3-codex``, ``gpt-5.4``).
    """
    model_key = canonical_model_name(token_model) or str(token_model)
    if token_direction not in {"input", "output"}:
        raise ValueError("token_direction must be 'input' or 'output'")

    currency_filter = currency
    if currency_filter is None:
        currencies = get_available_currencies(conn, project_name)
        currency_filter = currencies[0] if currencies else None

    where = ["project_name = ?", "usage_date = ?"]
    params: list[object] = [project_name, usage_date]
    if currency_filter:
        where.append("currency = ?")
        params.append(currency_filter)
    _append_billing_subproject_filter(where, params, subproject_name)
    where_sql = " AND ".join(where)
    rows = conn.execute(
        f"""
        SELECT meter, COALESCE(cost_usd, 0) AS cost_usd
        FROM transactions
        WHERE {where_sql}
        """,
        tuple(params),
    ).fetchall()
    meter_rows = [(str(r["meter"] or ""), float(r["cost_usd"])) for r in rows]
    total = sum_meter_costs(
        meter_rows,
        token_model=model_key,
        token_direction=token_direction,
    )
    if cost_debug_enabled():
        matched = [
            (m, c)
            for m, c in meter_rows
            if c > 0
            and meter_matches_model_direction(
                m,
                token_model=model_key,
                token_direction=token_direction,
            )
        ]
        log_cost_step(
            "sum_transaction_cost project=%s date=%s model=%s dir=%s "
            "tx_rows=%d matched_meters=%d total_usd=%.6f samples=%s",
            project_name,
            usage_date,
            model_key,
            token_direction,
            len(meter_rows),
            len(matched),
            total,
            [m for m, _ in matched[:4]],
        )
    return total


def _meter_split_cost_for_model_day(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    usage_date: str,
    token_model: str,
    currency: str | None = None,
    subproject_name: str | None = None,
) -> dict[str, object]:
    """
    Bill input/output USD for one model day from transaction ``Meter`` rows only.

    Never estimates from daily totals or token ratios.
    """
    bill_in = sum_transaction_cost_usd_for_model_day(
        conn,
        project_name,
        usage_date=usage_date,
        token_model=token_model,
        token_direction="input",
        currency=currency,
        subproject_name=subproject_name,
    )
    bill_out = sum_transaction_cost_usd_for_model_day(
        conn,
        project_name,
        usage_date=usage_date,
        token_model=token_model,
        token_direction="output",
        currency=currency,
        subproject_name=subproject_name,
    )
    meter_total = bill_in + bill_out
    if meter_total <= 0:
        return {
            "input_cost_usd": None,
            "output_cost_usd": None,
            "total_cost_usd": None,
            "allocation_method": "no_meter_match",
        }
    method = (
        "meter_matched"
        if bill_in > 0 and bill_out > 0
        else "meter_matched_partial"
    )
    return {
        "input_cost_usd": round_cost(bill_in) if bill_in > 0 else None,
        "output_cost_usd": round_cost(bill_out) if bill_out > 0 else None,
        "total_cost_usd": round_cost(meter_total),
        "allocation_method": method,
    }


def get_imported_token_daily_cost_by_model(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    currency: str | None = None,
    subproject_name: str | None = None,
) -> list[dict[str, object]]:
    """
    Per calendar day + model: split daily cost into input/output buckets.

    For each (date, model, direction), sum ``transactions`` rows whose ``Meter`` matches
    that model and direction (see ``sum_transaction_cost_usd_for_model_day``).

    When no meter rows match, costs and unit prices are left empty (no estimation).
    """
    where = ["project_name = ?"]
    params: list[object] = [project_name]
    _append_subproject_filter(where, params, subproject_name)
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
    _, chosen_currency = get_timeseries(
        conn,
        project_name,
        start_date=eff_start,
        end_date=eff_end,
        granularity="day",
        currency=currency,
    )
    out: list[dict[str, object]] = []
    for d in sorted(by_date_model.keys(), reverse=True):
        models = by_date_model.get(d, {})
        for model_name in sorted(models.keys()):
            tok = models[model_name]
            in_tok = float(tok["input"])
            out_tok = float(tok["output"])
            if in_tok + out_tok <= 0:
                continue

            split = _meter_split_cost_for_model_day(
                conn,
                project_name,
                usage_date=d,
                token_model=model_name,
                currency=chosen_currency,
                subproject_name=subproject_name,
            )
            allocation_method = str(split["allocation_method"])
            in_cost = split.get("input_cost_usd")
            out_cost = split.get("output_cost_usd")
            total_cost = split.get("total_cost_usd")
            log_cost_step(
                "daily_cost_row date=%s model=%s in_tok=%.0f out_tok=%.0f "
                "bill_in=%s bill_out=%s method=%s",
                d,
                model_name,
                in_tok,
                out_tok,
                in_cost,
                out_cost,
                allocation_method,
            )
            out.append(
                {
                    "date": d,
                    "model_name": model_name,
                    "input_cost_usd": in_cost,
                    "output_cost_usd": out_cost,
                    "total_cost_usd": total_cost,
                    "allocation_method": allocation_method,
                }
            )
    return out


def trace_transaction_cost_match(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    usage_date: str,
    token_model: str,
    currency: str | None = None,
) -> dict[str, object]:
    """Step-by-step trace for one (date, model): which meters matched input vs output."""
    model_key = canonical_model_name(token_model) or str(token_model)
    currency_filter = currency
    if currency_filter is None:
        currencies = get_available_currencies(conn, project_name)
        currency_filter = currencies[0] if currencies else None
    where = ["project_name = ?", "usage_date = ?"]
    params: list[object] = [project_name, usage_date]
    if currency_filter:
        where.append("currency = ?")
        params.append(currency_filter)
    where_sql = " AND ".join(where)
    rows = conn.execute(
        f"""
        SELECT meter, COALESCE(cost_usd, 0) AS cost_usd
        FROM transactions
        WHERE {where_sql}
        ORDER BY meter ASC
        """,
        tuple(params),
    ).fetchall()
    input_hits: list[dict[str, object]] = []
    output_hits: list[dict[str, object]] = []
    unmatched: list[dict[str, object]] = []
    for r in rows:
        meter = str(r["meter"] or "")
        cost = float(r["cost_usd"] or 0.0)
        if cost <= 0:
            continue
        parsed = parse_foundry_meter(meter)
        row = {
            "meter": meter,
            "cost_usd": round_cost(cost),
            "parsed_model": parsed.token_model if parsed else None,
            "parsed_direction": parsed.billing_direction if parsed else None,
        }
        if meter_matches_model_direction(meter, token_model=model_key, token_direction="input"):
            input_hits.append(row)
        elif meter_matches_model_direction(meter, token_model=model_key, token_direction="output"):
            output_hits.append(row)
        else:
            unmatched.append(row)
    bill_in = sum(float(x["cost_usd"]) for x in input_hits)
    bill_out = sum(float(x["cost_usd"]) for x in output_hits)
    return {
        "project": project_name,
        "date": usage_date,
        "token_model": model_key,
        "currency": currency_filter,
        "input_matched": input_hits,
        "output_matched": output_hits,
        "unmatched_meters": unmatched[:20],
        "input_cost_usd": round_cost(bill_in),
        "output_cost_usd": round_cost(bill_out),
        "total_cost_usd": round_cost(bill_in + bill_out),
    }


def get_imported_token_models_with_prices(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    subproject_name: str | None = None,
) -> list[dict[str, object]]:
    where = ["project_name = ?"]
    params: list[object] = [project_name]
    _append_subproject_filter(where, params, subproject_name)
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

    catalog_rows = _fetch_catalog_price_rows(conn)

    def _metric_pick(model_name: str, metric_name: str) -> sqlite3.Row | None:
        picked = _pick_catalog_price_row(
            catalog_rows, target_token_model=model_name, metric_name=metric_name
        )
        if not picked:
            return None
        for r in price_rows:
            if (
                str(r["model_name"]) == picked["catalog_model_name"]
                and str(r["metric_name"]) == metric_name
            ):
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


def _float_stats(vals: list[float], *, money: bool = False) -> dict[str, float | int | None]:
    if not vals:
        return {"min": None, "max": None, "mean": None, "median": None, "count": 0}
    r = round_cost if money else (lambda x: float(x))
    return {
        "min": r(min(vals)),
        "max": r(max(vals)),
        "mean": r(_mean(vals)),
        "median": r(_median(vals)),
        "count": len(vals),
    }


def _period_effective_usd_per_1m_stats(
    daily_rows: list[dict[str, object]],
) -> dict[str, float | int | None]:
    """
    Period-weighted effective USD/1M: sum(meter cost) ÷ sum(tokens) per direction.

    Unlike averaging daily implied rates, this matches finance-style unit economics
    over the selected window.
    """
    input_cost = 0.0
    output_cost = 0.0
    input_tokens = 0.0
    output_tokens = 0.0
    matched_days = 0
    for row in daily_rows:
        method = str(row.get("allocation_method") or "")
        if method not in {"meter_matched", "meter_matched_partial"}:
            continue
        in_tok = float(row.get("input_tokens") or 0.0)
        out_tok = float(row.get("output_tokens") or 0.0)
        in_raw = row.get("input_cost_usd")
        out_raw = row.get("output_cost_usd")
        if in_raw is not None and in_tok > 0:
            input_cost += float(in_raw)
            input_tokens += in_tok
        if out_raw is not None and out_tok > 0:
            output_cost += float(out_raw)
            output_tokens += out_tok
        if in_raw is not None or out_raw is not None:
            matched_days += 1

    usd_in: float | None = None
    usd_out: float | None = None
    usd_blend: float | None = None
    if input_tokens > 0 and input_cost > 0:
        usd_in = round_cost((input_cost / input_tokens) * TOKENS_PER_MILLION)
    if output_tokens > 0 and output_cost > 0:
        usd_out = round_cost((output_cost / output_tokens) * TOKENS_PER_MILLION)
    total_tokens = input_tokens + output_tokens
    total_cost = input_cost + output_cost
    if total_tokens > 0 and total_cost > 0:
        usd_blend = round_cost((total_cost / total_tokens) * TOKENS_PER_MILLION)

    return {
        "usd_per_1m_input": usd_in,
        "usd_per_1m_output": usd_out,
        "usd_per_1m_blended": usd_blend,
        "input_tokens": int(input_tokens) if input_tokens > 0 else 0,
        "output_tokens": int(output_tokens) if output_tokens > 0 else 0,
        "matched_days": matched_days,
    }


_CATALOG_FAMILY_TOKENS = ("codex", "mini", "chat", "max", "pro", "nano", "shortco", "short")


def _catalog_extra_families(name: str) -> set[str]:
    low = str(name or "").lower()
    return {tok for tok in _CATALOG_FAMILY_TOKENS if tok in low}


def _catalog_family_penalty(target_canonical: str, catalog_model_name: str) -> int:
    """Lower is better. Penalize catalog variants with families absent from the token model."""
    tgt = (target_canonical or "").lower()
    cat = str(catalog_model_name or "").lower()
    allowed = _catalog_extra_families(tgt)
    penalty = 0
    for extra in _catalog_extra_families(cat):
        if extra in allowed:
            continue
        if extra == "pro":
            penalty += 25
        elif extra in {"codex", "mini", "chat", "max"}:
            penalty += 15
        else:
            penalty += 8
    return penalty


def _is_global_standard_price_row(row: sqlite3.Row) -> bool:
    scope = str(row["deployment_scope"] or "").strip().lower()
    mode = str(row["billing_mode"] or "").strip().lower()
    return scope == "global" and mode == "standard"


def _catalog_name_match_tier(target_norm: str, catalog_model_name: str) -> int:
    """0 = exact normalized match, 1 = fuzzy substring, 2 = no match."""
    cn = _norm_model_name(catalog_model_name)
    if not target_norm or not cn:
        return 2
    if cn == target_norm:
        return 0
    if target_norm in cn or cn in target_norm:
        return 1
    return 2


def _fetch_catalog_price_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            model_name,
            metric_name,
            amount,
            deployment_scope,
            billing_mode,
            effective_date,
            id
        FROM model_prices
        WHERE price_currency = 'USD'
          AND billing_mode = 'standard'
          AND metric_name IN ('input', 'output')
          AND amount > 0
        ORDER BY effective_date DESC, id DESC
        """
    ).fetchall()


def _pick_catalog_price_row(
    rows: list[sqlite3.Row],
    *,
    target_token_model: str,
    metric_name: str,
) -> dict[str, object] | None:
    """
    Choose one catalog row for a token model + metric.

    Priority: (1) deployment_scope=global & billing_mode=standard,
    then other standard rows; within each pool pick best name fit (not lowest price).
    """
    target_norm = _norm_model_name(target_token_model)
    target_canonical = canonical_model_name(target_token_model) or str(target_token_model)
    if not target_norm:
        return None

    metric_rows = [r for r in rows if str(r["metric_name"]) == metric_name]
    name_matched = [
        r
        for r in metric_rows
        if _catalog_name_match_tier(target_norm, str(r["model_name"])) < 2
    ]
    if not name_matched:
        return None

    global_std = [r for r in name_matched if _is_global_standard_price_row(r)]
    pools: list[tuple[str, list[sqlite3.Row]]] = []
    if global_std:
        pools.append(("global_standard", global_std))
    other_standard = [r for r in name_matched if r not in global_std]
    if other_standard:
        pools.append(("standard", other_standard))

    def _sort_key(r: sqlite3.Row) -> tuple[int, int, int, int]:
        tier = _catalog_name_match_tier(target_norm, str(r["model_name"]))
        penalty = _catalog_family_penalty(target_canonical, str(r["model_name"]))
        return (tier, penalty, len(str(r["model_name"])), -int(r["id"] or 0))

    for price_tier, pool in pools:
        best = min(pool, key=_sort_key)
        catalog_name = str(best["model_name"])
        tier = _catalog_name_match_tier(target_norm, catalog_name)
        return {
            "catalog_model_name": catalog_name,
            "amount": float(best["amount"]),
            "match_kind": "exact" if tier == 0 else "fuzzy",
            "price_tier": price_tier,
            "deployment_scope": str(best["deployment_scope"] or ""),
            "billing_mode": str(best["billing_mode"] or ""),
        }
    return None


def _catalog_price_match_kind(target: str, catalog_model_name: str) -> str:
    tier = _catalog_name_match_tier(_norm_model_name(target), catalog_model_name)
    if tier == 0:
        return "exact"
    if tier == 1:
        return "fuzzy"
    return "none"


def _resolve_catalog_prices_for_model_name(
    conn: sqlite3.Connection, model_name: str
) -> dict[str, object]:
    """
    Resolve catalog USD/1M input & output for a token/billing model name.

    Prefers ``global`` + ``standard`` rows in ``model_prices``, then best name match.
    Returns which catalog row was used for each metric.
    """
    rows = _fetch_catalog_price_rows(conn)
    input_src = _pick_catalog_price_row(rows, target_token_model=model_name, metric_name="input")
    output_src = _pick_catalog_price_row(rows, target_token_model=model_name, metric_name="output")
    return {
        "input": input_src["amount"] if input_src else None,
        "output": output_src["amount"] if output_src else None,
        "input_source": input_src,
        "output_source": output_src,
    }


def _catalog_usd_per_1m_for_model_name(conn: sqlite3.Connection, model_name: str) -> dict[str, float | None]:
    resolved = _resolve_catalog_prices_for_model_name(conn, model_name)
    return {
        "input": resolved.get("input"),  # type: ignore[return-value]
        "output": resolved.get("output"),  # type: ignore[return-value]
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


def resource_short_name(resource_id: str | None) -> str:
    if not resource_id:
        return "Unattributed"
    rid = str(resource_id).strip().rstrip("/")
    if not rid:
        return "Unattributed"
    return rid.split("/")[-1] or "Unattributed"


def get_project_billing_by_resource(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    currency: str | None = None,
    subproject_name: str | None = None,
) -> dict[str, object]:
    """Aggregate billing CSV costs per Azure resource and service."""
    currency_filter = currency
    if currency_filter is None:
        currencies = get_available_currencies(conn, project_name)
        currency_filter = currencies[0] if currencies else "USD"

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
    _append_billing_subproject_filter(where, params, subproject_name)
    where_sql = " AND ".join(where)

    raw_rows = conn.execute(
        f"""
        SELECT
            resource_id,
            resource_type,
            resource_location,
            resource_group_name,
            COALESCE(NULLIF(TRIM(service_name), ''), 'Unknown service') AS service_name,
            usage_date,
            COALESCE(cost_usd, 0) AS cost_usd
        FROM transactions
        WHERE {where_sql}
        """,
        tuple(params),
    ).fetchall()

    if not raw_rows:
        return {
            "available": False,
            "project": project_name,
            "subproject": subproject_name,
            "currency": currency_filter,
            "from_date": start_date,
            "to_date": end_date,
            "total_cost_usd": None,
            "rows": [],
            "resource_totals": [],
        }

    agg: dict[tuple[str, str], dict[str, object]] = {}
    by_resource: dict[str, dict[str, object]] = {}
    total = 0.0
    for r in raw_rows:
        rid = str(r["resource_id"] or "").strip()
        svc = str(r["service_name"])
        key = (rid, svc)
        cost = float(r["cost_usd"])
        total += cost
        st = agg.setdefault(
            key,
            {
                "resource_id": rid or None,
                "resource_name": resource_short_name(rid or None),
                "resource_type": r["resource_type"],
                "resource_location": r["resource_location"],
                "resource_group_name": r["resource_group_name"],
                "service_name": svc,
                "cost_usd": 0.0,
                "days": set(),
            },
        )
        st["cost_usd"] = float(st["cost_usd"]) + cost
        days = st["days"]
        assert isinstance(days, set)
        days.add(str(r["usage_date"]))

        rt = by_resource.setdefault(
            rid,
            {
                "resource_id": rid or None,
                "resource_name": resource_short_name(rid or None),
                "resource_type": r["resource_type"],
                "resource_location": r["resource_location"],
                "resource_group_name": r["resource_group_name"],
                "cost_usd": 0.0,
                "days": set(),
            },
        )
        rt["cost_usd"] = float(rt["cost_usd"]) + cost
        rt_days = rt["days"]
        assert isinstance(rt_days, set)
        rt_days.add(str(r["usage_date"]))

    out_rows: list[dict[str, object]] = []
    for st in agg.values():
        cost_raw = float(st["cost_usd"])
        cost = round_cost(cost_raw) or 0.0
        share = round(cost_raw / total * 100.0, 1) if total > 0 else None
        days_set = st["days"]
        assert isinstance(days_set, set)
        out_rows.append(
            {
                "resource_id": st["resource_id"],
                "resource_name": st["resource_name"],
                "resource_type": st["resource_type"],
                "resource_location": st["resource_location"],
                "resource_group_name": st["resource_group_name"],
                "service_name": st["service_name"],
                "cost_usd": cost,
                "share_pct": share,
                "days_with_cost": len(days_set),
            }
        )

    out_rows.sort(key=lambda row: float(row["cost_usd"] or 0.0), reverse=True)

    resource_totals: list[dict[str, object]] = []
    for rt in by_resource.values():
        cost_raw = float(rt["cost_usd"])
        share = round(cost_raw / total * 100.0, 1) if total > 0 else None
        rt_days = rt["days"]
        assert isinstance(rt_days, set)
        resource_totals.append(
            {
                "resource_id": rt["resource_id"],
                "resource_name": rt["resource_name"],
                "resource_type": rt["resource_type"],
                "resource_location": rt["resource_location"],
                "resource_group_name": rt["resource_group_name"],
                "cost_usd": round_cost(cost_raw),
                "share_pct": share,
                "days_with_cost": len(rt_days),
            }
        )
    resource_totals.sort(key=lambda row: float(row["cost_usd"] or 0.0), reverse=True)

    return {
        "available": True,
        "project": project_name,
        "subproject": subproject_name,
        "currency": currency_filter,
        "from_date": start_date,
        "to_date": end_date,
        "total_cost_usd": round_cost(total),
        "row_count": len(out_rows),
        "rows": out_rows,
        "resource_totals": resource_totals,
    }


def get_project_daily_cost_by_resource(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    currency: str | None = None,
) -> dict[str, object]:
    """Daily OpEx totals per Azure resource (subproject segment) for chart breakdown."""
    currency_filter = currency
    if currency_filter is None:
        currencies = get_available_currencies(conn, project_name)
        currency_filter = currencies[0] if currencies else "USD"

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

    raw_rows = conn.execute(
        f"""
        SELECT
            usage_date AS date,
            resource_id,
            COALESCE(SUM(cost_usd), 0) AS cost_usd
        FROM transactions
        WHERE {where_sql}
        GROUP BY usage_date, resource_id
        ORDER BY date ASC, resource_id ASC
        """,
        tuple(params),
    ).fetchall()

    if not raw_rows:
        return {
            "available": False,
            "project": project_name,
            "currency": currency_filter,
            "resource_count": 0,
            "series": [],
        }

    by_resource: dict[str, dict[str, float]] = {}
    all_dates: set[str] = set()
    for row in raw_rows:
        d = str(row["date"])
        name = resource_short_name(str(row["resource_id"] or "").strip() or None)
        cost = float(row["cost_usd"] or 0)
        all_dates.add(d)
        bucket = by_resource.setdefault(name, {})
        bucket[d] = bucket.get(d, 0.0) + cost

    sorted_dates = sorted(all_dates)
    series: list[dict[str, object]] = []
    for name in sorted(by_resource.keys(), key=lambda n: (-sum(by_resource[n].values()), n)):
        by_date = by_resource[name]
        points = [
            {
                "date": d,
                "cost_usd": round_cost(by_date[d]) if d in by_date else None,
            }
            for d in sorted_dates
        ]
        series.append({"resource_name": name, "points": points})

    return {
        "available": True,
        "project": project_name,
        "currency": currency_filter,
        "from_date": start_date,
        "to_date": end_date,
        "resource_count": len(series),
        "series": series,
    }


def get_financial_daily_cost_by_segment(
    conn: sqlite3.Connection,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    currency: str | None = None,
    project_names: list[str] | None = None,
) -> dict[str, object]:
    """
    Daily OpEx by segment for consolidated reports.

    - Single project in scope: segments = Azure resources (same as Cost page).
    - Multiple projects: segments = project names.
    """
    scoped_projects = list(project_names) if project_names else list_projects(conn)
    scoped_projects = [p for p in scoped_projects if str(p).strip()]
    segment_mode = "resource" if len(scoped_projects) == 1 else "project"

    currency_filter = currency
    if currency_filter is None:
        currencies = get_all_currencies(
            conn,
            start_date=start_date,
            end_date=end_date,
            project_names=project_names,
        )
        currency_filter = currencies[0] if currencies else "USD"

    where: list[str] = []
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
    if currency_filter:
        where.append("currency = ?")
        params.append(currency_filter)
    where_sql = " AND ".join(where) if where else "1=1"

    if segment_mode == "resource":
        group_cols = "usage_date, resource_id"
        select_cols = "usage_date AS date, resource_id, NULL AS project_name"
    else:
        group_cols = "usage_date, project_name"
        select_cols = "usage_date AS date, NULL AS resource_id, project_name"

    raw_rows = conn.execute(
        f"""
        SELECT
            {select_cols},
            COALESCE(SUM(cost_usd), 0) AS cost_usd
        FROM transactions
        WHERE {where_sql}
        GROUP BY {group_cols}
        ORDER BY date ASC
        """,
        tuple(params),
    ).fetchall()

    if not raw_rows:
        return {
            "available": False,
            "segment_mode": segment_mode,
            "currency": currency_filter,
            "resource_count": 0,
            "series": [],
        }

    by_segment: dict[str, dict[str, float]] = {}
    all_dates: set[str] = set()
    for row in raw_rows:
        d = str(row["date"])
        if segment_mode == "resource":
            name = resource_short_name(str(row["resource_id"] or "").strip() or None)
        else:
            name = str(row["project_name"] or "Unknown")
        cost = float(row["cost_usd"] or 0)
        all_dates.add(d)
        bucket = by_segment.setdefault(name, {})
        bucket[d] = bucket.get(d, 0.0) + cost

    sorted_dates = sorted(all_dates)
    series: list[dict[str, object]] = []
    for name in sorted(by_segment.keys(), key=lambda n: (-sum(by_segment[n].values()), n)):
        by_date = by_segment[name]
        points = [
            {
                "date": d,
                "cost_usd": round_cost(by_date[d]) if d in by_date else None,
            }
            for d in sorted_dates
        ]
        series.append({"resource_name": name, "points": points})

    return {
        "available": True,
        "segment_mode": segment_mode,
        "currency": currency_filter,
        "from_date": start_date,
        "to_date": end_date,
        "resource_count": len(series),
        "series": series,
    }


def _project_token_model_names(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[str]:
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
        SELECT DISTINCT model_name
        FROM token_usage_points
        WHERE {where_sql}
        """,
        tuple(params),
    ).fetchall()
    names: set[str] = set()
    for r in rows:
        m = canonical_model_name(r["model_name"]) or str(r["model_name"])
        if m:
            names.add(m)
    return sorted(names)


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
    token_models = _project_token_model_names(
        conn,
        project_name,
        start_date=start_date,
        end_date=end_date,
    )
    return aggregate_billing_rows(rows, token_models=token_models)


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
                    "billing_input_usd": round_cost(bin_c),
                    "billing_output_usd": round_cost(bout_c),
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
        "parsed_cost_usd": round_cost(parsed_cost),
        "total_cost_usd": round_cost(total_cost),
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
    subproject_name: str | None = None,
) -> dict[str, object]:
    """
    Implied USD per 1M tokens per model per day.

    Sum billing ``Meter`` rows matched to token CSV model columns
    (e.g. ``5.3 codex inp`` → ``gpt-5.3-codex`` input). Days without a meter
    match are omitted (no proportional estimation).
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
    _append_subproject_filter(where, params, subproject_name)
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
            "allocation_method": "meter_only",
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
    _, chosen_currency = get_timeseries(
        conn,
        project_name,
        start_date=eff_start,
        end_date=eff_end,
        granularity="day",
        currency=currency,
    )
    used_meter_match = False
    used_partial = False

    model_daily: dict[str, list[dict[str, object]]] = {}
    models_seen: set[str] = set()
    for _d, models in by_date_model.items():
        for mn in models.keys():
            models_seen.add(mn)

    for usage_date in token_dates:
        day_models = by_date_model.get(usage_date, {})
        if not day_models:
            continue

        for model_name, tok in day_models.items():
            in_tok = tok["input"]
            out_tok = tok["output"]
            model_total = in_tok + out_tok
            if model_total <= 0:
                continue

            split = _meter_split_cost_for_model_day(
                conn,
                project_name,
                usage_date=usage_date,
                token_model=model_name,
                currency=chosen_currency,
                subproject_name=subproject_name,
            )
            alloc_method = str(split["allocation_method"])
            if alloc_method == "no_meter_match":
                continue

            if alloc_method == "meter_matched_partial":
                used_partial = True
            else:
                used_meter_match = True

            bill_in = float(split["input_cost_usd"] or 0.0)
            bill_out = float(split["output_cost_usd"] or 0.0)
            allocated_cost = float(split["total_cost_usd"] or 0.0)
            usd_per_1m_input = (
                (bill_in / in_tok) * TOKENS_PER_MILLION if in_tok > 0 and bill_in > 0 else None
            )
            usd_per_1m_output = (
                (bill_out / out_tok) * TOKENS_PER_MILLION
                if out_tok > 0 and bill_out > 0
                else None
            )

            usd_per_1m_blended = (allocated_cost / model_total) * TOKENS_PER_MILLION

            model_daily.setdefault(model_name, []).append(
                {
                    "date": usage_date,
                    "cost_usd_allocated": round_cost(allocated_cost),
                    "input_cost_usd": round_cost(bill_in) if bill_in > 0 else None,
                    "output_cost_usd": round_cost(bill_out) if bill_out > 0 else None,
                    "input_tokens": in_tok,
                    "output_tokens": out_tok,
                    "total_tokens": model_total,
                    "usd_per_1m_input": (
                        round_cost(usd_per_1m_input) if usd_per_1m_input is not None else None
                    ),
                    "usd_per_1m_output": (
                        round_cost(usd_per_1m_output) if usd_per_1m_output is not None else None
                    ),
                    "usd_per_1m_blended": round_cost(usd_per_1m_blended),
                    "allocation_method": alloc_method,
                }
            )

    models_out: list[dict[str, object]] = []
    for model_name in sorted(models_seen):
        daily = model_daily.get(model_name, [])
        catalog = _catalog_usd_per_1m_for_model_name(conn, model_name)
        period_effective = _period_effective_usd_per_1m_stats(daily)
        models_out.append(
            {
                "model_name": model_name,
                "catalog_usd_per_1m_input": catalog["input"],
                "catalog_usd_per_1m_output": catalog["output"],
                "period_effective_usd_per_1m_input": period_effective["usd_per_1m_input"],
                "period_effective_usd_per_1m_output": period_effective["usd_per_1m_output"],
                "period_effective_usd_per_1m_blended": period_effective["usd_per_1m_blended"],
                "daily": daily,
                "stats": {
                    "period_effective": period_effective,
                    "input": _float_stats(
                        [float(d["usd_per_1m_input"]) for d in daily if d["usd_per_1m_input"] is not None],
                        money=True,
                    ),
                    "output": _float_stats(
                        [float(d["usd_per_1m_output"]) for d in daily if d["usd_per_1m_output"] is not None],
                        money=True,
                    ),
                    "blended": _float_stats(
                        [float(d["usd_per_1m_blended"]) for d in daily if d["usd_per_1m_blended"] is not None],
                        money=True,
                    ),
                },
            }
        )

    if used_meter_match and used_partial:
        top_method = "meter_matched_with_partial_days"
    elif used_meter_match or used_partial:
        top_method = "meter_matched_partial" if used_partial and not used_meter_match else "meter_matched"
    else:
        top_method = "no_meter_match"

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


def _catalog_cost_from_tokens(
    in_tok: float,
    out_tok: float,
    catalog: dict[str, float | None],
) -> float | None:
    """Catalog list cost: input/output tokens × USD per 1M from model_prices."""
    total = 0.0
    priced = False
    cin = catalog.get("input")
    cout = catalog.get("output")
    if cin is not None and in_tok > 0:
        total += in_tok * float(cin) / TOKENS_PER_MILLION
        priced = True
    if cout is not None and out_tok > 0:
        total += out_tok * float(cout) / TOKENS_PER_MILLION
        priced = True
    if not priced:
        return None
    return round_cost(total)


def _reconciled_meter_actual(input_t: float, output_t: float, summed_actual: float) -> float:
    """Row total = input + output when split costs exist (matches column sums)."""
    if input_t > 0 or output_t > 0:
        return input_t + output_t
    return summed_actual


def _billing_other_rows_for_project(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    start_date: str | None,
    end_date: str | None,
    currency: str | None,
    meter_matched_usd: float,
) -> list[dict[str, object]]:
    """Non-token-meter billing lines that reconcile model rows to full billing total."""
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
    rows = conn.execute(
        f"""
        SELECT COALESCE(NULLIF(TRIM(service_name), ''), 'Other / unnamed') AS service_name,
               COALESCE(SUM(cost_usd), 0) AS cost_usd
        FROM transactions
        WHERE {where_sql}
        GROUP BY service_name
        HAVING cost_usd > 0
        ORDER BY cost_usd DESC
        """,
        tuple(params),
    ).fetchall()
    by_service = {str(r["service_name"]): float(r["cost_usd"]) for r in rows}
    if not by_service:
        return []

    meter_matched = max(0.0, float(meter_matched_usd))
    foundry_key = "Foundry Models"
    foundry_total = by_service.pop(foundry_key, 0.0)
    result: list[dict[str, object]] = []

    unmatched_foundry = round_cost(max(0.0, foundry_total - meter_matched))
    if unmatched_foundry is not None and unmatched_foundry > 0:
        result.append(
            {
                "model_name": "Others · Foundry (unmatched meters)",
                "row_kind": "billing_other",
                "service_name": foundry_key,
                "actual_cost_usd": unmatched_foundry,
                "input_cost_usd": None,
                "output_cost_usd": None,
                "catalog_cost_usd": None,
                "variance_pct": None,
                "days_with_rows": None,
                "catalog_price_input": None,
                "catalog_price_output": None,
            }
        )

    for svc, usd in sorted(by_service.items(), key=lambda item: item[1], reverse=True):
        rc = round_cost(usd)
        if rc is None or rc <= 0:
            continue
        result.append(
            {
                "model_name": f"Others · {svc}",
                "row_kind": "billing_other",
                "service_name": svc,
                "actual_cost_usd": rc,
                "input_cost_usd": None,
                "output_cost_usd": None,
                "catalog_cost_usd": None,
                "variance_pct": None,
                "days_with_rows": None,
                "catalog_price_input": None,
                "catalog_price_output": None,
            }
        )
    return result


def _model_summary_row_from_agg(st: dict[str, object], model_name: str) -> dict[str, object]:
    input_t = float(st["input_cost_usd"])
    output_t = float(st["output_cost_usd"])
    actual_t = _reconciled_meter_actual(input_t, output_t, float(st["actual_cost_usd"]))
    catalog_t = float(st["catalog_cost_usd"])
    catalog_in_t = float(st["catalog_input_cost_usd"])
    catalog_out_t = float(st["catalog_output_cost_usd"])
    variance = round_cost(actual_t - catalog_t) if catalog_t > 0 or actual_t > 0 else None
    variance_pct = None
    if catalog_t > 0:
        variance_pct = round((actual_t - catalog_t) / catalog_t * 100.0, 1)
    return {
        "model_name": model_name,
        "row_kind": "model",
        "actual_cost_usd": round_cost(actual_t) if actual_t > 0 else None,
        "input_cost_usd": round_cost(input_t) if input_t > 0 else None,
        "output_cost_usd": round_cost(output_t) if output_t > 0 else None,
        "catalog_cost_usd": round_cost(catalog_t) if catalog_t > 0 else None,
        "catalog_input_cost_usd": (
            round_cost(catalog_in_t) if catalog_in_t > 0 else None
        ),
        "catalog_output_cost_usd": (
            round_cost(catalog_out_t) if catalog_out_t > 0 else None
        ),
        "variance_usd": variance,
        "variance_pct": variance_pct,
        "days_with_rows": int(st["days_with_rows"]),
        "catalog_usd_per_1m_input": st.get("catalog_usd_per_1m_input"),
        "catalog_usd_per_1m_output": st.get("catalog_usd_per_1m_output"),
        "catalog_price_input": st.get("catalog_price_input"),
        "catalog_price_output": st.get("catalog_price_output"),
    }


def _catalog_market_summary_extras(
    *,
    total_actual: float,
    total_catalog: float,
    total_meter_raw: float,
    days_with_catalog: int,
) -> dict[str, object]:
    """Full-billing vs Market variance plus meter-matched subset fields."""
    variance_usd = round_cost(total_actual - total_catalog) if days_with_catalog else None
    variance_pct = None
    if days_with_catalog and total_catalog > 0:
        variance_pct = round((total_actual - total_catalog) / total_catalog * 100.0, 1)
    meter_variance_usd = None
    meter_variance_pct = None
    if days_with_catalog and total_catalog > 0 and total_meter_raw > 0:
        meter_variance_usd = round_cost(total_meter_raw - total_catalog)
        meter_variance_pct = round((total_meter_raw - total_catalog) / total_catalog * 100.0, 1)
    billing_other_usd = None
    if total_actual > 0 and total_meter_raw > 0:
        other = round_cost(total_actual - total_meter_raw)
        if other is not None and other > 0:
            billing_other_usd = other
    return {
        "total_meter_cost_usd": round_cost(total_meter_raw) if total_meter_raw > 0 else None,
        "billing_other_usd": billing_other_usd,
        "variance_usd": variance_usd,
        "variance_pct": variance_pct,
        "meter_variance_usd": meter_variance_usd,
        "meter_variance_pct": meter_variance_pct,
    }


def get_catalog_market_cost_timeseries(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    currency: str | None = None,
    subproject_name: str | None = None,
) -> dict[str, object]:
    """
    Per-model and daily totals: actual billed cost vs catalog list price (tokens × USD/1M).

    ``daily_by_model`` rows include meter-matched actual cost per model/day only.
    ``points`` are project-level daily totals (billing actual vs sum of catalog market).
    """
    chosen_currency = currency
    if chosen_currency is None:
        currencies = get_available_currencies(conn, project_name)
        chosen_currency = currencies[0] if currencies else "USD"

    catalog_cache: dict[str, dict[str, object]] = {}
    unpriced_models: set[str] = set()

    def _catalog_for(model_name: str) -> dict[str, object]:
        if model_name not in catalog_cache:
            catalog_cache[model_name] = _resolve_catalog_prices_for_model_name(conn, model_name)
        return catalog_cache[model_name]

    daily_by_model: list[dict[str, object]] = []
    token_data_source: str

    if project_has_imported_tokens(conn, project_name):
        token_data_source = "imported"
        for row in get_imported_token_daily_by_model(
            conn,
            project_name,
            start_date=start_date,
            end_date=end_date,
            currency=chosen_currency,
            subproject_name=subproject_name,
        ):
            model = str(row["model_name"])
            in_tok = float(row["input_tokens"])
            out_tok = float(row["output_tokens"])
            if in_tok <= 0 and out_tok <= 0:
                continue
            cat = _catalog_for(model)
            if cat.get("input") is None and cat.get("output") is None:
                unpriced_models.add(model)
            catalog_cost = _catalog_cost_from_tokens(in_tok, out_tok, cat)
            actual_raw = row.get("total_cost_usd")
            in_cost_raw = row.get("input_cost_usd")
            out_cost_raw = row.get("output_cost_usd")
            catalog_in = _catalog_cost_from_tokens(in_tok, 0.0, cat)
            catalog_out = _catalog_cost_from_tokens(0.0, out_tok, cat)
            daily_by_model.append(
                {
                    "date": str(row["date"]),
                    "model_name": model,
                    "actual_cost_usd": (
                        round_cost(float(actual_raw))
                        if actual_raw is not None
                        else None
                    ),
                    "input_cost_usd": (
                        round_cost(float(in_cost_raw))
                        if in_cost_raw is not None
                        else None
                    ),
                    "output_cost_usd": (
                        round_cost(float(out_cost_raw))
                        if out_cost_raw is not None
                        else None
                    ),
                    "catalog_cost_usd": catalog_cost,
                    "catalog_input_cost_usd": catalog_in,
                    "catalog_output_cost_usd": catalog_out,
                    "input_tokens": in_tok,
                    "output_tokens": out_tok,
                    "catalog_usd_per_1m_input": cat.get("input"),
                    "catalog_usd_per_1m_output": cat.get("output"),
                    "catalog_price_input": cat.get("input_source"),
                    "catalog_price_output": cat.get("output_source"),
                    "allocation_method": row.get("allocation_method"),
                }
            )
    else:
        token_rows, _, model_name, _, source = get_token_timeseries(
            conn,
            project_name,
            start_date=start_date,
            end_date=end_date,
            granularity="day",
            currency=chosen_currency,
            subproject_name=subproject_name,
        )
        token_data_source = source or "none"
        if not model_name or token_data_source == "none":
            return {
                "available": False,
                "reason": "no_token_volume",
                "project": project_name,
                "currency": chosen_currency,
                "token_data_source": token_data_source,
                "points": [],
                "daily_by_model": [],
                "model_summary": [],
                "summary": {},
                "unpriced_models": [],
            }
        model = str(model_name)
        cat = _catalog_for(model)
        if cat.get("input") is None and cat.get("output") is None:
            unpriced_models.add(model)
        for p in token_rows:
            d = str(p.get("date") or "")
            if not d:
                continue
            in_raw = p.get("estimated_input_tokens")
            out_raw = p.get("estimated_output_tokens")
            if in_raw is None and out_raw is None:
                continue
            in_tok = float(in_raw or 0.0)
            out_tok = float(out_raw or 0.0)
            catalog_cost = _catalog_cost_from_tokens(in_tok, out_tok, cat)
            cost_usd = p.get("cost_usd")
            daily_by_model.append(
                {
                    "date": d,
                    "model_name": model,
                    "actual_cost_usd": (
                        round_cost(float(cost_usd)) if cost_usd is not None else None
                    ),
                    "catalog_cost_usd": catalog_cost,
                    "input_tokens": in_tok,
                    "output_tokens": out_tok,
                    "catalog_usd_per_1m_input": cat.get("input"),
                    "catalog_usd_per_1m_output": cat.get("output"),
                    "catalog_price_input": cat.get("input_source"),
                    "catalog_price_output": cat.get("output_source"),
                    "allocation_method": "estimated_from_billing",
                }
            )

    if not daily_by_model:
        return {
            "available": False,
            "reason": "no_token_volume",
            "project": project_name,
            "currency": chosen_currency,
            "token_data_source": token_data_source,
            "points": [],
            "daily_by_model": [],
            "model_summary": [],
            "summary": {},
            "unpriced_models": sorted(unpriced_models),
        }

    catalog_by_date: dict[str, float] = {}
    model_actual_sum: dict[str, float] = {}
    for row in daily_by_model:
        d = str(row["date"])
        c = row.get("catalog_cost_usd")
        if c is not None:
            catalog_by_date[d] = catalog_by_date.get(d, 0.0) + float(c)
        a = row.get("actual_cost_usd")
        if a is not None:
            model_actual_sum[d] = model_actual_sum.get(d, 0.0) + float(a)

    actual_by_date: dict[str, float] = {}
    ts_points, _ = get_timeseries(
        conn,
        project_name,
        start_date=start_date,
        end_date=end_date,
        granularity="day",
        currency=chosen_currency,
        subproject_name=subproject_name,
    )
    for p in ts_points:
        d = str(p.get("date") or "")
        v = p.get("cost_usd")
        if d and v is not None:
            actual_by_date[d] = float(v)

    all_dates = sorted(set(actual_by_date.keys()) | set(catalog_by_date.keys()))
    points: list[dict[str, object]] = []
    for d in all_dates:
        cat_val = catalog_by_date.get(d)
        points.append(
            {
                "date": d,
                "actual_cost_usd": (
                    round_cost(actual_by_date[d]) if d in actual_by_date else None
                ),
                "catalog_cost_usd": (
                    round_cost(cat_val) if cat_val is not None else None
                ),
                "model_actual_sum_usd": (
                    round_cost(model_actual_sum[d]) if d in model_actual_sum else None
                ),
            }
        )

    summary_by_model: dict[str, dict[str, object]] = {}
    for row in daily_by_model:
        m = str(row["model_name"])
        st = summary_by_model.setdefault(
            m,
            {
                "model_name": m,
                "actual_cost_usd": 0.0,
                "input_cost_usd": 0.0,
                "output_cost_usd": 0.0,
                "catalog_cost_usd": 0.0,
                "catalog_input_cost_usd": 0.0,
                "catalog_output_cost_usd": 0.0,
                "days_with_rows": 0,
                "catalog_usd_per_1m_input": row.get("catalog_usd_per_1m_input"),
                "catalog_usd_per_1m_output": row.get("catalog_usd_per_1m_output"),
                "catalog_price_input": row.get("catalog_price_input"),
                "catalog_price_output": row.get("catalog_price_output"),
            },
        )
        st["days_with_rows"] = int(st["days_with_rows"]) + 1
        a = row.get("actual_cost_usd")
        cin = row.get("input_cost_usd")
        cout = row.get("output_cost_usd")
        c = row.get("catalog_cost_usd")
        cat_in = row.get("catalog_input_cost_usd")
        cat_out = row.get("catalog_output_cost_usd")
        if a is not None:
            st["actual_cost_usd"] = float(st["actual_cost_usd"]) + float(a)
        if cin is not None:
            st["input_cost_usd"] = float(st["input_cost_usd"]) + float(cin)
        if cout is not None:
            st["output_cost_usd"] = float(st["output_cost_usd"]) + float(cout)
        if c is not None:
            st["catalog_cost_usd"] = float(st["catalog_cost_usd"]) + float(c)
        if cat_in is not None:
            st["catalog_input_cost_usd"] = float(st["catalog_input_cost_usd"]) + float(cat_in)
        if cat_out is not None:
            st["catalog_output_cost_usd"] = float(st["catalog_output_cost_usd"]) + float(cat_out)

    model_summary: list[dict[str, object]] = []
    for m in sorted(summary_by_model.keys()):
        model_summary.append(_model_summary_row_from_agg(summary_by_model[m], m))

    _sort_rows_by_date_desc(daily_by_model)

    total_catalog = sum(float(c) for c in catalog_by_date.values())
    total_actual = _sum_billing_cost_usd(
        conn,
        project_name=project_name,
        start_date=start_date,
        end_date=end_date,
        currency=chosen_currency,
        subproject_name=subproject_name,
    )
    total_meter_raw = sum(
        _reconciled_meter_actual(
            float(st["input_cost_usd"]),
            float(st["output_cost_usd"]),
            float(st["actual_cost_usd"]),
        )
        for st in summary_by_model.values()
    )
    total_input = sum(
        float(r["input_cost_usd"])
        for r in daily_by_model
        if r.get("input_cost_usd") is not None
    )
    total_output = sum(
        float(r["output_cost_usd"])
        for r in daily_by_model
        if r.get("output_cost_usd") is not None
    )
    total_catalog_input = sum(
        float(r["catalog_input_cost_usd"])
        for r in daily_by_model
        if r.get("catalog_input_cost_usd") is not None
    )
    total_catalog_output = sum(
        float(r["catalog_output_cost_usd"])
        for r in daily_by_model
        if r.get("catalog_output_cost_usd") is not None
    )
    days_with_catalog = sum(1 for d in all_dates if d in catalog_by_date)

    summary_extras = _catalog_market_summary_extras(
        total_actual=total_actual,
        total_catalog=total_catalog,
        total_meter_raw=total_meter_raw,
        days_with_catalog=days_with_catalog,
    )
    billing_other_rows = _billing_other_rows_for_project(
        conn,
        project_name,
        start_date=start_date,
        end_date=end_date,
        currency=chosen_currency,
        meter_matched_usd=total_meter_raw,
    )

    return {
        "available": True,
        "project": project_name,
        "currency": chosen_currency,
        "token_data_source": token_data_source,
        "catalog_model_hint": (
            sorted(unpriced_models)[:8] if unpriced_models else None
        ),
        "points": points,
        "daily_by_model": daily_by_model,
        "model_summary": model_summary,
        "billing_other_rows": billing_other_rows,
        "summary": {
            "total_catalog_cost_usd": round_cost(total_catalog) if days_with_catalog else None,
            "total_actual_cost_usd": round_cost(total_actual) if total_actual else None,
            "total_input_cost_usd": round_cost(total_input) if total_input > 0 else None,
            "total_output_cost_usd": round_cost(total_output) if total_output > 0 else None,
            "total_catalog_input_cost_usd": (
                round_cost(total_catalog_input) if total_catalog_input > 0 else None
            ),
            "total_catalog_output_cost_usd": (
                round_cost(total_catalog_output) if total_catalog_output > 0 else None
            ),
            **summary_extras,
            "days_with_catalog": days_with_catalog,
            "model_count": len(model_summary),
        },
        "unpriced_models": sorted(unpriced_models),
        "unit_label": "USD per 1M tokens (catalog list)",
    }


def _sum_optional_cost(a: object | None, b: object | None) -> float | None:
    if a is None and b is None:
        return None
    return _safe_float(a) + _safe_float(b)


def _merge_catalog_daily_rows(
    existing: dict[str, object] | None, row: dict[str, object]
) -> dict[str, object]:
    if existing is None:
        return dict(row)
    out = dict(existing)
    for key in (
        "actual_cost_usd",
        "input_cost_usd",
        "output_cost_usd",
        "catalog_cost_usd",
        "catalog_input_cost_usd",
        "catalog_output_cost_usd",
        "input_tokens",
        "output_tokens",
    ):
        merged = _sum_optional_cost(existing.get(key), row.get(key))
        out[key] = round_cost(merged) if merged is not None else None
    am_a = str(existing.get("allocation_method") or "")
    am_b = str(row.get("allocation_method") or "")
    if am_a and am_b and am_a != am_b:
        out["allocation_method"] = "mixed"
    return out


def _unit_rate_delta_pct(
    catalog: float | None,
    effective: float | None,
) -> float | None:
    if catalog is None or effective is None or catalog == 0:
        return None
    return round((effective - catalog) / catalog * 100.0, 1)


def _daily_rows_by_model(
    daily_by_model: list[dict[str, object]],
) -> dict[str, list[dict[str, object]]]:
    by_model: dict[str, list[dict[str, object]]] = {}
    for row in daily_by_model:
        m = str(row["model_name"])
        by_model.setdefault(m, []).append(row)
    return by_model


def _model_unit_rate_row(
    model_name: str,
    *,
    catalog_in: object | None,
    catalog_out: object | None,
    daily_rows: list[dict[str, object]],
    actual_cost_usd: float | None = None,
) -> dict[str, object] | None:
    period_effective = _period_effective_usd_per_1m_stats(daily_rows)
    eff_in = period_effective["usd_per_1m_input"]
    eff_out = period_effective["usd_per_1m_output"]
    if (
        catalog_in is None
        and catalog_out is None
        and eff_in is None
        and eff_out is None
    ):
        return None
    cin = float(catalog_in) if catalog_in is not None else None
    cout = float(catalog_out) if catalog_out is not None else None
    ein = float(eff_in) if eff_in is not None else None
    eout = float(eff_out) if eff_out is not None else None
    return {
        "model_name": model_name,
        "catalog_usd_per_1m_input": catalog_in,
        "catalog_usd_per_1m_output": catalog_out,
        "effective_usd_per_1m_input": eff_in,
        "effective_usd_per_1m_output": eff_out,
        "input_delta_pct": _unit_rate_delta_pct(cin, ein),
        "output_delta_pct": _unit_rate_delta_pct(cout, eout),
        "matched_days": period_effective["matched_days"],
        "actual_cost_usd": round_cost(actual_cost_usd) if actual_cost_usd else None,
    }


def _build_scoped_model_unit_rates(
    daily_by_model: list[dict[str, object]],
    model_summary: list[dict[str, object]],
) -> list[dict[str, object]]:
    by_model = _daily_rows_by_model(daily_by_model)
    rows_out: list[dict[str, object]] = []
    for ms in model_summary:
        m = str(ms["model_name"])
        row = _model_unit_rate_row(
            m,
            catalog_in=ms.get("catalog_usd_per_1m_input"),
            catalog_out=ms.get("catalog_usd_per_1m_output"),
            daily_rows=by_model.get(m, []),
            actual_cost_usd=float(ms.get("actual_cost_usd") or 0.0) or None,
        )
        if row is not None:
            rows_out.append(row)
    rows_out.sort(
        key=lambda r: float(r.get("actual_cost_usd") or 0.0),
        reverse=True,
    )
    return rows_out


def _build_project_unit_rates(
    conn: sqlite3.Connection,
    project_names: list[str],
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    currency: str | None = None,
) -> list[dict[str, object]]:
    projects_out: list[dict[str, object]] = []
    for pn in project_names:
        analysis = get_model_implied_usd_per_1m_analysis(
            conn,
            pn,
            start_date=start_date,
            end_date=end_date,
            currency=currency,
        )
        if not analysis.get("available"):
            continue
        models_out: list[dict[str, object]] = []
        for m in analysis.get("models") or []:
            catalog_in = m.get("catalog_usd_per_1m_input")
            catalog_out = m.get("catalog_usd_per_1m_output")
            eff_in = m.get("period_effective_usd_per_1m_input")
            eff_out = m.get("period_effective_usd_per_1m_output")
            if (
                catalog_in is None
                and catalog_out is None
                and eff_in is None
                and eff_out is None
            ):
                continue
            cin = float(catalog_in) if catalog_in is not None else None
            cout = float(catalog_out) if catalog_out is not None else None
            ein = float(eff_in) if eff_in is not None else None
            eout = float(eff_out) if eff_out is not None else None
            models_out.append(
                {
                    "model_name": m["model_name"],
                    "catalog_usd_per_1m_input": catalog_in,
                    "catalog_usd_per_1m_output": catalog_out,
                    "effective_usd_per_1m_input": eff_in,
                    "effective_usd_per_1m_output": eff_out,
                    "input_delta_pct": _unit_rate_delta_pct(cin, ein),
                    "output_delta_pct": _unit_rate_delta_pct(cout, eout),
                    "matched_days": (
                        m.get("stats", {})
                        .get("period_effective", {})
                        .get("matched_days")
                    ),
                }
            )
        if models_out:
            projects_out.append({"project_name": pn, "models": models_out})
    return projects_out


def _model_summary_from_daily_by_model(
    daily_by_model: list[dict[str, object]],
) -> list[dict[str, object]]:
    summary_by_model: dict[str, dict[str, object]] = {}
    for row in daily_by_model:
        m = str(row["model_name"])
        st = summary_by_model.setdefault(
            m,
            {
                "model_name": m,
                "actual_cost_usd": 0.0,
                "input_cost_usd": 0.0,
                "output_cost_usd": 0.0,
                "catalog_cost_usd": 0.0,
                "catalog_input_cost_usd": 0.0,
                "catalog_output_cost_usd": 0.0,
                "days_with_rows": 0,
                "catalog_usd_per_1m_input": row.get("catalog_usd_per_1m_input"),
                "catalog_usd_per_1m_output": row.get("catalog_usd_per_1m_output"),
                "catalog_price_input": row.get("catalog_price_input"),
                "catalog_price_output": row.get("catalog_price_output"),
            },
        )
        st["days_with_rows"] = int(st["days_with_rows"]) + 1
        for src_key, dst_key in (
            ("actual_cost_usd", "actual_cost_usd"),
            ("input_cost_usd", "input_cost_usd"),
            ("output_cost_usd", "output_cost_usd"),
            ("catalog_cost_usd", "catalog_cost_usd"),
            ("catalog_input_cost_usd", "catalog_input_cost_usd"),
            ("catalog_output_cost_usd", "catalog_output_cost_usd"),
        ):
            v = row.get(src_key)
            if v is not None:
                st[dst_key] = float(st[dst_key]) + float(v)

    model_summary: list[dict[str, object]] = []
    for m in sorted(summary_by_model.keys()):
        model_summary.append(_model_summary_row_from_agg(summary_by_model[m], m))
    return model_summary


def get_all_catalog_market_breakdown(
    conn: sqlite3.Connection,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    currency: str | None = None,
    project_names: list[str] | None = None,
) -> dict[str, object]:
    """
    Cross-project rollup of catalog-market / meter cost analytics (Cost + Tokens core views).
    """
    scoped_projects = project_names if project_names else list_projects(conn)
    merged_daily: dict[tuple[str, str], dict[str, object]] = {}
    points_by_date: dict[str, dict[str, object]] = {}
    unpriced_models: set[str] = set()
    projects_with_data: list[str] = []
    token_sources: set[str] = set()
    chosen_currency = currency

    for pn in scoped_projects:
        ts = get_catalog_market_cost_timeseries(
            conn,
            pn,
            start_date=start_date,
            end_date=end_date,
            currency=chosen_currency,
        )
        if not ts.get("available"):
            continue
        projects_with_data.append(pn)
        chosen_currency = str(ts.get("currency") or chosen_currency or "USD")
        src = ts.get("token_data_source")
        if src:
            token_sources.add(str(src))
        for m in ts.get("unpriced_models") or []:
            unpriced_models.add(str(m))

        for row in ts.get("daily_by_model") or []:
            key = (str(row["date"]), str(row["model_name"]))
            merged_daily[key] = _merge_catalog_daily_rows(merged_daily.get(key), row)

        for p in ts.get("points") or []:
            d = str(p.get("date") or "")
            if not d:
                continue
            cur = points_by_date.get(d)
            if cur is None:
                points_by_date[d] = {
                    "date": d,
                    "actual_cost_usd": p.get("actual_cost_usd"),
                    "catalog_cost_usd": p.get("catalog_cost_usd"),
                    "model_actual_sum_usd": p.get("model_actual_sum_usd"),
                }
            else:
                cur["actual_cost_usd"] = _sum_optional_cost(
                    cur.get("actual_cost_usd"), p.get("actual_cost_usd")
                )
                cur["catalog_cost_usd"] = _sum_optional_cost(
                    cur.get("catalog_cost_usd"), p.get("catalog_cost_usd")
                )
                cur["model_actual_sum_usd"] = _sum_optional_cost(
                    cur.get("model_actual_sum_usd"), p.get("model_actual_sum_usd")
                )

    daily_by_model = list(merged_daily.values())
    _sort_rows_by_date_desc(daily_by_model)

    if not daily_by_model and not points_by_date:
        return {
            "available": False,
            "reason": "no_token_volume",
            "currency": chosen_currency,
            "projects_with_data": [],
            "token_data_source": None,
            "points": [],
            "daily_by_model": [],
            "model_summary": [],
            "model_unit_rates": [],
            "project_unit_rates": [],
            "summary": {},
            "unpriced_models": sorted(unpriced_models),
        }

    model_summary = _model_summary_from_daily_by_model(daily_by_model)

    catalog_by_date: dict[str, float] = {}
    for row in daily_by_model:
        d = str(row["date"])
        c = row.get("catalog_cost_usd")
        if c is not None:
            catalog_by_date[d] = catalog_by_date.get(d, 0.0) + float(c)

    points: list[dict[str, object]] = []
    for d in sorted(points_by_date.keys()):
        entry = points_by_date[d]
        points.append(
            {
                "date": d,
                "actual_cost_usd": (
                    round_cost(entry["actual_cost_usd"])
                    if entry.get("actual_cost_usd") is not None
                    else None
                ),
                "catalog_cost_usd": (
                    round_cost(entry["catalog_cost_usd"])
                    if entry.get("catalog_cost_usd") is not None
                    else None
                ),
                "model_actual_sum_usd": (
                    round_cost(entry["model_actual_sum_usd"])
                    if entry.get("model_actual_sum_usd") is not None
                    else None
                ),
            }
        )

    total_catalog = sum(catalog_by_date.values())
    total_actual = _sum_billing_cost_usd(
        conn,
        start_date=start_date,
        end_date=end_date,
        currency=chosen_currency,
        project_names=scoped_projects,
    )
    total_input = sum(
        float(r["input_cost_usd"])
        for r in daily_by_model
        if r.get("input_cost_usd") is not None
    )
    total_output = sum(
        float(r["output_cost_usd"])
        for r in daily_by_model
        if r.get("output_cost_usd") is not None
    )
    total_catalog_input = sum(
        float(r["catalog_input_cost_usd"])
        for r in daily_by_model
        if r.get("catalog_input_cost_usd") is not None
    )
    total_catalog_output = sum(
        float(r["catalog_output_cost_usd"])
        for r in daily_by_model
        if r.get("catalog_output_cost_usd") is not None
    )
    days_with_catalog = len(catalog_by_date)

    total_meter_raw = sum(
        float(m.get("actual_cost_usd") or 0.0) for m in model_summary
    )
    summary_extras = _catalog_market_summary_extras(
        total_actual=total_actual,
        total_catalog=total_catalog,
        total_meter_raw=total_meter_raw,
        days_with_catalog=days_with_catalog,
    )

    if len(token_sources) == 1:
        token_data_source = next(iter(token_sources))
    elif len(token_sources) > 1:
        token_data_source = "mixed"
    else:
        token_data_source = None

    return {
        "available": True,
        "currency": chosen_currency,
        "projects_with_data": projects_with_data,
        "token_data_source": token_data_source,
        "catalog_model_hint": (
            sorted(unpriced_models)[:8] if unpriced_models else None
        ),
        "points": points,
        "daily_by_model": daily_by_model,
        "model_summary": model_summary,
        "model_unit_rates": _build_scoped_model_unit_rates(daily_by_model, model_summary),
        "project_unit_rates": _build_project_unit_rates(
            conn,
            projects_with_data,
            start_date=start_date,
            end_date=end_date,
            currency=chosen_currency,
        ),
        "summary": {
            "total_catalog_cost_usd": round_cost(total_catalog) if days_with_catalog else None,
            "total_actual_cost_usd": round_cost(total_actual) if total_actual else None,
            "total_input_cost_usd": round_cost(total_input) if total_input > 0 else None,
            "total_output_cost_usd": round_cost(total_output) if total_output > 0 else None,
            "total_catalog_input_cost_usd": (
                round_cost(total_catalog_input) if total_catalog_input > 0 else None
            ),
            "total_catalog_output_cost_usd": (
                round_cost(total_catalog_output) if total_catalog_output > 0 else None
            ),
            **summary_extras,
            "days_with_catalog": days_with_catalog,
            "model_count": len(model_summary),
            "project_count": len(projects_with_data),
        },
        "unpriced_models": sorted(unpriced_models),
        "unit_label": "USD per 1M tokens (catalog list)",
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
        if cost_out > 0 and tout > 0:
            usd_out = (cost_out / tout) * TOKENS_PER_MILLION
            output_vals.append(usd_out)

        points.append(
            {
                "date": d,
                "cost_usd": round_cost(display_cost) if display_cost is not None else None,
                "input_tokens": tin if has_tokens else None,
                "output_tokens": tout if has_tokens else None,
                "usd_per_1m_input": round_cost(usd_in) if usd_in is not None else None,
                "usd_per_1m_output": round_cost(usd_out) if usd_out is not None else None,
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
            "input": _float_stats(input_vals, money=True),
            "output": _float_stats(output_vals, money=True),
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
    return normalize_token_column(v)


def _get_project_token_price_model(
    conn: sqlite3.Connection, *, project_name: str
) -> dict[str, object] | None:
    cfg = get_project_model_config(conn, project_name)
    if not cfg:
        return None

    target = _norm_model_name(cfg["model_name"])
    if not target:
        return None

    catalog_rows = _fetch_catalog_price_rows(conn)
    pin = _pick_catalog_price_row(
        catalog_rows, target_token_model=str(cfg["model_name"]), metric_name="input"
    )
    pout = _pick_catalog_price_row(
        catalog_rows, target_token_model=str(cfg["model_name"]), metric_name="output"
    )
    if not pin or not pout:
        return None

    regions: set[str] = set()
    for picked in (pin, pout):
        for r in conn.execute(
            """
            SELECT price_region FROM model_prices
            WHERE model_name = ? AND metric_name IN ('input', 'output')
            """,
            (picked["catalog_model_name"],),
        ).fetchall():
            if r["price_region"]:
                regions.add(str(r["price_region"]))

    return {
        "model_name": cfg["model_name"],
        "input_price": float(pin["amount"]),
        "output_price": float(pout["amount"]),
        # Might be multiple regions if multiple price entries exist for the same model.
        # Keep it fully visible for the dashboard (frontend can wrap/scroll if needed).
        "price_region": ", ".join(sorted(regions)) if regions else None,
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
    subproject_name: str | None = None,
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
    _append_billing_subproject_filter(where, params, subproject_name)

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

    total_cost_usd = round_cost(_safe_float(row["actual_cost_usd_total"])) or 0.0

    if project_has_imported_tokens(conn, project_name):
        in_tok, out_tok = get_imported_token_totals(
            conn,
            project_name,
            start_date=from_date,
            end_date=to_date,
            subproject_name=subproject_name,
        )
        token_where = ["project_name = ?"]
        token_params: list[object] = [project_name]
        _append_subproject_filter(token_where, token_params, subproject_name)
        if from_date:
            token_where.append("usage_date >= ?")
            token_params.append(from_date)
        if to_date:
            token_where.append("usage_date <= ?")
            token_params.append(to_date)
        token_row = conn.execute(
            f"""
            SELECT MIN(usage_date) AS min_usage_date, MAX(usage_date) AS max_usage_date
            FROM token_usage_points
            WHERE {' AND '.join(token_where)}
            """,
            tuple(token_params),
        ).fetchone()
        token_min = token_row["min_usage_date"]
        token_max = token_row["max_usage_date"]
        if subproject_name is not None:
            min_usage = _iso_date_min(token_min, row["min_usage_date"])
            max_usage = _iso_date_max(token_max, row["max_usage_date"])
        else:
            min_usage = _iso_date_min(token_min, row["min_usage_date"])
            max_usage = _iso_date_max(token_max, row["max_usage_date"])
        return ProjectStats(
            project_name=project_name,
            from_date=from_date,
            to_date=to_date,
            min_usage_date=min_usage,
            max_usage_date=max_usage,
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
    subproject_name: str | None = None,
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
    _append_billing_subproject_filter(where, params, subproject_name)

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
            "cost_usd": round_cost(float(r["actual_cost_usd_total"])) or 0.0,
        }
        for r in rows
    ]
    return points, currency_filter


def get_token_timeseries(
    conn: sqlite3.Connection,
    project_name: str,
    start_date: str | None = None,
    end_date: str | None = None,
    granularity: str = "day",
    currency: str | None = None,
    subproject_name: str | None = None,
) -> tuple[list[dict], str | None, str | None, str | None, str | None]:
    if project_has_imported_tokens(conn, project_name):
        imported = get_imported_token_timeseries(
            conn,
            project_name,
            start_date=start_date,
            end_date=end_date,
            granularity=granularity,
            subproject_name=subproject_name,
        )
        rows: list[dict] = []
        for p in imported:
            in_tok = p.get("input_tokens", p.get("estimated_input_tokens"))
            out_tok = p.get("output_tokens", p.get("estimated_output_tokens"))
            total = p.get("total_tokens", p.get("estimated_total_tokens"))
            if total is None and in_tok is not None and out_tok is not None:
                total = float(in_tok) + float(out_tok)
            rows.append(
                {
                    "date": p["date"],
                    "input_tokens": in_tok,
                    "output_tokens": out_tok,
                    "total_tokens": total,
                    "estimated_input_tokens": in_tok,
                    "estimated_output_tokens": out_tok,
                    "estimated_total_tokens": total,
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


def get_token_metric_points(
    conn: sqlite3.Connection,
    project_name: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    subproject_name: str | None = None,
) -> dict[str, object]:
    """
    Return token/performance metric time-series points for a project.

    Shape:
      {
        "available": bool,
        "metrics": {
          <metric_name>: {
            "metric_name": str,
            "unit": "pct"|"ms"|"count",
            "models": [str],
            "points": [{"recorded_at": "...", "usage_date": "YYYY-MM-DD", "values": {model: value}}]
          }
        }
      }
    """
    where = ["project_name = ?"]
    params: list[object] = [project_name]
    _append_subproject_filter(where, params, subproject_name)
    if start_date:
        where.append("usage_date >= ?")
        params.append(start_date)
    if end_date:
        where.append("usage_date <= ?")
        params.append(end_date)

    rows = conn.execute(
        f"""
        SELECT
          recorded_at,
          usage_date,
          model_name,
          metric_name,
          metric_value,
          metric_unit
        FROM token_metric_points
        WHERE {' AND '.join(where)}
        ORDER BY recorded_at ASC, model_name ASC
        """,
        tuple(params),
    ).fetchall()

    if not rows:
        return {"available": False, "metrics": {}}

    metrics: dict[str, dict[str, object]] = {}
    for r in rows:
        mn = str(r["metric_name"])
        unit = str(r["metric_unit"] or "count")
        metric = metrics.get(mn)
        if metric is None:
            metric = {
                "metric_name": mn,
                "unit": unit,
                "models": [],
                "points": [],
            }
            metrics[mn] = metric
        if str(r["model_name"]) not in metric["models"]:
            metric["models"].append(str(r["model_name"]))

    # group by (metric_name, recorded_at)
    idx: dict[tuple[str, str], dict[str, object]] = {}
    for r in rows:
        mn = str(r["metric_name"])
        ra = str(r["recorded_at"])
        key = (mn, ra)
        p = idx.get(key)
        if p is None:
            p = {"recorded_at": ra, "usage_date": str(r["usage_date"]), "values": {}}
            idx[key] = p
            metrics[mn]["points"].append(p)
        p["values"][str(r["model_name"])] = float(r["metric_value"] or 0.0)

    # Ensure consistent ordering newest first for UI tables, while charts can reverse.
    for m in metrics.values():
        pts = list(m["points"])
        pts.sort(key=lambda x: str(x.get("recorded_at") or ""), reverse=True)
        m["points"] = pts
        m["models"] = sorted(list(m["models"]))

    return {"available": True, "metrics": metrics}


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
            "cost_usd": round_cost(float(r["actual_cost_usd_total"])) or 0.0,
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
    Aggregate imported token totals (input/output/total) for all-financial reports.

    Only sums Grafana/token CSV imports per project — no cost-based token estimates.
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
    imported_projects = 0

    for pn in scoped_projects:
        if not project_has_imported_tokens(conn, pn):
            continue
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

    periods.sort()

    def display_single_or_multiple(vals: set[str]) -> str | None:
        vals = {v for v in vals if v}
        if not vals:
            return None
        if len(vals) == 1:
            return next(iter(vals))
        return f"Multiple ({len(vals)})"

    model_display = display_single_or_multiple(token_models)
    token_data_source = "imported" if imported_projects else None

    points: list[dict] = []
    for d in periods:
        entry = per_period.get(d, {"has": False, "input": 0.0, "output": 0.0})
        if not entry.get("has"):
            points.append(
                {
                    "date": d,
                    "input_tokens": None,
                    "output_tokens": None,
                    "total_tokens": None,
                }
            )
        else:
            in_tok = float(entry["input"])
            out_tok = float(entry["output"])
            points.append(
                {
                    "date": d,
                    "input_tokens": in_tok,
                    "output_tokens": out_tok,
                    "total_tokens": in_tok + out_tok,
                }
            )

    return points, model_display, "bills/<project>/token/", token_data_source


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
    report_token_dates_day = [p["date"] for p in token_daily_points]
    report_token_dates_month = [p["date"] for p in token_monthly_points]
    day_set = set(report_dates_day)
    month_set = set(report_dates_month)
    token_day_set = set(report_token_dates_day)
    token_month_set = set(report_token_dates_month)

    # Compute sum across per-project endpoints' underlying functions.
    cost_day_sum: dict[str, float] = {d: 0.0 for d in report_dates_day}
    cost_month_sum: dict[str, float] = {d: 0.0 for d in report_dates_month}

    token_day_has: dict[str, bool] = {d: False for d in report_token_dates_day}
    token_day_input_sum: dict[str, float] = {d: 0.0 for d in report_token_dates_day}
    token_day_output_sum: dict[str, float] = {d: 0.0 for d in report_token_dates_day}

    token_month_has: dict[str, bool] = {d: False for d in report_token_dates_month}
    token_month_input_sum: dict[str, float] = {d: 0.0 for d in report_token_dates_month}
    token_month_output_sum: dict[str, float] = {d: 0.0 for d in report_token_dates_month}

    token_models: set[str] = set()

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

        if not project_has_imported_tokens(conn, pn):
            continue

        meta = get_imported_token_meta(
            conn, pn, start_date=start_date, end_date=end_date
        )
        for m in meta.get("models") or []:
            token_models.add(str(m))

        for p in get_imported_token_timeseries(
            conn,
            pn,
            start_date=start_date,
            end_date=end_date,
            granularity="day",
        ):
            d = p["date"]
            if d not in token_day_set:
                continue
            in_tok = p.get("input_tokens")
            if in_tok is None:
                in_tok = p.get("estimated_input_tokens")
            out_tok = p.get("output_tokens")
            if out_tok is None:
                out_tok = p.get("estimated_output_tokens")
            if in_tok is None or out_tok is None:
                continue
            token_day_has[d] = True
            token_day_input_sum[d] += float(in_tok)
            token_day_output_sum[d] += float(out_tok)

        for p in get_imported_token_timeseries(
            conn,
            pn,
            start_date=start_date,
            end_date=end_date,
            granularity="month",
        ):
            d = p["date"]
            if d not in token_month_set:
                continue
            in_tok = p.get("input_tokens")
            if in_tok is None:
                in_tok = p.get("estimated_input_tokens")
            out_tok = p.get("output_tokens")
            if out_tok is None:
                out_tok = p.get("estimated_output_tokens")
            if in_tok is None or out_tok is None:
                continue
            token_month_has[d] = True
            token_month_input_sum[d] += float(in_tok)
            token_month_output_sum[d] += float(out_tok)

    def display_single_or_multiple(vals: set[str]) -> str | None:
        vals = {v for v in vals if v}
        if not vals:
            return None
        if len(vals) == 1:
            return next(iter(vals))
        return f"Multiple ({len(vals)})"

    expected_model_display = display_single_or_multiple(token_models)
    expected_region_display = "bills/<project>/token/"

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

        report_token = stats.get("token_actual") or {}
        report_in_total = float(report_token.get("input_tokens_total") or 0.0)
        report_out_total = float(report_token.get("output_tokens_total") or 0.0)
        computed_in_total = sum(v for d, v in token_day_input_sum.items() if token_day_has[d])
        computed_out_total = sum(v for d, v in token_day_output_sum.items() if token_day_has[d])

        add_check(
            "token_totals_input_matches",
            abs(report_in_total - computed_in_total) <= eps_tokens,
            f"report={report_in_total}, computed={computed_in_total}",
        )
        add_check(
            "token_totals_output_matches",
            abs(report_out_total - computed_out_total) <= eps_tokens,
            f"report={report_out_total}, computed={computed_out_total}",
        )
    else:
        # Deep mode: per-period points must match.
        token_daily_by_date = {p["date"]: p for p in token_daily_points}
        token_monthly_by_date = {p["date"]: p for p in token_monthly_points}

        for p in daily_points:
            d = p["date"]
            computed_cost = cost_day_sum.get(d, 0.0)
            report_cost = float(p["cost_usd"] or 0.0)
            add_check(
                f"cost_daily_point_matches:{d}",
                abs(report_cost - computed_cost) <= eps_cost,
                f"report={report_cost}, computed={computed_cost}",
            )

        for d in report_token_dates_day:
            tp = token_daily_by_date.get(d)
            if not token_day_has[d]:
                add_check(
                    f"token_daily_point_none:{d}",
                    tp is not None and tp.get("input_tokens") is None and tp.get("output_tokens") is None,
                )
                continue

            report_in = tp.get("input_tokens") if tp else None
            report_out = tp.get("output_tokens") if tp else None
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

        for p in monthly_points:
            d = p["date"]
            computed_cost = cost_month_sum.get(d, 0.0)
            report_cost = float(p["cost_usd"] or 0.0)
            add_check(
                f"cost_monthly_point_matches:{d}",
                abs(report_cost - computed_cost) <= eps_cost,
                f"report={report_cost}, computed={computed_cost}",
            )

        for d in report_token_dates_month:
            tp = token_monthly_by_date.get(d)
            if not token_month_has[d]:
                add_check(
                    f"token_monthly_point_none:{d}",
                    tp is not None and tp.get("input_tokens") is None and tp.get("output_tokens") is None,
                )
                continue

            report_in = tp.get("input_tokens") if tp else None
            report_out = tp.get("output_tokens") if tp else None
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


def get_financial_project_daily_cost(
    conn: sqlite3.Connection,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    currency: str | None = None,
    project_names: list[str] | None = None,
) -> dict[str, object]:
    """
    Per-project daily billing and averages for the selected scope.

    avg_daily_cost_usd = total_cost_usd / billed_days (days with non-zero billing rows).
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
        return {
            "currency": None,
            "dates": [],
            "projects": [],
            "summaries": [],
            "points": [],
        }

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
            usage_date,
            COALESCE(SUM(cost_usd), 0) AS cost_usd
        FROM transactions
        WHERE {where_sql}
        GROUP BY project_name, usage_date
        HAVING COALESCE(SUM(cost_usd), 0) <> 0
        ORDER BY usage_date ASC, project_name ASC
        """,
        tuple(params),
    ).fetchall()

    by_project: dict[str, dict[str, object]] = {}
    dates_set: set[str] = set()
    points: list[dict[str, object]] = []
    for r in rows:
        pn = str(r["project_name"])
        day = str(r["usage_date"])
        cost = round_cost(_safe_float(r["cost_usd"])) or 0.0
        dates_set.add(day)
        points.append({"project_name": pn, "date": day, "cost_usd": cost})
        bucket = by_project.setdefault(
            pn,
            {"days": set(), "daily": []},
        )
        days_set = bucket["days"]
        assert isinstance(days_set, set)
        days_set.add(day)
        daily_list = bucket["daily"]
        assert isinstance(daily_list, list)
        daily_list.append({"date": day, "cost_usd": cost})

    summary_rows = conn.execute(
        f"""
        SELECT
            project_name,
            COALESCE(SUM(cost_usd), 0) AS total_cost_usd,
            COUNT(DISTINCT CASE WHEN cost_usd IS NOT NULL AND cost_usd <> 0 THEN usage_date END) AS billed_days
        FROM transactions
        WHERE {where_sql}
        GROUP BY project_name
        HAVING COALESCE(SUM(cost_usd), 0) > 0
        ORDER BY total_cost_usd DESC, project_name ASC
        """,
        tuple(params),
    ).fetchall()

    summaries: list[dict[str, object]] = []
    for r in summary_rows:
        total = round_cost(_safe_float(r["total_cost_usd"])) or 0.0
        billed_days = int(r["billed_days"])
        avg_daily = round_cost(total / billed_days) if billed_days > 0 else None
        meter_share_pct = None
        pn = str(r["project_name"])
        if total > 0 and chosen_currency is not None:
            ts = get_catalog_market_cost_timeseries(
                conn,
                pn,
                start_date=start_date,
                end_date=end_date,
                currency=chosen_currency,
            )
            meter_raw = (ts.get("summary") or {}).get("total_meter_cost_usd")
            if meter_raw is not None and total > 0:
                meter_share_pct = round((float(meter_raw) / total) * 100.0, 1)
        summaries.append(
            {
                "project_name": pn,
                "total_cost_usd": total,
                "billed_days": billed_days,
                "avg_daily_cost_usd": avg_daily,
                "meter_share_pct": meter_share_pct,
            }
        )

    return {
        "currency": chosen_currency,
        "dates": sorted(dates_set),
        "projects": [str(s["project_name"]) for s in summaries],
        "summaries": summaries,
        "points": points,
    }


def get_financial_project_breakdown(
    conn: sqlite3.Connection,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    currency: str | None = None,
    project_names: list[str] | None = None,
) -> list[dict]:
    """
    Per-project cost and imported token volume in the same report scope.

    Include token-only projects so the report does not hide usage just because a
    selected period has no matching billing rows.
    """
    _, chosen_currency = get_all_timeseries(
        conn,
        start_date=start_date,
        end_date=end_date,
        granularity="day",
        currency=currency,
        project_names=project_names,
    )

    cost_by_project: dict[str, dict[str, object]] = {}
    if chosen_currency is not None:
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
                COUNT(DISTINCT CASE WHEN cost_usd IS NOT NULL AND cost_usd <> 0 THEN usage_date END) AS actual_days
            FROM transactions
            WHERE {where_sql}
            GROUP BY project_name
            HAVING COALESCE(SUM(cost_usd), 0) > 0
            """,
            tuple(params),
        ).fetchall()
        for r in rows:
            cost_by_project[str(r["project_name"])] = {
                "actual_cost_usd_total": round_cost(_safe_float(r["cost_usd_total"])) or 0.0,
                "actual_days": int(r["actual_days"]),
            }

    scoped_projects = project_names if project_names else list_projects(conn)
    out: list[dict] = []
    for pn in scoped_projects:
        cost_row = cost_by_project.get(pn) or {}
        total = float(cost_row.get("actual_cost_usd_total") or 0.0)
        in_tok: float | None = None
        out_tok: float | None = None
        model_names: list[str] = []
        if project_has_imported_tokens(conn, pn):
            in_val, out_val = get_imported_token_totals(
                conn, pn, start_date=start_date, end_date=end_date
            )
            in_tok = in_val
            out_tok = out_val
            meta = get_imported_token_meta(
                conn, pn, start_date=start_date, end_date=end_date
            )
            model_names = [str(m) for m in (meta.get("models") or []) if m]
        has_cost = total > 0
        has_tokens = (in_tok is not None and in_tok > 0) or (out_tok is not None and out_tok > 0)
        if not has_cost and not has_tokens:
            continue
        actual_days = int(cost_row.get("actual_days") or 0)
        avg_daily = round_cost(total / actual_days) if actual_days > 0 and total > 0 else None
        meter_cost: float | None = None
        platform_cost: float | None = None
        catalog_cost: float | None = None
        billing_variance_usd: float | None = None
        billing_variance_pct: float | None = None
        meter_variance_usd: float | None = None
        meter_variance_pct: float | None = None
        if chosen_currency is not None and (total > 0 or has_tokens):
            ts = get_catalog_market_cost_timeseries(
                conn,
                pn,
                start_date=start_date,
                end_date=end_date,
                currency=chosen_currency,
            )
            cm_summary = ts.get("summary") or {}
            meter_raw = cm_summary.get("total_meter_cost_usd")
            platform_raw = cm_summary.get("billing_other_usd")
            catalog_raw = cm_summary.get("total_catalog_cost_usd")
            if meter_raw is not None:
                meter_cost = float(meter_raw)
            if platform_raw is not None:
                platform_cost = float(platform_raw)
            elif meter_cost is None and total > 0:
                platform_cost = round_cost(total)
            if catalog_raw is not None:
                catalog_f = float(catalog_raw)
                if catalog_f > 0:
                    catalog_cost = round_cost(catalog_f)
                    if total > 0:
                        billing_variance_usd = round_cost(total - catalog_f)
                        billing_variance_pct = round(
                            (total - catalog_f) / catalog_f * 100.0, 1
                        )
                    meter_variance_usd = cm_summary.get("meter_variance_usd")
                    meter_variance_pct = cm_summary.get("meter_variance_pct")
        out.append(
            {
                "project_name": pn,
                "actual_cost_usd_total": total,
                "meter_cost_usd": meter_cost,
                "platform_cost_usd": platform_cost,
                "catalog_cost_usd": catalog_cost,
                "billing_variance_usd": billing_variance_usd,
                "billing_variance_pct": billing_variance_pct,
                "meter_variance_usd": meter_variance_usd,
                "meter_variance_pct": meter_variance_pct,
                "actual_days": actual_days,
                "avg_daily_cost_usd": avg_daily,
                "currency": chosen_currency,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "token_models": model_names,
            }
        )
    out.sort(
        key=lambda r: (
            -float(r.get("actual_cost_usd_total") or 0.0),
            -float(r.get("input_tokens") or 0.0) - float(r.get("output_tokens") or 0.0),
            str(r.get("project_name") or ""),
        )
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

    total_actual_raw = _sum_billing_cost_usd(
        conn,
        start_date=start_date,
        end_date=end_date,
        currency=chosen_currency,
        project_names=project_names,
    )
    total_actual = round_cost(total_actual_raw) or 0.0

    input_tokens_total = 0.0
    output_tokens_total = 0.0
    projects_with_imported_tokens = 0
    scoped_projects = project_names if project_names else list_projects(conn)
    for project_name in scoped_projects:
        if not project_has_imported_tokens(conn, project_name):
            continue
        in_tok, out_tok = get_imported_token_totals(
            conn,
            project_name,
            start_date=start_date,
            end_date=end_date,
        )
        projects_with_imported_tokens += 1
        input_tokens_total += in_tok
        output_tokens_total += out_tok

    return {
        "currency": chosen_currency,
        "daily": {
            "count_days": len(daily_points),
            "total_actual": total_actual,
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
        "token_actual": {
            "projects_with_imported_tokens": projects_with_imported_tokens,
            "input_tokens_total": input_tokens_total,
            "output_tokens_total": output_tokens_total,
        },
        "project_breakdown": get_financial_project_breakdown(
            conn,
            start_date=start_date,
            end_date=end_date,
            currency=currency,
            project_names=project_names,
        ),
        "project_daily_cost": get_financial_project_daily_cost(
            conn,
            start_date=start_date,
            end_date=end_date,
            currency=currency,
            project_names=project_names,
        ),
        "daily_by_segment": get_financial_daily_cost_by_segment(
            conn,
            start_date=start_date,
            end_date=end_date,
            currency=chosen_currency,
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
    subproject_name: str | None = None,
) -> dict:
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    mode = mode.strip().lower()
    if mode not in {"simple", "full", "billing"}:
        raise ValueError("mode must be 'simple', 'full', or 'billing'")

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
    _append_billing_subproject_filter(where, params, subproject_name)

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
                    "cost_usd": round_cost(cost_usd),
                    "cost": round_cost(None if r["cost"] is None else float(r["cost"])),
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

    if mode == "billing":
        rows = conn.execute(
            f"""
            SELECT
                usage_date,
                resource_id,
                resource_type,
                resource_location,
                resource_group_name,
                service_name,
                service_tier,
                meter,
                cost_usd,
                cost,
                currency,
                source_file,
                source_row_index
            FROM transactions
            WHERE {where_sql}
            ORDER BY usage_date DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            tuple([*params, page_size, offset]),
        ).fetchall()
        billing_rows: list[dict[str, object]] = []
        for r in rows:
            billing_rows.append(
                {
                    "usage_date": r["usage_date"],
                    "resource_name": resource_short_name(r["resource_id"]),
                    "resource_id": r["resource_id"],
                    "resource_type": r["resource_type"],
                    "resource_location": r["resource_location"],
                    "resource_group_name": r["resource_group_name"],
                    "service_name": r["service_name"],
                    "service_tier": r["service_tier"],
                    "meter": r["meter"],
                    "cost_usd": round_cost(
                        None if r["cost_usd"] is None else float(r["cost_usd"])
                    ),
                    "cost": round_cost(None if r["cost"] is None else float(r["cost"])),
                    "currency": r["currency"],
                    "source_file": r["source_file"],
                    "source_row_index": r["source_row_index"],
                }
            )
        return {
            "total": int(total),
            "page": page,
            "page_size": page_size,
            "mode": "billing",
            "rows": billing_rows,
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
                "cost_usd": round_cost(None if r["cost_usd"] is None else float(r["cost_usd"])),
                "cost": round_cost(None if r["cost"] is None else float(r["cost"])),
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
