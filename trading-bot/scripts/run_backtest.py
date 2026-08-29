#!/usr/bin/env python
"""Run a backtest (and optionally walk-forward validation) from the CLI.

Usage:
    python -m scripts.run_backtest --symbol AAPL --days 180 --timeframe 15m
    python -m scripts.run_backtest --symbol AAPL --days 730 --walk-forward
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.loader import load_risk_config, load_strategy_config  # noqa: E402
from src.backtesting.backtest_engine import BacktestConfig, BacktestEngine  # noqa: E402
from src.backtesting.walk_forward import WalkForwardRunner  # noqa: E402
from src.core.enums import AssetClass, Timeframe  # noqa: E402
from src.data.providers.yfinance_provider import YFinanceProvider  # noqa: E402
from src.monitoring.logger import configure_logging  # noqa: E402
from src.ai.decision_engine import AIDecisionEngine  # noqa: E402
from src.risk.risk_manager import RiskConfig, RiskManager  # noqa: E402
from src.strategy.strategy_engine import StrategyEngine  # noqa: E402

logger = logging.getLogger("trading_bot.cli.backtest")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest the AI trading strategy.")
    parser.add_argument("--symbol", type=str, required=True)
    parser.add_argument("--asset-class", type=str, default="stock", choices=["stock", "etf", "crypto"])
    parser.add_argument("--timeframe", type=str, default="15m", choices=["1m", "5m", "15m", "1h", "4h"])
    parser.add_argument("--days", type=int, default=180, help="Lookback window in days")
    parser.add_argument("--starting-equity", type=float, default=100_000.0)
    parser.add_argument("--walk-forward", action="store_true")
    parser.add_argument("--train-bars", type=int, default=1000)
    parser.add_argument("--test-bars", type=int, default=250)
    parser.add_argument("--output", type=str, default="", help="Optional path to write JSON results")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    configure_logging("INFO")

    strategy_cfg = load_strategy_config()
    risk_cfg = load_risk_config()

    provider = YFinanceProvider()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    timeframe = Timeframe(args.timeframe)
    asset_class = AssetClass(args.asset_class)

    logger.info("Fetching historical data for %s (%s to %s)", args.symbol, start.date(), end.date())
    ohlcv = await provider.get_historical_bars(args.symbol, timeframe, start, end)
    logger.info("Loaded %d bars", len(ohlcv))

    if args.walk_forward:
        runner = WalkForwardRunner(
            indicator_cfg=strategy_cfg["indicators"],
            decision_weights=strategy_cfg["scoring_weights"],
            min_confidence_threshold=strategy_cfg.get("min_confidence_threshold", 65.0),
            risk_config=RiskConfig.from_dict(risk_cfg),
            backtest_config=BacktestConfig(starting_equity=args.starting_equity),
        )
        results = runner.run(args.symbol, asset_class, timeframe, ohlcv, train_bars=args.train_bars, test_bars=args.test_bars)
        summary = runner.aggregate_out_of_sample_metrics(results)
        print(json.dumps(summary, indent=2))
        for r in results:
            print(f"\nWindow {r.window.test_start.date()} -> {r.window.test_end.date()}:")
            print(json.dumps(r.result.performance.as_dict(), indent=2))
        output = {"summary": summary, "windows": [r.result.performance.as_dict() for r in results]}
    else:
        engine = BacktestEngine(
            strategy_engine=StrategyEngine(strategy_cfg["indicators"]),
            decision_engine=AIDecisionEngine(strategy_cfg["scoring_weights"], strategy_cfg.get("min_confidence_threshold", 65.0)),
            risk_manager=RiskManager(RiskConfig.from_dict(risk_cfg)),
            config=BacktestConfig(starting_equity=args.starting_equity),
        )
        result = engine.run(args.symbol, asset_class, timeframe, ohlcv)
        print(json.dumps(result.performance.as_dict(), indent=2))
        print(f"\nRejection reasons: {json.dumps(result.journal.rejection_reason_counts(), indent=2)}")
        output = result.performance.as_dict()

    if args.output:
        Path(args.output).write_text(json.dumps(output, indent=2))
        logger.info("Wrote results to %s", args.output)


if __name__ == "__main__":
    asyncio.run(main())
