"""Turns raw indicator columns into discrete TechnicalSignal events
(breakout, reversal, momentum, trend continuation, unusual volume) that the
strategy engine can reason about."""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from src.core.domain import TechnicalSignal
from src.core.enums import SignalType, Timeframe, TrendDirection


def _direction_from_row(row: pd.Series) -> TrendDirection:
    val = row.get("trend_direction", "flat")
    return TrendDirection(val) if val in {"up", "down", "flat"} else TrendDirection.FLAT


def detect_breakout(row: pd.Series, symbol: str, timeframe: Timeframe, ts: datetime) -> TechnicalSignal | None:
    if not bool(row.get("breakout", False)):
        return None
    direction = TrendDirection.UP if row["close"] > row.get("resistance", row["close"]) else TrendDirection.DOWN
    return TechnicalSignal(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=ts,
        signal_type=SignalType.BREAKOUT,
        direction=direction,
        strength=min(1.0, abs(row.get("relative_volume", 1.0)) / 3.0),
        details={"close": row["close"], "resistance": row.get("resistance"), "support": row.get("support")},
    )


def detect_reversal(row: pd.Series, prev_row: pd.Series, symbol: str, timeframe: Timeframe, ts: datetime) -> TechnicalSignal | None:
    """RSI crossing back out of overbought/oversold territory."""
    rsi = row.get("rsi")
    prev_rsi = prev_row.get("rsi")
    if rsi is None or prev_rsi is None:
        return None
    if prev_rsi < 30 <= rsi:
        return TechnicalSignal(
            symbol=symbol, timeframe=timeframe, timestamp=ts,
            signal_type=SignalType.REVERSAL, direction=TrendDirection.UP,
            strength=min(1.0, (rsi - 30) / 20), details={"rsi": rsi, "prev_rsi": prev_rsi},
        )
    if prev_rsi > 70 >= rsi:
        return TechnicalSignal(
            symbol=symbol, timeframe=timeframe, timestamp=ts,
            signal_type=SignalType.REVERSAL, direction=TrendDirection.DOWN,
            strength=min(1.0, (70 - rsi) / 20), details={"rsi": rsi, "prev_rsi": prev_rsi},
        )
    return None


def detect_momentum(row: pd.Series, symbol: str, timeframe: Timeframe, ts: datetime) -> TechnicalSignal | None:
    hist = row.get("macd_histogram")
    if hist is None or pd.isna(hist):
        return None
    macd_val = row.get("macd", 0.0)
    if hist > 0 and macd_val > 0:
        return TechnicalSignal(
            symbol=symbol, timeframe=timeframe, timestamp=ts,
            signal_type=SignalType.MOMENTUM, direction=TrendDirection.UP,
            strength=min(1.0, abs(hist) / max(abs(row.get("close", 1)) * 0.002, 1e-9)),
            details={"macd_histogram": hist},
        )
    if hist < 0 and macd_val < 0:
        return TechnicalSignal(
            symbol=symbol, timeframe=timeframe, timestamp=ts,
            signal_type=SignalType.MOMENTUM, direction=TrendDirection.DOWN,
            strength=min(1.0, abs(hist) / max(abs(row.get("close", 1)) * 0.002, 1e-9)),
            details={"macd_histogram": hist},
        )
    return None


def detect_trend_continuation(row: pd.Series, symbol: str, timeframe: Timeframe, ts: datetime) -> TechnicalSignal | None:
    direction = _direction_from_row(row)
    if direction == TrendDirection.FLAT:
        return None
    ema_9, ema_21, ema_50 = row.get("ema_9"), row.get("ema_21"), row.get("ema_50")
    if None in (ema_9, ema_21, ema_50) or any(pd.isna(v) for v in (ema_9, ema_21, ema_50)):
        return None
    aligned_up = ema_9 > ema_21 > ema_50
    aligned_down = ema_9 < ema_21 < ema_50
    if direction == TrendDirection.UP and aligned_up:
        return TechnicalSignal(
            symbol=symbol, timeframe=timeframe, timestamp=ts,
            signal_type=SignalType.TREND_CONTINUATION, direction=TrendDirection.UP,
            strength=0.7, details={"ema_9": ema_9, "ema_21": ema_21, "ema_50": ema_50},
        )
    if direction == TrendDirection.DOWN and aligned_down:
        return TechnicalSignal(
            symbol=symbol, timeframe=timeframe, timestamp=ts,
            signal_type=SignalType.TREND_CONTINUATION, direction=TrendDirection.DOWN,
            strength=0.7, details={"ema_9": ema_9, "ema_21": ema_21, "ema_50": ema_50},
        )
    return None


def detect_unusual_volume(row: pd.Series, symbol: str, timeframe: Timeframe, ts: datetime, threshold: float = 2.0) -> TechnicalSignal | None:
    rel_vol = row.get("relative_volume", 1.0)
    if rel_vol is None or pd.isna(rel_vol) or rel_vol < threshold:
        return None
    direction = _direction_from_row(row)
    return TechnicalSignal(
        symbol=symbol, timeframe=timeframe, timestamp=ts,
        signal_type=SignalType.UNUSUAL_VOLUME, direction=direction,
        strength=min(1.0, rel_vol / (threshold * 2)), details={"relative_volume": rel_vol},
    )


def detect_all_signals(
    df: pd.DataFrame, symbol: str, timeframe: Timeframe, idx: int = -1
) -> list[TechnicalSignal]:
    """Run all detectors against the row at `idx` (default: latest bar)."""
    row = df.iloc[idx]
    prev_row = df.iloc[idx - 1] if abs(idx) < len(df) else row
    ts = row.name if isinstance(row.name, datetime) else datetime.utcnow()

    detectors = [
        detect_breakout(row, symbol, timeframe, ts),
        detect_reversal(row, prev_row, symbol, timeframe, ts),
        detect_momentum(row, symbol, timeframe, ts),
        detect_trend_continuation(row, symbol, timeframe, ts),
        detect_unusual_volume(row, symbol, timeframe, ts),
    ]
    return [s for s in detectors if s is not None]
