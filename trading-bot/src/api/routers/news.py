"""News feed and sentiment."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from src.api.deps import get_bot
from src.orchestrator import TradingBot

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("/recent")
async def recent_news(bot: TradingBot = Depends(get_bot), limit: int = Query(50, le=200)) -> list[dict]:
    events = sorted(bot._recent_news, key=lambda e: e.published_at, reverse=True)[:limit]
    return [
        {
            "id": e.id,
            "symbol": e.symbol,
            "headline": e.headline,
            "source": e.source,
            "published_at": e.published_at.isoformat(),
            "category": e.category.value,
            "sentiment": e.sentiment.value,
            "sentiment_score": round(e.sentiment_score, 3),
            "confidence": round(e.confidence, 3),
            "impact_estimate": round(e.impact_estimate, 3),
            "url": e.url,
        }
        for e in events
    ]
