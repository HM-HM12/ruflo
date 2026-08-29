# Architecture

## Design goals

1. **Survive first, compound second.** The system is optimized for
   risk-adjusted returns and capital preservation, not trade frequency. It
   must be able to confidently do nothing.
2. **Single point of risk authority.** Exactly one component — the Risk
   Manager — can approve a trade. No other module, including the AI decision
   engine, can bypass it.
3. **No look-ahead, ever.** Backtesting only ever sees data available as of
   the simulated timestamp; live trading only ever sees data available now.
4. **Paper by default.** Live trading requires clearing multiple explicit,
   independent gates (see "Execution Layer" below) — it must never be a
   silent config toggle.
5. **Independently testable modules.** Every layer takes and returns plain
   value objects (`src/core/domain.py`) so it can be unit-tested in
   isolation, without spinning up the rest of the system.

## Data flow

```
                     ┌─────────────────────┐
                     │   Market Data        │  (Alpaca / ccxt / yfinance)
                     │   News Data          │  (NewsAPI / Finnhub)
                     └──────────┬───────────┘
                                │
                     ┌──────────▼───────────┐
                     │  Feature Engineering  │  EMA/RSI/MACD/VWAP/ATR/BB/
                     │  (src/features)       │  relative volume/support-
                     │                       │  resistance/breakout
                     └──────────┬───────────┘
                                │
          ┌─────────────────────┼─────────────────────┐
          │                                             │
┌─────────▼──────────┐                     ┌────────────▼────────────┐
│  Sentiment Analysis  │                     │   Regime Detection       │
│  (src/sentiment)      │                     │   (src/regime)            │
│  bullish/bearish/     │                     │   bull/bear/sideways/     │
│  neutral + confidence │                     │   high-vol/low-vol/news   │
│  + impact, deduped    │                     └────────────┬────────────┘
└─────────┬──────────┘                                    │
          └─────────────────────┬─────────────────────────┘
                                │
                     ┌──────────▼───────────┐
                     │   Strategy Engine     │  fuses technicals + sentiment
                     │   (src/strategy)      │  + regime into a StrategySignal
                     └──────────┬───────────┘
                                │
                     ┌──────────▼───────────┐
                     │  AI Decision Engine   │  0-100 weighted score;
                     │  (src/ai)             │  NO_TRADE below threshold
                     └──────────┬───────────┘
                                │  TradeSetup (proposal only)
                     ┌──────────▼───────────┐
                     │    Risk Manager       │  FINAL AUTHORITY:
                     │    (src/risk)         │  position sizing, stop-loss
                     │                       │  requirement, daily loss kill
                     │                       │  switch, circuit breaker,
                     │                       │  exposure caps, no revenge
                     │                       │  trading, global kill switch
                     └──────────┬───────────┘
                        approved │  rejected
                                │  └──────────────────► Trading Journal
                     ┌──────────▼───────────┐               (records why)
                     │  Execution Engine     │
                     │  (src/execution)      │
                     │  paper broker (default) │
                     │  live broker (gated)     │
                     └──────────┬───────────┘
                                │  Fill
                     ┌──────────▼───────────┐
                     │  Portfolio Manager    │  positions, exposure, equity
                     │  (src/portfolio)      │
                     └──────────┬───────────┘
                                │
                ┌────────────────┼────────────────┐
      ┌─────────▼────────┐          ┌───────────▼──────────┐
      │  Trading Journal   │          │   Alerts / Dashboard   │
      │  (src/journal)      │          │   (src/alerts, src/api) │
      └────────────────────┘          └────────────────────────┘
```

## Why a 0-100 weighted score, not a black box

The AI decision engine (`src/ai/decision_engine.py`) computes seven
independent component scores (news sentiment, technical setup, momentum,
volume, market trend, volatility, risk/reward), each 0-100, then combines
them with configurable weights (`config/strategy.yaml`). This is
deliberately legible: every trade (and every rejection) can be explained
component-by-component in the trading journal, rather than trusting an
opaque model. Two hard rules keep it honest:

- **A single news headline is capped.** `news_dampening_cap` (default 0.6)
  limits how much confidence any one event can carry into the
  `news_sentiment` component, so a sensational headline can't unilaterally
  push a setup over the confidence threshold.
- **No stop-loss, no trade — full stop.** If the strategy engine cannot
  derive a valid ATR-based stop, the decision engine outputs `NO_TRADE`
  regardless of how high the other components score.

## Why the Risk Manager is architecturally separate

`src/risk/risk_manager.py` takes a `TradeSetup` (the AI's proposal) and an
`AccountState` (current equity/exposure/trade count, supplied by the
Portfolio Manager) and returns an approve/reject decision — never the
reverse. Position size is computed once, inside the risk manager, as a pure
function of equity and stop distance
(`src/risk/position_sizing.fixed_fractional_size`). Nothing else in the
codebase computes position size, which is the concrete mechanism that
enforces "never increase size to recover a loss."

The circuit breaker (`src/risk/circuit_breaker.py`) tracks three
independent trip conditions:

- **Daily loss kill switch** — trips once realized daily loss reaches
  `max_daily_loss_pct`; stays tripped for the rest of the trading day.
- **Consecutive-loss circuit breaker** — trips after
  `consecutive_loss_circuit_breaker` losing trades in a row; cools down for
  `circuit_breaker_cooldown_minutes`.
- **Per-symbol cooldown** — a symbol that just stopped out is cooled down
  for `symbol_cooldown_minutes_after_loss`, which is the concrete mechanism
  that enforces "no revenge trading."

A fourth, manual **global kill switch** (`emergency_stop()` /
`resume_after_emergency_stop()`) is exposed via the dashboard and API for a
human to halt everything immediately.

## Execution layer: paper by default, live behind four gates

`src/execution/execution_engine.build_broker()` is the single decision
point for which broker instance gets used. It only returns a live broker
if **all four** of these hold:

1. `BROKER_MODE=live`
2. `LIVE_TRADING_CONFIRMED=true`
3. `LIVE_TRADING_CONFIRMATION_PHRASE` exactly equals `"I UNDERSTAND THE RISK"`
4. A real broker adapter has been deliberately implemented in
   `src/execution/live_broker_stub.py` (it ships raising
   `LiveTradingNotConfirmed` by default — there is no live trading code path
   until an operator writes one)

Missing any gate silently and safely falls back to the paper broker, with a
loud warning log — the system never fails open into live trading.

## Backtesting correctness

`src/backtesting/backtest_engine.py` enforces no-look-ahead at three levels:

- Indicators are computed causally (see `src/features/indicators.py` —
  including a fix to `support_resistance()`, which originally used a
  centered rolling window and had to be corrected to a strictly trailing
  confirmation window).
- A signal generated from data through bar N can only be filled at bar
  N+1's open — never the same bar that produced it.
- Stop-loss/take-profit checks use the *next* bar's high/low, not the
  signal bar's.

`src/backtesting/walk_forward.py` splits history into rolling
train/test windows and only ever scores the out-of-sample `test` slice,
specifically to avoid "optimize until it looks good historically."

## Market regime awareness

`src/regime/regime_detector.py` classifies the current regime from ATR
percentile and EMA trend slope into bull / bear / sideways / high-vol /
low-vol / news-event. The `market_trend` and `volatility` score components
in the decision engine are directly regime-aware (e.g., a `NEWS_EVENT`
regime scores low on `market_trend`), and `config/strategy.yaml`'s
`regime.reduce_trading_regimes` / `halt_trading_regimes` let an operator
configure the system to automatically throttle or halt trading in dangerous
conditions.
