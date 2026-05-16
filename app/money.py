"""Monetary amounts: 2 decimal places for all cost-related API values."""

from __future__ import annotations

import math
from typing import Any

COST_DECIMAL_PLACES = 2


def round_cost(value: float | int | None) -> float | None:
    """Round a cost amount to ``COST_DECIMAL_PLACES`` (None stays None)."""
    if value is None:
        return None
    x = float(value)
    if not math.isfinite(x):
        return None
    return round(x, COST_DECIMAL_PLACES)


def round_cost_fields(row: dict[str, Any], *keys: str) -> dict[str, Any]:
    """Return a shallow copy with listed cost keys rounded."""
    out = dict(row)
    for key in keys:
        if key in out and out[key] is not None:
            out[key] = round_cost(out[key])
    return out
