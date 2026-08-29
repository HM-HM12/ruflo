"""Centralized application settings loaded from environment variables.

Never hard-code credentials. Every secret below is read from the environment
(or a local .env file, via pydantic-settings) and nothing is committed.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Environment ---------------------------------------------------
    environment: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"

    # --- Trading mode (safety-critical) ---------------------------------
    # Paper trading is the ONLY mode enabled by default. Flipping to live
    # trading requires setting BOTH of the following to true explicitly,
    # plus a manual confirmation step in the CLI/API (see execution/live
    # broker stub). This is intentionally redundant.
    broker_mode: Literal["paper", "live"] = "paper"
    live_trading_confirmed: bool = False
    live_trading_confirmation_phrase: str = ""  # must equal "I UNDERSTAND THE RISK"

    # --- Database ---------------------------------------------------
    database_url: str = "postgresql+asyncpg://trading:trading@localhost:5432/trading_bot"
    redis_url: str = "redis://localhost:6379/0"

    # --- Market data provider credentials --------------------------
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"

    binance_api_key: str = ""
    binance_secret_key: str = ""

    polygon_api_key: str = ""

    # --- News provider credentials -----------------------------------
    newsapi_key: str = ""
    finnhub_api_key: str = ""
    alphavantage_api_key: str = ""

    # --- Alerting --------------------------------------------------
    slack_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    alert_email_smtp_host: str = ""
    alert_email_from: str = ""
    alert_email_to: str = ""

    # --- Risk defaults (overridable via config/risk.yaml at runtime) ---
    max_risk_per_trade_pct: float = 1.0
    max_daily_loss_pct: float = 3.0
    max_trades_per_day: int = 10
    max_simultaneous_positions: int = 5
    max_exposure_per_asset_pct: float = 20.0
    consecutive_loss_circuit_breaker: int = 3
    circuit_breaker_cooldown_minutes: int = 60

    # --- AI decision engine --------------------------------------------
    min_confidence_threshold: float = 65.0  # 0-100 scale

    # --- API / dashboard --------------------------------------------
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    starting_equity: float = 100_000.0

    @field_validator("broker_mode")
    @classmethod
    def _paper_by_default(cls, v: str) -> str:
        return v

    @property
    def live_trading_fully_authorized(self) -> bool:
        """Both flags AND the exact confirmation phrase must be present.
        Any missing piece silently forces paper mode upstream."""
        return (
            self.broker_mode == "live"
            and self.live_trading_confirmed
            and self.live_trading_confirmation_phrase == "I UNDERSTAND THE RISK"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
