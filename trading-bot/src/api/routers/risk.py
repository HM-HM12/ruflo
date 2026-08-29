"""Risk exposure snapshot."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.deps import get_bot
from src.orchestrator import TradingBot

router = APIRouter(prefix="/api/risk", tags=["risk"])


@router.get("/exposure")
async def exposure(bot: TradingBot = Depends(get_bot)) -> dict:
    mark_prices = {sym: pos.entry_price for sym, pos in bot.portfolio.positions.items()}
    account = bot.portfolio.account_state(mark_prices)
    cfg = bot.risk_manager._config
    return {
        "equity": round(account.equity, 2),
        "exposure_by_symbol": {k: round(v, 2) for k, v in account.exposure_by_symbol.items()},
        "max_exposure_per_asset_pct": cfg.max_exposure_per_asset_pct,
        "max_risk_per_trade_pct": cfg.max_risk_per_trade_pct,
        "max_daily_loss_pct": cfg.max_daily_loss_pct,
        "max_trades_per_day": cfg.max_trades_per_day,
        "trades_today_count": account.trades_today_count,
        "max_simultaneous_positions": cfg.max_simultaneous_positions,
        "open_positions_count": account.open_positions_count,
        "consecutive_loss_circuit_breaker": cfg.consecutive_loss_circuit_breaker,
        "consecutive_losses": bot.risk_manager.circuit_breaker.state.consecutive_losses,
        "circuit_breaker_cooldown_until": (
            bot.risk_manager.circuit_breaker.state.cooldown_until.isoformat()
            if bot.risk_manager.circuit_breaker.state.cooldown_until else None
        ),
        "symbol_cooldowns": {
            sym: until.isoformat() for sym, until in bot.risk_manager.circuit_breaker.state.symbol_cooldowns.items()
        },
    }
