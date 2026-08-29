from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from src.core.time_utils import to_utc_timestamp


def test_naive_datetime_is_localized_to_utc():
    result = to_utc_timestamp(datetime(2024, 1, 1, 12, 0, 0))
    assert result == pd.Timestamp("2024-01-01 12:00:00", tz="UTC")


def test_utc_aware_datetime_passes_through():
    """Regression test: pd.Timestamp(dt, tz='UTC') raises ValueError when
    `dt` is already timezone-aware — and every real caller in this codebase
    (orchestrator.py, scripts/run_backtest.py) passes
    datetime.now(timezone.utc), which is exactly that case."""
    dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    result = to_utc_timestamp(dt)
    assert result == pd.Timestamp("2024-01-01 12:00:00", tz="UTC")


def test_non_utc_aware_datetime_is_converted():
    import zoneinfo
    ny = zoneinfo.ZoneInfo("America/New_York")
    dt = datetime(2024, 1, 1, 7, 0, 0, tzinfo=ny)  # UTC-5 in January
    result = to_utc_timestamp(dt)
    assert result == pd.Timestamp("2024-01-01 12:00:00", tz="UTC")
