from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.ai.decision_engine import AIDecisionEngine
from src.core.domain import IndicatorSnapshot, NewsEvent, StrategySignal
from src.core.enums import (
    AssetClass, MarketRegime, NewsCategory, NewsSentiment, RejectionReason, Timeframe,
    TradeDecision, TrendDirection,
)


def _snapshot(**overrides) -> IndicatorSnapshot:
    defaults = dict(
        symbol="AAPL", timeframe=Timeframe.M15, timestamp=datetime.now(timezone.utc),
        close=100.0, ema_9=102.0, ema_21=101.0, ema_50=100.0, ema_200=95.0,
        rsi=55.0, macd=0.5, macd_signal=0.2, macd_histogram=0.3, vwap=99.5,
        atr=1.0, bb_upper=103.0, bb_middle=100.0, bb_lower=97.0,
        volume=20000, relative_volume=1.5, nearest_support=95.0, nearest_resistance=105.0,
        trend_direction=TrendDirection.UP,
    )
    defaults.update(overrides)
    return IndicatorSnapshot(**defaults)


def _signal(**overrides) -> StrategySignal:
    snapshot = overrides.pop("indicator_snapshot", _snapshot())
    defaults = dict(
        symbol="AAPL", asset_class=AssetClass.STOCK, timestamp=datetime.now(timezone.utc),
        direction=TrendDirection.UP, indicator_snapshot=snapshot, related_news=[],
        technical_signals=[], regime=MarketRegime.BULL,
        suggested_stop_loss=snapshot.close - 2, suggested_take_profit=snapshot.close + 4,
    )
    defaults.update(overrides)
    return StrategySignal(**defaults)


def test_weights_must_sum_to_one():
    with pytest.raises(ValueError):
        AIDecisionEngine(weights={"news_sentiment": 0.5, "technical_setup": 0.3})


def test_strong_bullish_setup_produces_enter_long():
    engine = AIDecisionEngine(min_confidence_threshold=50.0)
    news = NewsEvent(
        id="1", symbol="AAPL", headline="AAPL beats earnings, raises guidance", source="test",
        published_at=datetime.now(timezone.utc), category=NewsCategory.EARNINGS,
        sentiment=NewsSentiment.BULLISH, sentiment_score=0.8, confidence=0.9, impact_estimate=0.5,
        fingerprint="fp1",
    )
    signal = _signal(related_news=[news])
    setup = engine.evaluate(signal)
    assert setup.decision == TradeDecision.ENTER_LONG
    assert setup.confidence > 50.0
    assert setup.rejection_reason is None


def test_below_threshold_confidence_is_no_trade():
    engine = AIDecisionEngine(min_confidence_threshold=99.9)
    signal = _signal()
    setup = engine.evaluate(signal)
    assert setup.decision == TradeDecision.NO_TRADE
    assert setup.rejection_reason == RejectionReason.BELOW_CONFIDENCE_THRESHOLD


def test_flat_direction_is_no_trade_even_with_high_scores():
    snapshot = _snapshot(trend_direction=TrendDirection.FLAT)
    signal = _signal(indicator_snapshot=snapshot, direction=TrendDirection.FLAT)
    engine = AIDecisionEngine(min_confidence_threshold=1.0)
    setup = engine.evaluate(signal)
    assert setup.decision == TradeDecision.NO_TRADE
    assert setup.rejection_reason == RejectionReason.CONFLICTING_SIGNALS


def test_missing_stop_loss_forces_no_trade():
    signal = _signal(suggested_stop_loss=None)
    engine = AIDecisionEngine(min_confidence_threshold=1.0)
    setup = engine.evaluate(signal)
    assert setup.decision == TradeDecision.NO_TRADE
    assert setup.rejection_reason == RejectionReason.NO_VALID_STOP_LOSS


def test_single_sensational_headline_cannot_dominate_score():
    """A single extremely bullish headline, even at max sentiment and
    confidence, must be dampened so it alone can't swing the decision."""
    engine = AIDecisionEngine(min_confidence_threshold=50.0, news_dampening_cap=0.6)
    extreme_news = NewsEvent(
        id="1", symbol="AAPL", headline="AAPL SKYROCKETS ON MASSIVE NEWS", source="test",
        published_at=datetime.now(timezone.utc), category=NewsCategory.OTHER,
        sentiment=NewsSentiment.BULLISH, sentiment_score=1.0, confidence=1.0, impact_estimate=1.0,
        fingerprint="fp1",
    )
    # Weak/neutral technicals otherwise
    neutral_snapshot = _snapshot(ema_9=100.0, ema_21=100.0, ema_50=100.0, rsi=50.0, macd_histogram=0.0, relative_volume=1.0)
    signal = _signal(indicator_snapshot=neutral_snapshot, related_news=[extreme_news])
    setup = engine.evaluate(signal)
    news_component_score = setup.score_breakdown.news_sentiment
    # sentiment_score(1.0) * min(confidence, cap=0.6) mapped to 0-100 -> 50 + 0.6*50 = 80, not 100
    assert news_component_score == pytest.approx(80.0, abs=0.5)
    assert news_component_score < 100.0


def test_no_news_is_neutral_not_bullish_or_bearish():
    engine = AIDecisionEngine()
    signal = _signal(related_news=[])
    setup = engine.evaluate(signal)
    assert setup.score_breakdown.news_sentiment == pytest.approx(50.0)


def test_engine_can_say_no_trade_on_choppy_conflicting_evidence():
    """The AI must be capable of confidently doing nothing — this is a
    correctness requirement, not a failure mode."""
    snapshot = _snapshot(
        ema_9=100.0, ema_21=100.1, ema_50=99.9, rsi=50.0, macd_histogram=0.0,
        relative_volume=0.9, trend_direction=TrendDirection.FLAT,
    )
    signal = _signal(indicator_snapshot=snapshot, direction=TrendDirection.FLAT, regime=MarketRegime.SIDEWAYS)
    engine = AIDecisionEngine(min_confidence_threshold=65.0)
    setup = engine.evaluate(signal)
    assert setup.decision == TradeDecision.NO_TRADE
