"""Tests for the MT5 integration, using a fake `MetaTrader5` module in place
of the real (Windows-only) package. The real package can't be installed in
CI/Linux dev environments, but every call this codebase makes to it is
exercised here against a faithful-enough fake, so the actual integration
logic — the account-type safety gate above all — is still verified.
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from src.core.domain import Order
from src.core.enums import OrderSide, OrderStatus, OrderType
from src.core.exceptions import BrokerConnectionError, LiveTradingNotConfirmed


ACCOUNT_TRADE_MODE_DEMO = 0
ACCOUNT_TRADE_MODE_CONTEST = 1
ACCOUNT_TRADE_MODE_REAL = 2
TRADE_RETCODE_DONE = 10009


def make_fake_mt5(trade_mode: int = ACCOUNT_TRADE_MODE_DEMO, login: int = 12345):
    """Build a minimal fake of the MetaTrader5 module surface this codebase
    actually calls, with enough behavior to drive the real code paths."""
    fake = types.ModuleType("MetaTrader5")

    # --- constants -------------------------------------------------
    fake.ACCOUNT_TRADE_MODE_DEMO = ACCOUNT_TRADE_MODE_DEMO
    fake.ACCOUNT_TRADE_MODE_CONTEST = ACCOUNT_TRADE_MODE_CONTEST
    fake.ACCOUNT_TRADE_MODE_REAL = ACCOUNT_TRADE_MODE_REAL
    fake.TRADE_RETCODE_DONE = TRADE_RETCODE_DONE
    fake.TRADE_ACTION_DEAL = 1
    fake.TRADE_ACTION_PENDING = 5
    fake.TRADE_ACTION_REMOVE = 8
    fake.ORDER_TYPE_BUY = 0
    fake.ORDER_TYPE_SELL = 1
    fake.ORDER_TYPE_BUY_LIMIT = 2
    fake.ORDER_TYPE_SELL_LIMIT = 3
    fake.ORDER_TYPE_BUY_STOP = 4
    fake.ORDER_TYPE_SELL_STOP = 5
    fake.ORDER_TIME_GTC = 0
    fake.SYMBOL_FILLING_IOC = 0b010
    fake.SYMBOL_FILLING_FOK = 0b001
    fake.ORDER_FILLING_IOC = 1
    fake.ORDER_FILLING_FOK = 0
    fake.ORDER_FILLING_RETURN = 2
    fake.TIMEFRAME_M1 = 1
    fake.TIMEFRAME_M5 = 5
    fake.TIMEFRAME_M15 = 15
    fake.TIMEFRAME_H1 = 16385
    fake.TIMEFRAME_H4 = 16388

    state = {
        "initialized": False,
        "order_send_result": None,
        "orders_get_result": [],
        "history_deals_result": [],
        "rates": None,
        "tick": None,
    }
    fake._state = state

    def initialize(**kwargs):
        state["initialized"] = True
        return True

    def last_error():
        return (1, "fake error")

    def terminal_info():
        return types.SimpleNamespace(connected=True) if state["initialized"] else None

    def account_info():
        if not state["initialized"]:
            return None
        return types.SimpleNamespace(login=login, server="FakeServer", trade_mode=trade_mode)

    def symbol_info(symbol):
        return types.SimpleNamespace(
            visible=True, trade_contract_size=100.0,
            filling_mode=fake.SYMBOL_FILLING_IOC,
        )

    def symbol_select(symbol, enable):
        return True

    def symbol_info_tick(symbol):
        return state["tick"]

    def copy_rates_range(symbol, timeframe, start, end):
        return state["rates"]

    def order_send(request):
        state["last_request"] = request
        return state["order_send_result"]

    def orders_get(ticket=None):
        return state["orders_get_result"]

    def history_deals_get(position=None):
        return state["history_deals_result"]

    def shutdown():
        state["initialized"] = False

    fake.initialize = initialize
    fake.last_error = last_error
    fake.terminal_info = terminal_info
    fake.account_info = account_info
    fake.symbol_info = symbol_info
    fake.symbol_select = symbol_select
    fake.symbol_info_tick = symbol_info_tick
    fake.copy_rates_range = copy_rates_range
    fake.order_send = order_send
    fake.orders_get = orders_get
    fake.history_deals_get = history_deals_get
    fake.shutdown = shutdown

    return fake


@pytest.fixture(autouse=True)
def _reset_connection_singleton():
    """Mt5Connection tracks the connected login as class-level state so
    repeated calls don't reinitialize needlessly — reset it between tests
    so fakes with different logins/modes don't leak into each other."""
    from src.data.providers.mt5_connection import Mt5Connection
    Mt5Connection._connected_login = None
    yield
    Mt5Connection._connected_login = None


def _install_fake(monkeypatch, trade_mode=ACCOUNT_TRADE_MODE_DEMO, login=12345):
    fake = make_fake_mt5(trade_mode=trade_mode, login=login)
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    return fake


def _credentials():
    from src.data.providers.mt5_connection import Mt5Credentials
    return Mt5Credentials(login=12345, password="pw", server="FakeServer")


# --- Mt5Connection -----------------------------------------------------

def test_connection_raises_if_no_account_logged_in(monkeypatch):
    fake = _install_fake(monkeypatch)
    fake.account_info = lambda: None  # simulate terminal up, nobody logged in

    from src.data.providers.mt5_connection import Mt5Connection
    conn = Mt5Connection(_credentials())
    with pytest.raises(BrokerConnectionError):
        conn.connect()


def test_connection_raises_if_initialize_fails(monkeypatch):
    fake = _install_fake(monkeypatch)
    fake.initialize = lambda **kw: False

    from src.data.providers.mt5_connection import Mt5Connection
    conn = Mt5Connection(_credentials())
    with pytest.raises(BrokerConnectionError):
        conn.connect()


def test_is_demo_account_reflects_trade_mode(monkeypatch):
    _install_fake(monkeypatch, trade_mode=ACCOUNT_TRADE_MODE_DEMO)
    from src.data.providers.mt5_connection import Mt5Connection
    conn = Mt5Connection(_credentials())
    assert conn.is_demo_account() is True


def test_is_demo_account_false_for_real(monkeypatch):
    _install_fake(monkeypatch, trade_mode=ACCOUNT_TRADE_MODE_REAL)
    from src.data.providers.mt5_connection import Mt5Connection
    conn = Mt5Connection(_credentials())
    assert conn.is_demo_account() is False


# --- Mt5Broker: the safety gate is the whole point ----------------------

def test_broker_refuses_real_account_when_paper_expected(monkeypatch):
    _install_fake(monkeypatch, trade_mode=ACCOUNT_TRADE_MODE_REAL)
    from src.execution.mt5_broker import Mt5Broker

    with pytest.raises(LiveTradingNotConfirmed):
        Mt5Broker(_credentials(), symbol="XAUUSD", expect_live_account=False)


def test_broker_refuses_demo_account_when_live_expected(monkeypatch):
    _install_fake(monkeypatch, trade_mode=ACCOUNT_TRADE_MODE_DEMO)
    from src.execution.mt5_broker import Mt5Broker

    with pytest.raises(LiveTradingNotConfirmed):
        Mt5Broker(_credentials(), symbol="XAUUSD", expect_live_account=True)


def test_broker_accepts_matching_demo_paper_pair(monkeypatch):
    _install_fake(monkeypatch, trade_mode=ACCOUNT_TRADE_MODE_DEMO)
    from src.execution.mt5_broker import Mt5Broker

    broker = Mt5Broker(_credentials(), symbol="XAUUSD", expect_live_account=False)
    assert broker.is_live is False


def test_broker_accepts_matching_real_live_pair(monkeypatch):
    _install_fake(monkeypatch, trade_mode=ACCOUNT_TRADE_MODE_REAL)
    from src.execution.mt5_broker import Mt5Broker

    broker = Mt5Broker(_credentials(), symbol="XAUUSD", expect_live_account=True)
    assert broker.is_live is True


def test_broker_accepts_contest_account_as_non_real(monkeypatch):
    """A contest account is not REAL money either — must be treated like
    demo for the paper-mode gate."""
    _install_fake(monkeypatch, trade_mode=ACCOUNT_TRADE_MODE_CONTEST)
    from src.execution.mt5_broker import Mt5Broker

    broker = Mt5Broker(_credentials(), symbol="XAUUSD", expect_live_account=False)
    assert broker.is_live is False


# --- Lot sizing -----------------------------------------------------------

def test_quantity_to_lots_uses_contract_size_and_rounds_to_step(monkeypatch):
    _install_fake(monkeypatch, trade_mode=ACCOUNT_TRADE_MODE_DEMO)
    from src.execution.mt5_broker import Mt5Broker

    broker = Mt5Broker(
        _credentials(), symbol="XAUUSD", expect_live_account=False,
        lot_step=0.01, min_lot=0.01, max_lot=100.0,
    )
    # contract_size=100 (from fake symbol_info): 250 ounces -> 2.5 lots
    assert broker._quantity_to_lots(250.0) == pytest.approx(2.5)
    # sub-lot-step amounts round to the nearest step
    assert broker._quantity_to_lots(2.3) == pytest.approx(0.02)


def test_quantity_to_lots_clamped_to_min_and_max(monkeypatch):
    _install_fake(monkeypatch, trade_mode=ACCOUNT_TRADE_MODE_DEMO)
    from src.execution.mt5_broker import Mt5Broker

    broker = Mt5Broker(
        _credentials(), symbol="XAUUSD", expect_live_account=False,
        lot_step=0.01, min_lot=0.05, max_lot=1.0,
    )
    assert broker._quantity_to_lots(0.1) == pytest.approx(0.05)  # floored to min
    assert broker._quantity_to_lots(100_000.0) == pytest.approx(1.0)  # capped to max


# --- Market order submission ----------------------------------------------

@pytest.mark.asyncio
async def test_submit_market_order_success_populates_fill(monkeypatch):
    fake = _install_fake(monkeypatch, trade_mode=ACCOUNT_TRADE_MODE_DEMO)
    fake._state["tick"] = types.SimpleNamespace(bid=2400.10, ask=2400.40, time=int(datetime.now(timezone.utc).timestamp()))
    fake._state["order_send_result"] = types.SimpleNamespace(retcode=TRADE_RETCODE_DONE, order=555, price=2400.40, volume=2.5)

    from src.execution.mt5_broker import Mt5Broker

    broker = Mt5Broker(_credentials(), symbol="XAUUSD", expect_live_account=False)
    order = Order(id="", symbol="XAUUSD", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=250.0, stop_price=2380.0, take_profit_price=2440.0)

    result = await broker.submit_order(order)

    assert result.status == OrderStatus.FILLED
    assert result.average_fill_price == pytest.approx(2400.40)
    assert fake._state["last_request"]["volume"] == pytest.approx(2.5)
    assert fake._state["last_request"]["symbol"] == "XAUUSD"
    assert fake._state["last_request"]["sl"] == 2380.0
    assert fake._state["last_request"]["tp"] == 2440.0

    fills = await broker.get_fills(result.id)
    assert len(fills) == 1
    assert fills[0].price == pytest.approx(2400.40)


@pytest.mark.asyncio
async def test_submit_market_order_rejected_on_bad_retcode(monkeypatch):
    fake = _install_fake(monkeypatch, trade_mode=ACCOUNT_TRADE_MODE_DEMO)
    fake._state["tick"] = types.SimpleNamespace(bid=2400.10, ask=2400.40, time=int(datetime.now(timezone.utc).timestamp()))
    fake._state["order_send_result"] = types.SimpleNamespace(retcode=99999, order=0, price=0.0, volume=0.0)

    from src.execution.mt5_broker import Mt5Broker

    broker = Mt5Broker(_credentials(), symbol="XAUUSD", expect_live_account=False)
    order = Order(id="", symbol="XAUUSD", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=100.0)

    result = await broker.submit_order(order)
    assert result.status == OrderStatus.REJECTED


@pytest.mark.asyncio
async def test_submit_market_order_rejected_without_tick(monkeypatch):
    fake = _install_fake(monkeypatch, trade_mode=ACCOUNT_TRADE_MODE_DEMO)
    fake._state["tick"] = None

    from src.execution.mt5_broker import Mt5Broker

    broker = Mt5Broker(_credentials(), symbol="XAUUSD", expect_live_account=False)
    order = Order(id="", symbol="XAUUSD", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=100.0)

    result = await broker.submit_order(order)
    assert result.status == OrderStatus.REJECTED


# --- Mt5Provider ------------------------------------------------------

@pytest.mark.asyncio
async def test_provider_historical_bars_truncates_to_end(monkeypatch):
    fake = _install_fake(monkeypatch, trade_mode=ACCOUNT_TRADE_MODE_DEMO)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    rates = []
    for i in range(10):
        ts = now - timedelta(minutes=(9 - i) * 15)
        rates.append({
            "time": int(ts.timestamp()), "open": 2400.0 + i, "high": 2401.0 + i,
            "low": 2399.0 + i, "close": 2400.5 + i, "tick_volume": 100 + i,
        })
    fake._state["rates"] = rates

    from src.data.providers.mt5_connection import Mt5Credentials
    from src.data.providers.mt5_provider import Mt5Provider
    from src.core.enums import Timeframe

    provider = Mt5Provider(Mt5Credentials(login=12345, password="pw", server="FakeServer"), symbol="XAUUSD")
    cutoff = now - timedelta(minutes=45)  # should exclude the last few synthetic bars
    df = await provider.get_historical_bars("XAUUSD", Timeframe.M15, now - timedelta(hours=3), cutoff)

    from src.core.time_utils import to_utc_timestamp

    assert not df.empty
    assert (df.index <= to_utc_timestamp(cutoff)).all()
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


@pytest.mark.asyncio
async def test_provider_latest_quote(monkeypatch):
    fake = _install_fake(monkeypatch, trade_mode=ACCOUNT_TRADE_MODE_DEMO)
    fake._state["tick"] = types.SimpleNamespace(bid=2400.10, ask=2400.40, time=int(datetime.now(timezone.utc).timestamp()))

    from src.data.providers.mt5_connection import Mt5Credentials
    from src.data.providers.mt5_provider import Mt5Provider

    provider = Mt5Provider(Mt5Credentials(login=12345, password="pw", server="FakeServer"), symbol="XAUUSD")
    quote = await provider.get_latest_quote("XAUUSD")
    assert quote.bid == pytest.approx(2400.10)
    assert quote.ask == pytest.approx(2400.40)


# --- build_broker() settings wiring, incl. safe fallback behavior --------

def _mt5_settings(**overrides):
    from config.settings import Settings
    defaults = dict(
        broker_platform="mt5", mt5_login=12345, mt5_password="pw", mt5_server="FakeServer",
        mt5_symbol="XAUUSD", broker_mode="paper", live_trading_confirmed=False,
        live_trading_confirmation_phrase="",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_build_broker_returns_mt5_broker_for_paper_demo(monkeypatch):
    _install_fake(monkeypatch, trade_mode=ACCOUNT_TRADE_MODE_DEMO)
    from src.execution.execution_engine import build_broker
    from src.execution.mt5_broker import Mt5Broker

    broker = build_broker(_mt5_settings())
    assert isinstance(broker, Mt5Broker)
    assert broker.is_live is False


def test_build_broker_falls_back_to_paper_if_mt5_account_mismatches(monkeypatch):
    """Config says paper, but the terminal happens to be logged into a real
    account — build_broker must never hand back an MT5 broker in that
    state; it falls back to the fully synthetic PaperBroker instead."""
    _install_fake(monkeypatch, trade_mode=ACCOUNT_TRADE_MODE_REAL)
    from src.execution.execution_engine import build_broker
    from src.execution.paper_broker import PaperBroker

    broker = build_broker(_mt5_settings())
    assert isinstance(broker, PaperBroker)


def test_build_broker_refuses_live_mt5_without_full_authorization(monkeypatch):
    _install_fake(monkeypatch, trade_mode=ACCOUNT_TRADE_MODE_REAL)
    from src.execution.execution_engine import build_broker
    from src.execution.paper_broker import PaperBroker

    settings = _mt5_settings(broker_mode="live", live_trading_confirmed=False)
    broker = build_broker(settings)
    assert isinstance(broker, PaperBroker)


def test_build_broker_returns_mt5_broker_for_fully_authorized_live(monkeypatch):
    _install_fake(monkeypatch, trade_mode=ACCOUNT_TRADE_MODE_REAL)
    from src.execution.execution_engine import build_broker
    from src.execution.mt5_broker import Mt5Broker

    settings = _mt5_settings(
        broker_mode="live", live_trading_confirmed=True,
        live_trading_confirmation_phrase="I UNDERSTAND THE RISK",
    )
    broker = build_broker(settings)
    assert isinstance(broker, Mt5Broker)
    assert broker.is_live is True
