"""Technical indicators, implemented directly on pandas/NumPy so the project
has no hard dependency on TA-Lib's C extension (which is often painful to
install). Every function is pure and takes/returns pandas Series aligned to
the input DataFrame's index — no hidden state, easy to unit test.

Expects OHLCV DataFrames with columns: open, high, low, close, volume.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = {"open", "high", "low", "close", "volume"}


def _validate(df: pd.DataFrame) -> None:
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"OHLCV DataFrame missing columns: {missing}")


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    # Wilder's smoothing (equivalent to an EMA with alpha = 1/period)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + rs))
    return result.fillna(50.0).where(avg_loss != 0, 100.0)


def macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def true_range(df: pd.DataFrame) -> pd.Series:
    _validate(df)
    prev_close = df["close"].shift(1)
    ranges = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = true_range(df)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def bollinger_bands(
    series: pd.Series, period: int = 20, std_dev: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    middle = sma(series, period)
    std = series.rolling(window=period, min_periods=period).std()
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    return upper, middle, lower


def vwap(df: pd.DataFrame) -> pd.Series:
    """Session-cumulative VWAP. Assumes the DataFrame index is a single
    trading session; for multi-day data, group by date before calling."""
    _validate(df)
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    cumulative_pv = (typical_price * df["volume"]).cumsum()
    cumulative_vol = df["volume"].cumsum().replace(0, np.nan)
    # ffill (not bfill!) for the degenerate zero-cumulative-volume edge
    # case — filling from the future would be a look-ahead violation, even
    # if this only ever bites the first bar or two.
    return (cumulative_pv / cumulative_vol).ffill().fillna(typical_price)


def vwap_by_session(df: pd.DataFrame) -> pd.Series:
    """VWAP that resets at each new calendar day, for multi-day intraday data."""
    _validate(df)
    session = df.index.normalize() if isinstance(df.index, pd.DatetimeIndex) else None
    if session is None:
        return vwap(df)
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    pv = typical_price * df["volume"]
    grouped_pv = pv.groupby(session).cumsum()
    grouped_vol = df["volume"].groupby(session).cumsum().replace(0, np.nan)
    # See vwap() above: ffill only, never bfill — no look-ahead.
    return (grouped_pv / grouped_vol).ffill().fillna(typical_price)


def relative_volume(volume: pd.Series, lookback: int = 20) -> pd.Series:
    """Current volume vs. the trailing average (excluding the current bar)."""
    avg_volume = volume.shift(1).rolling(window=lookback, min_periods=lookback).mean()
    return (volume / avg_volume.replace(0, np.nan)).fillna(1.0)


def support_resistance(df: pd.DataFrame, lookback: int = 50, order: int = 3) -> tuple[pd.Series, pd.Series]:
    """Rolling nearest support/resistance from local swing highs/lows.

    A swing high/low can only be *confirmed* once `order` bars have passed
    on both sides of it — so, to stay strictly causal (no look-ahead), a
    candidate at bar (i - order) is confirmed using only data through bar i:
    it must be the max/min within the trailing window [i - 2*order, i].
    This means swing-point confirmation lags real time by `order` bars,
    exactly as it would for a live trader watching the same chart.
    """
    _validate(df)
    highs = df["high"]
    lows = df["low"]
    closes = df["close"]

    candidate_high = highs.shift(order)
    candidate_low = lows.shift(order)
    trailing_max = highs.rolling(window=2 * order + 1, min_periods=1).max()
    trailing_min = lows.rolling(window=2 * order + 1, min_periods=1).min()

    is_swing_high = candidate_high == trailing_max
    is_swing_low = candidate_low == trailing_min

    swing_high_prices = candidate_high.where(is_swing_high)
    swing_low_prices = candidate_low.where(is_swing_low)

    support = pd.Series(index=df.index, dtype=float)
    resistance = pd.Series(index=df.index, dtype=float)

    sh_window = swing_high_prices.rolling(window=lookback, min_periods=1)
    sl_window = swing_low_prices.rolling(window=lookback, min_periods=1)

    for i in range(len(df)):
        start = max(0, i - lookback)
        close = closes.iloc[i]
        window_highs = swing_high_prices.iloc[start : i + 1].dropna()
        window_lows = swing_low_prices.iloc[start : i + 1].dropna()

        above = window_highs[window_highs > close]
        below = window_lows[window_lows < close]

        resistance.iloc[i] = above.min() if not above.empty else np.nan
        support.iloc[i] = below.max() if not below.empty else np.nan

    return support, resistance


def breakout_detected(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    """True where the close breaks above the prior `lookback`-bar high or
    below the prior `lookback`-bar low."""
    _validate(df)
    prior_high = df["high"].shift(1).rolling(window=lookback, min_periods=lookback).max()
    prior_low = df["low"].shift(1).rolling(window=lookback, min_periods=lookback).min()
    return (df["close"] > prior_high) | (df["close"] < prior_low)


def trend_direction_series(close: pd.Series, fast: int = 21, slow: int = 200) -> pd.Series:
    """Simple EMA-cross trend classification: up / down / flat."""
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    diff_pct = (ema_fast - ema_slow) / ema_slow.replace(0, np.nan)
    direction = pd.Series("flat", index=close.index, dtype=object)
    direction[diff_pct > 0.0015] = "up"
    direction[diff_pct < -0.0015] = "down"
    return direction


def compute_all(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Compute the full indicator set used by the strategy engine and attach
    as new columns on a copy of the input DataFrame."""
    _validate(df)
    out = df.copy()

    for period in cfg.get("ema_periods", [9, 21, 50, 200]):
        out[f"ema_{period}"] = ema(out["close"], period)

    out["rsi"] = rsi(out["close"], cfg.get("rsi_period", 14))

    macd_line, signal_line, hist = macd(
        out["close"],
        cfg.get("macd_fast", 12),
        cfg.get("macd_slow", 26),
        cfg.get("macd_signal", 9),
    )
    out["macd"] = macd_line
    out["macd_signal"] = signal_line
    out["macd_histogram"] = hist

    out["atr"] = atr(out, cfg.get("atr_period", 14))

    bb_upper, bb_middle, bb_lower = bollinger_bands(
        out["close"], cfg.get("bollinger_period", 20), cfg.get("bollinger_std_dev", 2.0)
    )
    out["bb_upper"] = bb_upper
    out["bb_middle"] = bb_middle
    out["bb_lower"] = bb_lower

    out["vwap"] = vwap_by_session(out)
    out["relative_volume"] = relative_volume(out["volume"], cfg.get("relative_volume_lookback", 20))
    out["breakout"] = breakout_detected(out, cfg.get("breakout_lookback", 20))
    out["trend_direction"] = trend_direction_series(out["close"])

    support, resistance = support_resistance(out, cfg.get("support_resistance_lookback", 50))
    out["support"] = support
    out["resistance"] = resistance

    return out
