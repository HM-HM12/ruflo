"""SQLAlchemy ORM models — the database schema. Every trade, every AI
decision (including ones the risk manager or decision engine rejected), and
every news event the bot reacted to is persisted here for audit and
post-mortem analysis.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class TradeRecord(Base):
    __tablename__ = "trades"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    side: Mapped[str] = mapped_column(String(10))
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    trailing_stop: Mapped[float | None] = mapped_column(Float, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    fees: Mapped[float] = mapped_column(Float, default=0.0)
    slippage: Mapped[float] = mapped_column(Float, default=0.0)
    ai_confidence: Mapped[float] = mapped_column(Float)
    market_regime: Mapped[str] = mapped_column(String(30))
    entry_reason: Mapped[str] = mapped_column(Text)
    exit_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    news_event_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("news_events.id"), nullable=True)
    news_sentiment: Mapped[str | None] = mapped_column(String(10), nullable=True)
    technical_signals: Mapped[dict] = mapped_column(JSON, default=dict)
    is_paper: Mapped[bool] = mapped_column(Boolean, default=True)

    news_event: Mapped["NewsEventRecord | None"] = relationship(back_populates="trades")
    journal_entries: Mapped[list["JournalEntryRecord"]] = relationship(back_populates="trade")


class JournalEntryRecord(Base):
    """Every AI decision, whether or not it resulted in a trade. Rejected
    setups are recorded with their reason so the bot's judgement can be
    audited after the fact."""

    __tablename__ = "journal_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    decision: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[float] = mapped_column(Float)
    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    was_executed: Mapped[bool] = mapped_column(Boolean, default=False)
    rejection_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    rejection_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasoning: Mapped[str] = mapped_column(Text)
    market_regime: Mapped[str] = mapped_column(String(30))
    trade_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("trades.id"), nullable=True)

    trade: Mapped["TradeRecord | None"] = relationship(back_populates="journal_entries")


class NewsEventRecord(Base):
    __tablename__ = "news_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # fingerprint
    symbol: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    headline: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(100))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    category: Mapped[str] = mapped_column(String(30))
    sentiment: Mapped[str] = mapped_column(String(10))
    sentiment_score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    impact_estimate: Mapped[float] = mapped_column(Float)
    url: Mapped[str] = mapped_column(String(500), default="")

    trades: Mapped[list["TradeRecord"]] = relationship(back_populates="news_event")


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    equity: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)
    open_positions_count: Mapped[int] = mapped_column(Integer)
    daily_realized_pnl: Mapped[float] = mapped_column(Float)
    market_regime: Mapped[str] = mapped_column(String(30))


class AlertRecord(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    level: Mapped[str] = mapped_column(String(10))
    event_type: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    delivered_channels: Mapped[dict] = mapped_column(JSON, default=dict)


class BacktestRunRecord(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    strategy_config: Mapped[dict] = mapped_column(JSON, default=dict)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    symbols: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
