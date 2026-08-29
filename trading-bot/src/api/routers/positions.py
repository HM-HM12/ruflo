"""Open positions."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.deps import get_bot
from src.orchestrator import TradingBot

router = APIRouter(prefix="/api/positions", tags=["positions"])


@router.get("/open")
async def open_positions(bot: TradingBot = Depends(get_bot)) -> list[dict]:
    return [
        {
            "symbol": symbol,
            "side": pos.side.value,
            "quantity": pos.quantity,
            "entry_price": pos.entry_price,
            "stop_loss": pos.stop_loss,
            "take_profit": pos.take_profit,
            "trailing_stop_price": pos.trailing_stop_price,
            "unrealized_pnl": round(pos.unrealized_pnl, 2),
            "opened_at": pos.opened_at.isoformat(),
        }
        for symbol, pos in bot.portfolio.positions.items()
    ]
