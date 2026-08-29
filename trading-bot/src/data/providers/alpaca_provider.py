"""Alpaca Markets provider — stocks/ETFs, paper and live REST + streaming.
Requires ALPACA_API_KEY / ALPACA_SECRET_KEY (paper keys by default, see
config/settings.py). Install with `pip install alpaca-py`.
"""
from __future__ import annotations

from datetime import datetime
from typing import AsyncIterator

import pandas as pd

from src.core.domain import Quote
from src.core.enums import Timeframe
from src.core.exceptions import DataProviderError
from src.data.market_data_provider import MarketDataProvider

_TIMEFRAME_MAP = {
    Timeframe.M1: "1Min",
    Timeframe.M5: "5Min",
    Timeframe.M15: "15Min",
    Timeframe.H1: "1Hour",
    Timeframe.H4: "4Hour",
}


class AlpacaProvider(MarketDataProvider):
    def __init__(self, api_key: str, secret_key: str, base_url: str) -> None:
        if not api_key or not secret_key:
            raise DataProviderError(
                "Alpaca credentials missing. Set ALPACA_API_KEY / ALPACA_SECRET_KEY."
            )
        try:
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.live import StockDataStream
            from alpaca.trading.client import TradingClient
        except ImportError as exc:  # pragma: no cover
            raise DataProviderError("alpaca-py is not installed. Run `pip install alpaca-py`.") from exc

        self._history_client = StockHistoricalDataClient(api_key, secret_key)
        self._trading_client = TradingClient(api_key, secret_key, paper="paper" in base_url)
        self._stream_client = StockDataStream(api_key, secret_key)

    async def get_historical_bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> pd.DataFrame:
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

        unit_map = {
            Timeframe.M1: (1, TimeFrameUnit.Minute),
            Timeframe.M5: (5, TimeFrameUnit.Minute),
            Timeframe.M15: (15, TimeFrameUnit.Minute),
            Timeframe.H1: (1, TimeFrameUnit.Hour),
            Timeframe.H4: (4, TimeFrameUnit.Hour),
        }
        amount, unit = unit_map[timeframe]
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame(amount, unit),
            start=start,
            end=end,
        )
        bars = self._history_client.get_stock_bars(request)
        df = bars.df
        if df.empty:
            raise DataProviderError(f"No historical bars for {symbol}")
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(symbol, level=0)
        df = df.rename(columns={"open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"})
        df = df[["open", "high", "low", "close", "volume"]]
        # Enforce no-look-ahead even if the vendor API is lenient about `end`.
        return df[df.index <= pd.Timestamp(end, tz="UTC")]

    async def get_latest_quote(self, symbol: str) -> Quote:
        from alpaca.data.requests import StockLatestQuoteRequest

        request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
        quote = self._history_client.get_stock_latest_quote(request)[symbol]
        return Quote(
            symbol=symbol,
            timestamp=quote.timestamp,
            bid=float(quote.bid_price),
            ask=float(quote.ask_price),
            bid_size=float(quote.bid_size),
            ask_size=float(quote.ask_size),
        )

    async def stream_bars(self, symbols: list[str], timeframe: Timeframe) -> AsyncIterator[pd.Series]:
        import asyncio

        queue: asyncio.Queue = asyncio.Queue()

        async def _handler(bar) -> None:
            series = pd.Series(
                {"open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close, "volume": bar.volume,
                 "symbol": bar.symbol},
                name=bar.timestamp,
            )
            await queue.put(series)

        self._stream_client.subscribe_bars(_handler, *symbols)
        run_task = asyncio.ensure_future(self._stream_client._run_forever())
        try:
            while True:
                yield await queue.get()
        finally:
            run_task.cancel()

    async def is_market_open(self, symbol: str) -> bool:
        clock = self._trading_client.get_clock()
        return bool(clock.is_open)

    async def health_check(self) -> bool:
        try:
            self._trading_client.get_clock()
            return True
        except Exception:
            return False
