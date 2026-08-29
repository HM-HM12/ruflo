"""Domain exceptions. Keeping these distinct from generic exceptions lets the
orchestrator and API layer catch precisely what they mean to handle."""


class TradingBotError(Exception):
    """Base class for all trading-bot domain errors."""


class RiskLimitExceeded(TradingBotError):
    """Raised when an action would violate a hard risk limit."""


class KillSwitchActive(TradingBotError):
    """Raised when an action is attempted while a kill switch is engaged."""


class InvalidStopLoss(TradingBotError):
    """Raised when an order would be submitted without a valid stop-loss."""


class LiveTradingNotConfirmed(TradingBotError):
    """Raised when live trading is attempted without explicit, multi-step
    confirmation. Paper trading is the only mode enabled by default."""


class BrokerConnectionError(TradingBotError):
    """Raised on broker/exchange API connectivity failures."""


class DataProviderError(TradingBotError):
    """Raised on market or news data provider failures."""


class InsufficientDataError(TradingBotError):
    """Raised when there isn't enough historical data to compute a feature."""


class BacktestConfigError(TradingBotError):
    """Raised for invalid backtest configuration (e.g. date ranges that would
    introduce look-ahead bias)."""
