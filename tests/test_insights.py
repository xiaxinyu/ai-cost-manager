from __future__ import annotations

from app.insights import (
    InsightCard,
    compute_cost_insights,
    compute_report_insights,
    compute_token_insights,
    insight_cards_to_dicts,
)


def _ids(cards: list[InsightCard]) -> list[str]:
    return [c.id for c in cards]


def test_market_variance_below_market():
    catalog = {
        "available": True,
        "summary": {
            "variance_pct": -12.5,
            "variance_usd": -50.0,
            "total_actual_cost_usd": 350.0,
            "total_catalog_cost_usd": 400.0,
        },
    }
    cards = compute_cost_insights(project="p1", points=[], catalog_market=catalog)
    market = next(c for c in cards if c.id == "market_variance")
    assert market.severity == "info"
    assert "Below Market" in market.title
    assert market.metrics["variance_pct"] == -12.5


def test_market_variance_above_market_watch():
    catalog = {
        "available": True,
        "summary": {
            "variance_pct": 15.0,
            "variance_usd": 30.0,
            "total_actual_cost_usd": 230.0,
            "total_catalog_cost_usd": 200.0,
        },
    }
    cards = compute_cost_insights(project="p1", points=[], catalog_market=catalog)
    market = next(c for c in cards if c.id == "market_variance")
    assert market.severity == "watch"
    assert "Above Market" in market.title


def test_unpriced_models_insight():
    catalog = {"available": True, "unpriced_models": ["gpt-x", "gpt-y"]}
    cards = compute_cost_insights(project="p1", points=[], catalog_market=catalog)
    unpriced = next(c for c in cards if c.id == "unpriced_models")
    assert unpriced.metrics["count"] == 2
    assert unpriced.severity == "watch"


def test_peak_day_and_dod_swing():
    points = [
        {"date": "2026-01-01", "cost_usd": 10.0},
        {"date": "2026-01-02", "cost_usd": 50.0},
        {"date": "2026-01-03", "cost_usd": 5.0},
    ]
    cards = compute_cost_insights(project="p1", points=points, catalog_market=None)
    peak = next(c for c in cards if c.id == "peak_day")
    assert peak.metrics["date"] == "2026-01-02"
    swing = next(c for c in cards if c.id == "largest_dod_swing")
    assert swing.metrics["date"] == "2026-01-02"
    assert swing.metrics["change_pct"] == 400.0


def test_meter_coverage_action():
    payload = {
        "points": [{"date": "2026-01-01", "input_tokens": 100, "output_tokens": 50}],
        "daily_by_model": [{"date": "2026-01-01", "model_name": "m1"}],
        "_cost_meta": {"row_count": 10, "rows_meter_matched": 2, "rows_meter_partial": 1},
        "token_data_source": "imported",
    }
    cards = compute_token_insights(project="p1", payload=payload)
    meter = next(c for c in cards if c.id == "meter_coverage")
    assert meter.severity == "action"
    assert meter.metrics["pct"] == 30.0


def test_token_ratio_insight():
    points = [
        {"date": "2026-01-01", "input_tokens": 100, "output_tokens": 200},
        {"date": "2026-01-02", "input_tokens": 100, "output_tokens": 50},
    ]
    payload = {
        "points": points,
        "daily_by_model": [],
        "token_data_source": "imported",
    }
    cards = compute_token_insights(project="p1", payload=payload)
    ratio = next(c for c in cards if c.id == "token_out_in_ratio")
    assert ratio.metrics["valid_days"] == 2
    assert ratio.metrics["above_1_days"] == 1
    assert ratio.metrics["below_1_days"] == 1


def test_report_concentration_and_volatility():
    report = {
        "daily": {"total_actual": 100.0, "var_actual": 400.0, "avg_actual": 10.0},
        "daily_points": [
            {"date": "2026-01-01", "cost_usd": 5.0},
            {"date": "2026-01-02", "cost_usd": 95.0},
        ],
        "project_breakdown": [
            {"project_name": "alpha", "actual_cost_usd_total": 80.0},
            {"project_name": "beta", "actual_cost_usd_total": 20.0},
        ],
        "catalog_market": {"available": False},
        "has_imported_tokens": False,
        "token_data_source": "estimated",
    }
    cards = compute_report_insights(report)
    assert "concentration_project" in _ids(cards)
    conc = next(c for c in cards if c.id == "concentration_project")
    assert conc.metrics["top_pct"] == 80.0
    assert conc.severity == "watch"
    vol = next(c for c in cards if c.id == "spend_volatility")
    assert vol.metrics["cv_pct"] > 60


def test_missing_token_csv_when_billing_without_import():
    report = {
        "daily": {"total_actual": 50.0},
        "daily_points": [{"date": "2026-01-01", "cost_usd": 50.0}],
        "project_breakdown": [],
        "catalog_market": {"available": False},
        "has_imported_tokens": False,
        "token_data_source": "estimated",
    }
    cards = compute_report_insights(report)
    assert "missing_token_csv" in _ids(cards)


def test_insight_cards_to_dicts_roundtrip():
    card = InsightCard(
        id="test",
        category="spend",
        severity="info",
        title="T",
        summary="S",
        metrics={"x": 1},
        recommendation=None,
    )
    d = insight_cards_to_dicts([card])[0]
    assert d["id"] == "test"
    assert d["metrics"]["x"] == 1
