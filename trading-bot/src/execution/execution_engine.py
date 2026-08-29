"""Execution Engine: the only place orders are actually submitted. Ties
together the broker abstraction, order-status tracking, reconnection
handling, and — critically — the paper/live gate.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from config.settings import Settings
from src.core.domain import Fill, Order
from src.core.enums import OrderSide, OrderStatus, OrderType
from src.core.exceptions import BrokerConnectionError, LiveTradingNotConfirmed
from src.execution.broker_interface import BrokerInterface
from src.execution.paper_broker import PaperBroker

logger = logging.getLogger(__name__)


def build_broker(settings: Settings) -> BrokerInterface:
    """The single decision point for paper vs. live. Every one of the four
    gates documented in live_broker_stub.py must hold, or we silently and
    safely fall back to paper trading with a loud log warning — trading
    never fails open into a live broker."""
    if settings.broker_mode == "live":
        if not settings.live_trading_fully_authorized:
            logger.warning(
                "BROKER_MODE=live was requested but live trading is not fully "
                "authorized (LIVE_TRADING_CONFIRMED and/or the confirmation "
                "phrase are missing). Falling back to PAPER trading."
            )
            return PaperBroker()
        from src.execution.live_broker_stub import LiveBrokerStub

        try:
            return LiveBrokerStub()
        except LiveTradingNotConfirmed:
            logger.error(
                "Live trading was fully authorized by config but no live broker "
                "adapter is implemented. Refusing to trade live; falling back to paper."
            )
            return PaperBroker()
    return PaperBroker()


class ExecutionEngine:
    def __init__(self, broker: BrokerInterface, max_reconnect_attempts: int = 5, reconnect_backoff_seconds: float = 2.0) -> None:
        self._broker = broker
        self._max_reconnect_attempts = max_reconnect_attempts
        self._reconnect_backoff_seconds = reconnect_backoff_seconds
        self._connected = True

    @property
    def is_live(self) -> bool:
        return self._broker.is_live

    async def _with_reconnect(self, coro_factory):
        attempt = 0
        while True:
            try:
                result = await coro_factory()
                self._connected = True
                return result
            except BrokerConnectionError:
                attempt += 1
                self._connected = False
                if attempt > self._max_reconnect_attempts:
                    logger.error("Broker connection failed after %d attempts", attempt)
                    raise
                backoff = self._reconnect_backoff_seconds * (2 ** (attempt - 1))
                logger.warning("Broker call failed (attempt %d), retrying in %.1fs", attempt, backoff)
                await asyncio.sleep(backoff)

    async def submit_market_order(
        self, symbol: str, side: OrderSide, quantity: float,
        stop_loss: float | None = None, take_profit: float | None = None,
        client_order_id: str = "", parent_trade_id: str | None = None,
    ) -> Order:
        order = Order(
            id=str(uuid.uuid4()), symbol=symbol, side=side, order_type=OrderType.MARKET,
            quantity=quantity, stop_price=stop_loss, take_profit_price=take_profit,
            client_order_id=client_order_id or str(uuid.uuid4()),
            parent_trade_id=parent_trade_id,
        )
        return await self._with_reconnect(lambda: self._broker.submit_order(order))

    async def submit_limit_order(
        self, symbol: str, side: OrderSide, quantity: float, limit_price: float,
        stop_loss: float | None = None, take_profit: float | None = None,
    ) -> Order:
        order = Order(
            id=str(uuid.uuid4()), symbol=symbol, side=side, order_type=OrderType.LIMIT,
            quantity=quantity, limit_price=limit_price, stop_price=stop_loss,
            take_profit_price=take_profit,
        )
        return await self._with_reconnect(lambda: self._broker.submit_order(order))

    async def submit_stop_order(
        self, symbol: str, side: OrderSide, quantity: float, stop_price: float,
    ) -> Order:
        order = Order(
            id=str(uuid.uuid4()), symbol=symbol, side=side, order_type=OrderType.STOP,
            quantity=quantity, stop_price=stop_price,
        )
        return await self._with_reconnect(lambda: self._broker.submit_order(order))

    async def cancel(self, order_id: str) -> bool:
        return await self._with_reconnect(lambda: self._broker.cancel_order(order_id))

    async def poll_status(self, order_id: str) -> Order:
        return await self._with_reconnect(lambda: self._broker.get_order_status(order_id))

    async def get_fills(self, order_id: str) -> list[Fill]:
        return await self._with_reconnect(lambda: self._broker.get_fills(order_id))

    async def health_check(self) -> bool:
        try:
            healthy = await self._broker.health_check()
            self._connected = healthy
            return healthy
        except Exception:
            self._connected = False
            return False
