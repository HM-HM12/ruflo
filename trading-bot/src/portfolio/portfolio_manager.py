"""Portfolio Manager: source of truth for positions, exposure, and equity.
Feeds AccountState to the Risk Manager and applies fills from the Execution
Engine. Holds no trading logic — purely bookkeeping."""
from __future__ import annotations

from datetime import datetime, timezone

from src.core.domain import Fill, Position
from src.core.enums import OrderSide
from src.risk.risk_manager import AccountState


class PortfolioManager:
    def __init__(self, starting_equity: float) -> None:
        self.cash: float = starting_equity
        self.starting_equity: float = starting_equity
        self._starting_equity_today: float = starting_equity
        self._today: datetime = datetime.now(timezone.utc).date()
        self.positions: dict[str, Position] = {}
        self.trades_today_count: int = 0
        self.daily_realized_pnl: float = 0.0
        self.equity_curve: list[tuple[datetime, float]] = []
        self.closed_trade_pnls: list[float] = []

    def _roll_day_if_needed(self, now: datetime) -> None:
        if now.date() != self._today:
            self._today = now.date()
            self._starting_equity_today = self.equity(mark_prices={})
            self.trades_today_count = 0
            self.daily_realized_pnl = 0.0

    def equity(self, mark_prices: dict[str, float]) -> float:
        """cash already reflects the signed cash flow of opening each
        position (paid out for longs, received for shorts); adding the
        signed current market value of each open position yields
        cash_before_trade + unrealized_pnl for both sides. See
        Position.compute_unrealized_pnl for the sign convention this
        mirrors."""
        signed_market_value = sum(
            (1 if pos.side == OrderSide.BUY else -1) * pos.quantity * mark_prices.get(sym, pos.entry_price)
            for sym, pos in self.positions.items()
        )
        return self.cash + signed_market_value

    def total_exposure_value(self, mark_prices: dict[str, float]) -> dict[str, float]:
        return {
            symbol: pos.quantity * mark_prices.get(symbol, pos.entry_price)
            for symbol, pos in self.positions.items()
        }

    def apply_entry_fill(self, fill: Fill, stop_loss: float | None, take_profit: float | None, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        self._roll_day_if_needed(now)
        # Long: capital is deployed (cash out). Short: proceeds from the
        # sale are received (cash in) — simplified, no margin/borrow cost.
        gross = fill.quantity * fill.price
        self.cash += (-gross - fill.fee) if fill.side == OrderSide.BUY else (gross - fill.fee)
        self.positions[fill.symbol] = Position(
            symbol=fill.symbol,
            side=fill.side,
            quantity=fill.quantity,
            entry_price=fill.price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            opened_at=now,
        )
        self.trades_today_count += 1

    def apply_exit_fill(self, fill: Fill, now: datetime | None = None) -> float:
        """Returns realized P&L for this close."""
        now = now or datetime.now(timezone.utc)
        self._roll_day_if_needed(now)
        position = self.positions.pop(fill.symbol, None)
        if position is None:
            return 0.0
        direction = 1 if position.side == OrderSide.BUY else -1
        pnl = direction * (fill.price - position.entry_price) * fill.quantity - fill.fee
        # Closing a long: sell for proceeds (cash in). Closing a short: buy
        # back to cover (cash out).
        gross = fill.quantity * fill.price
        self.cash += (gross - fill.fee) if position.side == OrderSide.BUY else (-gross - fill.fee)
        self.daily_realized_pnl += pnl
        self.closed_trade_pnls.append(pnl)
        return pnl

    def mark_to_market(self, mark_prices: dict[str, float], now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        self._roll_day_if_needed(now)
        for symbol, position in self.positions.items():
            if symbol in mark_prices:
                position.unrealized_pnl = position.compute_unrealized_pnl(mark_prices[symbol])
        self.equity_curve.append((now, self.equity(mark_prices)))

    def account_state(self, mark_prices: dict[str, float]) -> AccountState:
        return AccountState(
            equity=self.equity(mark_prices),
            starting_equity_today=self._starting_equity_today,
            daily_realized_pnl=self.daily_realized_pnl,
            open_positions_count=len(self.positions),
            trades_today_count=self.trades_today_count,
            exposure_by_symbol=self.total_exposure_value(mark_prices),
        )

    def has_open_position(self, symbol: str) -> bool:
        return symbol in self.positions
