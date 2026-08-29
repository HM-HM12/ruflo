"""The Risk Manager: final authority over every trade.

No other component may bypass this. The AI decision engine proposes; the
risk manager disposes. Every check here is a hard rule, not a suggestion —
if any check fails, the trade is rejected and the reason is recorded.

Non-negotiable behavioral constraints enforced here:
  - never increase position size to "recover" a loss (no martingale)
  - never revenge-trade (symbol-level cooldown after a stop-out)
  - never accept an order without a valid stop-loss
  - never exceed configured daily loss, trade count, exposure, or
    concurrent-position limits
  - kill switches (daily-loss and global/emergency) hard-stop all new entries
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.core.domain import RiskCheckResult, TradeSetup
from src.core.enums import RejectionReason, TradeDecision
from src.risk.circuit_breaker import CircuitBreaker
from src.risk.position_sizing import PositionSizeResult, fixed_fractional_size, volatility_adjusted_size


@dataclass
class AccountState:
    """Everything the risk manager needs to know about current portfolio
    state. Populated by the Portfolio Manager each cycle — the risk manager
    never reaches into portfolio internals directly."""

    equity: float
    starting_equity_today: float
    daily_realized_pnl: float
    open_positions_count: int
    trades_today_count: int
    exposure_by_symbol: dict[str, float] = field(default_factory=dict)  # symbol -> $ exposure


@dataclass
class RiskConfig:
    max_risk_per_trade_pct: float = 1.0
    max_daily_loss_pct: float = 3.0
    max_trades_per_day: int = 10
    max_simultaneous_positions: int = 5
    max_exposure_per_asset_pct: float = 20.0
    consecutive_loss_circuit_breaker: int = 3
    circuit_breaker_cooldown_minutes: int = 60
    require_stop_loss: bool = True
    position_sizing_method: str = "fixed_fractional"
    symbol_cooldown_minutes_after_loss: int = 30

    @classmethod
    def from_dict(cls, data: dict) -> "RiskConfig":
        known_fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known_fields})


class RiskManager:
    def __init__(self, config: RiskConfig) -> None:
        self._config = config
        self.circuit_breaker = CircuitBreaker(
            consecutive_loss_threshold=config.consecutive_loss_circuit_breaker,
            cooldown_minutes=config.circuit_breaker_cooldown_minutes,
            symbol_cooldown_minutes=config.symbol_cooldown_minutes_after_loss,
        )

    def evaluate(
        self, setup: TradeSetup, account: AccountState, now: datetime | None = None
    ) -> RiskCheckResult:
        """The single entry point every proposed trade must pass through."""
        now = now or datetime.utcnow()

        if setup.decision == TradeDecision.NO_TRADE:
            return RiskCheckResult(approved=False, reason=setup.rejection_reason, detail="Decision engine returned NO_TRADE")

        if self.circuit_breaker.state.global_kill_switch_active:
            return RiskCheckResult(
                approved=False,
                reason=RejectionReason.KILL_SWITCH_ACTIVE,
                detail=f"Global kill switch active: {self.circuit_breaker.state.global_kill_switch_reason}",
            )

        self.circuit_breaker.reset_daily_state(now)
        if self.circuit_breaker.state.daily_loss_kill_switch_active:
            return RiskCheckResult(approved=False, reason=RejectionReason.DAILY_LOSS_LIMIT_REACHED, detail="Daily loss kill switch already tripped")

        # Check daily loss BEFORE this trade — if we're already over the
        # limit, trip the switch now and reject.
        daily_loss_pct = self._daily_loss_pct(account)
        if daily_loss_pct >= self._config.max_daily_loss_pct:
            self.circuit_breaker.trip_daily_loss_kill_switch(now)
            return RiskCheckResult(approved=False, reason=RejectionReason.DAILY_LOSS_LIMIT_REACHED, detail=f"Daily loss {daily_loss_pct:.2f}% >= limit {self._config.max_daily_loss_pct}%")

        if self.circuit_breaker.is_tripped(now):
            return RiskCheckResult(approved=False, reason=RejectionReason.CIRCUIT_BREAKER_ACTIVE, detail=f"{self.circuit_breaker.state.consecutive_losses} consecutive losses; cooling down until {self.circuit_breaker.state.cooldown_until}")

        if self.circuit_breaker.is_symbol_in_cooldown(setup.symbol, now):
            return RiskCheckResult(approved=False, reason=RejectionReason.CIRCUIT_BREAKER_ACTIVE, detail=f"{setup.symbol} is in post-loss cooldown (no revenge trading)")

        if self._config.require_stop_loss and not setup.stop_loss:
            return RiskCheckResult(approved=False, reason=RejectionReason.NO_VALID_STOP_LOSS, detail="No stop-loss on proposed setup")

        if account.trades_today_count >= self._config.max_trades_per_day:
            return RiskCheckResult(approved=False, reason=RejectionReason.MAX_TRADES_PER_DAY_REACHED, detail=f"{account.trades_today_count} trades already taken today")

        if account.open_positions_count >= self._config.max_simultaneous_positions:
            return RiskCheckResult(approved=False, reason=RejectionReason.MAX_OPEN_POSITIONS_REACHED, detail=f"{account.open_positions_count} open positions at limit")

        size_result = self._compute_size(setup, account)

        projected_exposure = account.exposure_by_symbol.get(setup.symbol, 0.0) + size_result.quantity * setup.entry_price
        max_exposure = account.equity * (self._config.max_exposure_per_asset_pct / 100.0)
        if projected_exposure > max_exposure:
            return RiskCheckResult(
                approved=False,
                reason=RejectionReason.MAX_EXPOSURE_PER_ASSET_REACHED,
                detail=f"Projected exposure {projected_exposure:.2f} exceeds cap {max_exposure:.2f} for {setup.symbol}",
            )

        if size_result.quantity <= 0:
            return RiskCheckResult(approved=False, reason=RejectionReason.NO_VALID_STOP_LOSS, detail="Computed position size is non-positive")

        return RiskCheckResult(
            approved=True,
            reason=None,
            max_position_size=size_result.quantity,
            risked_amount=size_result.risked_amount,
            detail=f"Approved: {size_result.quantity:.4f} units, risking {size_result.risked_amount:.2f}",
        )

    def _daily_loss_pct(self, account: AccountState) -> float:
        if account.starting_equity_today <= 0:
            return 0.0
        loss = max(0.0, -account.daily_realized_pnl)
        return (loss / account.starting_equity_today) * 100.0

    def _compute_size(self, setup: TradeSetup, account: AccountState) -> PositionSizeResult:
        # Position size is a pure function of equity and stop distance —
        # NEVER a function of confidence, streaks, or prior losses. This is
        # the concrete enforcement of "no martingale."
        if self._config.position_sizing_method == "volatility_adjusted":
            atr = setup.strategy_signal.indicator_snapshot.atr
            return volatility_adjusted_size(
                equity=account.equity,
                entry_price=setup.entry_price,
                stop_loss=setup.stop_loss,
                atr=atr,
                max_risk_per_trade_pct=self._config.max_risk_per_trade_pct,
            )
        return fixed_fractional_size(
            equity=account.equity,
            entry_price=setup.entry_price,
            stop_loss=setup.stop_loss,
            max_risk_per_trade_pct=self._config.max_risk_per_trade_pct,
        )

    def record_trade_closed(self, symbol: str, pnl: float, now: datetime | None = None) -> None:
        self.circuit_breaker.record_trade_result(symbol, pnl, now)

    def emergency_stop(self, reason: str) -> None:
        self.circuit_breaker.trip_global_kill_switch(reason)

    def resume_after_emergency_stop(self) -> None:
        self.circuit_breaker.reset_global_kill_switch()
