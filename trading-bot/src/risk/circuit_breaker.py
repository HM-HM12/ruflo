"""Consecutive-loss circuit breaker and kill switches. Tracks state across
the trading session so the risk manager can consult it on every decision."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class CircuitBreakerState:
    consecutive_losses: int = 0
    cooldown_until: datetime | None = None
    daily_loss_kill_switch_active: bool = False
    daily_loss_kill_switch_date: datetime | None = None
    global_kill_switch_active: bool = False
    global_kill_switch_reason: str = ""
    symbol_cooldowns: dict[str, datetime] = field(default_factory=dict)


class CircuitBreaker:
    def __init__(
        self,
        consecutive_loss_threshold: int = 3,
        cooldown_minutes: int = 60,
        symbol_cooldown_minutes: int = 30,
    ) -> None:
        self._threshold = consecutive_loss_threshold
        self._cooldown_minutes = cooldown_minutes
        self._symbol_cooldown_minutes = symbol_cooldown_minutes
        self.state = CircuitBreakerState()

    def record_trade_result(self, symbol: str, pnl: float, now: datetime | None = None) -> None:
        now = now or datetime.utcnow()
        if pnl < 0:
            self.state.consecutive_losses += 1
            # No revenge trading: cool the specific symbol down after a loss.
            self.state.symbol_cooldowns[symbol] = now + timedelta(minutes=self._symbol_cooldown_minutes)
            if self.state.consecutive_losses >= self._threshold:
                self.state.cooldown_until = now + timedelta(minutes=self._cooldown_minutes)
        else:
            self.state.consecutive_losses = 0

    def is_tripped(self, now: datetime | None = None) -> bool:
        now = now or datetime.utcnow()
        if self.state.cooldown_until is None:
            return False
        if now >= self.state.cooldown_until:
            self.state.cooldown_until = None
            self.state.consecutive_losses = 0
            return False
        return True

    def is_symbol_in_cooldown(self, symbol: str, now: datetime | None = None) -> bool:
        now = now or datetime.utcnow()
        until = self.state.symbol_cooldowns.get(symbol)
        if until is None:
            return False
        if now >= until:
            del self.state.symbol_cooldowns[symbol]
            return False
        return True

    def trip_daily_loss_kill_switch(self, now: datetime | None = None) -> None:
        now = now or datetime.utcnow()
        self.state.daily_loss_kill_switch_active = True
        self.state.daily_loss_kill_switch_date = now

    def reset_daily_state(self, now: datetime | None = None) -> None:
        """Called once at the start of each trading day."""
        now = now or datetime.utcnow()
        if (
            self.state.daily_loss_kill_switch_date is None
            or self.state.daily_loss_kill_switch_date.date() != now.date()
        ):
            self.state.daily_loss_kill_switch_active = False
            self.state.daily_loss_kill_switch_date = None

    def trip_global_kill_switch(self, reason: str) -> None:
        """Emergency global kill switch — manual or automated (e.g. broker
        API errors, unexplained P&L discrepancy). Requires explicit reset."""
        self.state.global_kill_switch_active = True
        self.state.global_kill_switch_reason = reason

    def reset_global_kill_switch(self) -> None:
        self.state.global_kill_switch_active = False
        self.state.global_kill_switch_reason = ""
