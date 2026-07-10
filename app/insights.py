"""Deterministic cost & token insight cards for dashboards and reports."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class InsightCard:
    id: str
    category: str  # spend | market | token | quality | trend | portfolio
    severity: str  # info | watch | action
    title: str
    summary: str
    metrics: dict[str, Any] = field(default_factory=dict)
    recommendation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fmt_cost(n: float | None) -> str:
    if n is None or not math.isfinite(float(n)):
        return "—"
    return f"{float(n):,.2f}"


def _fmt_pct(n: float | None, digits: int = 1) -> str:
    if n is None or not math.isfinite(float(n)):
        return "—"
    v = float(n)
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.{digits}f}%"


def _safe_float(v: object) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _enrich_daily_points(points: list[dict[str, Any]], *, newest_first: bool = True) -> list[dict[str, Any]]:
    rows = [
        {"date": str(p.get("date") or ""), "cost_usd": _safe_float(p.get("cost_usd")) or 0.0}
        for p in points or []
        if p.get("date")
    ]
    ordered = sorted(rows, key=lambda r: r["date"], reverse=newest_first)
    total = sum(r["cost_usd"] for r in ordered)
    out: list[dict[str, Any]] = []
    for i, r in enumerate(ordered):
        share = (r["cost_usd"] / total * 100.0) if total > 0 else None
        if newest_first:
            prior = ordered[i + 1] if i + 1 < len(ordered) else None
        else:
            prior = ordered[i - 1] if i > 0 else None
        change_pct = None
        if prior and prior["cost_usd"] > 0:
            change_pct = (r["cost_usd"] - prior["cost_usd"]) / prior["cost_usd"] * 100.0
        out.append({**r, "share_pct": share, "change_pct": change_pct})
    return out


def _ratio_stats_from_points(points: list[dict[str, Any]]) -> dict[str, Any]:
    ratios: list[float] = []
    for p in points or []:
        inp = _safe_float(p.get("input_tokens") or p.get("estimated_input_tokens"))
        out = _safe_float(p.get("output_tokens") or p.get("estimated_output_tokens"))
        if inp and inp > 0 and out is not None:
            ratios.append(out / inp)
    valid = len(ratios)
    if not valid:
        return {"valid_days": 0, "above_1_days": 0, "below_1_days": 0, "min": None, "max": None}
    above = sum(1 for v in ratios if v > 1.0)
    below = sum(1 for v in ratios if v < 1.0)
    return {
        "valid_days": valid,
        "above_1_days": above,
        "below_1_days": below,
        "min": min(ratios),
        "max": max(ratios),
    }


def _append(cards: list[InsightCard], card: InsightCard | None) -> None:
    if card is not None:
        cards.append(card)


def _market_variance_insight(catalog: dict[str, Any] | None) -> InsightCard | None:
    if not catalog or catalog.get("available") is not True:
        return None
    summary = catalog.get("summary") or {}
    v_pct = _safe_float(summary.get("variance_pct"))
    v_usd = _safe_float(summary.get("variance_usd"))
    actual = _safe_float(summary.get("total_actual_cost_usd"))
    market = _safe_float(summary.get("total_catalog_cost_usd"))
    if v_pct is None and v_usd is None:
        return None
    if v_pct is not None and v_pct < -5:
        severity = "info"
        title = "Below list price"
        summary = (
            f"OpEx {_fmt_cost(actual)} is {_fmt_pct(v_pct)} vs list price {_fmt_cost(market)} "
            f"({_fmt_cost(v_usd)} gap)."
        )
    elif v_pct is not None and v_pct > 5:
        severity = "watch"
        title = "Above list price"
        summary = (
            f"OpEx {_fmt_cost(actual)} exceeds list price {_fmt_cost(market)} by {_fmt_pct(v_pct)} "
            f"({_fmt_cost(v_usd)})."
        )
    else:
        severity = "info"
        title = "Aligned with list price"
        summary = f"OpEx {_fmt_cost(actual)} vs list price {_fmt_cost(market)} ({_fmt_pct(v_pct)})."
    return InsightCard(
        id="market_variance",
        category="market",
        severity=severity,
        title=title,
        summary=summary,
        metrics={
            "variance_pct": v_pct,
            "variance_usd": v_usd,
            "actual_usd": actual,
            "market_usd": market,
        },
    )


def _unpriced_models_insight(catalog: dict[str, Any] | None) -> InsightCard | None:
    if not catalog or catalog.get("available") is not True:
        return None
    unpriced = catalog.get("unpriced_models") or []
    if not unpriced:
        return None
    n = len(unpriced)
    sample = ", ".join(str(m) for m in unpriced[:3])
    more = f" +{n - 3} more" if n > 3 else ""
    return InsightCard(
        id="unpriced_models",
        category="market",
        severity="watch" if n >= 2 else "info",
        title="Models without list price",
        summary=f"{n} model(s) lack catalog USD/1M — list-price totals exclude them ({sample}{more}).",
        metrics={"count": n, "models": unpriced[:8]},
        recommendation="Add or sync prices in Price catalog for complete list-price comparison.",
    )


def _meter_coverage_insight(cost_meta: dict[str, Any] | None) -> InsightCard | None:
    if not cost_meta:
        return None
    total = int(cost_meta.get("row_count") or 0)
    if total <= 0:
        return None
    matched = int(cost_meta.get("rows_meter_matched") or 0) + int(
        cost_meta.get("rows_meter_partial") or 0
    )
    pct = matched / total * 100.0
    severity = "info" if pct >= 80 else ("watch" if pct >= 50 else "action")
    return InsightCard(
        id="meter_coverage",
        category="quality",
        severity=severity,
        title="Meter match coverage",
        summary=f"{matched}/{total} model-days ({pct:.0f}%) have meter-matched OpEx cost.",
        metrics={"matched": matched, "total": total, "pct": round(pct, 1)},
        recommendation=None if pct >= 80 else "Review billing meters or model names on unmatched rows.",
    )


def _peak_day_insight(daily_points: list[dict[str, Any]]) -> InsightCard | None:
    enriched = _enrich_daily_points(daily_points)
    if not enriched:
        return None
    peak = max(enriched, key=lambda r: r["cost_usd"])
    if peak["cost_usd"] <= 0:
        return None
    return InsightCard(
        id="peak_day",
        category="trend",
        severity="info",
        title="Peak billing day",
        summary=(
            f"{peak['date']}: {_fmt_cost(peak['cost_usd'])} "
            f"({_fmt_pct(peak.get('share_pct'))} of period Actual)."
        ),
        metrics={
            "date": peak["date"],
            "cost_usd": peak["cost_usd"],
            "share_pct": peak.get("share_pct"),
        },
    )


def _largest_dod_swing_insight(daily_points: list[dict[str, Any]]) -> InsightCard | None:
    enriched = _enrich_daily_points(daily_points)
    swings = [
        r for r in enriched if r.get("change_pct") is not None and math.isfinite(r["change_pct"])
    ]
    if not swings:
        return None
    top = max(swings, key=lambda r: abs(r["change_pct"]))
    if abs(top["change_pct"]) < 25:
        return None
    severity = "watch" if abs(top["change_pct"]) >= 50 else "info"
    return InsightCard(
        id="largest_dod_swing",
        category="trend",
        severity=severity,
        title="Largest day-over-day swing",
        summary=f"{top['date']}: {_fmt_pct(top['change_pct'])} vs prior day ({_fmt_cost(top['cost_usd'])}).",
        metrics={"date": top["date"], "change_pct": top["change_pct"], "cost_usd": top["cost_usd"]},
    )


def _concentration_insight(
    breakdown: list[dict[str, Any]],
    *,
    label_key: str = "project_name",
    value_key: str = "actual_cost_usd_total",
    scope: str = "project",
) -> InsightCard | None:
    rows = [
        {
            "name": str(r.get(label_key) or ""),
            "value": _safe_float(r.get(value_key)) or 0.0,
        }
        for r in breakdown or []
        if r.get(label_key)
    ]
    rows = [r for r in rows if r["value"] > 0]
    if not rows:
        return None
    rows.sort(key=lambda r: r["value"], reverse=True)
    total = sum(r["value"] for r in rows)
    top1_pct = rows[0]["value"] / total * 100.0 if total > 0 else 0
    top3_pct = sum(r["value"] for r in rows[:3]) / total * 100.0 if total > 0 else 0
    severity = "watch" if top1_pct > 50 or top3_pct > 80 else "info"
    return InsightCard(
        id=f"concentration_{scope}",
        category="spend",
        severity=severity,
        title=f"{scope.capitalize()} concentration",
        summary=(
            f"Top {scope} {rows[0]['name']} is {top1_pct:.1f}% of Actual "
            f"({_fmt_cost(rows[0]['value'])} of {_fmt_cost(total)})."
        ),
        metrics={
            "top_name": rows[0]["name"],
            "top_pct": round(top1_pct, 1),
            "top3_pct": round(top3_pct, 1),
            "total_usd": total,
        },
    )


def _billing_other_insight(catalog: dict[str, Any] | None) -> InsightCard | None:
    if not catalog or catalog.get("available") is not True:
        return None
    summary = catalog.get("summary") or {}
    other = _safe_float(summary.get("billing_other_usd"))
    billing = _safe_float(summary.get("total_actual_cost_usd"))
    meter = _safe_float(summary.get("total_meter_cost_usd"))
    if other is None or other <= 0.5 or billing is None or meter is None:
        return None
    share = other / billing * 100.0 if billing > 0 else 0.0
    return InsightCard(
        id="billing_other",
        category="quality",
        severity="info" if share < 35 else "watch",
        title="Non-model billing",
        summary=(
            f"{_fmt_cost(other)} ({share:.0f}%) of Actual is outside token meter match "
            f"({_fmt_cost(meter)} matched vs {_fmt_cost(billing)} total billing)."
        ),
        metrics={
            "billing_other_usd": other,
            "total_billing_usd": billing,
            "meter_matched_usd": meter,
            "share_pct": round(share, 1),
        },
        recommendation="Defender, networking, Bing, or unmatched meters — see billing CSV.",
    )


def _model_concentration_from_catalog(catalog: dict[str, Any] | None) -> InsightCard | None:
    if not catalog or catalog.get("available") is not True:
        return None
    models = catalog.get("model_summary") or []
    return _concentration_insight(
        [
            {
                "project_name": m.get("model_name"),
                "actual_cost_usd_total": m.get("actual_cost_usd"),
            }
            for m in models
        ],
        label_key="project_name",
        scope="model",
    )


def _io_cost_skew_insight(catalog: dict[str, Any] | None) -> InsightCard | None:
    if not catalog or catalog.get("available") is not True:
        return None
    summary = catalog.get("summary") or {}
    inp = _safe_float(summary.get("total_input_cost_usd"))
    out = _safe_float(summary.get("total_output_cost_usd"))
    if inp is None and out is None:
        return None
    tin = inp or 0.0
    tout = out or 0.0
    total = tin + tout
    if total <= 0:
        return None
    out_pct = tout / total * 100.0
    if out_pct < 70 and out_pct > 30:
        return None
    severity = "watch" if out_pct >= 70 else "info"
    lean = "output-heavy" if out_pct >= 70 else "input-heavy"
    return InsightCard(
        id="io_cost_skew",
        category="spend",
        severity=severity,
        title="Input vs output cost mix",
        summary=(
            f"Actual split: in {_fmt_cost(tin)} ({100 - out_pct:.0f}%) · "
            f"out {_fmt_cost(tout)} ({out_pct:.0f}%) — {lean} billing."
        ),
        metrics={"input_usd": tin, "output_usd": tout, "output_pct": round(out_pct, 1)},
    )


def _token_ratio_insight(points: list[dict[str, Any]]) -> InsightCard | None:
    stats = _ratio_stats_from_points(points)
    if stats["valid_days"] == 0:
        return None
    rmin = stats["min"]
    rmax = stats["max"]
    span = ""
    if rmin is not None and rmax is not None:
        span = f" · range {rmin:.3f}–{rmax:.3f}"
    severity = "watch" if stats["below_1_days"] == stats["valid_days"] and stats["valid_days"] >= 5 else "info"
    return InsightCard(
        id="token_out_in_ratio",
        category="token",
        severity=severity,
        title="Output / input ratio",
        summary=(
            f"{stats['valid_days']} valid days: >1: {stats['above_1_days']} · "
            f"<1: {stats['below_1_days']}{span}."
        ),
        metrics=stats,
    )


def _missing_token_csv_insight(
    *,
    has_billing: bool,
    token_data_source: str | None,
    project: str | None = None,
) -> InsightCard | None:
    if not has_billing or token_data_source == "imported":
        return None
    proj = f" for {project}" if project else ""
    return InsightCard(
        id="missing_token_csv",
        category="quality",
        severity="watch",
        title="No imported token CSV",
        summary=(
            f"Billing exists{proj} but token CSV is missing — list-price and $/1M insights need "
            "bills/<project>/token/ imports."
        ),
        metrics={"token_data_source": token_data_source},
        recommendation="Import token CSV via Import page to unlock token and list-price analysis.",
    )


def _unit_price_drift_insight(daily_by_model: list[dict[str, Any]]) -> InsightCard | None:
    """Latest meter $/1M vs catalog for models with both."""
    by_model: dict[str, dict[str, Any]] = {}
    for row in daily_by_model or []:
        name = str(row.get("model_name") or "")
        if not name:
            continue
        d = str(row.get("date") or "")
        cur = by_model.get(name)
        if cur is None or d > str(cur.get("date") or ""):
            by_model[name] = row
    drifts: list[tuple[str, float | None, float | None]] = []
    for name, row in by_model.items():
        cin = _safe_float(row.get("usd_per_1m_input"))
        cout = _safe_float(row.get("usd_per_1m_output"))
        mkin = _safe_float(row.get("catalog_usd_per_1m_input"))
        mkout = _safe_float(row.get("catalog_usd_per_1m_output"))
        pin = None
        pout = None
        if cin is not None and mkin and mkin > 0:
            pin = (cin - mkin) / mkin * 100.0
        if cout is not None and mkout and mkout > 0:
            pout = (cout - mkout) / mkout * 100.0
        if pin is not None or pout is not None:
            drifts.append((name, pin, pout))
    if not drifts:
        return None
    drifts.sort(key=lambda x: min(abs(x[1] or 0), abs(x[2] or 0)), reverse=True)
    name, pin, pout = drifts[0]
    bits = []
    if pin is not None:
        bits.append(f"in {_fmt_pct(pin, 0)}")
    if pout is not None:
        bits.append(f"out {_fmt_pct(pout, 0)}")
    return InsightCard(
        id="unit_price_drift",
        category="market",
        severity="info",
        title="Unit price vs list price",
        summary=f"Latest {name}: {' · '.join(bits)} vs catalog list price USD/1M.",
        metrics={"model": name, "in_pct": pin, "out_pct": pout, "models_compared": len(drifts)},
    )


def _spend_volatility_insight(daily_stats: dict[str, Any] | None) -> InsightCard | None:
    if not daily_stats:
        return None
    var_a = _safe_float(daily_stats.get("var_actual"))
    avg = _safe_float(daily_stats.get("avg_actual"))
    if var_a is None or avg is None or avg <= 0:
        return None
    cv = math.sqrt(var_a) / avg * 100.0
    severity = "watch" if cv > 60 else "info"
    return InsightCard(
        id="spend_volatility",
        category="spend",
        severity=severity,
        title="Daily spend volatility",
        summary=f"Population variance {_fmt_cost(var_a)} · CV ~{cv:.0f}% of mean daily Actual.",
        metrics={"variance": var_a, "avg": avg, "cv_pct": round(cv, 1)},
    )


def insight_cards_to_dicts(cards: list[InsightCard]) -> list[dict[str, Any]]:
    return [c.to_dict() for c in cards]


def compute_cost_insights(
    *,
    project: str,
    points: list[dict[str, Any]] | None,
    catalog_market: dict[str, Any] | None,
) -> list[InsightCard]:
    cards: list[InsightCard] = []
    daily = points or []
    has_billing = any((_safe_float(p.get("cost_usd")) or 0) > 0 for p in daily)

    _append(cards, _market_variance_insight(catalog_market))
    _append(cards, _billing_other_insight(catalog_market))
    _append(cards, _unpriced_models_insight(catalog_market))
    _append(cards, _model_concentration_from_catalog(catalog_market))
    _append(cards, _io_cost_skew_insight(catalog_market))
    _append(cards, _peak_day_insight(daily))
    _append(cards, _largest_dod_swing_insight(daily))

    if catalog_market:
        src = catalog_market.get("token_data_source")
        _append(
            cards,
            _missing_token_csv_insight(
                has_billing=has_billing,
                token_data_source=str(src) if src else None,
                project=project,
            ),
        )

    return cards[:7]


def _latest_metric_point(metric: dict[str, Any] | None) -> dict[str, Any] | None:
    if not metric:
        return None
    pts = metric.get("points") or []
    return pts[0] if pts else None


def _metric_model_values(point: dict[str, Any] | None) -> dict[str, float]:
    if not point:
        return {}
    out: dict[str, float] = {}
    for k, v in (point.get("values") or {}).items():
        fv = _safe_float(v)
        if fv is not None:
            out[str(k)] = fv
    return out


def _perf_cache_insight(token_metrics: dict[str, Any] | None) -> InsightCard | None:
    if not token_metrics or token_metrics.get("available") is not True:
        return None
    cache = (token_metrics.get("metrics") or {}).get("cache_match_rate")
    latest = _latest_metric_point(cache)
    vals = _metric_model_values(latest)
    if not vals:
        return None
    ranked = sorted(vals.items(), key=lambda x: x[1], reverse=True)
    best_model, best_pct = ranked[0]
    worst_model, worst_pct = ranked[-1]
    active = [m for m, v in vals.items() if v > 0]
    if not active:
        return InsightCard(
            id="perf_cache_zero",
            category="quality",
            severity="watch",
            title="Cache match rate at zero",
            summary=(
                f"Latest bucket ({latest.get('usage_date') or '—'}): all models report 0% cache match. "
                "Prompt caching may be unused or not exported in metrics."
            ),
            metrics={"usage_date": latest.get("usage_date"), "models": list(vals.keys())},
            recommendation="Review prompt design for cacheable prefixes; confirm metrics CSV covers cached tokens.",
        )
    if best_pct < 5.0:
        return InsightCard(
            id="perf_cache_low",
            category="quality",
            severity="watch",
            title="Low cache match rate",
            summary=(
                f"Latest: best {best_model} at {best_pct:.2f}% · lowest {worst_model} at {worst_pct:.2f}%. "
                "Caching headroom may reduce input-token cost."
            ),
            metrics={"best_model": best_model, "best_pct": best_pct, "worst_pct": worst_pct},
            recommendation="Stabilize system prompts and reuse context blocks to lift cache hit rate.",
        )
    return InsightCard(
        id="perf_cache_leader",
        category="quality",
        severity="info",
        title="Cache match leader",
        summary=(
            f"Latest: {best_model} leads at {best_pct:.2f}% · spread to {worst_model} ({worst_pct:.2f}%)."
        ),
        metrics={"best_model": best_model, "best_pct": best_pct, "worst_model": worst_model, "worst_pct": worst_pct},
    )


def _perf_latency_insight(token_metrics: dict[str, Any] | None) -> InsightCard | None:
    if not token_metrics or token_metrics.get("available") is not True:
        return None
    lat = (token_metrics.get("metrics") or {}).get("avg_latency")
    latest = _latest_metric_point(lat)
    vals = _metric_model_values(latest)
    active = {m: v for m, v in vals.items() if v > 0}
    if not active:
        return None
    ranked = sorted(active.items(), key=lambda x: x[1], reverse=True)
    slow_model, slow_ms = ranked[0]
    fast_model, fast_ms = ranked[-1]
    severity = "watch" if slow_ms >= 30_000 else "info"
    ratio = slow_ms / fast_ms if fast_ms > 0 else None
    ratio_txt = f" · {ratio:.1f}× vs fastest ({fast_model})" if ratio and ratio > 1.5 else ""
    return InsightCard(
        id="perf_latency_spread",
        category="quality",
        severity=severity,
        title="Latency spread by model",
        summary=(
            f"Latest avg latency: {slow_model} {slow_ms:,.0f} ms (slowest){ratio_txt} · "
            f"fastest {fast_model} {fast_ms:,.0f} ms."
        ),
        metrics={"slow_model": slow_model, "slow_ms": slow_ms, "fast_model": fast_model, "fast_ms": fast_ms},
        recommendation="Shift latency-sensitive traffic toward faster models when quality allows.",
    )


def _perf_requests_insight(token_metrics: dict[str, Any] | None) -> InsightCard | None:
    if not token_metrics or token_metrics.get("available") is not True:
        return None
    req = (token_metrics.get("metrics") or {}).get("model_requests")
    latest = _latest_metric_point(req)
    vals = _metric_model_values(latest)
    total = sum(vals.values())
    if total <= 0:
        return None
    ranked = sorted(vals.items(), key=lambda x: x[1], reverse=True)
    top_model, top_n = ranked[0]
    share = top_n / total * 100.0
    severity = "watch" if share >= 70 and len(ranked) > 1 else "info"
    others = ", ".join(f"{m} {n:,.0f}" for m, n in ranked[1:3])
    tail = f" · also {others}" if others else ""
    return InsightCard(
        id="perf_request_mix",
        category="trend",
        severity=severity,
        title="Request volume concentration",
        summary=(
            f"Latest bucket: {top_model} {top_n:,.0f} requests ({share:.0f}% of {total:,.0f} total){tail}."
        ),
        metrics={"top_model": top_model, "top_share_pct": round(share, 1), "total_requests": total},
        recommendation="High concentration increases blast radius — validate capacity and fallback models.",
    )


def _perf_cost_link_insight(
    token_metrics: dict[str, Any] | None,
    daily_by_model: list[dict[str, Any]] | None,
) -> InsightCard | None:
    """Link high-traffic models to token cost share when both datasets exist."""
    if not token_metrics or token_metrics.get("available") is not True:
        return None
    req = (token_metrics.get("metrics") or {}).get("model_requests")
    latest = _latest_metric_point(req)
    req_vals = _metric_model_values(latest)
    if not req_vals or not daily_by_model:
        return None
    by_model_cost: dict[str, float] = {}
    for row in daily_by_model:
        name = str(row.get("model_name") or "")
        if not name:
            continue
        cost = _safe_float(row.get("cost_usd")) or 0.0
        by_model_cost[name] = by_model_cost.get(name, 0.0) + cost
    if not by_model_cost:
        return None
    total_cost = sum(by_model_cost.values())
    if total_cost <= 0:
        return None
    top_req_model = max(req_vals.items(), key=lambda x: x[1])[0]
    req_share = req_vals[top_req_model] / sum(req_vals.values()) * 100.0
    cost_share = by_model_cost.get(top_req_model, 0.0) / total_cost * 100.0
    if cost_share < 1 and req_share > 40:
        return InsightCard(
            id="perf_cost_request_skew",
            category="spend",
            severity="watch",
            title="Traffic vs spend mismatch",
            summary=(
                f"{top_req_model} drives {req_share:.0f}% of latest requests but only "
                f"{cost_share:.0f}% of meter cost in range — check token mix and pricing tier."
            ),
            metrics={
                "model": top_req_model,
                "request_share_pct": round(req_share, 1),
                "cost_share_pct": round(cost_share, 1),
            },
        )
    top_cost_model = max(by_model_cost.items(), key=lambda x: x[1])[0]
    if top_cost_model == top_req_model:
        return InsightCard(
            id="perf_cost_request_aligned",
            category="spend",
            severity="info",
            title="Top traffic aligns with top spend",
            summary=(
                f"{top_req_model} is both the busiest model (latest requests) and largest cost driver "
                f"({cost_share:.0f}% of range spend) — optimize here first."
            ),
            metrics={"model": top_req_model, "cost_share_pct": round(cost_share, 1)},
            recommendation="Tune cache rate and latency for this model before smaller models.",
        )
    return InsightCard(
        id="perf_cost_request_split",
        category="spend",
        severity="info",
        title="Cost vs traffic split",
        summary=(
            f"Latest requests peak on {top_req_model} ({req_share:.0f}%) but spend leader is "
            f"{top_cost_model} ({by_model_cost[top_cost_model] / total_cost * 100:.0f}% of cost)."
        ),
        metrics={
            "top_request_model": top_req_model,
            "top_cost_model": top_cost_model,
        },
        recommendation="Compare $/1M and output ratio between these models when rightsizing.",
    )


def compute_performance_insights(
    *,
    token_metrics: dict[str, Any] | None,
    daily_by_model: list[dict[str, Any]] | None = None,
) -> list[InsightCard]:
    cards: list[InsightCard] = []
    _append(cards, _perf_cache_insight(token_metrics))
    _append(cards, _perf_latency_insight(token_metrics))
    _append(cards, _perf_requests_insight(token_metrics))
    _append(cards, _perf_cost_link_insight(token_metrics, daily_by_model))
    return cards[:4]


def compute_token_insights(
    *,
    project: str,
    payload: dict[str, Any],
    catalog_market: dict[str, Any] | None = None,
) -> list[InsightCard]:
    cards: list[InsightCard] = []
    points = payload.get("points") or []
    daily_by_model = payload.get("daily_by_model") or []
    cost_meta = payload.get("_cost_meta")
    token_source = payload.get("token_data_source")
    token_metrics = payload.get("token_metrics")

    _append(cards, _meter_coverage_insight(cost_meta))
    _append(
        cards,
        _missing_token_csv_insight(
            has_billing=bool(daily_by_model or points),
            token_data_source=str(token_source) if token_source else None,
            project=project,
        ),
    )
    _append(cards, _token_ratio_insight(points))
    _append(cards, _unit_price_drift_insight(daily_by_model))
    _append(cards, _market_variance_insight(catalog_market))
    _append(cards, _unpriced_models_insight(catalog_market))
    for perf in compute_performance_insights(
        token_metrics=token_metrics if isinstance(token_metrics, dict) else None,
        daily_by_model=daily_by_model,
    ):
        _append(cards, perf)

    return cards[:9]


def compute_report_insights(report: dict[str, Any]) -> list[InsightCard]:
    cards: list[InsightCard] = []
    daily = report.get("daily") or {}
    daily_points = report.get("daily_points") or []
    catalog = report.get("catalog_market")
    breakdown = report.get("project_breakdown") or []
    token_actual = report.get("token_actual") or {}
    token_points = report.get("token_daily_points") or []
    has_imported = report.get("has_imported_tokens") is True

    _append(cards, _concentration_insight(breakdown, scope="project"))
    _append(cards, _market_variance_insight(catalog))
    _append(cards, _unpriced_models_insight(catalog))
    _append(cards, _model_concentration_from_catalog(catalog))
    _append(cards, _io_cost_skew_insight(catalog))
    _append(cards, _spend_volatility_insight(daily))
    _append(cards, _peak_day_insight(daily_points))
    _append(cards, _largest_dod_swing_insight(daily_points))

    if has_imported:
        _append(cards, _token_ratio_insight(token_points))
        inp = _safe_float(token_actual.get("input_tokens_total"))
        out = _safe_float(token_actual.get("output_tokens_total"))
        if inp and inp > 0 and out is not None:
            ratio = out / inp
            cards.append(
                InsightCard(
                    id="portfolio_token_volume",
                    category="token",
                    severity="info",
                    title="Imported token volume",
                    summary=(
                        f"{int(token_actual.get('projects_with_imported_tokens') or 0)} projects · "
                        f"in {inp:,.0f} · out {out:,.0f} tokens (out/in {ratio:.3f})."
                    ),
                    metrics={
                        "input_tokens": inp,
                        "output_tokens": out,
                        "ratio": ratio,
                    },
                )
            )
    else:
        _append(
            cards,
            _missing_token_csv_insight(
                has_billing=(_safe_float(daily.get("total_actual")) or 0) > 0,
                token_data_source=report.get("token_data_source"),
            ),
        )

    # Deduplicate by id while preserving order
    seen: set[str] = set()
    unique: list[InsightCard] = []
    for c in cards:
        if c.id in seen:
            continue
        seen.add(c.id)
        unique.append(c)
    return unique[:7]
