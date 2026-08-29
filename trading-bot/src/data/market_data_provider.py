"""Abstract market data provider interface. Every concrete provider (Alpaca,
ccxt/Binance, yfinance, etc.) implements this so the rest of the system
never depends on a specific vendor's API shape."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import AsyncIterator

import pandas as pd

from src.core.domain import Quote
from src.core.enums import Timeframe


class MarketDataProvider(ABC):
    """Contract for both historical (backtesting) and live (paper/live
    trading) market data access."""

    @abstractmethod
    async def get_historical_bars(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """Return an OHLCV DataFrame indexed by UTC timestamp, columns:
        open, high, low, close, volume. Must contain ONLY bars with
        timestamp <= `end` — callers rely on this for backtest correctness
        (no look-ahead)."""

    @abstractmethod
    async def get_latest_quote(self, symbol: str) -> Quote:
        """Return the most recent bid/ask for a symbol."""

    @abstractmethod
    async def stream_bars(
        self, symbols: list[str], timeframe: Timeframe
    ) -> AsyncIterator[pd.Series]:
        """Yield new bars as they close, for live/paper trading."""

    @abstractmethod
    async def is_market_open(self, symbol: str) -> bool:
        """Whether the relevant market is currently open for this symbol."""

    async def health_check(self) -> bool:
        """Cheap connectivity check used by the reconnection handler."""
        return True
