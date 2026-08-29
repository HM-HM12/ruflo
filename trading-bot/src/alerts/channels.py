"""Alert delivery channels. Each channel is independently optional — a
missing webhook URL / SMTP host just means that channel silently no-ops
rather than crashing the alert dispatch."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from src.core.enums import AlertLevel

logger = logging.getLogger("trading_bot.alerts")


class AlertChannel(ABC):
    @abstractmethod
    async def send(self, level: AlertLevel, title: str, message: str) -> bool:
        """Return True if delivered."""


class ConsoleChannel(AlertChannel):
    """Always active — the guaranteed-delivery fallback channel."""

    async def send(self, level: AlertLevel, title: str, message: str) -> bool:
        log_fn = {AlertLevel.INFO: logger.info, AlertLevel.WARNING: logger.warning, AlertLevel.CRITICAL: logger.critical}[level]
        log_fn("[%s] %s: %s", level.value.upper(), title, message)
        return True


class SlackChannel(AlertChannel):
    def __init__(self, webhook_url: str) -> None:
        self._webhook_url = webhook_url

    async def send(self, level: AlertLevel, title: str, message: str) -> bool:
        if not self._webhook_url:
            return False
        try:
            import httpx
        except ImportError:
            logger.warning("httpx not installed; cannot send Slack alert")
            return False
        emoji = {AlertLevel.INFO: ":information_source:", AlertLevel.WARNING: ":warning:", AlertLevel.CRITICAL: ":rotating_light:"}[level]
        payload = {"text": f"{emoji} *{title}*\n{message}"}
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.post(self._webhook_url, json=payload)
                return resp.status_code < 300
        except Exception:
            logger.exception("Failed to deliver Slack alert")
            return False


class TelegramChannel(AlertChannel):
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id

    async def send(self, level: AlertLevel, title: str, message: str) -> bool:
        if not self._bot_token or not self._chat_id:
            return False
        try:
            import httpx
        except ImportError:
            return False
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.post(url, json={"chat_id": self._chat_id, "text": f"[{level.value.upper()}] {title}\n{message}"})
                return resp.status_code < 300
        except Exception:
            logger.exception("Failed to deliver Telegram alert")
            return False


class EmailChannel(AlertChannel):
    def __init__(self, smtp_host: str, from_addr: str, to_addr: str) -> None:
        self._smtp_host = smtp_host
        self._from_addr = from_addr
        self._to_addr = to_addr

    async def send(self, level: AlertLevel, title: str, message: str) -> bool:
        if not (self._smtp_host and self._from_addr and self._to_addr):
            return False
        import asyncio
        import smtplib
        from email.mime.text import MIMEText

        def _send() -> bool:
            try:
                msg = MIMEText(message)
                msg["Subject"] = f"[{level.value.upper()}] {title}"
                msg["From"] = self._from_addr
                msg["To"] = self._to_addr
                with smtplib.SMTP(self._smtp_host, timeout=5) as server:
                    server.send_message(msg)
                return True
            except Exception:
                logger.exception("Failed to deliver email alert")
                return False

        return await asyncio.get_event_loop().run_in_executor(None, _send)
