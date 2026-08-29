"""Kill switch controls — the dashboard's emergency stop button lives here.
Deliberately synchronous and side-effect-only: no confirmation dance,
because a stuck human needing to fumble through a modal in a live-risk
moment is worse than an accidental stop.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api.deps import get_bot
from src.orchestrator import TradingBot

router = APIRouter(prefix="/api/kill-switch", tags=["kill-switch"])


class StopRequest(BaseModel):
    reason: str = "manual dashboard stop"


@router.post("/engage")
async def engage(payload: StopRequest, bot: TradingBot = Depends(get_bot)) -> dict:
    bot.emergency_stop(payload.reason)
    await bot.alert_manager.kill_switch_triggered(payload.reason)
    return {"status": "engaged", "reason": payload.reason}


@router.post("/resume")
async def resume(bot: TradingBot = Depends(get_bot)) -> dict:
    bot.resume()
    return {"status": "resumed"}


@router.get("/status")
async def status(bot: TradingBot = Depends(get_bot)) -> dict:
    state = bot.risk_manager.circuit_breaker.state
    return {
        "global_kill_switch_active": state.global_kill_switch_active,
        "global_kill_switch_reason": state.global_kill_switch_reason,
        "daily_loss_kill_switch_active": state.daily_loss_kill_switch_active,
    }
