"""Live broker adapter — DISABLED BY DEFAULT.

This module intentionally does nothing dangerous until a human has cleared
every one of these gates:

  1. `BROKER_MODE=live` in the environment
  2. `LIVE_TRADING_CONFIRMED=true` in the environment
  3. `LIVE_TRADING_CONFIRMATION_PHRASE="I UNDERSTAND THE RISK"` in the
     environment (exact match)
  4. A real broker adapter implementing BrokerInterface has been wired in
     below, replacing NotImplementedError — this repo ships NO live trading
     code path by default. Wiring a real broker (e.g. Alpaca's live trading
     REST client, or a live ccxt exchange instance with real API keys) is a
     deliberate, separate decision the operator must make explicitly.

`build_broker()` in src/execution/execution_engine.py is the single place
that decides paper vs. live, and it raises LiveTradingNotConfirmed unless
ALL of the above are true. There is no other path to a live order.
"""
from __future__ import annotations

from src.core.domain import Fill, Order
from src.core.exceptions import LiveTradingNotConfirmed
from src.execution.broker_interface import BrokerInterface


class LiveBrokerStub(BrokerInterface):
    """Placeholder that refuses to do anything. Replace the body of each
    method with real broker calls ONLY after you have read and understood
    the gating logic in execution_engine.build_broker(), and only for a
    broker/account you have independently verified is a paper/sandbox
    account before ever pointing it at production credentials."""

    def __init__(self, *_args, **_kwargs) -> None:
        raise LiveTradingNotConfirmed(
            "Live trading is not implemented in this build. This is intentional: "
            "connect a real broker adapter deliberately, after reading "
            "execution/live_broker_stub.py and execution/execution_engine.py."
        )

    @property
    def is_live(self) -> bool:
        return True

    async def submit_order(self, order: Order) -> Order:  # pragma: no cover
        raise LiveTradingNotConfirmed("Live order submission is not implemented.")

    async def cancel_order(self, order_id: str) -> bool:  # pragma: no cover
        raise LiveTradingNotConfirmed("Live order cancellation is not implemented.")

    async def get_order_status(self, order_id: str) -> Order:  # pragma: no cover
        raise LiveTradingNotConfirmed("Live order status is not implemented.")

    async def get_fills(self, order_id: str) -> list[Fill]:  # pragma: no cover
        raise LiveTradingNotConfirmed("Live fills retrieval is not implemented.")

    async def health_check(self) -> bool:  # pragma: no cover
        return False
