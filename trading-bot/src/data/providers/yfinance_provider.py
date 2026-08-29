"""yfinance-backed provider. Free, no API key required — this is the default
provider for backtesting and local development. Not recommended for live
low-latency trading (use AlpacaProvider or CcxtProvider for that); yfinance
data is delayed and rate-limited.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import AsyncIterator

import pandas as pd

from src.core.domain import Quote
from src.core.enums import Timeframe
from src.core.exceptions import DataProviderError
from src.data.market_data_provider import MarketDataProvider

_TIMEFRAME_TO_INTERVAL = {
    Timeframe.M1: "1m",
    Timeframe.M5: "5m",
    Timeframe.M15: "15m",
    Timeframe.H1: "1h",
    Timeframe.H4: "1h",  # yfinance has no native 4h bar; caller should resample
}


class YFinanceProvider(MarketDataProvider):
    def __init__(self) -> None:
        try:
            import yfinance as yf  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise DataProviderError(
                "yfinance is not installed. Run `pip install yfinance`."
            ) from exc
        self._yf = __import__("yfinance")

    async def get_historical_bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> pd.DataFrame:
        interval = _TIMEFRAME_TO_INTERVAL.get(timeframe, "1d")
        loop = asyncio.get_event_loop()

        def _fetch() -> pd.DataFrame:
            ticker = self._yf.Ticker(symbol)
            df = ticker.history(start=start, end=end, interval=interval, auto_adjust=False)
            return df

        df = await loop.run_in_executor(None, _fetch)
        if df.empty:
            raise DataProviderError(f"No historical data returned for {symbol} ({interval})")

        df = df.rename(
            columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}
        )[["open", "high", "low", "close", "volume"]]
        df.index = pd.to_datetime(df.index, utc=True)
        # Strict no-look-ahead guarantee: truncate anything beyond `end`.
        df = df[df.index <= pd.Timestamp(end, tz="UTC")]

        if timeframe == Timeframe.H4:
            df = df.resample("4h").agg(
                {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
            ).dropna()

        return df

    async def get_latest_quote(self, symbol: str) -> Quote:
        loop = asyncio.get_event_loop()

        def _fetch() -> dict:
            ticker = self._yf.Ticker(symbol)
            fast_info = ticker.fast_info
            return {
                "bid": getattr(fast_info, "bid", None) or fast_info.get("bid"),
                "ask": getattr(fast_info, "ask", None) or fast_info.get("ask"),
                "last": fast_info.get("lastPrice") if hasattr(fast_info, "get") else fast_info.last_price,
            }

        info = await loop.run_in_executor(None, _fetch)
        last = info.get("last") or 0.0
        bid = info.get("bid") or last
        ask = info.get("ask") or last
        return Quote(symbol=symbol, timestamp=datetime.utcnow(), bid=bid, ask=ask)

    async def stream_bars(self, symbols: list[str], timeframe: Timeframe) -> AsyncIterator[pd.Series]:
        """yfinance has no native streaming API — this polls at an interval
        appropriate to the timeframe. For genuine low-latency streaming, use
        AlpacaProvider (stocks/ETFs) or CcxtProvider (crypto) instead."""
        poll_seconds = {
            Timeframe.M1: 15,
            Timeframe.M5: 30,
            Timeframe.M15: 60,
            Timeframe.H1: 120,
            Timeframe.H4: 300,
        }.get(timeframe, 30)

        last_seen: dict[str, pd.Timestamp] = {}
        while True:
            for symbol in symbols:
                try:
                    end = datetime.utcnow()
                    start = end - pd.Timedelta(days=2)
                    df = await self.get_historical_bars(symbol, timeframe, start, end)
                except DataProviderError:
                    continue
                if df.empty:
                    continue
                latest_ts = df.index[-1]
                if last_seen.get(symbol) != latest_ts:
                    last_seen[symbol] = latest_ts
                    bar = df.iloc[-1].copy()
                    bar.name = latest_ts
                    bar["symbol"] = symbol
                    yield bar
            await asyncio.sleep(poll_seconds)

    async def is_market_open(self, symbol: str) -> bool:
        loop = asyncio.get_event_loop()

        def _fetch() -> bool:
            ticker = self._yf.Ticker(symbol)
            return bool(ticker.fast_info.get("marketState", "CLOSED") in ("REGULAR", "OPEN"))

        try:
            return await loop.run_in_executor(None, _fetch)
        except Exception:
            return False
