"""Walk-forward testing: split history into rolling train / validation /
out-of-sample windows and require the strategy to prove itself on data it
was never tuned against. This is how we avoid curve-fitting a strategy that
"looks good" only in-sample.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.ai.decision_engine import AIDecisionEngine
from src.backtesting.backtest_engine import BacktestConfig, BacktestEngine, BacktestResult
from src.core.domain import NewsEvent
from src.core.enums import AssetClass, Timeframe
from src.core.exceptions import BacktestConfigError
from src.risk.risk_manager import RiskConfig, RiskManager
from src.strategy.strategy_engine import StrategyEngine


@dataclass
class WalkForwardWindow:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


@dataclass
class WalkForwardResult:
    window: WalkForwardWindow
    result: BacktestResult


def generate_windows(
    index: pd.DatetimeIndex, train_bars: int, test_bars: int, step_bars: int | None = None
) -> list[WalkForwardWindow]:
    step_bars = step_bars or test_bars
    if train_bars + test_bars > len(index):
        raise BacktestConfigError("Not enough historical data for even one walk-forward window")

    windows = []
    start_idx = 0
    while start_idx + train_bars + test_bars <= len(index):
        train_start = index[start_idx]
        train_end = index[start_idx + train_bars - 1]
        test_start = index[start_idx + train_bars]
        test_end = index[start_idx + train_bars + test_bars - 1]
        windows.append(WalkForwardWindow(train_start, train_end, test_start, test_end))
        start_idx += step_bars
    return windows


class WalkForwardRunner:
    """Runs the SAME strategy/decision/risk configuration across every
    out-of-sample window. This module intentionally does not include a
    parameter-search loop that re-fits weights per window — that would be
    exactly the "optimize until it looks good historically" anti-pattern
    the spec warns against. If you add parameter search, only ever tune on
    the `train` slice of each window and evaluate on `test`.
    """

    def __init__(
        self,
        indicator_cfg: dict,
        decision_weights: dict,
        min_confidence_threshold: float,
        risk_config: RiskConfig,
        backtest_config: BacktestConfig | None = None,
    ) -> None:
        self._indicator_cfg = indicator_cfg
        self._decision_weights = decision_weights
        self._min_confidence_threshold = min_confidence_threshold
        self._risk_config = risk_config
        self._backtest_config = backtest_config or BacktestConfig()

    def run(
        self,
        symbol: str,
        asset_class: AssetClass,
        timeframe: Timeframe,
        ohlcv: pd.DataFrame,
        news_events: list[NewsEvent] | None = None,
        train_bars: int = 1000,
        test_bars: int = 250,
        step_bars: int | None = None,
    ) -> list[WalkForwardResult]:
        windows = generate_windows(ohlcv.index, train_bars, test_bars, step_bars)
        results = []

        for window in windows:
            # Only the test slice is ever backtested/scored — the train
            # slice exists to make the intent explicit (and to be used by
            # any future parameter-search step) but is never evaluated.
            test_slice = ohlcv.loc[window.test_start : window.test_end]
            warmup_slice = ohlcv.loc[: window.test_start].iloc[-self._backtest_config.warmup_bars :]
            combined = pd.concat([warmup_slice, test_slice])
            combined = combined[~combined.index.duplicated(keep="first")]

            engine = BacktestEngine(
                strategy_engine=StrategyEngine(self._indicator_cfg),
                decision_engine=AIDecisionEngine(self._decision_weights, self._min_confidence_threshold),
                risk_manager=RiskManager(self._risk_config),
                config=self._backtest_config,
            )
            relevant_news = [e for e in (news_events or []) if window.test_start <= e.published_at <= window.test_end]
            result = engine.run(symbol, asset_class, timeframe, combined, relevant_news)
            results.append(WalkForwardResult(window=window, result=result))

        return results

    @staticmethod
    def aggregate_out_of_sample_metrics(results: list[WalkForwardResult]) -> dict:
        """Combine per-window out-of-sample results into a single summary —
        the number that actually matters, not any single window's luck."""
        if not results:
            return {}
        total_trades = sum(r.result.performance.num_trades for r in results)
        avg_return = sum(r.result.performance.total_return_pct for r in results) / len(results)
        avg_sharpe = sum(r.result.performance.sharpe_ratio for r in results) / len(results)
        avg_max_dd = sum(r.result.performance.max_drawdown_pct for r in results) / len(results)
        win_rate = sum(r.result.performance.win_rate_pct for r in results) / len(results)
        return {
            "num_windows": len(results),
            "total_trades": total_trades,
            "avg_return_pct_per_window": round(avg_return, 3),
            "avg_sharpe_ratio": round(avg_sharpe, 3),
            "avg_max_drawdown_pct": round(avg_max_dd, 3),
            "avg_win_rate_pct": round(win_rate, 2),
        }
