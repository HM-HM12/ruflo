# AI Trading Bot

A production-style, AI-assisted algorithmic trading system for short-term
trading in stocks, ETFs, and crypto. It fuses technical analysis with news
sentiment through a weighted 0–100 AI decision engine, and hands every
proposed trade to a risk manager that has final veto authority.

**Paper trading is the only mode enabled by default.** Live trading requires
deliberately clearing multiple explicit gates — see "Live trading (disabled
by default)" in [SETUP.md](SETUP.md) and `src/execution/live_broker_stub.py`.

This is not a guaranteed-profit system. It is designed to survive first and
compound risk-adjusted returns second — it is explicitly built to say
**NO_TRADE** when the evidence isn't there.

## Quick start (paper trading, local)

```bash
cd trading-bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp env.example .env   # then edit .env if you want live data providers

# Run the test suite
pytest

# Run a backtest
python -m scripts.run_backtest --symbol AAPL --days 180

# Run paper trading (CLI, no dashboard)
python -m scripts.run_paper_trading --symbols AAPL,MSFT,SPY

# Or run the full stack (API + Postgres + Redis + dashboard) via Docker
docker compose up --build
# API:       http://localhost:8000/api/health
# Dashboard: http://localhost:3000
```

See [SETUP.md](SETUP.md) for full setup instructions, and
[ARCHITECTURE.md](ARCHITECTURE.md) for the system design and strategy
rationale.

## Project layout

```
trading-bot/
  config/            settings.py (env-driven), risk.yaml, strategy.yaml
  src/
    core/            enums, exceptions, shared domain value objects
    data/            market data + news providers (Alpaca, ccxt, yfinance, NewsAPI, Finnhub)
    features/        technical indicators + market structure signal detection
    sentiment/       news sentiment analysis + dedup
    strategy/        fuses technicals + sentiment into a StrategySignal
    ai/              decision engine — 0-100 weighted scoring, NO_TRADE gate
    risk/            risk manager (final authority), position sizing, circuit breaker
    portfolio/       position & equity bookkeeping
    execution/       broker abstraction, paper broker, gated live-broker stub
    regime/          market regime detection (bull/bear/sideways/vol/news)
    backtesting/      backtest engine, walk-forward optimizer, performance metrics
    journal/         trading journal (records every decision, incl. rejections)
    db/              SQLAlchemy models + Alembic migrations
    alerts/          alert manager + channels (console/Slack/Telegram/email)
    api/             FastAPI REST + WebSocket backend for the dashboard
    orchestrator.py  TradingBot — the live/paper trading loop
  scripts/           CLI entrypoints (run_paper_trading.py, run_backtest.py)
  tests/             pytest unit tests
  dashboard/         Next.js dashboard (equity, positions, journal, news, risk, kill switch)
```

Every module above is independently unit-testable and has no hidden
dependency on the others beyond the explicit value objects in
`src/core/domain.py`.

## Safety model, in one paragraph

The AI decision engine (`src/ai/decision_engine.py`) never places a trade —
it only scores a setup and proposes a direction. Every proposal, regardless
of confidence, is evaluated by `src/risk/risk_manager.py`, which is the only
component with the authority to approve an order. Position size is a pure
function of account equity and stop-loss distance — never of confidence,
win/loss streaks, or urgency. The risk manager also owns the daily-loss kill
switch, the consecutive-loss circuit breaker, per-symbol cooldowns (no
revenge trading), exposure caps, and the global emergency stop. See
`ARCHITECTURE.md` for the full data flow.
