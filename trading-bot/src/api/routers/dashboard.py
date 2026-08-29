"""Aggregate dashboard summary endpoint: equity, daily P&L, drawdown, win
rate, risk exposure, current regime — everything the dashboard's top
summary bar needs in one call."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.deps import get_bot
from src.orchestrator import TradingBot

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
async def get_summary(bot: TradingBot = Depends(get_bot)) -> dict:
    mark_prices = {sym: pos.entry_price for sym, pos in bot.portfolio.positions.items()}
    equity = bot.portfolio.equity(mark_prices)
    account = bot.portfolio.account_state(mark_prices)

    closed_pnls = bot.portfolio.closed_trade_pnls
    wins = [p for p in closed_pnls if p > 0]
    win_rate = (len(wins) / len(closed_pnls) * 100) if closed_pnls else 0.0

    equity_values = [e for _, e in bot.portfolio.equity_curve] or [equity]
    running_max = 0.0
    max_dd = 0.0
    for val in equity_values:
        running_max = max(running_max, val)
        if running_max > 0:
            max_dd = min(max_dd, (val - running_max) / running_max * 100)

    return {
        "mode": "paper" if bot.is_paper else "live",
        "equity": round(equity, 2),
        "starting_equity": bot.portfolio.starting_equity,
        "cash": round(bot.portfolio.cash, 2),
        "daily_pnl": round(account.daily_realized_pnl, 2),
        "open_positions_count": account.open_positions_count,
        "trades_today_count": account.trades_today_count,
        "win_rate_pct": round(win_rate, 2),
        "max_drawdown_pct": round(max_dd, 3),
        "total_closed_trades": len(closed_pnls),
        "kill_switch_active": bot.risk_manager.circuit_breaker.state.global_kill_switch_active,
        "daily_loss_kill_switch_active": bot.risk_manager.circuit_breaker.state.daily_loss_kill_switch_active,
        "circuit_breaker_tripped": bot.risk_manager.circuit_breaker.is_tripped(),
        "consecutive_losses": bot.risk_manager.circuit_breaker.state.consecutive_losses,
    }
