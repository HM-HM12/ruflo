"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-29
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "news_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("symbol", sa.String(20), nullable=True),
        sa.Column("headline", sa.Text, nullable=False),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("sentiment", sa.String(10), nullable=False),
        sa.Column("sentiment_score", sa.Float, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("impact_estimate", sa.Float, nullable=False),
        sa.Column("url", sa.String(500), server_default=""),
    )
    op.create_index("ix_news_events_symbol", "news_events", ["symbol"])
    op.create_index("ix_news_events_published_at", "news_events", ["published_at"])

    op.create_table(
        "trades",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("entry_price", sa.Float, nullable=False),
        sa.Column("exit_price", sa.Float, nullable=True),
        sa.Column("quantity", sa.Float, nullable=False),
        sa.Column("stop_loss", sa.Float, nullable=True),
        sa.Column("take_profit", sa.Float, nullable=True),
        sa.Column("trailing_stop", sa.Float, nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("realized_pnl", sa.Float, nullable=True),
        sa.Column("fees", sa.Float, server_default="0"),
        sa.Column("slippage", sa.Float, server_default="0"),
        sa.Column("ai_confidence", sa.Float, nullable=False),
        sa.Column("market_regime", sa.String(30), nullable=False),
        sa.Column("entry_reason", sa.Text, nullable=False),
        sa.Column("exit_reason", sa.Text, nullable=True),
        sa.Column("news_event_id", sa.String(36), sa.ForeignKey("news_events.id"), nullable=True),
        sa.Column("news_sentiment", sa.String(10), nullable=True),
        sa.Column("technical_signals", sa.JSON, nullable=True),
        sa.Column("is_paper", sa.Boolean, server_default=sa.true()),
    )
    op.create_index("ix_trades_symbol", "trades", ["symbol"])

    op.create_table(
        "journal_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("score_breakdown", sa.JSON, nullable=True),
        sa.Column("was_executed", sa.Boolean, server_default=sa.false()),
        sa.Column("rejection_reason", sa.String(50), nullable=True),
        sa.Column("rejection_detail", sa.Text, nullable=True),
        sa.Column("reasoning", sa.Text, nullable=False),
        sa.Column("market_regime", sa.String(30), nullable=False),
        sa.Column("trade_id", sa.String(36), sa.ForeignKey("trades.id"), nullable=True),
    )
    op.create_index("ix_journal_entries_timestamp", "journal_entries", ["timestamp"])
    op.create_index("ix_journal_entries_symbol", "journal_entries", ["symbol"])

    op.create_table(
        "equity_snapshots",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("equity", sa.Float, nullable=False),
        sa.Column("cash", sa.Float, nullable=False),
        sa.Column("open_positions_count", sa.Integer, nullable=False),
        sa.Column("daily_realized_pnl", sa.Float, nullable=False),
        sa.Column("market_regime", sa.String(30), nullable=False),
    )
    op.create_index("ix_equity_snapshots_timestamp", "equity_snapshots", ["timestamp"])

    op.create_table(
        "alerts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("level", sa.String(10), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("delivered_channels", sa.JSON, nullable=True),
    )
    op.create_index("ix_alerts_timestamp", "alerts", ["timestamp"])

    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("strategy_config", sa.JSON, nullable=True),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbols", sa.JSON, nullable=True),
        sa.Column("metrics", sa.JSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("backtest_runs")
    op.drop_table("alerts")
    op.drop_index("ix_equity_snapshots_timestamp", table_name="equity_snapshots")
    op.drop_table("equity_snapshots")
    op.drop_index("ix_journal_entries_symbol", table_name="journal_entries")
    op.drop_index("ix_journal_entries_timestamp", table_name="journal_entries")
    op.drop_table("journal_entries")
    op.drop_index("ix_trades_symbol", table_name="trades")
    op.drop_table("trades")
    op.drop_index("ix_news_events_published_at", table_name="news_events")
    op.drop_index("ix_news_events_symbol", table_name="news_events")
    op.drop_table("news_events")
