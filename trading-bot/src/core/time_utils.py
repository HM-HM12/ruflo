"""Timezone-safe datetime helpers shared by every market data provider.

`pd.Timestamp(dt, tz="UTC")` raises ValueError if `dt` is already
timezone-aware ("Cannot pass a datetime or Timestamp with tzinfo with the
tz parameter") — and every real caller in this codebase (orchestrator.py,
scripts/run_backtest.py) passes `datetime.now(timezone.utc)`, which *is*
timezone-aware. `to_utc_timestamp` handles both cases correctly so
providers can enforce their no-look-ahead truncation without this trap.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd


def to_utc_timestamp(dt: datetime | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(dt)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
