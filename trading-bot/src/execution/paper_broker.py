"""Simulated paper-trading broker. This is the DEFAULT and, unless live
trading is explicitly enabled (see config/settings.py and
live_broker_stub.py), the ONLY broker the bot will ever submit orders to.

Simulates realistic frictions so paper-trading results aren't misleadingly
clean: configurable slippage, partial fills, and a small rejection
probability to exercise error-handling paths.
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone

from src.core.domain import Fill, Order
from src.core.enums import OrderSide, OrderStatus, OrderType
from src.core.exceptions import BrokerConnectionError
from src.execution.broker_interface import BrokerInterface


class PaperBroker(BrokerInterface):
    def __init__(
        self,
        slippage_bps: float = 2.0,
        partial_fill_probability: float = 0.1,
        min_partial_fill_ratio: float = 0.4,
        rejection_probability: float = 0.0,
        fee_bps: float = 1.0,
        latency_simulation_disabled: bool = True,
        rng_seed: int | None = None,
    ) -> None:
        self._slippage_bps = slippage_bps
        self._partial_fill_probability = partial_fill_probability
        self._min_partial_fill_ratio = min_partial_fill_ratio
        self._rejection_probability = rejection_probability
        self._fee_bps = fee_bps
        self._latency_simulation_disabled = latency_simulation_disabled
        self._rng = random.Random(rng_seed)
        self._orders: dict[str, Order] = {}
        self._fills: dict[str, list[Fill]] = {}
        self._connected = True

    @property
    def is_live(self) -> bool:
        return False

    def set_market_price(self, symbol: str, price: float) -> None:
        """Test/backtest hook — the paper broker has no real market feed of
        its own, so the caller (execution engine / backtester) pushes the
        current reference price before submitting market orders."""
        self._last_price = getattr(self, "_last_price", {})
        self._last_price[symbol] = price

    async def submit_order(self, order: Order) -> Order:
        if not self._connected:
            raise BrokerConnectionError("Paper broker is simulating a disconnect")

        order.id = order.id or str(uuid.uuid4())
        order.status = OrderStatus.SUBMITTED
        order.updated_at = datetime.now(timezone.utc)
        self._orders[order.id] = order
        self._fills[order.id] = []

        if self._rng.random() < self._rejection_probability:
            order.status = OrderStatus.REJECTED
            return order

        reference_price = getattr(self, "_last_price", {}).get(order.symbol, order.limit_price or order.stop_price)
        if reference_price is None:
            order.status = OrderStatus.REJECTED
            return order

        fill_price = self._apply_slippage(reference_price, order.side)

        if order.order_type == OrderType.LIMIT and order.limit_price is not None:
            crosses = (
                (order.side == OrderSide.BUY and fill_price > order.limit_price)
                or (order.side == OrderSide.SELL and fill_price < order.limit_price)
            )
            if crosses:
                order.status = OrderStatus.SUBMITTED  # resting, unfilled
                return order
            fill_price = order.limit_price

        fill_ratio = 1.0
        if self._rng.random() < self._partial_fill_probability:
            fill_ratio = self._rng.uniform(self._min_partial_fill_ratio, 0.99)

        filled_qty = order.quantity * fill_ratio
        fee = filled_qty * fill_price * (self._fee_bps / 10_000)
        fill = Fill(
            order_id=order.id,
            symbol=order.symbol,
            side=order.side,
            quantity=filled_qty,
            price=fill_price,
            timestamp=datetime.now(timezone.utc),
            fee=fee,
            slippage=abs(fill_price - reference_price),
        )
        self._fills[order.id].append(fill)

        order.filled_quantity = filled_qty
        order.average_fill_price = fill_price
        order.status = OrderStatus.FILLED if fill_ratio >= 0.999 else OrderStatus.PARTIALLY_FILLED
        order.updated_at = datetime.now(timezone.utc)
        return order

    def _apply_slippage(self, reference_price: float, side: OrderSide) -> float:
        random_bps = self._rng.uniform(0, self._slippage_bps)
        direction = 1 if side == OrderSide.BUY else -1  # buys slip up, sells slip down
        return reference_price * (1 + direction * random_bps / 10_000)

    async def fill_resting_order(self, order_id: str) -> Order:
        """Simulate a resting limit order finally filling (e.g. price
        returned to the limit level on a later bar). Called by the
        execution engine's order-status polling loop."""
        order = self._orders.get(order_id)
        if order is None or order.status != OrderStatus.SUBMITTED:
            return order
        reference_price = getattr(self, "_last_price", {}).get(order.symbol)
        if reference_price is None or order.limit_price is None:
            return order
        crosses = (
            (order.side == OrderSide.BUY and reference_price <= order.limit_price)
            or (order.side == OrderSide.SELL and reference_price >= order.limit_price)
        )
        if not crosses:
            return order
        fill_price = order.limit_price
        fee = order.quantity * fill_price * (self._fee_bps / 10_000)
        fill = Fill(
            order_id=order.id, symbol=order.symbol, side=order.side,
            quantity=order.quantity, price=fill_price,
            timestamp=datetime.now(timezone.utc), fee=fee, slippage=0.0,
        )
        self._fills[order.id].append(fill)
        order.filled_quantity = order.quantity
        order.average_fill_price = fill_price
        order.status = OrderStatus.FILLED
        order.updated_at = datetime.now(timezone.utc)
        return order

    async def cancel_order(self, order_id: str) -> bool:
        order = self._orders.get(order_id)
        if order is None or order.status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED):
            return False
        order.status = OrderStatus.CANCELLED
        order.updated_at = datetime.now(timezone.utc)
        return True

    async def get_order_status(self, order_id: str) -> Order:
        order = self._orders.get(order_id)
        if order is None:
            raise BrokerConnectionError(f"Unknown order id {order_id}")
        return order

    async def get_fills(self, order_id: str) -> list[Fill]:
        return list(self._fills.get(order_id, []))

    async def health_check(self) -> bool:
        return self._connected

    def simulate_disconnect(self) -> None:
        self._connected = False

    def simulate_reconnect(self) -> None:
        self._connected = True
