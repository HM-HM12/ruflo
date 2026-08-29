"""News sentiment analysis.

Design goals from the spec:
  - classify bullish / bearish / neutral with a confidence and an estimated
    market impact
  - never let a single sensational headline drive a trade on its own
  - detect and collapse duplicate coverage of the same underlying event

Default backend is VADER (rule-based, no network calls, no model download —
reliable to run in CI/offline). A pluggable `SentimentBackend` protocol lets
you swap in a transformer/LLM-based classifier (e.g. FinBERT or a Claude/GPT
call) in production without touching the rest of the pipeline — just
implement `.score(text) -> (float, float)` returning (sentiment in [-1,1],
confidence in [0,1]).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Protocol

from src.core.domain import NewsEvent
from src.core.enums import NewsCategory, NewsSentiment

try:
    from nltk.sentiment.vader import SentimentIntensityAnalyzer

    _VADER_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when nltk isn't installed
    _VADER_AVAILABLE = False


class SentimentBackend(Protocol):
    def score(self, text: str) -> tuple[float, float]:
        """Return (sentiment in [-1, 1], confidence in [0, 1])."""


class VaderSentimentBackend:
    """Rule-based fallback/default. Deterministic, offline, zero cost."""

    def __init__(self) -> None:
        if not _VADER_AVAILABLE:
            raise RuntimeError(
                "nltk is required for VaderSentimentBackend. Install with "
                "`pip install nltk` and run `python -m nltk.downloader vader_lexicon`."
            )
        self._analyzer = SentimentIntensityAnalyzer()

    def score(self, text: str) -> tuple[float, float]:
        scores = self._analyzer.polarity_scores(text)
        compound = scores["compound"]  # already in [-1, 1]
        confidence = min(1.0, abs(compound) + 0.15 * (1 - scores["neu"]))
        return compound, confidence


class LexiconFallbackBackend:
    """Zero-dependency keyword lexicon used only if nltk/VADER isn't
    installed. Deliberately conservative — low confidence by default so it
    can never dominate the AI decision engine's score on its own."""

    _BULLISH = {
        "beat", "beats", "surge", "soars", "upgrade", "upgraded", "record",
        "growth", "profit", "outperform", "rally", "breakthrough", "approval",
        "acquire", "acquisition", "partnership", "raises guidance", "strong",
        "exceeds", "bullish",
    }
    _BEARISH = {
        "miss", "misses", "plunge", "plunges", "downgrade", "downgraded",
        "lawsuit", "investigation", "recall", "bankruptcy", "layoffs",
        "cuts guidance", "weak", "decline", "fraud", "default", "bearish",
        "sec charges", "delisted",
    }

    def score(self, text: str) -> tuple[float, float]:
        words = re.findall(r"[a-z']+", text.lower())
        text_lower = text.lower()
        bull_hits = sum(1 for w in words if w in self._BULLISH)
        bear_hits = sum(1 for w in words if w in self._BEARISH)
        bull_hits += sum(2 for phrase in self._BULLISH if " " in phrase and phrase in text_lower)
        bear_hits += sum(2 for phrase in self._BEARISH if " " in phrase and phrase in text_lower)

        total = bull_hits + bear_hits
        if total == 0:
            return 0.0, 0.1
        sentiment = (bull_hits - bear_hits) / total
        confidence = min(0.6, 0.2 + 0.1 * total)  # capped: keyword matching is weak evidence
        return sentiment, confidence


_CATEGORY_KEYWORDS: dict[NewsCategory, list[str]] = {
    NewsCategory.EARNINGS: ["earnings", "eps", "quarterly results", "revenue"],
    NewsCategory.SEC_FILING: ["sec filing", "form 8-k", "form 10-k", "form 10-q", "form 4"],
    NewsCategory.ANALYST_RATING: ["upgrade", "downgrade", "price target", "initiates coverage", "rating"],
    NewsCategory.MERGER_ACQUISITION: ["acquire", "acquisition", "merger", "buyout", "takeover"],
    NewsCategory.LAWSUIT_REGULATORY: ["lawsuit", "sues", "investigation", "sec charges", "settlement", "fine"],
    NewsCategory.ECONOMIC_DATA: ["cpi", "gdp", "jobs report", "nonfarm payrolls", "pmi", "unemployment"],
    NewsCategory.INTEREST_RATE: ["fed", "federal reserve", "interest rate", "rate hike", "rate cut", "fomc"],
    NewsCategory.GEOPOLITICAL: ["war", "sanctions", "tariff", "election", "geopolitical"],
    NewsCategory.GUIDANCE: ["guidance", "outlook", "forecast raised", "forecast cut"],
}


def classify_category(headline: str, summary: str = "") -> NewsCategory:
    text = f"{headline} {summary}".lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return category
    return NewsCategory.OTHER


def _normalize_for_fingerprint(headline: str) -> str:
    text = re.sub(r"[^a-z0-9 ]", "", headline.lower())
    text = re.sub(r"\s+", " ", text).strip()
    # Drop very common leading wire-service boilerplate so re-syndicated
    # copies of the same story fingerprint identically.
    text = re.sub(r"^(update \d+[: ]?|breaking[: ]?)", "", text)
    return text


def compute_fingerprint(symbol: str | None, headline: str, published_at: datetime | None = None) -> str:
    """Content-based identity for a news event: same symbol + normalized
    headline collapses to the same fingerprint regardless of source or
    publish time. Deliberately time-independent — the actual "is this a
    duplicate right now" question is a separate, explicit time-window check
    (see NewsSentimentAnalyzer._is_duplicate), which compares this
    fingerprint's last-seen timestamp against `duplicate_window_minutes`.
    An earlier version folded a coarse time bucket into the hash itself,
    which caused two headlines minutes apart to silently get *different*
    fingerprints whenever they straddled a bucket boundary (e.g. an
    epoch-aligned 30-minute edge) — defeating dedup for events that should
    have collapsed. `published_at` is accepted but unused; kept for
    backward-compatible call sites.
    """
    del published_at
    normalized = _normalize_for_fingerprint(headline)
    key = f"{symbol or ''}|{normalized}"
    return hashlib.sha256(key.encode()).hexdigest()[:24]


@dataclass
class RawNewsItem:
    symbol: str | None
    headline: str
    source: str
    published_at: datetime
    url: str = ""
    summary: str = ""


class NewsSentimentAnalyzer:
    """Analyzes raw news items into deduplicated NewsEvent objects with
    sentiment, confidence, and impact estimate."""

    def __init__(
        self,
        backend: SentimentBackend | None = None,
        duplicate_window_minutes: int = 30,
        max_single_headline_contribution: float = 0.6,
    ) -> None:
        if backend is not None:
            self._backend = backend
        elif _VADER_AVAILABLE:
            self._backend = VaderSentimentBackend()
        else:
            self._backend = LexiconFallbackBackend()
        self._duplicate_window_minutes = duplicate_window_minutes
        self._max_single_headline_contribution = max_single_headline_contribution
        self._seen_fingerprints: dict[str, datetime] = {}

    def _is_duplicate(self, fingerprint: str, published_at: datetime) -> bool:
        last_seen = self._seen_fingerprints.get(fingerprint)
        if last_seen is None:
            return False
        return published_at - last_seen < timedelta(minutes=self._duplicate_window_minutes)

    def analyze(self, item: RawNewsItem) -> NewsEvent | None:
        """Returns None if this is a duplicate of a recently-seen event."""
        fingerprint = compute_fingerprint(item.symbol, item.headline)
        if self._is_duplicate(fingerprint, item.published_at):
            return None
        self._seen_fingerprints[fingerprint] = item.published_at

        text = f"{item.headline}. {item.summary}".strip()
        sentiment_score, confidence = self._backend.score(text)
        # Cap how much a single headline's raw intensity can imply impact —
        # impact is intensity * confidence * a hard ceiling, never 1:1.
        impact_estimate = min(
            self._max_single_headline_contribution,
            abs(sentiment_score) * confidence,
        )

        if sentiment_score > 0.15:
            sentiment = NewsSentiment.BULLISH
        elif sentiment_score < -0.15:
            sentiment = NewsSentiment.BEARISH
        else:
            sentiment = NewsSentiment.NEUTRAL

        return NewsEvent(
            id=fingerprint,
            symbol=item.symbol,
            headline=item.headline,
            source=item.source,
            published_at=item.published_at,
            category=classify_category(item.headline, item.summary),
            sentiment=sentiment,
            sentiment_score=sentiment_score,
            confidence=confidence,
            impact_estimate=impact_estimate,
            fingerprint=fingerprint,
            url=item.url,
            raw_summary=item.summary,
        )

    def analyze_batch(self, items: Iterable[RawNewsItem]) -> list[NewsEvent]:
        results = []
        for item in sorted(items, key=lambda i: i.published_at):
            event = self.analyze(item)
            if event is not None:
                results.append(event)
        return results

    def aggregate_symbol_sentiment(self, events: list[NewsEvent], symbol: str, lookback_hours: float = 24) -> tuple[float, float]:
        """Combine multiple recent news events for a symbol into one
        (sentiment, confidence) pair, weighted by confidence and recency, so
        that repeated coverage of the same story (already deduped) can't
        swamp a single strong contrarian data point either."""
        now = max((e.published_at for e in events), default=datetime.utcnow())
        relevant = [
            e for e in events
            if e.symbol == symbol and (now - e.published_at) <= timedelta(hours=lookback_hours)
        ]
        if not relevant:
            return 0.0, 0.0

        weights = []
        for e in relevant:
            age_hours = (now - e.published_at).total_seconds() / 3600
            recency_weight = max(0.1, 1 - age_hours / lookback_hours)
            weights.append(e.confidence * recency_weight)

        total_weight = sum(weights) or 1.0
        weighted_sentiment = sum(e.sentiment_score * w for e, w in zip(relevant, weights)) / total_weight
        avg_confidence = sum(e.confidence * w for e, w in zip(relevant, weights)) / total_weight
        return weighted_sentiment, min(1.0, avg_confidence)
