"""Shared MetaTrader 5 terminal connection.

The `MetaTrader5` package is a thin wrapper around IPC calls to a locally
running MT5 terminal — there is no concept of a stateless HTTP client here.
`mt5.initialize()` opens (or reuses) that connection process-wide, so both
Mt5Provider (market data) and Mt5Broker (execution) share the single
connection managed by this module rather than each calling initialize()
independently.

Platform note: the official package only ships for Windows. It is not
importable on Linux/macOS at all (no wheel exists), which is why the import
is deferred to first use, exactly like the other optional providers
(alpaca-py, ccxt) — the rest of the codebase must remain importable without
it installed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from src.core.exceptions import BrokerConnectionError

logger = logging.getLogger("trading_bot.mt5")


@dataclass(frozen=True, slots=True)
class Mt5Credentials:
    login: int
    password: str
    server: str
    path: str = ""  # optional path to terminal64.exe; blank = auto-detect


class Mt5Connection:
    """Process-wide singleton-ish handle. Safe to construct multiple times
    with the same credentials — mt5.initialize() is idempotent for the same
    terminal/account and cheap to call again."""

    _connected_login: int | None = None

    def __init__(self, credentials: Mt5Credentials) -> None:
        try:
            import MetaTrader5 as mt5
        except ImportError as exc:  # pragma: no cover — exercised only off-Windows
            raise BrokerConnectionError(
                "The MetaTrader5 package is not installed or not available on this "
                "platform. It only ships official wheels for Windows and requires a "
                "locally running MT5 terminal — see trading-bot/SETUP.md's MT5 "
                "section. Install with `pip install MetaTrader5` on Windows."
            ) from exc
        self._mt5 = mt5
        self._credentials = credentials

    def connect(self):
        """Returns the connected `MetaTrader5` module. Raises
        BrokerConnectionError on failure — never fails silently into an
        unauthenticated state."""
        mt5 = self._mt5
        c = self._credentials

        if Mt5Connection._connected_login == c.login and mt5.terminal_info() is not None:
            return mt5  # already connected as this account

        kwargs = {}
        if c.path:
            kwargs["path"] = c.path
        if c.login:
            kwargs.update(login=c.login, password=c.password, server=c.server)

        if not mt5.initialize(**kwargs):
            error = mt5.last_error()
            raise BrokerConnectionError(f"MetaTrader5.initialize() failed: {error}")

        account_info = mt5.account_info()
        if account_info is None:
            mt5.shutdown()
            raise BrokerConnectionError(
                f"Connected to MT5 terminal but no account is logged in: {mt5.last_error()}"
            )

        Mt5Connection._connected_login = account_info.login
        logger.info(
            "Connected to MT5: login=%s server=%s trade_mode=%s",
            account_info.login, account_info.server, account_info.trade_mode,
        )
        return mt5

    def account_trade_mode(self):
        """Returns the MT5 ACCOUNT_TRADE_MODE_* constant for the currently
        connected account — the ground truth for demo vs. real, verified
        live from the terminal rather than trusted from config."""
        mt5 = self.connect()
        info = mt5.account_info()
        if info is None:
            raise BrokerConnectionError("MT5 account_info() unavailable after connect")
        return info.trade_mode

    def is_demo_account(self) -> bool:
        mt5 = self._mt5
        return self.account_trade_mode() != mt5.ACCOUNT_TRADE_MODE_REAL

    def symbol_info(self, symbol: str):
        mt5 = self.connect()
        info = mt5.symbol_info(symbol)
        if info is None:
            raise BrokerConnectionError(
                f"Symbol '{symbol}' not found on this MT5 account — check the exact "
                f"symbol name in your broker's Market Watch panel (MT5_SYMBOL setting)."
            )
        if not info.visible and not mt5.symbol_select(symbol, True):
            raise BrokerConnectionError(f"Could not add symbol '{symbol}' to Market Watch")
        return info

    def shutdown(self) -> None:
        self._mt5.shutdown()
        Mt5Connection._connected_login = None
