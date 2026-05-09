from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


SCHEMA_VERSION = 3

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
    token_estimate_model: str | None


def _safe_float(x: object) -> float:
    if x is None:
        return 0.0
    return float(x)


def list_projects(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM projects ORDER BY name").fetchall()
    return [r["name"] for r in rows]


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
    if not v:
        return ""
    return "".join(ch for ch in v.lower() if ch.isalnum())


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
        token_estimate_model=token_estimate.get("model_name"),
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


def get_token_timeseries(
    conn: sqlite3.Connection,
    project_name: str,
    start_date: str | None = None,
    end_date: str | None = None,
    granularity: str = "day",
    currency: str | None = None,
) -> tuple[list[dict], str | None, str | None, str | None]:
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
    return rows, chosen_currency, str(price_model["model_name"]), price_model.get("price_region")


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
) -> tuple[list[dict], str | None, str | None]:
    """
    Aggregate token estimates (input/output/total) for the same scope as all-financial reports.

    Token estimates are computed per-project using its linked model prices (Mode Price -> price_region).
    If no project in scope has a matching token price model, token fields are returned as null.
    """
    if granularity not in {"day", "month"}:
        raise ValueError("granularity must be 'day' or 'month'")

    date_expr = "usage_date" if granularity == "day" else "substr(usage_date, 1, 7)"

    # Use the same period set as financial cost points (ensures charts align on x-axis).
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

    per_period: dict[str, dict[str, object]] = {}
    for d in periods:
        per_period[d] = {
            "input": 0.0,
            "output": 0.0,
            "has": False,
        }

    scoped_projects = project_names if project_names else list_projects(conn)
    token_models: set[str] = set()
    token_regions: set[str] = set()

    for pn in scoped_projects:
        price_model = _get_project_token_price_model(conn, project_name=pn)
        if not price_model:
            continue

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
            period = r["period"]
            if period not in period_set:
                continue

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

    def display_single_or_multiple(vals: set[str]) -> str | None:
        vals = {v for v in vals if v}
        if not vals:
            return None
        if len(vals) == 1:
            return next(iter(vals))
        return f"Multiple ({len(vals)})"

    model_display = display_single_or_multiple(token_models)
    region_display = display_single_or_multiple(token_regions)

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

    return points, model_display, region_display


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

    token_daily_points, token_model_display, token_region_display = get_all_token_timeseries(
        conn,
        start_date=start_date,
        end_date=end_date,
        granularity="day",
        currency=chosen_currency,
        project_names=project_names,
    )
    token_monthly_points, _, _ = get_all_token_timeseries(
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
        tp_day, _, _, _ = get_token_timeseries(
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

        tp_month, _, _, _ = get_token_timeseries(
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
            unit_quantity, unit_name, unit_expression, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        list(rows),
    )
    conn.commit()
    c = conn.execute("SELECT COUNT(*) AS c FROM model_prices").fetchone()["c"]
    return int(c)


def get_model_price_filter_options(conn: sqlite3.Connection) -> dict[str, list[str]]:
    def _list_values(col: str) -> list[str]:
        q = f"SELECT DISTINCT {col} AS v FROM model_prices WHERE {col} IS NOT NULL AND {col} != '' ORDER BY {col}"
        rows = conn.execute(q).fetchall()
        return [r["v"] for r in rows]

    return {
        "vendors": _list_values("vendor"),
        "platforms": _list_values("platform"),
        "model_series": _list_values("model_series"),
        "currencies": _list_values("price_currency"),
        "regions": _list_values("price_region"),
    }


def get_model_prices(
    conn: sqlite3.Connection,
    *,
    vendor: str | None = None,
    platform: str | None = None,
    model_series: str | None = None,
) -> list[dict]:
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
    rows = conn.execute(
        f"""
        SELECT
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
        """
        ,
        tuple(params),
    ).fetchall()

    return [
        {
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
