from __future__ import annotations

import numpy as np
import pandas as pd

from src.features.indicators import (
    atr,
    bollinger_bands,
    breakout_detected,
    compute_all,
    ema,
    macd,
    relative_volume,
    rsi,
    sma,
)


def test_ema_converges_to_price_in_flat_series():
    series = pd.Series([100.0] * 50)
    result = ema(series, 10)
    assert abs(result.iloc[-1] - 100.0) < 1e-6


def test_sma_matches_manual_average():
    series = pd.Series(range(1, 11), dtype=float)
    result = sma(series, 5)
    assert result.iloc[-1] == np.mean([6, 7, 8, 9, 10])


def test_rsi_is_bounded_0_100(uptrend_ohlcv):
    result = rsi(uptrend_ohlcv["close"])
    valid = result.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()


def test_rsi_high_in_strong_uptrend(uptrend_ohlcv):
    result = rsi(uptrend_ohlcv["close"], period=14)
    # A persistent uptrend should push RSI well above the neutral midpoint.
    assert result.iloc[-1] > 55


def test_macd_returns_three_aligned_series(uptrend_ohlcv):
    macd_line, signal_line, hist = macd(uptrend_ohlcv["close"])
    assert len(macd_line) == len(signal_line) == len(hist) == len(uptrend_ohlcv)
    # histogram should equal macd - signal wherever both are defined
    both_defined = macd_line.notna() & signal_line.notna()
    pd.testing.assert_series_equal(
        hist[both_defined], (macd_line - signal_line)[both_defined], check_names=False
    )


def test_atr_non_negative(uptrend_ohlcv):
    result = atr(uptrend_ohlcv)
    assert (result.dropna() >= 0).all()


def test_bollinger_bands_ordering(uptrend_ohlcv):
    upper, middle, lower = bollinger_bands(uptrend_ohlcv["close"])
    valid = upper.notna() & middle.notna() & lower.notna()
    assert (upper[valid] >= middle[valid]).all()
    assert (middle[valid] >= lower[valid]).all()


def test_relative_volume_neutral_when_flat():
    volume = pd.Series([1000.0] * 30)
    result = relative_volume(volume, lookback=10)
    assert abs(result.iloc[-1] - 1.0) < 1e-6


def test_breakout_detects_new_high():
    n = 30
    close = pd.Series([100.0] * (n - 1) + [200.0])
    high = close + 1
    low = close - 1
    open_ = close.copy()
    volume = pd.Series([1000.0] * n)
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})
    result = breakout_detected(df, lookback=20)
    assert bool(result.iloc[-1]) is True
    assert not bool(result.iloc[10])


def test_compute_all_produces_expected_columns(uptrend_ohlcv, indicator_cfg):
    out = compute_all(uptrend_ohlcv, indicator_cfg)
    expected_cols = {"ema_9", "ema_21", "ema_50", "ema_200", "rsi", "macd", "macd_signal",
                      "macd_histogram", "atr", "bb_upper", "bb_middle", "bb_lower", "vwap",
                      "relative_volume", "breakout", "trend_direction", "support", "resistance"}
    assert expected_cols.issubset(set(out.columns))
    assert len(out) == len(uptrend_ohlcv)


def test_no_look_ahead_indicators_stable_when_future_bars_appended(uptrend_ohlcv, indicator_cfg):
    """Critical correctness property for backtesting: indicator values up to
    bar N must not change when more bars are appended after N."""
    truncated = uptrend_ohlcv.iloc[:250]
    full = uptrend_ohlcv

    out_truncated = compute_all(truncated, indicator_cfg)
    out_full = compute_all(full, indicator_cfg)

    # EMA/RSI/MACD/support/resistance are all strictly causal (no centered
    # windows) so they must match exactly regardless of what comes after.
    for col in ["ema_9", "ema_21", "rsi", "macd", "atr", "vwap", "support", "resistance"]:
        pd.testing.assert_series_equal(
            out_truncated[col].iloc[:240], out_full[col].iloc[:240], check_names=False, atol=1e-8
        )


def test_support_resistance_does_not_use_future_bars():
    """Regression test for a look-ahead bug: swing high/low detection must
    only use bars available up to the current index, never peek forward."""
    from src.features.indicators import support_resistance

    n = 60
    high = pd.Series([100.0] * n)
    low = pd.Series([99.0] * n)
    close = pd.Series([99.5] * n)
    open_ = close.copy()
    volume = pd.Series([1000.0] * n)

    # Plant an obvious spike far in the future that should NOT affect
    # support/resistance computed at earlier bars.
    high.iloc[50] = 500.0
    low.iloc[50] = 500.0

    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})
    support, resistance = support_resistance(df, lookback=50, order=3)

    # At bar 30 (well before the spike at 50), resistance must not reflect
    # a level that could only be known by looking ahead to bar 50.
    assert pd.isna(resistance.iloc[30]) or resistance.iloc[30] < 500.0
