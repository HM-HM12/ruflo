"""Shared enumerations used across every module. Single source of truth for
domain vocabulary so modules never compare against raw strings."""
from __future__ import annotations

from enum import Enum


class Timeframe(str, Enum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"


class AssetClass(str, Enum):
    STOCK = "stock"
    ETF = "etf"
    CRYPTO = "crypto"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class PositionStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class TradeDecision(str, Enum):
    """The AI decision engine's only possible outputs. NO_TRADE is a
    first-class result, not an absence of one."""

    ENTER_LONG = "enter_long"
    ENTER_SHORT = "enter_short"
    NO_TRADE = "no_trade"


class RejectionReason(str, Enum):
    BELOW_CONFIDENCE_THRESHOLD = "below_confidence_threshold"
    RISK_MANAGER_VETO = "risk_manager_veto"
    DAILY_LOSS_LIMIT_REACHED = "daily_loss_limit_reached"
    MAX_TRADES_PER_DAY_REACHED = "max_trades_per_day_reached"
    MAX_OPEN_POSITIONS_REACHED = "max_open_positions_reached"
    MAX_EXPOSURE_PER_ASSET_REACHED = "max_exposure_per_asset_reached"
    CIRCUIT_BREAKER_ACTIVE = "circuit_breaker_active"
    KILL_SWITCH_ACTIVE = "kill_switch_active"
    NO_VALID_STOP_LOSS = "no_valid_stop_loss"
    DANGEROUS_MARKET_REGIME = "dangerous_market_regime"
    STALE_DATA = "stale_data"
    DUPLICATE_NEWS_EVENT = "duplicate_news_event"
    CONFLICTING_SIGNALS = "conflicting_signals"


class NewsSentiment(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class NewsCategory(str, Enum):
    EARNINGS = "earnings"
    SEC_FILING = "sec_filing"
    ANALYST_RATING = "analyst_rating"
    MERGER_ACQUISITION = "merger_acquisition"
    LAWSUIT_REGULATORY = "lawsuit_regulatory"
    ECONOMIC_DATA = "economic_data"
    INTEREST_RATE = "interest_rate"
    GEOPOLITICAL = "geopolitical"
    GUIDANCE = "guidance"
    OTHER = "other"


class MarketRegime(str, Enum):
    BULL = "bull"
    BEAR = "bear"
    SIDEWAYS = "sideways"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"
    NEWS_EVENT = "news_event"


class TrendDirection(str, Enum):
    UP = "up"
    DOWN = "down"
    FLAT = "flat"


class SignalType(str, Enum):
    BREAKOUT = "breakout"
    REVERSAL = "reversal"
    MOMENTUM = "momentum"
    TREND_CONTINUATION = "trend_continuation"
    UNUSUAL_VOLUME = "unusual_volume"


class BrokerMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class AlertLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertEvent(str, Enum):
    TRADE_OPENED = "trade_opened"
    TRADE_CLOSED = "trade_closed"
    BREAKING_NEWS = "breaking_news"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    API_DISCONNECT = "api_disconnect"
    BOT_CRASH = "bot_crash"
    RISK_LIMIT_EXCEEDED = "risk_limit_exceeded"
    UNUSUAL_MARKET_CONDITIONS = "unusual_market_conditions"
    KILL_SWITCH_TRIGGERED = "kill_switch_triggered"
