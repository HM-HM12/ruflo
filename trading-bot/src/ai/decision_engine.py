"""AI decision engine: turns a StrategySignal into a scored TradeSetup.

This module NEVER has the final word on whether a trade executes — that
authority belongs entirely to the risk manager (src/risk/risk_manager.py).
This engine's only job is to produce an honest confidence score and a
directional proposal, and to say NO_TRADE when the evidence doesn't clear
the bar. It must never be tuned to "stay active" — a low trade count on a
choppy day is a correct output, not a malfunction.
"""
from __future__ import annotations

from src.core.domain import ScoreBreakdown, StrategySignal, TradeSetup
from src.core.enums import MarketRegime, RejectionReason, TradeDecision, TrendDirection

DEFAULT_WEIGHTS = {
    "news_sentiment": 0.25,
    "technical_setup": 0.25,
    "momentum": 0.15,
    "volume": 0.10,
    "market_trend": 0.10,
    "volatility": 0.10,
    "risk_reward": 0.05,
}


def _validate_weights(weights: dict) -> None:
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"scoring_weights must sum to 1.0, got {total}")


class AIDecisionEngine:
    def __init__(
        self,
        weights: dict | None = None,
        min_confidence_threshold: float = 65.0,
        news_dampening_cap: float = 0.6,
    ) -> None:
        self._weights = weights or DEFAULT_WEIGHTS
        _validate_weights(self._weights)
        self._min_confidence_threshold = min_confidence_threshold
        # A single news event's contribution to the news_sentiment component
        # is capped so one sensational headline can never single-handedly
        # push a setup over the confidence threshold.
        self._news_dampening_cap = news_dampening_cap

    # -- component scorers (each returns 0-100) --------------------------

    def _score_news_sentiment(self, signal: StrategySignal) -> float:
        if not signal.related_news:
            return 50.0  # neutral: no news is not evidence either way
        # Each event's influence is capped at `news_dampening_cap`, and the
        # sum is normalized by EVENT COUNT (not by the sum of capped
        # weights). Normalizing by the weight sum would cancel the cap out
        # entirely for a single event (0.6/0.6 == 1.0) or for any number of
        # mutually-agreeing events — dividing by count instead means one
        # sensational headline can contribute at most
        # sentiment_score * news_dampening_cap, full stop.
        capped_events = [
            (e.sentiment_score, min(e.confidence, self._news_dampening_cap))
            for e in signal.related_news
        ]
        weighted = sum(score * conf for score, conf in capped_events) / len(capped_events)
        weighted = max(-1.0, min(1.0, weighted))
        return 50.0 + weighted * 50.0  # map [-1,1] -> [0,100]

    def _score_technical_setup(self, signal: StrategySignal) -> float:
        snap = signal.indicator_snapshot
        score = 50.0
        # EMA alignment
        if snap.ema_9 > snap.ema_21 > snap.ema_50:
            score += 15
        elif snap.ema_9 < snap.ema_21 < snap.ema_50:
            score -= 15
        # RSI positioning (avoid chasing extremes)
        if 45 <= snap.rsi <= 65:
            score += 5
        elif snap.rsi >= 80 or snap.rsi <= 20:
            score -= 10
        # Price vs VWAP
        if snap.close > snap.vwap:
            score += 5
        else:
            score -= 5
        # Bollinger squeeze/breakout context
        if snap.bb_upper and snap.close >= snap.bb_upper:
            score += 5
        elif snap.bb_lower and snap.close <= snap.bb_lower:
            score -= 5
        # Structural signals detected this bar
        for sig in signal.technical_signals:
            direction_bonus = 8 * sig.strength
            if sig.direction == TrendDirection.UP:
                score += direction_bonus
            elif sig.direction == TrendDirection.DOWN:
                score -= direction_bonus
        return max(0.0, min(100.0, score))

    def _score_momentum(self, signal: StrategySignal) -> float:
        snap = signal.indicator_snapshot
        hist = snap.macd_histogram
        magnitude = min(1.0, abs(hist) / max(snap.close * 0.002, 1e-9))
        base = 50.0 + (magnitude * 50.0 if hist > 0 else -magnitude * 50.0)
        return max(0.0, min(100.0, base))

    def _score_volume(self, signal: StrategySignal) -> float:
        rel_vol = signal.indicator_snapshot.relative_volume
        # Neutral at 1.0x, scales up to 100 at 3x+, down toward 30 below 0.5x
        if rel_vol >= 1.0:
            return min(100.0, 50.0 + (rel_vol - 1.0) * 25.0)
        return max(20.0, 50.0 - (1.0 - rel_vol) * 40.0)

    def _score_market_trend(self, signal: StrategySignal) -> float:
        regime_scores = {
            MarketRegime.BULL: 70.0,
            MarketRegime.BEAR: 70.0,  # trending either direction is tradeable
            MarketRegime.SIDEWAYS: 40.0,
            MarketRegime.HIGH_VOLATILITY: 35.0,
            MarketRegime.LOW_VOLATILITY: 45.0,
            MarketRegime.NEWS_EVENT: 25.0,
        }
        return regime_scores.get(signal.regime, 40.0)

    def _score_volatility(self, signal: StrategySignal) -> float:
        """Moderate volatility is favorable (room to reach target without
        stopping out on noise); extremes in either direction are penalized."""
        snap = signal.indicator_snapshot
        if snap.close <= 0:
            return 40.0
        atr_pct = (snap.atr / snap.close) * 100
        if 0.3 <= atr_pct <= 2.0:
            return 70.0
        if atr_pct > 4.0:
            return 20.0
        if atr_pct < 0.1:
            return 30.0
        return 45.0

    def _score_risk_reward(self, signal: StrategySignal) -> float:
        if not signal.suggested_stop_loss or not signal.suggested_take_profit:
            return 0.0
        entry = signal.indicator_snapshot.close
        risk = abs(entry - signal.suggested_stop_loss)
        reward = abs(signal.suggested_take_profit - entry)
        if risk <= 0:
            return 0.0
        rr = reward / risk
        return max(0.0, min(100.0, rr / 3.0 * 100.0))  # RR of 3:1 -> 100

    # -- public API --------------------------------------------------

    def evaluate(self, signal: StrategySignal) -> TradeSetup:
        breakdown = ScoreBreakdown(
            news_sentiment=self._score_news_sentiment(signal),
            technical_setup=self._score_technical_setup(signal),
            momentum=self._score_momentum(signal),
            volume=self._score_volume(signal),
            market_trend=self._score_market_trend(signal),
            volatility=self._score_volatility(signal),
            risk_reward=self._score_risk_reward(signal),
        )
        confidence = breakdown.weighted_total(self._weights)

        direction = signal.indicator_snapshot.trend_direction
        entry = signal.indicator_snapshot.close

        decision = TradeDecision.NO_TRADE
        rejection_reason: RejectionReason | None = None
        reasoning_parts = [
            f"news={breakdown.news_sentiment:.1f}",
            f"technical={breakdown.technical_setup:.1f}",
            f"momentum={breakdown.momentum:.1f}",
            f"volume={breakdown.volume:.1f}",
            f"trend={breakdown.market_trend:.1f}",
            f"volatility={breakdown.volatility:.1f}",
            f"risk_reward={breakdown.risk_reward:.1f}",
            f"confidence={confidence:.1f}",
        ]

        if confidence < self._min_confidence_threshold:
            rejection_reason = RejectionReason.BELOW_CONFIDENCE_THRESHOLD
            reasoning = "NO_TRADE: confidence below threshold (" + ", ".join(reasoning_parts) + ")"
        elif not signal.suggested_stop_loss:
            rejection_reason = RejectionReason.NO_VALID_STOP_LOSS
            reasoning = "NO_TRADE: no valid stop-loss could be derived (" + ", ".join(reasoning_parts) + ")"
        elif direction == TrendDirection.FLAT:
            rejection_reason = RejectionReason.CONFLICTING_SIGNALS
            reasoning = "NO_TRADE: no clear directional bias (" + ", ".join(reasoning_parts) + ")"
        else:
            decision = TradeDecision.ENTER_LONG if direction == TrendDirection.UP else TradeDecision.ENTER_SHORT
            reasoning = f"{decision.value.upper()}: " + ", ".join(reasoning_parts)

        return TradeSetup(
            symbol=signal.symbol,
            timestamp=signal.timestamp,
            decision=decision,
            confidence=round(confidence, 2),
            score_breakdown=breakdown,
            entry_price=entry,
            stop_loss=signal.suggested_stop_loss,
            take_profit=signal.suggested_take_profit,
            reasoning=reasoning,
            strategy_signal=signal,
            rejection_reason=rejection_reason,
        )
