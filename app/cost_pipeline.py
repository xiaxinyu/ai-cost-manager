"""Cost ↔ token matching pipeline version and debug traces."""

from __future__ import annotations

import logging
import os
from typing import Any

COST_PIPELINE_VERSION = "20260517-meter-sum-v2"

_log = logging.getLogger("app.cost_pipeline")
_logging_ready = False


def cost_debug_enabled() -> bool:
    return os.environ.get("COST_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}


def _ensure_cost_logging() -> None:
    global _logging_ready
    if _logging_ready or not cost_debug_enabled():
        return
    _logging_ready = True
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    _log.addHandler(handler)
    _log.setLevel(logging.INFO)
    _log.propagate = False


def log_cost_step(message: str, *args: Any) -> None:
    if cost_debug_enabled():
        _ensure_cost_logging()
        _log.info(message, *args)


def summarize_daily_cost_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    with_cost = sum(
        1
        for r in rows
        if r.get("input_cost_usd") is not None or r.get("output_cost_usd") is not None
    )
    meter_matched = sum(1 for r in rows if r.get("allocation_method") == "meter_matched")
    return {
        "pipeline_version": COST_PIPELINE_VERSION,
        "row_count": total,
        "rows_with_cost": with_cost,
        "rows_meter_matched": meter_matched,
        "rows_missing_cost": total - with_cost,
    }
