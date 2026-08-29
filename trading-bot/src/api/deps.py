"""Shared FastAPI dependencies. The running TradingBot instance is attached
to `app.state.bot` at startup (see api/main.py) and exposed here so router
modules don't need to import the orchestrator module directly."""
from __future__ import annotations

from fastapi import Request

from src.orchestrator import TradingBot


def get_bot(request: Request) -> TradingBot:
    bot = getattr(request.app.state, "bot", None)
    if bot is None:
        raise RuntimeError("TradingBot is not initialized on app.state")
    return bot
