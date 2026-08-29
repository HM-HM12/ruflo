"""Backtesting engine.

No-look-ahead guarantee: at simulated timestamp T, the strategy engine only
ever sees bars with timestamp <= T (`df.loc[:T]`), and news events are
filtered to `published_at <= T`. Stops/targets are checked against the
*next* bar's high/low — a signal generated on bar N can only be acted on
starting at bar N+1's open, exactly as in live trading where you can't fill
against the bar that produced the signal.

Includes transaction fees, spread, and slippage so results aren't
unrealistically clean, and routes every proposed trade through the same
RiskManager used in live/paper trading (identical position sizing and veto
logic — no separate, more lenient backtest-only risk path).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from src.ai.decision_engine import AIDecisionEngine
from src.backtesting.performance_metrics import ClosedTrade, PerformanceReport, compute_performance_report
from src.core.domain import Fill, NewsEvent
from src.core.enums import AssetClass, OrderSide, Timeframe, TradeDecision
from src.journal.trade_journal import TradeJournal
from src.portfolio.portfolio_manager import PortfolioManager
from src.risk.risk_manager import RiskManager
from src.strategy.strategy_engine import StrategyEngine


@dataclass
class BacktestConfig:
    starting_equity: float = 100_000.0
    fee_bps: float = 5.0       # round-trip transaction cost, in basis points of notional
    spread_bps: float = 2.0    # bid/ask spread cost applied on entry and exit
    slippage_bps: float = 3.0  # additional adverse price movement on fill
    warmup_bars: int = 210     # bars needed before indicators (EMA200 etc.) are valid


@dataclass
class BacktestResult:
    performance: PerformanceReport
    closed_trades: list[ClosedTrade]
    journal: TradeJournal
    equity_curve: pd.Series


class BacktestEngine:
    def __init__(
        self,
        strategy_engine: StrategyEngine,
        decision_engine: AIDecisionEngine,
        risk_manager: RiskManager,
        config: BacktestConfig | None = None,
    ) -> None:
        self._strategy_engine = strategy_engine
        self._decision_engine = decision_engine
        self._risk_manager = risk_manager
        self._config = config or BacktestConfig()

    def _apply_cost(self, price: float, side: OrderSide) -> float:
        """Apply spread + slippage as an adverse move relative to the
        reference price, in the direction that always hurts the trader."""
        total_bps = self._config.spread_bps + self._config.slippage_bps
        direction = 1 if side == OrderSide.BUY else -1
        return price * (1 + direction * total_bps / 10_000)

    def _fee(self, notional: float) -> float:
        return notional * (self._config.fee_bps / 10_000)

    def run(
        self,
        symbol: str,
        asset_class: AssetClass,
        timeframe: Timeframe,
        ohlcv: pd.DataFrame,
        news_events: list[NewsEvent] | None = None,
    ) -> BacktestResult:
        """Run a single-symbol backtest over the full length of `ohlcv`.
        `ohlcv` must be sorted ascending by timestamp and contain no gaps
        the strategy wouldn't have seen live (i.e., already point-in-time
        correct data from the provider)."""
        news_events = news_events or []
        portfolio = PortfolioManager(starting_equity=self._config.starting_equity)
        journal = TradeJournal()
        closed_trades: list[ClosedTrade] = []

        cfg = self._config
        n = len(ohlcv)

        # Compute indicators ONCE over the whole series rather than
        # recomputing the full indicator set (including an O(n)
        # support/resistance scan) from scratch on every bar — that
        # previously made a full backtest O(n^2). Every indicator in
        # compute_all is strictly causal, so slicing the precomputed frame
        # up to bar i is equivalent to having computed it on that slice
        # alone (see tests/test_indicators.py's no-look-ahead regression
        # tests, and StrategyEngine.enrich's docstring).
        enriched_full = self._strategy_engine.enrich(ohlcv)

        for i in range(cfg.warmup_bars, n - 1):
            window = enriched_full.iloc[: i + 1]
            current_ts = window.index[-1]
            next_bar = ohlcv.iloc[i + 1]

            relevant_news = [e for e in news_events if e.published_at <= current_ts]
            active_news = any((current_ts - e.published_at).total_seconds() <= 3600 for e in relevant_news)

            # --- manage existing position: check stop/target on the NEXT bar ---
            if portfolio.has_open_position(symbol):
                self._process_exit(symbol, portfolio, next_bar, closed_trades)

            # --- generate a new signal off data through `current_ts` ---
            signal = self._strategy_engine.build_signal_from_enriched(
                symbol=symbol, asset_class=asset_class, timeframe=timeframe,
                enriched=window, related_news=relevant_news, active_news_event=active_news,
            )
            setup = self._decision_engine.evaluate(signal)

            mark_prices = {symbol: window["close"].iloc[-1]}
            account = portfolio.account_state(mark_prices)

            risk_result = None
            if setup.decision != TradeDecision.NO_TRADE and not portfolio.has_open_position(symbol):
                risk_result = self._risk_manager.evaluate(setup, account, now=current_ts.to_pydatetime())
                if risk_result.approved:
                    self._process_entry(setup, risk_result.max_position_size, portfolio, next_bar, current_ts)

            journal.record_decision(setup, risk_result)
            portfolio.mark_to_market({symbol: next_bar["close"]}, now=_as_datetime(next_bar.name))

        # close any position still open at the end of the backtest window
        if portfolio.has_open_position(symbol):
            final_bar = ohlcv.iloc[-1]
            self._process_exit(symbol, portfolio, final_bar, closed_trades, force=True)

        equity_series = pd.Series(
            {ts: eq for ts, eq in portfolio.equity_curve}, dtype=float
        ).sort_index()
        if equity_series.empty:
            equity_series = pd.Series([cfg.starting_equity], index=[ohlcv.index[0]])

        periods_per_year = _periods_per_year(timeframe)
        report = compute_performance_report(closed_trades, equity_series, cfg.starting_equity, periods_per_year)

        return BacktestResult(performance=report, closed_trades=closed_trades, journal=journal, equity_curve=equity_series)

    def _process_entry(self, setup, quantity: float, portfolio: PortfolioManager, next_bar: pd.Series, signal_ts) -> None:
        side = OrderSide.BUY if setup.decision == TradeDecision.ENTER_LONG else OrderSide.SELL
        raw_price = float(next_bar["open"])  # fill at next bar's open — can't act on the same bar that signaled
        fill_price = self._apply_cost(raw_price, side)
        fee = self._fee(quantity * fill_price)
        fill_ts = _as_datetime(next_bar.name) if hasattr(next_bar, "name") else _as_datetime(signal_ts)
        fill = Fill(
            order_id=str(uuid.uuid4()), symbol=setup.symbol, side=side, quantity=quantity,
            price=fill_price, timestamp=fill_ts,
            fee=fee, slippage=abs(fill_price - raw_price),
        )
        # Pass the SIMULATED bar time, not wall-clock time — the portfolio's
        # daily rollover (trade count, daily P&L, kill switch) must key off
        # historical dates during a backtest, never real-world "today".
        portfolio.apply_entry_fill(fill, stop_loss=setup.stop_loss, take_profit=setup.take_profit, now=fill_ts)

    def _process_exit(self, symbol: str, portfolio: PortfolioManager, bar: pd.Series, closed_trades: list[ClosedTrade], force: bool = False) -> None:
        position = portfolio.positions.get(symbol)
        if position is None:
            return

        high, low = float(bar["high"]), float(bar["low"])
        exit_price = None
        exit_reason = ""

        if position.side == OrderSide.BUY:
            if position.stop_loss and low <= position.stop_loss:
                exit_price, exit_reason = position.stop_loss, "stop_loss"
            elif position.take_profit and high >= position.take_profit:
                exit_price, exit_reason = position.take_profit, "take_profit"
        else:
            if position.stop_loss and high >= position.stop_loss:
                exit_price, exit_reason = position.stop_loss, "stop_loss"
            elif position.take_profit and low <= position.take_profit:
                exit_price, exit_reason = position.take_profit, "take_profit"

        if force and exit_price is None:
            exit_price, exit_reason = float(bar["close"]), "backtest_end"

        if exit_price is None:
            return

        opposite_side = OrderSide.SELL if position.side == OrderSide.BUY else OrderSide.BUY
        fill_price = self._apply_cost(exit_price, opposite_side)
        fee = self._fee(position.quantity * fill_price)
        opened_at = position.opened_at
        fill_ts = _as_datetime(bar.name) if hasattr(bar, "name") else datetime.utcnow()
        fill = Fill(
            order_id=str(uuid.uuid4()), symbol=symbol, side=opposite_side, quantity=position.quantity,
            price=fill_price, timestamp=fill_ts,
            fee=fee, slippage=abs(fill_price - exit_price),
        )
        # Same reasoning as the entry side: keep the portfolio's notion of
        # "now" pinned to simulated time throughout the backtest.
        pnl = portfolio.apply_exit_fill(fill, now=fill_ts)
        closed_trades.append(
            ClosedTrade(
                symbol=symbol, side=position.side.value, entry_price=position.entry_price,
                exit_price=fill_price, quantity=position.quantity, opened_at=opened_at,
                closed_at=fill_ts, pnl=pnl, fees=fee,
            )
        )
        self._risk_manager.record_trade_closed(symbol, pnl, now=fill_ts)


def _as_datetime(value) -> datetime:
    """Normalize a pandas Timestamp (or plain datetime) to a stdlib
    datetime, defaulting to UTC-naive if no tz info is present."""
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime()
    if isinstance(value, datetime):
        return value
    return datetime.utcnow()


def _periods_per_year(timeframe: Timeframe) -> float:
    bars_per_day = {
        Timeframe.M1: 390, Timeframe.M5: 78, Timeframe.M15: 26,
        Timeframe.H1: 6.5, Timeframe.H4: 1.625,
    }.get(timeframe, 6.5)
    return bars_per_day * 252
