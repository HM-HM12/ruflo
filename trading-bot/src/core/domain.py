"""Value objects shared across the pipeline. These are the in-memory
contracts between modules — deliberately separate from the SQLAlchemy models
in db/models.py so the domain logic never depends on persistence details.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.core.enums import (
    AssetClass,
    MarketRegime,
    NewsCategory,
    NewsSentiment,
    OrderSide,
    OrderStatus,
    OrderType,
    RejectionReason,
    SignalType,
    Timeframe,
    TradeDecision,
    TrendDirection,
)


@dataclass(frozen=True, slots=True)
class MarketBar:
    symbol: str
    timeframe: Timeframe
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        if self.high < self.low:
            raise ValueError(f"{self.symbol}: high < low in bar at {self.timestamp}")
        if self.volume < 0:
            raise ValueError(f"{self.symbol}: negative volume at {self.timestamp}")


@dataclass(frozen=True, slots=True)
class Quote:
    symbol: str
    timestamp: datetime
    bid: float
    ask: float
    bid_size: float = 0.0
    ask_size: float = 0.0

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def spread_bps(self) -> float:
        return (self.spread / self.mid) * 10_000 if self.mid else 0.0


@dataclass(frozen=True, slots=True)
class NewsEvent:
    """A single deduplicated news/event item after sentiment analysis."""

    id: str
    symbol: Optional[str]
    headline: str
    source: str
    published_at: datetime
    category: NewsCategory
    sentiment: NewsSentiment
    sentiment_score: float  # -1.0 (max bearish) .. +1.0 (max bullish)
    confidence: float  # 0.0 .. 1.0
    impact_estimate: float  # 0.0 .. 1.0, estimated market-moving potential
    fingerprint: str  # dedup key (normalized headline + entity + rough time bucket)
    url: str = ""
    raw_summary: str = ""


@dataclass(frozen=True, slots=True)
class TechnicalSignal:
    symbol: str
    timeframe: Timeframe
    timestamp: datetime
    signal_type: SignalType
    direction: TrendDirection
    strength: float  # 0.0 .. 1.0
    details: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IndicatorSnapshot:
    """All computed indicator values for one symbol/timeframe/timestamp —
    the direct input to strategy fusion and the AI decision engine."""

    symbol: str
    timeframe: Timeframe
    timestamp: datetime
    close: float
    ema_9: float
    ema_21: float
    ema_50: float
    ema_200: float
    rsi: float
    macd: float
    macd_signal: float
    macd_histogram: float
    vwap: float
    atr: float
    bb_upper: float
    bb_middle: float
    bb_lower: float
    volume: float
    relative_volume: float
    nearest_support: Optional[float]
    nearest_resistance: Optional[float]
    trend_direction: TrendDirection


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    news_sentiment: float
    technical_setup: float
    momentum: float
    volume: float
    market_trend: float
    volatility: float
    risk_reward: float

    def weighted_total(self, weights: dict) -> float:
        return sum(getattr(self, k) * w for k, w in weights.items())


@dataclass(frozen=True, slots=True)
class StrategySignal:
    """Fused technical + sentiment signal, the input to the AI decision
    engine — not yet a trade decision."""

    symbol: str
    asset_class: AssetClass
    timestamp: datetime
    direction: TrendDirection
    indicator_snapshot: IndicatorSnapshot
    related_news: list[NewsEvent]
    technical_signals: list[TechnicalSignal]
    regime: MarketRegime
    suggested_stop_loss: Optional[float] = None
    suggested_take_profit: Optional[float] = None


@dataclass(frozen=True, slots=True)
class TradeSetup:
    """Output of the AI decision engine: a scored, fully-specified proposal
    that still must clear the risk manager before becoming an order."""

    symbol: str
    timestamp: datetime
    decision: TradeDecision
    confidence: float  # 0-100
    score_breakdown: ScoreBreakdown
    entry_price: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    reasoning: str
    strategy_signal: StrategySignal
    rejection_reason: Optional[RejectionReason] = None


@dataclass(frozen=True, slots=True)
class RiskCheckResult:
    approved: bool
    reason: Optional[RejectionReason]
    max_position_size: float = 0.0
    risked_amount: float = 0.0
    detail: str = ""


@dataclass
class Order:
    id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    average_fill_price: Optional[float] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    client_order_id: str = ""
    parent_trade_id: Optional[str] = None


@dataclass(frozen=True, slots=True)
class Fill:
    order_id: str
    symbol: str
    side: OrderSide
    quantity: float
    price: float
    timestamp: datetime
    fee: float = 0.0
    slippage: float = 0.0


@dataclass
class Position:
    symbol: str
    side: OrderSide
    quantity: float
    entry_price: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    opened_at: datetime
    trailing_stop_price: Optional[float] = None
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0

    def market_value(self, current_price: float) -> float:
        return self.quantity * current_price

    def compute_unrealized_pnl(self, current_price: float) -> float:
        direction = 1 if self.side == OrderSide.BUY else -1
        return direction * (current_price - self.entry_price) * self.quantity
