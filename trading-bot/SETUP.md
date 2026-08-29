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
