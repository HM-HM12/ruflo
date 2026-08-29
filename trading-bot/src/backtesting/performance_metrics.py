"""Backtest performance metrics: total return, CAGR, win rate, avg win/loss,
profit factor, max drawdown, Sharpe, Sortino, trade count, avg holding time,
best/worst trade, monthly performance.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd


@dataclass
class ClosedTrade:
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    opened_at: datetime
    closed_at: datetime
    pnl: float
    fees: float = 0.0

    @property
    def holding_period_hours(self) -> float:
        return (self.closed_at - self.opened_at).total_seconds() / 3600


@dataclass
class PerformanceReport:
    total_return_pct: float
    cagr_pct: float
    win_rate_pct: float
    average_win: float
    average_loss: float
    profit_factor: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    num_trades: int
    average_holding_hours: float
    best_trade_pnl: float
    worst_trade_pnl: float
    monthly_returns_pct: dict = field(default_factory=dict)
    starting_equity: float = 0.0
    ending_equity: float = 0.0

    def as_dict(self) -> dict:
        return {
            "total_return_pct": round(self.total_return_pct, 4),
            "cagr_pct": round(self.cagr_pct, 4),
            "win_rate_pct": round(self.win_rate_pct, 2),
            "average_win": round(self.average_win, 2),
            "average_loss": round(self.average_loss, 2),
            "profit_factor": round(self.profit_factor, 3) if math.isfinite(self.profit_factor) else None,
            "max_drawdown_pct": round(self.max_drawdown_pct, 3),
            "sharpe_ratio": round(self.sharpe_ratio, 3),
            "sortino_ratio": round(self.sortino_ratio, 3),
            "num_trades": self.num_trades,
            "average_holding_hours": round(self.average_holding_hours, 2),
            "best_trade_pnl": round(self.best_trade_pnl, 2),
            "worst_trade_pnl": round(self.worst_trade_pnl, 2),
            "monthly_returns_pct": self.monthly_returns_pct,
            "starting_equity": self.starting_equity,
            "ending_equity": self.ending_equity,
        }


def max_drawdown_pct(equity_curve: pd.Series) -> float:
    running_max = equity_curve.cummax()
    drawdown = (equity_curve - running_max) / running_max
    return float(drawdown.min() * 100) if not drawdown.empty else 0.0


def sharpe_ratio(returns: pd.Series, periods_per_year: float, risk_free_rate: float = 0.0) -> float:
    if returns.std(ddof=1) == 0 or returns.empty:
        return 0.0
    excess = returns - risk_free_rate / periods_per_year
    return float((excess.mean() / returns.std(ddof=1)) * math.sqrt(periods_per_year))


def sortino_ratio(returns: pd.Series, periods_per_year: float, risk_free_rate: float = 0.0) -> float:
    downside = returns[returns < 0]
    downside_std = downside.std(ddof=1)
    if not downside_std or math.isnan(downside_std) or downside_std == 0:
        return 0.0
    excess = returns - risk_free_rate / periods_per_year
    return float((excess.mean() / downside_std) * math.sqrt(periods_per_year))


def compute_performance_report(
    trades: list[ClosedTrade],
    equity_curve: pd.Series,
    starting_equity: float,
    periods_per_year: float = 252.0,
) -> PerformanceReport:
    ending_equity = float(equity_curve.iloc[-1]) if not equity_curve.empty else starting_equity
    total_return_pct = ((ending_equity / starting_equity) - 1) * 100 if starting_equity else 0.0

    if not equity_curve.empty and len(equity_curve.index) > 1:
        days = max((equity_curve.index[-1] - equity_curve.index[0]).days, 1)
        years = days / 365.25
        cagr_pct = (((ending_equity / starting_equity) ** (1 / years)) - 1) * 100 if years > 0 and starting_equity > 0 else 0.0
    else:
        cagr_pct = 0.0

    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [t.pnl for t in trades if t.pnl <= 0]
    win_rate = (len(wins) / len(trades) * 100) if trades else 0.0
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 0.0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    period_returns = equity_curve.pct_change().dropna() if not equity_curve.empty else pd.Series(dtype=float)

    monthly = {}
    if not equity_curve.empty:
        monthly_equity = equity_curve.resample("ME").last()
        monthly_returns = monthly_equity.pct_change().dropna() * 100
        monthly = {ts.strftime("%Y-%m"): round(float(val), 3) for ts, val in monthly_returns.items()}

    return PerformanceReport(
        total_return_pct=total_return_pct,
        cagr_pct=cagr_pct,
        win_rate_pct=win_rate,
        average_win=avg_win,
        average_loss=avg_loss,
        profit_factor=profit_factor,
        max_drawdown_pct=max_drawdown_pct(equity_curve),
        sharpe_ratio=sharpe_ratio(period_returns, periods_per_year),
        sortino_ratio=sortino_ratio(period_returns, periods_per_year),
        num_trades=len(trades),
        average_holding_hours=float(np.mean([t.holding_period_hours for t in trades])) if trades else 0.0,
        best_trade_pnl=max((t.pnl for t in trades), default=0.0),
        worst_trade_pnl=min((t.pnl for t in trades), default=0.0),
        monthly_returns_pct=monthly,
        starting_equity=starting_equity,
        ending_equity=ending_equity,
    )
