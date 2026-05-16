from __future__ import annotations

import pytest

from app.meter_match import (
    aggregate_billing_rows,
    parse_foundry_meter,
    sum_meter_costs,
    token_model_name,
    token_models_match,
)


@pytest.mark.parametrize(
    "meter,version,family,token_dir,billing_dir,token_model",
    [
        ("5.3 codex inp Gl 1M Tokens", "5.3", "codex", "input", "input", "gpt-5.3-codex"),
        ("5.3 codex opt Gl 1M Tokens", "5.3", "codex", "output", "output", "gpt-5.3-codex"),
        ("5.3 codex cd inp Gl 1M Tokens", "5.3", "codex", "input", "cached_input", "gpt-5.3-codex"),
        ("5.4 inp Gl 1M Tokens", "5.4", None, "input", "input", "gpt-5.4"),
        ("5.4 opt Gl 1M Tokens", "5.4", None, "output", "output", "gpt-5.4"),
        ("5.4 cd inp Gl 1M Tokens", "5.4", None, "input", "cached_input", "gpt-5.4"),
        ("5.3 codex inp GI 1M Tokens", "5.3", "codex", "input", "input", "gpt-5.3-codex"),
    ],
)
def test_parse_foundry_meter_real_patterns(
    meter, version, family, token_dir, billing_dir, token_model
):
    parsed = parse_foundry_meter(meter)
    assert parsed is not None
    assert parsed.version == version
    assert parsed.family == family
    assert parsed.token_direction == token_dir
    assert parsed.billing_direction == billing_dir
    assert parsed.token_model == token_model


def test_sum_meter_costs_by_model_direction():
    rows = [
        ("5.3 codex inp Gl 1M Tokens", 10.0),
        ("5.3 codex cd inp Gl 1M Tokens", 5.0),
        ("5.3 codex opt Gl 1M Tokens", 3.0),
        ("5.4 inp Gl 1M Tokens", 0.05),
    ]
    assert (
        sum_meter_costs(rows, token_model="gpt-5.3-codex", token_direction="input") == pytest.approx(15.0)
    )
    assert (
        sum_meter_costs(rows, token_model="gpt-5.3-codex", token_direction="output") == pytest.approx(3.0)
    )
    assert sum_meter_costs(rows, token_model="gpt-5.4", token_direction="input") == pytest.approx(0.05)


def test_aggregate_billing_rows_cached_input_rolls_to_input_bucket():
    rows = [
        ("2026-05-07", "5.3 codex inp Gl 1M Tokens", 10.0),
        ("2026-05-07", "5.3 codex cd inp Gl 1M Tokens", 5.0),
        ("2026-05-07", "5.3 codex opt Gl 1M Tokens", 3.0),
        ("2026-05-12", "5.4 inp Gl 1M Tokens", 0.05),
        ("2026-05-12", "5.4 opt Gl 1M Tokens", 0.02),
    ]
    agg = aggregate_billing_rows(rows)
    codex = agg["2026-05-07"]["gpt-5.3-codex"]
    assert codex["input"] == pytest.approx(15.0)
    assert codex["output"] == pytest.approx(3.0)
    g54 = agg["2026-05-12"]["gpt-5.4"]
    assert g54["input"] == pytest.approx(0.05)
    assert g54["output"] == pytest.approx(0.02)


def test_token_models_match_fuzzy():
    assert token_models_match("gpt-5.3-codex", "GPT-5.3-Codex")
    assert not token_models_match("gpt-5.3-codex", "gpt-5.4")


def test_token_model_name():
    assert token_model_name(version="5.3", family="codex") == "gpt-5.3-codex"
    assert token_model_name(version="5.4", family=None) == "gpt-5.4"
