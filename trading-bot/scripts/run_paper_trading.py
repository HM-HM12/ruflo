#!/usr/bin/env python
"""Run the bot in paper-trading mode from the command line (no dashboard).

Usage:
    python -m scripts.run_paper_trading --symbols AAPL,MSFT,SPY --timeframe 15m
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.loader import load_risk_config, load_strategy_config  # noqa: E402
from config.settings import get_settings  # noqa: E402
from src.alerts.alert_manager import AlertManager  # noqa: E402
from src.core.enums import Timeframe  # noqa: E402
from src.data.provider_factory import build_market_data_provider, resolve_trading_universe  # noqa: E402
from src.monitoring.logger import configure_logging  # noqa: E402
from src.orchestrator import TradingBot  # noqa: E402

logger = logging.getLogger("trading_bot.cli")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the AI trading bot in paper-trading mode.")
    parser.add_argument("--symbols", type=str, default="", help="Comma-separated symbols; defaults to config/strategy.yaml universe")
    parser.add_argument("--timeframe", type=str, default="", choices=["1m", "5m", "15m", "1h", "4h", ""], help="Primary timeframe")
    parser.add_argument("--poll-interval", type=int, default=30, help="Seconds between trading cycles")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    settings = get_settings()
    configure_logging(settings.log_level)

    if settings.broker_mode == "live":
        logger.critical(
            "BROKER_MODE=live is set. This script is intentionally paper-trading "
            "only; refusing to start. (For MT5, paper trading means your "
            "terminal is logged into a demo account — Mt5Broker verifies this "
            "independently of config, see src/execution/mt5_broker.py.) Going "
            "live is a deliberate, separate decision — see SETUP.md's "
            "'Live trading' section."
        )
        return

    strategy_cfg = load_strategy_config()
    risk_cfg = load_risk_config()

    default_symbols, asset_class = resolve_trading_universe(settings, strategy_cfg)
    symbols = args.symbols.split(",") if args.symbols else default_symbols
    timeframe = Timeframe(args.timeframe or strategy_cfg.get("primary_timeframe", "15m"))

    market_data = build_market_data_provider(settings)
    bot = TradingBot(settings, strategy_cfg, risk_cfg, market_data, news_data=None, alert_manager=AlertManager())

    logger.info("Starting PAPER trading: platform=%s symbols=%s timeframe=%s", settings.broker_platform, symbols, timeframe.value)
    try:
        await bot.run_forever(symbols, asset_class, timeframe, poll_interval_seconds=args.poll_interval)
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    finally:
        bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
