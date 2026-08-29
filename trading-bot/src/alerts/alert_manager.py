"""Alert Manager: dispatches events (trade opened/closed, breaking news,
daily loss limit, API disconnect, bot crash, risk limits exceeded, unusual
market conditions) to every configured channel."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.alerts.channels import AlertChannel, ConsoleChannel
from src.core.enums import AlertEvent, AlertLevel

logger = logging.getLogger("trading_bot.alerts")

_EVENT_LEVELS = {
    AlertEvent.TRADE_OPENED: AlertLevel.INFO,
    AlertEvent.TRADE_CLOSED: AlertLevel.INFO,
    AlertEvent.BREAKING_NEWS: AlertLevel.INFO,
    AlertEvent.DAILY_LOSS_LIMIT: AlertLevel.CRITICAL,
    AlertEvent.API_DISCONNECT: AlertLevel.WARNING,
    AlertEvent.BOT_CRASH: AlertLevel.CRITICAL,
    AlertEvent.RISK_LIMIT_EXCEEDED: AlertLevel.WARNING,
    AlertEvent.UNUSUAL_MARKET_CONDITIONS: AlertLevel.WARNING,
    AlertEvent.KILL_SWITCH_TRIGGERED: AlertLevel.CRITICAL,
}


class AlertManager:
    def __init__(self, channels: list[AlertChannel] | None = None) -> None:
        self._channels: list[AlertChannel] = channels or [ConsoleChannel()]
        self.history: list[dict] = []

    async def dispatch(self, event: AlertEvent, title: str, message: str) -> dict:
        level = _EVENT_LEVELS.get(event, AlertLevel.INFO)
        delivered = {}
        for channel in self._channels:
            try:
                delivered[type(channel).__name__] = await channel.send(level, title, message)
            except Exception:
                logger.exception("Alert channel %s raised unexpectedly", type(channel).__name__)
                delivered[type(channel).__name__] = False

        record = {
            "timestamp": datetime.now(timezone.utc),
            "event": event.value,
            "level": level.value,
            "title": title,
            "message": message,
            "delivered_channels": delivered,
        }
        self.history.append(record)
        return record

    async def trade_opened(self, symbol: str, side: str, quantity: float, price: float, confidence: float) -> None:
        await self.dispatch(
            AlertEvent.TRADE_OPENED, f"Trade opened: {symbol}",
            f"{side.upper()} {quantity:.4f} {symbol} @ {price:.2f} (confidence {confidence:.1f}/100)",
        )

    async def trade_closed(self, symbol: str, pnl: float, reason: str) -> None:
        await self.dispatch(
            AlertEvent.TRADE_CLOSED, f"Trade closed: {symbol}",
            f"{symbol} closed with P&L {pnl:+.2f} ({reason})",
        )

    async def breaking_news(self, symbol: str | None, headline: str, sentiment: str, impact: float) -> None:
        await self.dispatch(
            AlertEvent.BREAKING_NEWS, f"Breaking news{f' — {symbol}' if symbol else ''}",
            f"{headline} [{sentiment}, impact {impact:.2f}]",
        )

    async def daily_loss_limit_reached(self, loss_pct: float, limit_pct: float) -> None:
        await self.dispatch(
            AlertEvent.DAILY_LOSS_LIMIT, "Daily loss limit reached — kill switch engaged",
            f"Daily loss {loss_pct:.2f}% reached limit {limit_pct:.2f}%. No new trades will open today.",
        )

    async def api_disconnect(self, component: str, detail: str) -> None:
        await self.dispatch(AlertEvent.API_DISCONNECT, f"API disconnect: {component}", detail)

    async def bot_crash(self, error: str) -> None:
        await self.dispatch(AlertEvent.BOT_CRASH, "Bot crashed", error)

    async def risk_limit_exceeded(self, detail: str) -> None:
        await self.dispatch(AlertEvent.RISK_LIMIT_EXCEEDED, "Risk limit exceeded", detail)

    async def unusual_market_conditions(self, detail: str) -> None:
        await self.dispatch(AlertEvent.UNUSUAL_MARKET_CONDITIONS, "Unusual market conditions detected", detail)

    async def kill_switch_triggered(self, reason: str) -> None:
        await self.dispatch(AlertEvent.KILL_SWITCH_TRIGGERED, "Kill switch triggered", reason)
