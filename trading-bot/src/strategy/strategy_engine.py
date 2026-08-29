"""Strategy engine: fuses technical indicators, detected structural signals,
and news sentiment into a single StrategySignal — the input to the AI
decision engine. This module does NOT decide whether to trade; it only
assembles evidence.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from src.core.domain import IndicatorSnapshot, NewsEvent, StrategySignal
from src.core.enums import AssetClass, MarketRegime, Timeframe, TrendDirection
from src.features.indicators import compute_all
from src.features.market_structure import detect_all_signals
from src.regime.regime_detector import RegimeDetector


def build_indicator_snapshot(df: pd.DataFrame, symbol: str, timeframe: Timeframe) -> IndicatorSnapshot:
    row = df.iloc[-1]
    ts = row.name if isinstance(row.name, datetime) else datetime.utcnow()
    trend = row.get("trend_direction", "flat")
    return IndicatorSnapshot(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=ts,
        close=float(row["close"]),
        ema_9=float(row.get("ema_9", float("nan"))),
        ema_21=float(row.get("ema_21", float("nan"))),
        ema_50=float(row.get("ema_50", float("nan"))),
        ema_200=float(row.get("ema_200", float("nan"))),
        rsi=float(row.get("rsi", 50.0)),
        macd=float(row.get("macd", 0.0)),
        macd_signal=float(row.get("macd_signal", 0.0)),
        macd_histogram=float(row.get("macd_histogram", 0.0)),
        vwap=float(row.get("vwap", row["close"])),
        atr=float(row.get("atr", 0.0)),
        bb_upper=float(row.get("bb_upper", float("nan"))),
        bb_middle=float(row.get("bb_middle", float("nan"))),
        bb_lower=float(row.get("bb_lower", float("nan"))),
        volume=float(row.get("volume", 0.0)),
        relative_volume=float(row.get("relative_volume", 1.0)),
        nearest_support=float(row["support"]) if pd.notna(row.get("support")) else None,
        nearest_resistance=float(row["resistance"]) if pd.notna(row.get("resistance")) else None,
        trend_direction=TrendDirection(trend) if trend in {"up", "down", "flat"} else TrendDirection.FLAT,
    )


class StrategyEngine:
    def __init__(self, indicator_cfg: dict, regime_detector: RegimeDetector | None = None) -> None:
        self._indicator_cfg = indicator_cfg
        self._regime_detector = regime_detector or RegimeDetector()

    def enrich(self, ohlcv: pd.DataFrame) -> pd.DataFrame:
        """Compute the full indicator set once. Exposed separately from
        build_signal so callers that need to evaluate many timestamps over
        the same history — the backtester, chiefly — can compute indicators
        ONCE up front and slice the causal result, instead of recomputing
        the full indicator set (including the O(n) support/resistance scan)
        from scratch on every single bar. Recomputing per-bar previously
        made a full backtest run O(n^2); see build_signal_from_enriched."""
        return compute_all(ohlcv, self._indicator_cfg)

    def build_signal(
        self,
        symbol: str,
        asset_class: AssetClass,
        timeframe: Timeframe,
        ohlcv: pd.DataFrame,
        related_news: list[NewsEvent],
        active_news_event: bool = False,
    ) -> StrategySignal:
        """`ohlcv` must already be trimmed to "as of now" — no future bars —
        by the caller (backtester or live data loop). For live/paper
        trading this recomputes indicators once per cycle, which is fine;
        for backtesting, prefer enrich() + build_signal_from_enriched()."""
        enriched = self.enrich(ohlcv)
        return self.build_signal_from_enriched(symbol, asset_class, timeframe, enriched, related_news, active_news_event)

    def build_signal_from_enriched(
        self,
        symbol: str,
        asset_class: AssetClass,
        timeframe: Timeframe,
        enriched: pd.DataFrame,
        related_news: list[NewsEvent],
        active_news_event: bool = False,
    ) -> StrategySignal:
        """Build a signal from a DataFrame that has ALREADY had indicators
        computed (via enrich()/compute_all). `enriched` may be a slice of a
        larger precomputed frame — since every indicator in compute_all is
        strictly causal (see tests/test_indicators.py's no-look-ahead
        regression tests), slicing after the fact is equivalent to having
        computed indicators on the slice alone."""
        snapshot = build_indicator_snapshot(enriched, symbol, timeframe)
        technical_signals = detect_all_signals(enriched, symbol, timeframe)
        regime = self._regime_detector.detect(enriched, active_news_event=active_news_event)

        stop_loss, take_profit = self._suggest_stop_and_target(snapshot)

        return StrategySignal(
            symbol=symbol,
            asset_class=asset_class,
            timestamp=snapshot.timestamp,
            direction=snapshot.trend_direction,
            indicator_snapshot=snapshot,
            related_news=related_news,
            technical_signals=technical_signals,
            regime=regime,
            suggested_stop_loss=stop_loss,
            suggested_take_profit=take_profit,
        )

    def _suggest_stop_and_target(self, snapshot: IndicatorSnapshot) -> tuple[float | None, float | None]:
        """ATR-based stop suggestion; the risk manager independently
        validates and may override this — it is a suggestion, not policy."""
        if snapshot.atr <= 0:
            return None, None
        atr_multiple = 1.5
        rr_ratio = 2.0
        if snapshot.trend_direction == TrendDirection.UP:
            stop = snapshot.close - atr_multiple * snapshot.atr
            target = snapshot.close + atr_multiple * snapshot.atr * rr_ratio
        elif snapshot.trend_direction == TrendDirection.DOWN:
            stop = snapshot.close + atr_multiple * snapshot.atr
            target = snapshot.close - atr_multiple * snapshot.atr * rr_ratio
        else:
            return None, None
        return round(stop, 4), round(target, 4)
