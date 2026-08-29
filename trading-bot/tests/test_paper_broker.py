from __future__ import annotations

import pytest

from src.core.enums import OrderSide, OrderStatus, OrderType
from src.core.exceptions import BrokerConnectionError
from src.execution.paper_broker import PaperBroker
from src.core.domain import Order


def _order(**overrides) -> Order:
    defaults = dict(id="", symbol="AAPL", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=10.0)
    defaults.update(overrides)
    return Order(**defaults)


@pytest.mark.asyncio
async def test_market_order_fills_at_slippage_adjusted_price():
    broker = PaperBroker(slippage_bps=10.0, partial_fill_probability=0.0, rejection_probability=0.0, rng_seed=1)
    broker.set_market_price("AAPL", 100.0)
    order = await broker.submit_order(_order())
    assert order.status == OrderStatus.FILLED
    assert order.average_fill_price >= 100.0  # buys slip up
    assert order.average_fill_price <= 100.0 * 1.001  # within 10bps


@pytest.mark.asyncio
async def test_sell_slips_down_not_up():
    broker = PaperBroker(slippage_bps=10.0, partial_fill_probability=0.0, rejection_probability=0.0, rng_seed=2)
    broker.set_market_price("AAPL", 100.0)
    order = await broker.submit_order(_order(side=OrderSide.SELL))
    assert order.average_fill_price <= 100.0


@pytest.mark.asyncio
async def test_order_rejected_without_reference_price():
    broker = PaperBroker(rng_seed=3)
    order = await broker.submit_order(_order(symbol="UNKNOWN"))
    assert order.status == OrderStatus.REJECTED


@pytest.mark.asyncio
async def test_partial_fill_simulation():
    broker = PaperBroker(partial_fill_probability=1.0, min_partial_fill_ratio=0.5, rejection_probability=0.0, rng_seed=4)
    broker.set_market_price("AAPL", 100.0)
    order = await broker.submit_order(_order(quantity=100.0))
    assert order.status == OrderStatus.PARTIALLY_FILLED
    assert 0 < order.filled_quantity < 100.0


@pytest.mark.asyncio
async def test_limit_order_rests_if_it_does_not_cross():
    broker = PaperBroker(slippage_bps=0.0, partial_fill_probability=0.0, rejection_probability=0.0, rng_seed=5)
    broker.set_market_price("AAPL", 100.0)
    order = await broker.submit_order(_order(order_type=OrderType.LIMIT, limit_price=90.0))
    assert order.status == OrderStatus.SUBMITTED
    assert order.filled_quantity == 0.0


@pytest.mark.asyncio
async def test_disconnect_raises_broker_connection_error():
    broker = PaperBroker()
    broker.simulate_disconnect()
    with pytest.raises(BrokerConnectionError):
        await broker.submit_order(_order())
    broker.simulate_reconnect()
    broker.set_market_price("AAPL", 100.0)
    order = await broker.submit_order(_order())
    assert order.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED, OrderStatus.SUBMITTED)


@pytest.mark.asyncio
async def test_cancel_order():
    broker = PaperBroker(slippage_bps=0.0, partial_fill_probability=0.0, rejection_probability=0.0, rng_seed=6)
    broker.set_market_price("AAPL", 100.0)
    order = await broker.submit_order(_order(order_type=OrderType.LIMIT, limit_price=90.0))
    cancelled = await broker.cancel_order(order.id)
    assert cancelled is True
    status = await broker.get_order_status(order.id)
    assert status.status == OrderStatus.CANCELLED


@pytest.mark.asyncio
async def test_fees_are_charged_on_fills():
    broker = PaperBroker(slippage_bps=0.0, partial_fill_probability=0.0, rejection_probability=0.0, fee_bps=10.0, rng_seed=7)
    broker.set_market_price("AAPL", 100.0)
    order = await broker.submit_order(_order(quantity=10.0))
    fills = await broker.get_fills(order.id)
    assert len(fills) == 1
    assert fills[0].fee > 0
