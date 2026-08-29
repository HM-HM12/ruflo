# Setup

## Prerequisites

- Python 3.11+
- Node.js 20+ (for the dashboard)
- PostgreSQL 16 (or Docker)
- Redis 7 (or Docker)
- Docker + Docker Compose (recommended, for the full stack)

## 1. Local Python environment

```bash
cd trading-bot
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

## 2. Environment variables

```bash
cp env.example .env
```

Edit `.env`. At minimum for paper trading with the default `yfinance`
provider, you don't need any API keys — yfinance requires none. To use
Alpaca (stocks/ETFs, recommended for anything beyond casual local testing)
or ccxt/Binance (crypto), or to enable real news providers, fill in the
corresponding keys. **Never commit `.env`.**

## 3. Database

### Option A — Docker (recommended)

```bash
docker compose up -d postgres redis
alembic upgrade head
```

### Option B — local Postgres

Create a database and user matching `DATABASE_URL` in `.env`, then:

```bash
alembic upgrade head
```

For quick local iteration without Postgres, the ORM will also work against
SQLite (used automatically in the test suite) via
`src/db/session.init_db()`, but Alembic migrations target Postgres syntax —
use Postgres for anything beyond running tests.

## 4. Run the test suite

```bash
pytest -v --cov=src --cov-report=term-missing
```

All tests run against synthetic data — no network access or live
credentials required.

## 5. Run a backtest

```bash
python -m scripts.run_backtest --symbol AAPL --days 180 --timeframe 15m
python -m scripts.run_backtest --symbol AAPL --days 730 --walk-forward --train-bars 1000 --test-bars 250
```

Historical data is fetched via `yfinance` by default (no API key needed).

## 6. Run paper trading

```bash
python -m scripts.run_paper_trading --symbols AAPL,MSFT,SPY --timeframe 15m
```

This runs the bot loop in your terminal with no dashboard — useful for
smoke-testing before running the full stack.

## 7. Run the full stack (API + dashboard + Postgres + Redis)

```bash
docker compose up --build
```

- API: http://localhost:8000/api/health
- Dashboard: http://localhost:3000

Or run the pieces individually for development:

```bash
# Terminal 1
uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2
cd dashboard
npm install
npm run dev
```

## 8. Configuration reference

- `config/settings.py` — environment-driven application settings
  (Pydantic `BaseSettings`).
- `config/risk.yaml` — risk limits (overridable via env vars of the same
  name in upper-case, e.g. `MAX_RISK_PER_TRADE_PCT`).
- `config/strategy.yaml` — AI scoring weights, indicator parameters,
  trading universe, regime thresholds. `scoring_weights` must sum to 1.0
  (validated at load time).

## Live trading (disabled by default)

Paper trading is the only supported mode out of the box. To ever enable
live trading you must:

1. Set `BROKER_MODE=live` in `.env`.
2. Set `LIVE_TRADING_CONFIRMED=true` in `.env`.
3. Set `LIVE_TRADING_CONFIRMATION_PHRASE="I UNDERSTAND THE RISK"` in `.env`
   (exact match).
4. Implement a real broker adapter in
   `src/execution/live_broker_stub.py` — it ships raising
   `LiveTradingNotConfirmed` unconditionally. This is a deliberate, manual
   code change; there is no configuration-only path to live trading.

Even with all four gates cleared, start with a broker's own paper/sandbox
credentials first and verify behavior end-to-end before ever pointing the
adapter at a funded account. Read `ARCHITECTURE.md`'s "Execution layer"
section before doing any of this.

## Trading gold (or anything else) on MetaTrader 5

MT5 is a fully implemented broker platform (`src/execution/mt5_broker.py`)
and market data provider (`src/data/providers/mt5_provider.py`) — this is
not the same as the generic `live_broker_stub.py` gate above.

**Platform constraint, read this first:** the official `MetaTrader5` Python
package only ships wheels for **Windows**, and it talks to a MT5 terminal
running on the *same machine* over local IPC — there's no remote/HTTP mode.
That means this bot process (the API server or `run_paper_trading.py`) must
run on the same Windows machine as your MT5 terminal, with that terminal
already installed. Running the rest of the stack (Postgres, Redis, the
dashboard) via Docker on the same Windows host is fine; only the process
that imports `MetaTrader5` needs to run natively.

1. Install and open the MT5 terminal for your broker; note your account
   login, password, and server name (Files → Login to Trade Account shows
   these).
2. `pip install MetaTrader5` (Windows only — see the marker in
   `requirements.txt`).
3. In `.env`, set:
   ```
   BROKER_PLATFORM=mt5
   DATA_PROVIDER=mt5
   MT5_LOGIN=<your account number>
   MT5_PASSWORD=<your password>
   MT5_SERVER=<your broker's server name>
   MT5_SYMBOL=XAUUSD    # check your broker's exact gold symbol name — see below
   ```
4. **For paper trading (recommended first step):** log the MT5 terminal
   itself into a **demo account** and leave `BROKER_MODE=paper` (the
   default). `Mt5Broker` independently checks the connected account's
   `trade_mode` on every connection and refuses to proceed if it isn't
   actually a demo/contest account — a stray real login here does not
   silently become "safe" just because the config says paper.
5. Run `python -m scripts.run_paper_trading` (or the full API/dashboard
   stack) as usual — it now trades `MT5_SYMBOL` alone via MT5's real demo
   execution, spreads, and prices, instead of the synthetic `PaperBroker`.
6. **Going live** requires both the MT5 terminal logged into your real
   account AND the full `BROKER_MODE=live` / `LIVE_TRADING_CONFIRMED=true`
   / `LIVE_TRADING_CONFIRMATION_PHRASE` gate from the section above. If the
   terminal's actual account doesn't match (e.g. gate cleared but terminal
   still on demo), `Mt5Broker` refuses and the system falls back to the
   synthetic `PaperBroker` rather than doing nothing silently.

**Gold's symbol name is broker-specific.** Open MT5's "Market Watch" panel
(Ctrl+M) and find the exact spelling your broker uses — common variants are
`XAUUSD`, `XAUUSD.a`, `XAUUSDm`, `XAUUSD.raw`, or plain `GOLD`. Set
`MT5_SYMBOL` to match exactly; a mismatch raises `BrokerConnectionError` on
startup rather than silently trading the wrong instrument.

**Position sizing.** The risk manager computes position size in the
underlying instrument's natural unit (ounces, for gold) purely from account
equity and stop-loss distance — exactly as it does for stocks. `Mt5Broker`
converts that to MT5 lots at the point of order submission, using the
symbol's real contract size (`MT5_LOT_STEP` / `MT5_MIN_LOT` / `MT5_MAX_LOT`
control the rounding/clamping). You should not need to hand-tune lot sizes;
if `max_risk_per_trade_pct` in `config/risk.yaml` is 1%, that's still true
in dollar terms after the lot conversion.

## Troubleshooting

- **`ModuleNotFoundError` for `src` or `config`** — run commands from the
  `trading-bot/` directory (or use the `scripts/run_*.py` entrypoints,
  which add the project root to `sys.path`).
- **yfinance rate-limited / empty data** — yfinance has no official SLA;
  for production use, switch to `AlpacaProvider` or `CcxtProvider`.
- **`nltk` sentiment backend unavailable** — run
  `python -m nltk.downloader vader_lexicon` once, or rely on the built-in
  zero-dependency `LexiconFallbackBackend`, which is used automatically if
  `nltk` isn't installed.
- **Alembic can't connect** — confirm `DATABASE_URL` in `.env` and that
  Postgres is reachable (`docker compose ps`).
- **`MetaTrader5.initialize() failed`** — the terminal isn't running, isn't
  logged in, or `MT5_PATH` points to the wrong `terminal64.exe`. Try
  logging in manually in the terminal UI first, then leave `MT5_PATH` blank
  so `initialize()` auto-detects the running instance.
- **`Symbol 'XAUUSD' not found`** — your broker uses a different gold
  symbol name; check Market Watch (Ctrl+M) and update `MT5_SYMBOL`.
- **MT5 broker silently falls back to the synthetic `PaperBroker`** — this
  is the account-type safety gate in `src/execution/mt5_broker.py` working
  as intended; check the logs for exactly which check failed (wrong account
  type for the configured mode, or missing live-trading authorization).
