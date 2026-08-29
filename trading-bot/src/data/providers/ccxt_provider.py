"""ccxt-backed provider for crypto exchanges (default: Binance). ccxt gives
us a single interface across 100+ exchanges — swapping exchanges is a
one-line change (`exchange_id`). Install with `pip install ccxt`.
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

_TIMEFRAME_MAP = {
    Timeframe.M1: "1m",
    Timeframe.M5: "5m",
    Timeframe.M15: "15m",
    Timeframe.H1: "1h",
    Timeframe.H4: "4h",
}


class CcxtProvider(MarketDataProvider):
    def __init__(self, exchange_id: str = "binance", api_key: str = "", secret_key: str = "") -> None:
        try:
            import ccxt
        except ImportError as exc:  # pragma: no cover
            raise DataProviderError("ccxt is not installed. Run `pip install ccxt`.") from exc

        exchange_class = getattr(ccxt, exchange_id)
        self._exchange = exchange_class(
            {"apiKey": api_key, "secret": secret_key, "enableRateLimit": True}
        )

    async def get_historical_bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> pd.DataFrame:
        loop = asyncio.get_event_loop()
        interval = _TIMEFRAME_MAP[timeframe]
        since_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)

        all_rows: list[list] = []

        def _fetch(since: int) -> list[list]:
            return self._exchange.fetch_ohlcv(symbol, timeframe=interval, since=since, limit=1000)

        cursor = since_ms
        while cursor < end_ms:
            batch = await loop.run_in_executor(None, _fetch, cursor)
            if not batch:
                break
            all_rows.extend(batch)
            last_ts = batch[-1][0]
            if last_ts <= cursor:
                break
            cursor = last_ts + 1
            if len(batch) < 1000:
                break

        if not all_rows:
            raise DataProviderError(f"No historical OHLCV data for {symbol}")

        df = pd.DataFrame(all_rows, columns=["ts", "open", "high", "low", "close", "volume"])
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        df = df.set_index("ts").sort_index()
        df = df[~df.index.duplicated(keep="last")]
        # Strict no-look-ahead: never return bars past `end`.
        return df[df.index <= pd.Timestamp(end, tz="UTC")]

    async def get_latest_quote(self, symbol: str) -> Quote:
        loop = asyncio.get_event_loop()
        ticker = await loop.run_in_executor(None, self._exchange.fetch_ticker, symbol)
        return Quote(
            symbol=symbol,
            timestamp=datetime.utcnow(),
            bid=float(ticker.get("bid") or ticker["last"]),
            ask=float(ticker.get("ask") or ticker["last"]),
        )

    async def stream_bars(self, symbols: list[str], timeframe: Timeframe) -> AsyncIterator[pd.Series]:
        """ccxt's REST layer has no native websocket streaming (that's
        ccxt.pro, a paid add-on); this polls the latest closed candle at an
        interval matched to the timeframe."""
        poll_seconds = {
            Timeframe.M1: 10,
            Timeframe.M5: 20,
            Timeframe.M15: 45,
            Timeframe.H1: 90,
            Timeframe.H4: 180,
        }.get(timeframe, 20)

        last_seen: dict[str, pd.Timestamp] = {}
        while True:
            for symbol in symbols:
                try:
                    end = datetime.utcnow()
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
        return True  # crypto markets trade 24/7
