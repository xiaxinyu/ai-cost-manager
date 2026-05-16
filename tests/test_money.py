from __future__ import annotations

from app.money import round_cost


def test_round_cost_two_decimals() -> None:
    assert round_cost(15.13069572) == 15.13
    assert round_cost(0.004) == 0.0
    assert round_cost(None) is None
