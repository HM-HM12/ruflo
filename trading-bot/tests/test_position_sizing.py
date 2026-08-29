from __future__ import annotations

import pytest

from src.risk.position_sizing import fixed_fractional_size, volatility_adjusted_size


def test_fixed_fractional_size_matches_hand_calculation():
    result = fixed_fractional_size(equity=100_000.0, entry_price=50.0, stop_loss=48.0, max_risk_per_trade_pct=1.0)
    # risk budget = 1000; risk per share = 2 -> qty = 500
    assert result.quantity == pytest.approx(500.0)
    assert result.risked_amount == pytest.approx(1000.0)
    assert result.risk_per_share == pytest.approx(2.0)


def test_fixed_fractional_size_scales_with_risk_pct():
    small = fixed_fractional_size(100_000.0, 50.0, 48.0, max_risk_per_trade_pct=0.5)
    large = fixed_fractional_size(100_000.0, 50.0, 48.0, max_risk_per_trade_pct=2.0)
    assert large.quantity == pytest.approx(small.quantity * 4)


def test_fixed_fractional_size_rejects_zero_distance_stop():
    with pytest.raises(ValueError):
        fixed_fractional_size(100_000.0, 50.0, 50.0, 1.0)


def test_fixed_fractional_size_rejects_non_positive_entry():
    with pytest.raises(ValueError):
        fixed_fractional_size(100_000.0, 0.0, -1.0, 1.0)


def test_volatility_adjusted_size_floors_tight_stops():
    """A stop tighter than the ATR-based floor must not imply an oversized
    position: the effective distance is floored at atr_cap_multiple * atr *
    0.1, so quantity is capped at risk_budget / floor rather than blowing up
    toward risk_budget / raw_distance as the stop gets arbitrarily tight."""
    atr, atr_cap_multiple, risk_budget = 2.0, 3.0, 1_000.0  # 1% of 100k
    floor = atr_cap_multiple * atr * 0.1

    tight_stop = volatility_adjusted_size(equity=100_000.0, entry_price=50.0, stop_loss=49.9, atr=atr, max_risk_per_trade_pct=1.0)
    naive_unfloored_qty = risk_budget / abs(50.0 - 49.9)

    assert tight_stop.risk_per_share == pytest.approx(floor)
    assert tight_stop.quantity == pytest.approx(risk_budget / floor)
    assert tight_stop.quantity < naive_unfloored_qty  # the floor actually did something

    # Once the raw stop distance exceeds the floor, the floor no longer binds.
    wide_stop = volatility_adjusted_size(equity=100_000.0, entry_price=50.0, stop_loss=48.0, atr=atr, max_risk_per_trade_pct=1.0)
    assert wide_stop.risk_per_share == pytest.approx(2.0)


def test_volatility_adjusted_size_rejects_non_positive_atr():
    with pytest.raises(ValueError):
        volatility_adjusted_size(100_000.0, 50.0, 48.0, atr=0.0, max_risk_per_trade_pct=1.0)
