from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.core.domain import IndicatorSnapshot, ScoreBreakdown, StrategySignal, TradeSetup
from src.core.enums import (
    AssetClass, MarketRegime, RejectionReason, Timeframe, TradeDecision, TrendDirection,
)
from src.risk.risk_manager import AccountState, RiskConfig, RiskManager


def _make_snapshot(close=100.0, atr=1.0) -> IndicatorSnapshot:
    return IndicatorSnapshot(
        symbol="AAPL", timeframe=Timeframe.M15, timestamp=datetime.now(timezone.utc),
        close=close, ema_9=close, ema_21=close, ema_50=close, ema_200=close,
        rsi=55.0, macd=0.1, macd_signal=0.05, macd_histogram=0.05, vwap=close,
        atr=atr, bb_upper=close + 2, bb_middle=close, bb_lower=close - 2,
        volume=10000, relative_volume=1.2, nearest_support=close - 5,
        nearest_resistance=close + 5, trend_direction=TrendDirection.UP,
    )


def _make_signal(**overrides) -> StrategySignal:
    snapshot = overrides.pop("snapshot", _make_snapshot())
    defaults = dict(
        symbol="AAPL", asset_class=AssetClass.STOCK, timestamp=datetime.now(timezone.utc),
        direction=TrendDirection.UP, indicator_snapshot=snapshot, related_news=[],
        technical_signals=[], regime=MarketRegime.BULL,
        suggested_stop_loss=snapshot.close - 2, suggested_take_profit=snapshot.close + 4,
    )
    defaults.update(overrides)
    return StrategySignal(**defaults)


def _make_setup(decision=TradeDecision.ENTER_LONG, confidence=80.0, **signal_overrides) -> TradeSetup:
    signal = _make_signal(**signal_overrides)
    breakdown = ScoreBreakdown(80, 80, 80, 80, 80, 80, 80)
    return TradeSetup(
        symbol=signal.symbol, timestamp=signal.timestamp, decision=decision, confidence=confidence,
        score_breakdown=breakdown, entry_price=signal.indicator_snapshot.close,
        stop_loss=signal.suggested_stop_loss, take_profit=signal.suggested_take_profit,
        reasoning="test", strategy_signal=signal,
    )


def _account(equity=100_000.0, **overrides) -> AccountState:
    defaults = dict(
        equity=equity, starting_equity_today=equity, daily_realized_pnl=0.0,
        open_positions_count=0, trades_today_count=0, exposure_by_symbol={},
    )
    defaults.update(overrides)
    return AccountState(**defaults)


@pytest.fixture
def risk_manager() -> RiskManager:
    # Note: max_exposure_per_asset_pct is deliberately generous (60%) here
    # so tests unrelated to the exposure cap (sizing, circuit breaker, kill
    # switch) aren't incidentally blocked by it — a $100 entry with a $2
    # stop and 1% risk sizes to 500 shares ($50,000 notional, 50% of a
    # $100k account), which a realistic 20% cap would legitimately reject.
    # test_max_exposure_per_asset_enforced below exercises the cap directly
    # with its own tighter-than-default account state.
    return RiskManager(RiskConfig(max_risk_per_trade_pct=1.0, max_daily_loss_pct=3.0, max_trades_per_day=10,
                                   max_simultaneous_positions=5, max_exposure_per_asset_pct=60.0,
                                   consecutive_loss_circuit_breaker=3, circuit_breaker_cooldown_minutes=60))


def test_approved_trade_sizes_position_from_stop_distance(risk_manager):
    setup = _make_setup()
    result = risk_manager.evaluate(setup, _account())
    assert result.approved
    # risk budget = 1% of 100k = 1000; stop distance = 2 -> qty = 500
    assert result.max_position_size == pytest.approx(500.0, rel=1e-6)
    assert result.risked_amount == pytest.approx(1000.0, rel=1e-6)


def test_no_trade_decision_is_never_approved(risk_manager):
    setup = _make_setup(decision=TradeDecision.NO_TRADE)
    result = risk_manager.evaluate(setup, _account())
    assert not result.approved


def test_missing_stop_loss_is_rejected(risk_manager):
    signal = _make_signal(suggested_stop_loss=None)
    breakdown = ScoreBreakdown(80, 80, 80, 80, 80, 80, 80)
    setup = TradeSetup(
        symbol=signal.symbol, timestamp=signal.timestamp, decision=TradeDecision.ENTER_LONG, confidence=80.0,
        score_breakdown=breakdown, entry_price=signal.indicator_snapshot.close, stop_loss=None,
        take_profit=signal.suggested_take_profit, reasoning="test", strategy_signal=signal,
    )
    result = risk_manager.evaluate(setup, _account())
    assert not result.approved
    assert result.reason == RejectionReason.NO_VALID_STOP_LOSS


def test_daily_loss_limit_trips_kill_switch(risk_manager):
    setup = _make_setup()
    # daily loss of -3100 on 100k starting equity is 3.1% > 3.0% limit
    account = _account(daily_realized_pnl=-3100.0)
    result = risk_manager.evaluate(setup, account)
    assert not result.approved
    assert result.reason == RejectionReason.DAILY_LOSS_LIMIT_REACHED
    assert risk_manager.circuit_breaker.state.daily_loss_kill_switch_active

    # Even a fresh, otherwise-clean trade is blocked once the switch is tripped.
    result2 = risk_manager.evaluate(setup, _account())
    assert not result2.approved
    assert result2.reason == RejectionReason.DAILY_LOSS_LIMIT_REACHED


def test_max_trades_per_day_enforced(risk_manager):
    setup = _make_setup()
    account = _account(trades_today_count=10)
    result = risk_manager.evaluate(setup, account)
    assert not result.approved
    assert result.reason == RejectionReason.MAX_TRADES_PER_DAY_REACHED


def test_max_simultaneous_positions_enforced(risk_manager):
    setup = _make_setup()
    account = _account(open_positions_count=5)
    result = risk_manager.evaluate(setup, account)
    assert not result.approved
    assert result.reason == RejectionReason.MAX_OPEN_POSITIONS_REACHED


def test_max_exposure_per_asset_enforced(risk_manager):
    setup = _make_setup()
    # already holding $19,900 of AAPL; cap is 20% of 100k = 20,000. Adding
    # the new position (500 shares * $100 = $50,000) blows past the cap.
    account = _account(exposure_by_symbol={"AAPL": 19_900.0})
    result = risk_manager.evaluate(setup, account)
    assert not result.approved
    assert result.reason == RejectionReason.MAX_EXPOSURE_PER_ASSET_REACHED


def test_consecutive_loss_circuit_breaker_trips_and_cools_down(risk_manager):
    now = datetime.now(timezone.utc)
    for _ in range(3):
        risk_manager.record_trade_closed("MSFT", pnl=-10.0, now=now)

    setup = _make_setup()
    result = risk_manager.evaluate(setup, _account(), now=now)
    assert not result.approved
    assert result.reason == RejectionReason.CIRCUIT_BREAKER_ACTIVE

    later = now + timedelta(minutes=61)
    result_after_cooldown = risk_manager.evaluate(setup, _account(), now=later)
    assert result_after_cooldown.approved


def test_no_revenge_trading_symbol_cooldown(risk_manager):
    now = datetime.now(timezone.utc)
    risk_manager.record_trade_closed("AAPL", pnl=-5.0, now=now)

    setup = _make_setup()
    result = risk_manager.evaluate(setup, _account(), now=now + timedelta(minutes=5))
    assert not result.approved
    assert result.reason == RejectionReason.CIRCUIT_BREAKER_ACTIVE

    later = now + timedelta(minutes=31)
    result_after_cooldown = risk_manager.evaluate(setup, _account(), now=later)
    assert result_after_cooldown.approved


def test_position_size_never_scales_up_after_losses(risk_manager):
    """The explicit no-martingale requirement: size must be identical
    before and after a loss, for the same setup and equity."""
    result_before = risk_manager.evaluate(_make_setup(), _account())

    # Record a loss on a different symbol so the post-loss cooldown (a
    # separate, deliberate rule — see test_no_revenge_trading_symbol_cooldown)
    # doesn't block this comparison; we're isolating sizing behavior only.
    risk_manager.record_trade_closed("MSFT", pnl=-500.0)

    result_after = risk_manager.evaluate(_make_setup(), _account())
    assert result_before.max_position_size == pytest.approx(result_after.max_position_size, rel=1e-9)


def test_global_kill_switch_blocks_everything(risk_manager):
    setup = _make_setup()
    risk_manager.emergency_stop("test emergency")
    result = risk_manager.evaluate(setup, _account())
    assert not result.approved
    assert result.reason == RejectionReason.KILL_SWITCH_ACTIVE

    risk_manager.resume_after_emergency_stop()
    result2 = risk_manager.evaluate(setup, _account())
    assert result2.approved


def test_max_risk_per_trade_is_respected_regardless_of_confidence(risk_manager):
    """Risk sizing must be identical for a 99-confidence and a 66-confidence
    setup — confidence never scales size, only the decision to trade at all."""
    high_conf = _make_setup(confidence=99.0)
    low_conf = _make_setup(confidence=66.0)
    r_high = risk_manager.evaluate(high_conf, _account())
    r_low = risk_manager.evaluate(low_conf, _account())
    assert r_high.max_position_size == pytest.approx(r_low.max_position_size, rel=1e-9)
