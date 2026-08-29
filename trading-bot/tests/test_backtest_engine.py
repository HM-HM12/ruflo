from __future__ import annotations

from src.ai.decision_engine import AIDecisionEngine
from src.backtesting.backtest_engine import BacktestConfig, BacktestEngine
from src.core.enums import AssetClass, RejectionReason, Timeframe
from src.risk.risk_manager import RiskConfig, RiskManager
from src.strategy.strategy_engine import StrategyEngine


def _build_engine(indicator_cfg, min_confidence=65.0, starting_equity=100_000.0) -> BacktestEngine:
    return BacktestEngine(
        strategy_engine=StrategyEngine(indicator_cfg),
        decision_engine=AIDecisionEngine(min_confidence_threshold=min_confidence),
        risk_manager=RiskManager(RiskConfig(max_risk_per_trade_pct=1.0, max_daily_loss_pct=3.0)),
        config=BacktestConfig(starting_equity=starting_equity, warmup_bars=210),
    )


def test_backtest_runs_end_to_end_on_uptrend(uptrend_ohlcv, indicator_cfg):
    engine = _build_engine(indicator_cfg, min_confidence=50.0)
    result = engine.run("AAPL", AssetClass.STOCK, Timeframe.M15, uptrend_ohlcv)
    assert result.performance.starting_equity == 100_000.0
    assert result.performance.num_trades == len(result.closed_trades)
    # equity curve should be monotonically increasing in length with the loop
    assert not result.equity_curve.empty


def test_backtest_closed_trades_have_positive_quantity_and_valid_prices(uptrend_ohlcv, indicator_cfg):
    engine = _build_engine(indicator_cfg, min_confidence=1.0)
    result = engine.run("AAPL", AssetClass.STOCK, Timeframe.M15, uptrend_ohlcv)
    for trade in result.closed_trades:
        assert trade.quantity > 0
        assert trade.entry_price > 0
        assert trade.exit_price > 0
        assert trade.closed_at >= trade.opened_at


def test_high_confidence_threshold_yields_mostly_no_trade(choppy_ohlcv, indicator_cfg):
    """On genuinely choppy, low-signal data with a strict threshold, the
    engine should reject far more setups than it takes — proof that it can
    say NO_TRADE and isn't forced to always be in the market."""
    engine = _build_engine(indicator_cfg, min_confidence=95.0)
    result = engine.run("AAPL", AssetClass.STOCK, Timeframe.M15, choppy_ohlcv)
    rejected = len(result.journal.rejected_entries())
    executed = len(result.journal.executed_entries())
    assert rejected >= executed
    assert RejectionReason.BELOW_CONFIDENCE_THRESHOLD.value in result.journal.rejection_reason_counts() or executed == 0


def test_backtest_applies_transaction_costs(uptrend_ohlcv, indicator_cfg):
    cheap = _build_engine(indicator_cfg, min_confidence=50.0)
    cheap._config = BacktestConfig(starting_equity=100_000.0, fee_bps=0.0, spread_bps=0.0, slippage_bps=0.0, warmup_bars=210)
    expensive = _build_engine(indicator_cfg, min_confidence=50.0)
    expensive._config = BacktestConfig(starting_equity=100_000.0, fee_bps=50.0, spread_bps=20.0, slippage_bps=20.0, warmup_bars=210)

    result_cheap = cheap.run("AAPL", AssetClass.STOCK, Timeframe.M15, uptrend_ohlcv)
    result_expensive = expensive.run("AAPL", AssetClass.STOCK, Timeframe.M15, uptrend_ohlcv)

    if result_cheap.closed_trades and result_expensive.closed_trades:
        assert result_expensive.performance.ending_equity <= result_cheap.performance.ending_equity


def test_backtest_records_rejected_setups_with_reasons(choppy_ohlcv, indicator_cfg):
    engine = _build_engine(indicator_cfg, min_confidence=99.9)
    result = engine.run("AAPL", AssetClass.STOCK, Timeframe.M15, choppy_ohlcv)
    rejected = result.journal.rejected_entries()
    assert len(rejected) > 0
    assert all(e.rejection_reason is not None for e in rejected)
