"""Builds the configured MarketDataProvider from settings. Centralizes what
used to be a hardcoded YFinanceProvider() in the API/CLI entrypoints so
`DATA_PROVIDER=mt5` (or alpaca/ccxt) actually takes effect everywhere."""
from __future__ import annotations

from config.settings import Settings
from src.core.enums import AssetClass
from src.core.exceptions import DataProviderError
from src.data.market_data_provider import MarketDataProvider


def build_market_data_provider(settings: Settings) -> MarketDataProvider:
    if settings.data_provider == "yfinance":
        from src.data.providers.yfinance_provider import YFinanceProvider
        return YFinanceProvider()

    if settings.data_provider == "alpaca":
        from src.data.providers.alpaca_provider import AlpacaProvider
        return AlpacaProvider(settings.alpaca_api_key, settings.alpaca_secret_key, settings.alpaca_base_url)

    if settings.data_provider == "ccxt":
        from src.data.providers.ccxt_provider import CcxtProvider
        return CcxtProvider(api_key=settings.binance_api_key, secret_key=settings.binance_secret_key)

    if settings.data_provider == "mt5":
        from src.data.providers.mt5_connection import Mt5Credentials
        from src.data.providers.mt5_provider import Mt5Provider
        credentials = Mt5Credentials(
            login=settings.mt5_login, password=settings.mt5_password,
            server=settings.mt5_server, path=settings.mt5_path,
        )
        return Mt5Provider(credentials, symbol=settings.mt5_symbol)

    raise DataProviderError(f"Unknown data_provider setting: {settings.data_provider!r}")


def resolve_trading_universe(settings: Settings, strategy_cfg: dict) -> tuple[list[str], AssetClass]:
    """What symbols to trade and under which asset class, driven by
    settings rather than always assuming the equities universe in
    strategy.yaml. MT5 trades a single configured instrument (default:
    XAUUSD / gold) as a commodity CFD, independent of the stocks/etfs/
    crypto lists used for the other providers."""
    if settings.data_provider == "mt5" or settings.broker_platform == "mt5":
        return [settings.mt5_symbol], AssetClass.COMMODITY

    universe = strategy_cfg.get("universe", {})
    if settings.data_provider == "ccxt":
        return universe.get("crypto", []), AssetClass.CRYPTO

    return universe.get("stocks", []) + universe.get("etfs", []), AssetClass.STOCK
