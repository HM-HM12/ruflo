"""Trading Journal: records every AI decision — executed or rejected — plus
the full trade lifecycle. Works against the async database session when
available, and always keeps an in-memory copy so the backtester and unit
tests don't require a live database.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.core.domain import RiskCheckResult, TradeSetup
from src.core.enums import RejectionReason, TradeDecision


@dataclass
class JournalEntry:
    timestamp: datetime
    symbol: str
    decision: TradeDecision
    confidence: float
    score_breakdown: dict
    was_executed: bool
    reasoning: str
    market_regime: str
    rejection_reason: RejectionReason | None = None
    rejection_detail: str = ""
    trade_id: str | None = None


@dataclass
class TradeJournal:
    entries: list[JournalEntry] = field(default_factory=list)

    def record_decision(self, setup: TradeSetup, risk_result: RiskCheckResult | None, trade_id: str | None = None) -> JournalEntry:
        was_executed = bool(risk_result and risk_result.approved)
        rejection_reason = setup.rejection_reason or (risk_result.reason if risk_result else None)
        rejection_detail = risk_result.detail if risk_result and not risk_result.approved else ""

        entry = JournalEntry(
            timestamp=setup.timestamp,
            symbol=setup.symbol,
            decision=setup.decision,
            confidence=setup.confidence,
            score_breakdown={
                "news_sentiment": setup.score_breakdown.news_sentiment,
                "technical_setup": setup.score_breakdown.technical_setup,
                "momentum": setup.score_breakdown.momentum,
                "volume": setup.score_breakdown.volume,
                "market_trend": setup.score_breakdown.market_trend,
                "volatility": setup.score_breakdown.volatility,
                "risk_reward": setup.score_breakdown.risk_reward,
            },
            was_executed=was_executed,
            reasoning=setup.reasoning,
            market_regime=setup.strategy_signal.regime.value,
            rejection_reason=rejection_reason,
            rejection_detail=rejection_detail,
            trade_id=trade_id,
        )
        self.entries.append(entry)
        return entry

    def rejected_entries(self) -> list[JournalEntry]:
        return [e for e in self.entries if not e.was_executed]

    def executed_entries(self) -> list[JournalEntry]:
        return [e for e in self.entries if e.was_executed]

    def rejection_reason_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.rejected_entries():
            if entry.rejection_reason:
                key = entry.rejection_reason.value
                counts[key] = counts.get(key, 0) + 1
        return counts


async def persist_entry(session, entry: JournalEntry) -> None:
    """Persist a JournalEntry to the database. Import lazily to keep the
    journal usable in pure in-memory contexts (backtesting, unit tests)
    without a database dependency."""
    from src.db.models import JournalEntryRecord

    record = JournalEntryRecord(
        timestamp=entry.timestamp,
        symbol=entry.symbol,
        decision=entry.decision.value,
        confidence=entry.confidence,
        score_breakdown=entry.score_breakdown,
        was_executed=entry.was_executed,
        rejection_reason=entry.rejection_reason.value if entry.rejection_reason else None,
        rejection_detail=entry.rejection_detail,
        reasoning=entry.reasoning,
        market_regime=entry.market_regime,
        trade_id=entry.trade_id,
    )
    session.add(record)
    await session.commit()
