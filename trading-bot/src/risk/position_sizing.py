"""Position sizing. Size is always derived from stop-loss distance and the
configured max risk per trade — never from conviction, confidence score, or
a desire to "make back" a prior loss."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PositionSizeResult:
    quantity: float
    risked_amount: float
    risk_per_share: float


def fixed_fractional_size(
    equity: float,
    entry_price: float,
    stop_loss: float,
    max_risk_per_trade_pct: float,
) -> PositionSizeResult:
    """Classic fixed-fractional sizing: risk exactly
    `max_risk_per_trade_pct` % of equity, sized off the entry-to-stop
    distance. This is the only place position size is computed — nothing
    downstream may scale it up."""
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    risk_per_share = abs(entry_price - stop_loss)
    if risk_per_share <= 0:
        raise ValueError("stop_loss must differ from entry_price")

    risk_budget = equity * (max_risk_per_trade_pct / 100.0)
    quantity = risk_budget / risk_per_share
    return PositionSizeResult(quantity=quantity, risked_amount=risk_budget, risk_per_share=risk_per_share)


def volatility_adjusted_size(
    equity: float,
    entry_price: float,
    stop_loss: float,
    atr: float,
    max_risk_per_trade_pct: float,
    atr_cap_multiple: float = 3.0,
) -> PositionSizeResult:
    """Same fixed-fractional risk budget, but the effective stop distance is
    floored at `atr_cap_multiple * atr` so a tight/noisy stop can't imply an
    oversized position that gets shaken out by normal volatility."""
    if entry_price <= 0 or atr <= 0:
        raise ValueError("entry_price and atr must be positive")
    raw_distance = abs(entry_price - stop_loss)
    effective_distance = max(raw_distance, atr_cap_multiple * atr * 0.1)

    risk_budget = equity * (max_risk_per_trade_pct / 100.0)
    quantity = risk_budget / effective_distance
    return PositionSizeResult(quantity=quantity, risked_amount=risk_budget, risk_per_share=effective_distance)
