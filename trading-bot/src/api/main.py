"""FastAPI application: REST + WebSocket backend for the dashboard, and the
process that runs the trading bot's background loop.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.websockets import WebSocket

from config.loader import load_risk_config, load_strategy_config
from config.settings import get_settings
from src.alerts.alert_manager import AlertManager
from src.alerts.channels import ConsoleChannel, EmailChannel, SlackChannel, TelegramChannel
from src.api.routers import dashboard, killswitch, news, positions, risk, trades
from src.api.websocket import manager as ws_manager, websocket_endpoint
from src.core.enums import AssetClass, Timeframe
from src.data.providers.yfinance_provider import YFinanceProvider
from src.monitoring.logger import configure_logging
from src.orchestrator import TradingBot

logger = logging.getLogger("trading_bot.api")


def build_alert_manager(settings) -> AlertManager:
    channels = [ConsoleChannel()]
    if settings.slack_webhook_url:
        channels.append(SlackChannel(settings.slack_webhook_url))
    if settings.telegram_bot_token and settings.telegram_chat_id:
        channels.append(TelegramChannel(settings.telegram_bot_token, settings.telegram_chat_id))
    if settings.alert_email_smtp_host:
        channels.append(EmailChannel(settings.alert_email_smtp_host, settings.alert_email_from, settings.alert_email_to))
    return AlertManager(channels)


async def _broadcast_loop(bot: TradingBot) -> None:
    while True:
        mark_prices = {sym: pos.entry_price for sym, pos in bot.portfolio.positions.items()}
        await ws_manager.broadcast(
            {
                "type": "summary",
                "equity": bot.portfolio.equity(mark_prices),
                "open_positions": len(bot.portfolio.positions),
                "daily_pnl": bot.portfolio.daily_realized_pnl,
                "kill_switch_active": bot.risk_manager.circuit_breaker.state.global_kill_switch_active,
            }
        )
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)

    strategy_cfg = load_strategy_config()
    risk_cfg = load_risk_config()

    market_data = YFinanceProvider()
    alert_manager = build_alert_manager(settings)

    bot = TradingBot(settings, strategy_cfg, risk_cfg, market_data, news_data=None, alert_manager=alert_manager)
    app.state.bot = bot
    app.state.settings = settings

    universe = strategy_cfg["universe"]
    symbols = universe.get("stocks", []) + universe.get("etfs", [])
    timeframe = Timeframe(strategy_cfg.get("primary_timeframe", "15m"))

    bot_task = asyncio.create_task(bot.run_forever(symbols, AssetClass.STOCK, timeframe))
    broadcast_task = asyncio.create_task(_broadcast_loop(bot))

    logger.info("Trading bot API started (mode=%s)", "paper" if bot.is_paper else "live")
    try:
        yield
    finally:
        bot.stop()
        bot_task.cancel()
        broadcast_task.cancel()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="AI Trading Bot", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(dashboard.router)
    app.include_router(trades.router)
    app.include_router(positions.router)
    app.include_router(news.router)
    app.include_router(risk.router)
    app.include_router(killswitch.router)

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.websocket("/ws")
    async def ws_route(websocket: WebSocket) -> None:
        await websocket_endpoint(websocket)

    return app


app = create_app()
