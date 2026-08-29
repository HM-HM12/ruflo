"""MetaTrader 5 market data provider — real quotes/bars from your broker's
MT5 terminal for whatever symbol you configure (default: XAUUSD / gold).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import AsyncIterator

import pandas as pd

from src.core.domain import Quote
from src.core.enums import Timeframe
from src.core.exceptions import DataProviderError
from src.core.time_utils import to_utc_timestamp
from src.data.market_data_provider import MarketDataProvider
from src.data.providers.mt5_connection import Mt5Connection, Mt5Credentials

_TIMEFRAME_ATTR = {
    Timeframe.M1: "TIMEFRAME_M1",
    Timeframe.M5: "TIMEFRAME_M5",
    Timeframe.M15: "TIMEFRAME_M15",
    Timeframe.H1: "TIMEFRAME_H1",
    Timeframe.H4: "TIMEFRAME_H4",
}


class Mt5Provider(MarketDataProvider):
    def __init__(self, credentials: Mt5Credentials, symbol: str = "XAUUSD") -> None:
        self._connection = Mt5Connection(credentials)
        self._symbol = symbol

    async def get_historical_bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> pd.DataFrame:
        loop = asyncio.get_event_loop()

        def _fetch() -> pd.DataFrame:
            mt5 = self._connection.connect()
            mt5_timeframe = getattr(mt5, _TIMEFRAME_ATTR[timeframe])
            rates = mt5.copy_rates_range(symbol, mt5_timeframe, start, end)
            if rates is None or len(rates) == 0:
                raise DataProviderError(f"No MT5 bars for {symbol}: {mt5.last_error()}")
            df = pd.DataFrame(rates)
            df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
            df = df.set_index("time").rename(columns={"tick_volume": "volume"})
            return df[["open", "high", "low", "close", "volume"]]

        df = await loop.run_in_executor(None, _fetch)
        # Strict no-look-ahead guarantee, matching every other provider.
        return df[df.index <= to_utc_timestamp(end)]

    async def get_latest_quote(self, symbol: str) -> Quote:
        loop = asyncio.get_event_loop()

        def _fetch() -> Quote:
            mt5 = self._connection.connect()
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                raise DataProviderError(f"No MT5 tick for {symbol}: {mt5.last_error()}")
            return Quote(
                symbol=symbol,
                timestamp=datetime.fromtimestamp(tick.time, tz=timezone.utc),
                bid=float(tick.bid),
                ask=float(tick.ask),
            )

        return await loop.run_in_executor(None, _fetch)

    async def stream_bars(self, symbols: list[str], timeframe: Timeframe) -> AsyncIterator[pd.Series]:
        """MT5's Python API is synchronous/polling-based (no native
        websocket push in this wrapper), so — like the yfinance and ccxt
        providers — this polls for the latest closed bar."""
        poll_seconds = {
            Timeframe.M1: 5, Timeframe.M5: 15, Timeframe.M15: 30,
            Timeframe.H1: 60, Timeframe.H4: 120,
        }.get(timeframe, 15)

        last_seen: dict[str, pd.Timestamp] = {}
        while True:
            for symbol in symbols:
                try:
                    end = datetime.now(timezone.utc)
                    start = end - pd.Timedelta(hours=6)
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

        def _check() -> bool:
            mt5 = self._connection.connect()
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                return False
            # A stale tick (no new price in >5 min) is the practical signal
            # that this symbol's market/session is currently closed —
            # MT5 doesn't expose a simple "is open" boolean.
            age = datetime.now(timezone.utc) - datetime.fromtimestamp(tick.time, tz=timezone.utc)
            return age.total_seconds() < 300

        try:
            return await loop.run_in_executor(None, _check)
        except Exception:
            return False

    async def health_check(self) -> bool:
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, lambda: self._connection.connect() is not None)
        except Exception:
            return False
