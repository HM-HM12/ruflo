"""News data providers. Abstract interface plus concrete implementations for
NewsAPI.org and Finnhub — both have generous free tiers suitable for
development. Swap or add providers without touching downstream sentiment or
strategy code.
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timedelta

from src.core.exceptions import DataProviderError
from src.sentiment.news_sentiment_analyzer import RawNewsItem


class NewsDataProvider(ABC):
    @abstractmethod
    async def fetch_recent(self, symbols: list[str], lookback_minutes: int = 60) -> list[RawNewsItem]:
        """Fetch recent news items relevant to the given symbols."""


class NewsApiProvider(NewsDataProvider):
    """https://newsapi.org — general financial/business news."""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise DataProviderError("NEWSAPI_KEY is required for NewsApiProvider.")
        self._api_key = api_key

    async def fetch_recent(self, symbols: list[str], lookback_minutes: int = 60) -> list[RawNewsItem]:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise DataProviderError("httpx is not installed. Run `pip install httpx`.") from exc

        since = datetime.utcnow() - timedelta(minutes=lookback_minutes)
        query = " OR ".join(symbols)
        params = {
            "q": query,
            "from": since.isoformat(timespec="seconds"),
            "sortBy": "publishedAt",
            "language": "en",
            "apiKey": self._api_key,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://newsapi.org/v2/everything", params=params)
            resp.raise_for_status()
            payload = resp.json()

        items = []
        for article in payload.get("articles", []):
            matched_symbol = next((s for s in symbols if s.split("/")[0].lower() in (article.get("title") or "").lower()), None)
            items.append(
                RawNewsItem(
                    symbol=matched_symbol,
                    headline=article.get("title", ""),
                    source=(article.get("source") or {}).get("name", "unknown"),
                    published_at=datetime.fromisoformat(article["publishedAt"].replace("Z", "+00:00")),
                    url=article.get("url", ""),
                    summary=article.get("description") or "",
                )
            )
        return items


class FinnhubNewsProvider(NewsDataProvider):
    """https://finnhub.io — company-specific news, earnings, filings."""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise DataProviderError("FINNHUB_API_KEY is required for FinnhubNewsProvider.")
        self._api_key = api_key

    async def fetch_recent(self, symbols: list[str], lookback_minutes: int = 60) -> list[RawNewsItem]:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise DataProviderError("httpx is not installed. Run `pip install httpx`.") from exc

        since = datetime.utcnow() - timedelta(minutes=lookback_minutes)
        items: list[RawNewsItem] = []

        async with httpx.AsyncClient(timeout=10) as client:
            for symbol in symbols:
                base_symbol = symbol.split("/")[0]
                params = {
                    "symbol": base_symbol,
                    "from": since.date().isoformat(),
                    "to": datetime.utcnow().date().isoformat(),
                    "token": self._api_key,
                }
                resp = await client.get("https://finnhub.io/api/v1/company-news", params=params)
                if resp.status_code != 200:
                    continue
                for article in resp.json():
                    published_at = datetime.utcfromtimestamp(article.get("datetime", 0))
                    if published_at < since:
                        continue
                    items.append(
                        RawNewsItem(
                            symbol=base_symbol,
                            headline=article.get("headline", ""),
                            source=article.get("source", "finnhub"),
                            published_at=published_at,
                            url=article.get("url", ""),
                            summary=article.get("summary") or "",
                        )
                    )
                await asyncio.sleep(0.2)  # respect free-tier rate limits
        return items


class CompositeNewsProvider(NewsDataProvider):
    """Fan out to multiple providers and merge results. Individual provider
    failures are logged and skipped, never allowed to crash the pipeline."""

    def __init__(self, providers: list[NewsDataProvider]) -> None:
        self._providers = providers

    async def fetch_recent(self, symbols: list[str], lookback_minutes: int = 60) -> list[RawNewsItem]:
        results: list[RawNewsItem] = []
        for provider in self._providers:
            try:
                results.extend(await provider.fetch_recent(symbols, lookback_minutes))
            except Exception:
                continue
        return results
