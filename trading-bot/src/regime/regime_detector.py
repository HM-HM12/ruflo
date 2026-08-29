"""Market regime detection. The strategy is deliberately more cautious — or
entirely halted — when the regime turns dangerous, per the spec's
requirement to survive first, chase returns second.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.core.enums import MarketRegime, TrendDirection
from src.features.indicators import atr, ema


class RegimeDetector:
    def __init__(
        self,
        trend_lookback: int = 50,
        high_vol_atr_percentile: float = 80,
        low_vol_atr_percentile: float = 20,
    ) -> None:
        self._trend_lookback = trend_lookback
        self._high_vol_pct = high_vol_atr_percentile
        self._low_vol_pct = low_vol_atr_percentile

    def detect(self, df: pd.DataFrame, active_news_event: bool = False) -> MarketRegime:
        """Classify the current regime from an OHLCV DataFrame. `df` must
        have at least `trend_lookback` * 2 bars for a reliable read."""
        if active_news_event:
            return MarketRegime.NEWS_EVENT

        if len(df) < self._trend_lookback * 2:
            return MarketRegime.SIDEWAYS  # insufficient history -> assume cautious default

        close = df["close"]
        atr_series = atr(df, period=14).dropna()
        if atr_series.empty:
            return MarketRegime.SIDEWAYS

        current_atr_pct = (atr_series.iloc[-1] / close.iloc[-1]) * 100
        historical_atr_pct = (atr_series / close.loc[atr_series.index]) * 100
        high_threshold = np.percentile(historical_atr_pct, self._high_vol_pct)
        low_threshold = np.percentile(historical_atr_pct, self._low_vol_pct)

        if current_atr_pct >= high_threshold:
            return MarketRegime.HIGH_VOLATILITY
        if current_atr_pct <= low_threshold:
            return MarketRegime.LOW_VOLATILITY

        ema_fast = ema(close, self._trend_lookback // 2).iloc[-1]
        ema_slow = ema(close, self._trend_lookback).iloc[-1]
        pct_diff = (ema_fast - ema_slow) / ema_slow if ema_slow else 0.0

        if pct_diff > 0.01:
            return MarketRegime.BULL
        if pct_diff < -0.01:
            return MarketRegime.BEAR
        return MarketRegime.SIDEWAYS

    @staticmethod
    def trend_direction(regime: MarketRegime) -> TrendDirection:
        return {
            MarketRegime.BULL: TrendDirection.UP,
            MarketRegime.BEAR: TrendDirection.DOWN,
        }.get(regime, TrendDirection.FLAT)

    @staticmethod
    def should_reduce_trading(regime: MarketRegime, reduce_regimes: list[str]) -> bool:
        return regime.value in reduce_regimes

    @staticmethod
    def should_halt_trading(regime: MarketRegime, halt_regimes: list[str]) -> bool:
        return regime.value in halt_regimes
