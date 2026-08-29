"""Recent trades and the full trading journal, including rejected setups."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from src.api.deps import get_bot
from src.orchestrator import TradingBot

router = APIRouter(prefix="/api/trades", tags=["trades"])


@router.get("/recent")
async def recent_trades(bot: TradingBot = Depends(get_bot), limit: int = Query(50, le=500)) -> list[dict]:
    executed = [e for e in bot.journal.entries if e.was_executed][-limit:]
    return [
        {
            "timestamp": e.timestamp.isoformat(),
            "symbol": e.symbol,
            "decision": e.decision.value,
            "confidence": e.confidence,
            "reasoning": e.reasoning,
            "market_regime": e.market_regime,
            "trade_id": e.trade_id,
        }
        for e in reversed(executed)
    ]


@router.get("/journal")
async def full_journal(bot: TradingBot = Depends(get_bot), limit: int = Query(100, le=1000)) -> list[dict]:
    """Every decision the AI made, including trades it rejected and why —
    per the spec's requirement to explain what the bot chose NOT to do."""
    entries = bot.journal.entries[-limit:]
    return [
        {
            "timestamp": e.timestamp.isoformat(),
            "symbol": e.symbol,
            "decision": e.decision.value,
            "confidence": e.confidence,
            "score_breakdown": e.score_breakdown,
            "was_executed": e.was_executed,
            "rejection_reason": e.rejection_reason.value if e.rejection_reason else None,
            "rejection_detail": e.rejection_detail,
            "reasoning": e.reasoning,
            "market_regime": e.market_regime,
        }
        for e in reversed(entries)
    ]


@router.get("/rejection-stats")
async def rejection_stats(bot: TradingBot = Depends(get_bot)) -> dict:
    return bot.journal.rejection_reason_counts()
