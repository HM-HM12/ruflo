from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _make_ohlcv(n: int, start_price: float = 100.0, trend: float = 0.0, vol: float = 1.0, seed: int = 42, freq: str = "15min") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    returns = rng.normal(loc=trend, scale=vol / 100, size=n)
    close = start_price * np.cumprod(1 + returns)
    high = close * (1 + np.abs(rng.normal(0, 0.002, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.002, n)))
    open_ = np.roll(close, 1)
    open_[0] = start_price
    volume = rng.integers(1000, 10000, n).astype(float)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=index)


@pytest.fixture
def uptrend_ohlcv() -> pd.DataFrame:
    return _make_ohlcv(300, trend=0.0015, vol=0.8, seed=1)


@pytest.fixture
def downtrend_ohlcv() -> pd.DataFrame:
    return _make_ohlcv(300, trend=-0.0015, vol=0.8, seed=2)


@pytest.fixture
def choppy_ohlcv() -> pd.DataFrame:
    return _make_ohlcv(300, trend=0.0, vol=0.3, seed=3)


@pytest.fixture
def indicator_cfg() -> dict:
    return {
        "ema_periods": [9, 21, 50, 200],
        "rsi_period": 14,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "atr_period": 14,
        "bollinger_period": 20,
        "bollinger_std_dev": 2.0,
        "relative_volume_lookback": 20,
        "support_resistance_lookback": 50,
        "breakout_lookback": 20,
    }
