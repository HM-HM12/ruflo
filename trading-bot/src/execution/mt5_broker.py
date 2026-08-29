"""MetaTrader 5 execution adapter.

Unlike Alpaca/ccxt, MT5 has no separate "paper trading" API — a demo
account and a real account use the exact same MetaTrader5 Python calls, on
the exact same terminal software. The only way to tell them apart is to ask
the connected account what it is (`account_info().trade_mode`), so that is
exactly what this class does, on every construction:

  - `BROKER_MODE=paper` (default) -> this class REFUSES to initialize
    against a REAL account. You must log the MT5 terminal into a demo
    account for paper trading to work at all.
  - `BROKER_MODE=live` -> requires the full settings.live_trading_fully_authorized
    gate (see config/settings.py) AND the connected account must actually
    be REAL — if you've authorized live trading but the terminal happens to
    be logged into a demo account, this refuses too (fails safe both ways).

This mirrors execution_engine.build_broker()'s existing paper-by-default
philosophy, just enforced against the ground truth reported by the
terminal instead of a config value nobody can independently verify.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from src.core.domain import Fill, Order
from src.core.enums import OrderSide, OrderStatus, OrderType
from src.core.exceptions import BrokerConnectionError, LiveTradingNotConfirmed
from src.execution.broker_interface import BrokerInterface
from src.data.providers.mt5_connection import Mt5Connection, Mt5Credentials

logger = logging.getLogger("trading_bot.mt5.broker")

MAGIC_NUMBER = 990125  # arbitrary, identifies this bot's orders in MT5's terminal/history


class Mt5Broker(BrokerInterface):
    def __init__(
        self,
        credentials: Mt5Credentials,
        symbol: str,
        expect_live_account: bool,
        lot_step: float = 0.01,
        min_lot: float = 0.01,
        max_lot: float = 100.0,
        deviation_points: int = 20,
    ) -> None:
        self._connection = Mt5Connection(credentials)
        self._symbol = symbol
        self._lot_step = lot_step
        self._min_lot = min_lot
        self._max_lot = max_lot
        self._deviation_points = deviation_points

        mt5 = self._connection.connect()
        info = mt5.account_info()
        is_real = info.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL

        if expect_live_account and not is_real:
            self._connection.shutdown()
            raise LiveTradingNotConfirmed(
                f"BROKER_MODE=live is authorized, but the MT5 terminal is logged "
                f"into a non-real account (login={info.login}, trade_mode="
                f"{info.trade_mode}). Log the terminal into your live account, or "
                f"set BROKER_MODE=paper to trade this demo account safely."
            )
        if not expect_live_account and is_real:
            self._connection.shutdown()
            raise LiveTradingNotConfirmed(
                f"BROKER_MODE=paper (the default), but the MT5 terminal is logged "
                f"into a REAL account (login={info.login}). Refusing to place any "
                f"order against real money without the full live-trading "
                f"confirmation gate — log the terminal into a demo account for "
                f"paper trading, or see SETUP.md's 'Live trading' section."
            )

        self._is_live = is_real
        symbol_info = self._connection.symbol_info(symbol)
        self._contract_size = float(symbol_info.trade_contract_size) or 100.0
        logger.info(
            "MT5 broker ready: symbol=%s contract_size=%s account=%s (%s)",
            symbol, self._contract_size, info.login, "REAL" if is_real else "demo/contest",
        )

        self._orders: dict[str, dict] = {}  # our order id -> {"ticket": int|None, "order": Order}
        self._fills: dict[str, list[Fill]] = {}

    @property
    def is_live(self) -> bool:
        return self._is_live

    def _quantity_to_lots(self, quantity: float) -> float:
        """Convert a risk-manager-computed quantity (in the underlying
        instrument's natural unit — e.g. ounces of gold) into MT5 lots,
        using the symbol's real contract size, then round to the broker's
        lot step and clamp to [min_lot, max_lot]. This keeps position
        sizing broker-agnostic upstream (risk in $ / stop distance in $ =
        ounces at risk) and confines the lot-convention translation to this
        one boundary."""
        raw_lots = quantity / self._contract_size
        stepped = round(raw_lots / self._lot_step) * self._lot_step
        clamped = max(self._min_lot, min(self._max_lot, stepped))
        return round(clamped, 2)

    async def submit_order(self, order: Order) -> Order:
        import asyncio

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._submit_order_sync, order)

    def _submit_order_sync(self, order: Order) -> Order:
        mt5 = self._connection.connect()
        order.id = order.id or str(uuid.uuid4())
        lots = self._quantity_to_lots(order.quantity)

        tick = mt5.symbol_info_tick(order.symbol)
        if tick is None:
            order.status = OrderStatus.REJECTED
            self._orders[order.id] = {"ticket": None, "order": order}
            return order

        if order.order_type == OrderType.MARKET:
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": order.symbol,
                "volume": lots,
                "type": mt5.ORDER_TYPE_BUY if order.side == OrderSide.BUY else mt5.ORDER_TYPE_SELL,
                "price": tick.ask if order.side == OrderSide.BUY else tick.bid,
                "deviation": self._deviation_points,
                "magic": MAGIC_NUMBER,
                "comment": "ai-trading-bot",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": self._resolve_filling_mode(mt5, order.symbol),
            }
            if order.stop_price:
                request["sl"] = order.stop_price
            if order.take_profit_price:
                request["tp"] = order.take_profit_price
        else:
            request = self._build_pending_order_request(mt5, order, lots, tick)
            if request is None:
                order.status = OrderStatus.REJECTED
                self._orders[order.id] = {"ticket": None, "order": order}
                return order

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            retcode = result.retcode if result else mt5.last_error()
            logger.error("MT5 order_send failed for %s: retcode=%s", order.symbol, retcode)
            order.status = OrderStatus.REJECTED
            self._orders[order.id] = {"ticket": None, "order": order}
            return order

        now = datetime.now(timezone.utc)
        if order.order_type == OrderType.MARKET:
            order.status = OrderStatus.FILLED
            order.filled_quantity = order.quantity
            order.average_fill_price = float(result.price)
            fill = Fill(
                order_id=order.id, symbol=order.symbol, side=order.side,
                quantity=order.quantity, price=float(result.price), timestamp=now,
                fee=0.0,  # MT5 CFD costs are usually spread-embedded; see commission via history deals
                slippage=abs(float(result.price) - (tick.ask if order.side == OrderSide.BUY else tick.bid)),
            )
            self._fills.setdefault(order.id, []).append(fill)
        else:
            order.status = OrderStatus.SUBMITTED  # resting pending order

        order.updated_at = now
        self._orders[order.id] = {"ticket": result.order, "order": order}
        return order

    def _resolve_filling_mode(self, mt5, symbol: str):
        info = mt5.symbol_info(symbol)
        # Different brokers support different fill policies for the same
        # symbol; try IOC first (most common for CFDs), fall back to FOK.
        filling_flags = getattr(info, "filling_mode", 0)
        if filling_flags & mt5.SYMBOL_FILLING_IOC:
            return mt5.ORDER_FILLING_IOC
        if filling_flags & mt5.SYMBOL_FILLING_FOK:
            return mt5.ORDER_FILLING_FOK
        return mt5.ORDER_FILLING_RETURN

    def _build_pending_order_request(self, mt5, order: Order, lots: float, tick) -> dict | None:
        price = order.limit_price or order.stop_price
        if price is None:
            return None
        current = tick.ask if order.side == OrderSide.BUY else tick.bid
        if order.order_type == OrderType.LIMIT:
            order_type = (
                mt5.ORDER_TYPE_BUY_LIMIT if (order.side == OrderSide.BUY and price < current)
                else mt5.ORDER_TYPE_SELL_LIMIT if (order.side == OrderSide.SELL and price > current)
                else None
            )
        else:  # STOP
            order_type = (
                mt5.ORDER_TYPE_BUY_STOP if (order.side == OrderSide.BUY and price > current)
                else mt5.ORDER_TYPE_SELL_STOP if (order.side == OrderSide.SELL and price < current)
                else None
            )
        if order_type is None:
            return None
        return {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": order.symbol,
            "volume": lots,
            "type": order_type,
            "price": price,
            "sl": order.stop_price or 0.0,
            "tp": order.take_profit_price or 0.0,
            "magic": MAGIC_NUMBER,
            "comment": "ai-trading-bot",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._resolve_filling_mode(mt5, order.symbol),
        }

    async def cancel_order(self, order_id: str) -> bool:
        import asyncio

        record = self._orders.get(order_id)
        if record is None or record["ticket"] is None:
            return False
        loop = asyncio.get_event_loop()

        def _cancel() -> bool:
            mt5 = self._connection.connect()
            request = {"action": mt5.TRADE_ACTION_REMOVE, "order": record["ticket"]}
            result = mt5.order_send(request)
            success = result is not None and result.retcode == mt5.TRADE_RETCODE_DONE
            if success:
                record["order"].status = OrderStatus.CANCELLED
                record["order"].updated_at = datetime.now(timezone.utc)
            return success

        return await loop.run_in_executor(None, _cancel)

    async def get_order_status(self, order_id: str) -> Order:
        record = self._orders.get(order_id)
        if record is None:
            raise BrokerConnectionError(f"Unknown order id {order_id}")
        order: Order = record["order"]
        ticket = record["ticket"]
        if ticket is None or order.status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED):
            return order

        import asyncio
        loop = asyncio.get_event_loop()

        def _check() -> Order:
            mt5 = self._connection.connect()
            still_pending = mt5.orders_get(ticket=ticket)
            if still_pending:
                return order
            # No longer pending — it either filled or was cancelled/expired;
            # check history to find out which.
            deals = mt5.history_deals_get(position=ticket) or []
            if deals:
                deal = deals[-1]
                order.status = OrderStatus.FILLED
                order.filled_quantity = order.quantity
                order.average_fill_price = float(deal.price)
            else:
                order.status = OrderStatus.CANCELLED
            order.updated_at = datetime.now(timezone.utc)
            return order

        return await loop.run_in_executor(None, _check)

    async def get_fills(self, order_id: str) -> list[Fill]:
        return list(self._fills.get(order_id, []))

    async def health_check(self) -> bool:
        import asyncio
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, lambda: self._connection.connect() is not None)
        except Exception:
            return False
