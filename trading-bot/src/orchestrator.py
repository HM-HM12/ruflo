"""TradingBot: the live/paper trading orchestrator. Wires together data,
strategy, AI decision, risk, execution, portfolio, journal, and alerts into
one continuously-running loop.

This is intentionally a thin coordinator — all real logic lives in the
modules it calls, each of which is independently unit-tested.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from config.settings import Settings
from src.ai.decision_engine import AIDecisionEngine
from src.alerts.alert_manager import AlertManager
from src.core.domain import Fill
from src.core.enums import AssetClass, OrderSide, Timeframe, TradeDecision
from src.data.market_data_provider import MarketDataProvider
from src.data.news_data_provider import NewsDataProvider
from src.execution.execution_engine import ExecutionEngine, build_broker
from src.journal.trade_journal import TradeJournal
from src.portfolio.portfolio_manager import PortfolioManager
from src.regime.regime_detector import RegimeDetector
from src.risk.risk_manager import RiskConfig, RiskManager
from src.sentiment.news_sentiment_analyzer import NewsSentimentAnalyzer
from src.strategy.strategy_engine import StrategyEngine

logger = logging.getLogger("trading_bot.orchestrator")


class TradingBot:
    def __init__(
        self,
        settings: Settings,
        strategy_cfg: dict,
        risk_cfg: dict,
        market_data: MarketDataProvider,
        news_data: NewsDataProvider | None = None,
        alert_manager: AlertManager | None = None,
    ) -> None:
        self.settings = settings
        self.strategy_cfg = strategy_cfg
        self.market_data = market_data
        self.news_data = news_data
        self.alert_manager = alert_manager or AlertManager()

        self.strategy_engine = StrategyEngine(strategy_cfg["indicators"], RegimeDetector())
        self.decision_engine = AIDecisionEngine(
            weights=strategy_cfg["scoring_weights"],
            min_confidence_threshold=strategy_cfg.get("min_confidence_threshold", 65.0),
        )
        self.risk_manager = RiskManager(RiskConfig.from_dict(risk_cfg))
        self.portfolio = PortfolioManager(starting_equity=settings.starting_equity)
        self.journal = TradeJournal()
        self.sentiment_analyzer = NewsSentimentAnalyzer(
            duplicate_window_minutes=strategy_cfg.get("news", {}).get("duplicate_window_minutes", 30),
            max_single_headline_contribution=strategy_cfg.get("news", {}).get("max_single_headline_score_contribution", 0.6),
        )

        broker = build_broker(settings)
        self.execution_engine = ExecutionEngine(broker)
        self._running = False
        self._recent_news: list = []

    @property
    def is_paper(self) -> bool:
        return not self.execution_engine.is_live

    async def run_forever(self, symbols: list[str], asset_class: AssetClass, timeframe: Timeframe, poll_interval_seconds: int = 30) -> None:
        self._running = True
        logger.info("Starting trading bot in %s mode for %s", "PAPER" if self.is_paper else "LIVE", symbols)
        while self._running:
            try:
                await self._cycle(symbols, asset_class, timeframe)
            except Exception as exc:  # noqa: BLE001 — a single bad cycle must never crash the bot
                logger.exception("Trading cycle failed")
                await self.alert_manager.bot_crash(str(exc))
            await asyncio.sleep(poll_interval_seconds)

    def stop(self) -> None:
        self._running = False

    async def _refresh_news(self, symbols: list[str]) -> None:
        if self.news_data is None:
            return
        try:
            raw_items = await self.news_data.fetch_recent(symbols, lookback_minutes=60)
        except Exception:
            logger.exception("News fetch failed")
            await self.alert_manager.api_disconnect("news_provider", "Failed to fetch recent news")
            return

        for item in raw_items:
            event = self.sentiment_analyzer.analyze(item)
            if event is None:
                continue  # duplicate — silently skipped, as required
            self._recent_news.append(event)
            if event.impact_estimate > 0.4:
                await self.alert_manager.breaking_news(event.symbol, event.headline, event.sentiment.value, event.impact_estimate)

        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        self._recent_news = [e for e in self._recent_news if e.published_at.replace(tzinfo=timezone.utc) >= cutoff]

    async def _cycle(self, symbols: list[str], asset_class: AssetClass, timeframe: Timeframe) -> None:
        healthy = await self.execution_engine.health_check()
        if not healthy:
            await self.alert_manager.api_disconnect("broker", "Broker health check failed")
            return

        await self._refresh_news(symbols)

        mark_prices: dict[str, float] = {}
        for symbol in symbols:
            try:
                quote = await self.market_data.get_latest_quote(symbol)
                mark_prices[symbol] = quote.mid
            except Exception:
                logger.exception("Failed to fetch quote for %s", symbol)
                continue

        self.portfolio.mark_to_market(mark_prices)
        await self._manage_open_positions(mark_prices)

        for symbol in symbols:
            if symbol not in mark_prices:
                continue
            await self._evaluate_symbol(symbol, asset_class, timeframe, mark_prices)

    async def _manage_open_positions(self, mark_prices: dict[str, float]) -> None:
        for symbol, position in list(self.portfolio.positions.items()):
            price = mark_prices.get(symbol)
            if price is None:
                continue
            hit_stop = position.stop_loss and (
                (position.side == OrderSide.BUY and price <= position.stop_loss)
                or (position.side == OrderSide.SELL and price >= position.stop_loss)
            )
            hit_target = position.take_profit and (
                (position.side == OrderSide.BUY and price >= position.take_profit)
                or (position.side == OrderSide.SELL and price <= position.take_profit)
            )
            if hit_stop or hit_target:
                await self._close_position(symbol, price, "stop_loss" if hit_stop else "take_profit")

    async def _close_position(self, symbol: str, price: float, reason: str) -> None:
        position = self.portfolio.positions.get(symbol)
        if position is None:
            return
        opposite_side = OrderSide.SELL if position.side == OrderSide.BUY else OrderSide.BUY
        order = await self.execution_engine.submit_market_order(symbol, opposite_side, position.quantity)
        fill = Fill(order_id=order.id, symbol=symbol, side=opposite_side, quantity=order.filled_quantity or position.quantity,
                    price=order.average_fill_price or price, timestamp=datetime.now(timezone.utc))
        pnl = self.portfolio.apply_exit_fill(fill)
        self.risk_manager.record_trade_closed(symbol, pnl)
        await self.alert_manager.trade_closed(symbol, pnl, reason)

    async def _evaluate_symbol(self, symbol: str, asset_class: AssetClass, timeframe: Timeframe, mark_prices: dict[str, float]) -> None:
        if self.portfolio.has_open_position(symbol):
            return  # one position per symbol at a time — no pyramiding

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=10)
        try:
            ohlcv = await self.market_data.get_historical_bars(symbol, timeframe, start, end)
        except Exception:
            logger.exception("Failed to fetch bars for %s", symbol)
            return

        related_news = [e for e in self._recent_news if e.symbol == symbol]
        active_news_event = any((end - e.published_at.replace(tzinfo=timezone.utc)).total_seconds() <= 3600 for e in related_news)

        signal = self.strategy_engine.build_signal(symbol, asset_class, timeframe, ohlcv, related_news, active_news_event)
        setup = self.decision_engine.evaluate(signal)

        account = self.portfolio.account_state(mark_prices)
        risk_result = None
        if setup.decision != TradeDecision.NO_TRADE:
            risk_result = self.risk_manager.evaluate(setup, account)
            if risk_result.approved:
                await self._open_position(setup, risk_result.max_position_size)

        self.journal.record_decision(setup, risk_result)

    async def _open_position(self, setup, quantity: float) -> None:
        side = OrderSide.BUY if setup.decision == TradeDecision.ENTER_LONG else OrderSide.SELL
        order = await self.execution_engine.submit_market_order(
            setup.symbol, side, quantity, stop_loss=setup.stop_loss, take_profit=setup.take_profit,
        )
        fill_price = order.average_fill_price or setup.entry_price
        fill = Fill(order_id=order.id, symbol=setup.symbol, side=side, quantity=order.filled_quantity or quantity,
                    price=fill_price, timestamp=datetime.now(timezone.utc))
        self.portfolio.apply_entry_fill(fill, stop_loss=setup.stop_loss, take_profit=setup.take_profit)
        await self.alert_manager.trade_opened(setup.symbol, side.value, fill.quantity, fill_price, setup.confidence)

    def emergency_stop(self, reason: str = "manual") -> None:
        self.risk_manager.emergency_stop(reason)
        logger.critical("EMERGENCY STOP engaged: %s", reason)

    def resume(self) -> None:
        self.risk_manager.resume_after_emergency_stop()
        logger.warning("Emergency stop cleared; trading resumed")
