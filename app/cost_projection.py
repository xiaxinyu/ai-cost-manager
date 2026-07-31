"""Cost projection from USD/1M rates × daily token volume."""

from __future__ import annotations

from typing import Any


PER_1M = 1_000_000


def _round_cost(n: float) -> float:
    return round(float(n) + 0.0, 2)


def project_daily_cost(
    *,
    rate_in_per_1m: float | None,
    rate_out_per_1m: float | None,
    input_tokens_per_day: float | None,
    output_tokens_per_day: float | None,
    team_size: int | float | None = 1,
) -> dict[str, Any] | None:
    """Mirror of ``AppCostProjection.projectDailyCost`` (USD)."""
    rate_in = float(rate_in_per_1m) if rate_in_per_1m is not None else None
    rate_out = float(rate_out_per_1m) if rate_out_per_1m is not None else None
    in_tok = float(input_tokens_per_day or 0)
    out_tok = float(output_tokens_per_day or 0)
    try:
        team = int(team_size) if team_size is not None else 1
    except (TypeError, ValueError):
        team = 1
    team = max(1, team)
    if rate_in is None and rate_out is None:
        return None
    if in_tok <= 0 and out_tok <= 0:
        return None
    day_input = (
        (in_tok / PER_1M) * rate_in * team if rate_in is not None and in_tok > 0 else 0.0
    )
    day_output = (
        (out_tok / PER_1M) * rate_out * team if rate_out is not None and out_tok > 0 else 0.0
    )
    day = day_input + day_output
    if day < 0:
        return None
    return {
        "day_input": _round_cost(day_input),
        "day_output": _round_cost(day_output),
        "day": _round_cost(day),
        "days_7": _round_cost(day * 7),
        "days_30": _round_cost(day * 30),
        "days_365": _round_cost(day * 365),
        "input_tokens_per_day": in_tok,
        "output_tokens_per_day": out_tok,
        "team_size": team,
        "rate_in_per_1m": rate_in,
        "rate_out_per_1m": rate_out,
    }
