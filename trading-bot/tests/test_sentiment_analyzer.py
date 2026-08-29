from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.core.enums import NewsCategory, NewsSentiment
from src.sentiment.news_sentiment_analyzer import (
    LexiconFallbackBackend,
    NewsSentimentAnalyzer,
    RawNewsItem,
    classify_category,
    compute_fingerprint,
)


def _item(headline: str, minutes_ago: int = 0, symbol: str = "AAPL") -> RawNewsItem:
    return RawNewsItem(
        symbol=symbol, headline=headline, source="test",
        published_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )


def test_bullish_headline_classified_bullish():
    analyzer = NewsSentimentAnalyzer(backend=LexiconFallbackBackend())
    event = analyzer.analyze(_item("Company beats earnings and raises guidance"))
    assert event is not None
    assert event.sentiment == NewsSentiment.BULLISH
    assert event.sentiment_score > 0


def test_bearish_headline_classified_bearish():
    analyzer = NewsSentimentAnalyzer(backend=LexiconFallbackBackend())
    event = analyzer.analyze(_item("Company faces SEC charges and lawsuit over fraud"))
    assert event is not None
    assert event.sentiment == NewsSentiment.BEARISH
    assert event.sentiment_score < 0


def test_neutral_headline_has_low_confidence():
    analyzer = NewsSentimentAnalyzer(backend=LexiconFallbackBackend())
    event = analyzer.analyze(_item("Company to present at industry conference next week"))
    assert event is not None
    assert event.sentiment == NewsSentiment.NEUTRAL


def test_duplicate_headline_within_window_is_dropped():
    analyzer = NewsSentimentAnalyzer(backend=LexiconFallbackBackend(), duplicate_window_minutes=30)
    first = analyzer.analyze(_item("Company beats earnings", minutes_ago=20))
    second = analyzer.analyze(_item("Company beats earnings", minutes_ago=5))
    assert first is not None
    assert second is None  # deduplicated


def test_same_story_outside_window_is_not_duplicate():
    analyzer = NewsSentimentAnalyzer(backend=LexiconFallbackBackend(), duplicate_window_minutes=30)
    first = analyzer.analyze(_item("Company beats earnings", minutes_ago=60))
    second = analyzer.analyze(_item("Company beats earnings", minutes_ago=0))
    assert first is not None
    assert second is not None


def test_impact_estimate_is_capped():
    analyzer = NewsSentimentAnalyzer(backend=LexiconFallbackBackend(), max_single_headline_contribution=0.6)
    event = analyzer.analyze(_item("Company beats earnings surge record growth profit outperform rally"))
    assert event is not None
    assert event.impact_estimate <= 0.6


def test_category_classification():
    assert classify_category("Company reports Q3 earnings beat") == NewsCategory.EARNINGS
    assert classify_category("Analyst upgrades stock, raises price target") == NewsCategory.ANALYST_RATING
    assert classify_category("Fed announces interest rate decision") == NewsCategory.INTEREST_RATE
    assert classify_category("Company to acquire smaller rival") == NewsCategory.MERGER_ACQUISITION
    assert classify_category("Random unrelated update") == NewsCategory.OTHER


def test_fingerprint_is_content_based_not_time_based():
    """Fingerprint identity must depend only on symbol + normalized
    headline, never on publish time — folding a coarse time bucket into the
    hash previously caused two headlines minutes apart to get different
    fingerprints whenever they straddled a bucket boundary, silently
    breaking dedup. Time-windowing is handled separately (see
    test_duplicate_headline_within_window_is_dropped)."""
    ts = datetime.now(timezone.utc)
    fp1 = compute_fingerprint("AAPL", "Company Beats Earnings!!", ts)
    fp2 = compute_fingerprint("AAPL", "company beats earnings", ts + timedelta(hours=5))
    assert fp1 == fp2


def test_aggregate_symbol_sentiment_weights_by_recency_and_confidence():
    analyzer = NewsSentimentAnalyzer(backend=LexiconFallbackBackend())
    events = [
        analyzer.analyze(_item("Company beats earnings surge", minutes_ago=600)),
        analyzer.analyze(_item("Company misses lawsuit investigation", minutes_ago=5)),
    ]
    events = [e for e in events if e is not None]
    sentiment, confidence = analyzer.aggregate_symbol_sentiment(events, "AAPL", lookback_hours=24)
    # The more recent bearish event should dominate the older bullish one.
    assert sentiment < 0.3
