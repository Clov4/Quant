# Build Prompt: CSE (Casablanca Stock Exchange) Quant Trading System with GUI

> **Note on scope:** This prompt assumes "CSEMA" refers to the **Casablanca Stock Exchange market** (Bourse de Casablanca, Morocco — benchmark indices MASI / MASI 20 / MSI20, individual listed equities). If "CSEMA" actually refers to a specific ticker, fund, or sub-index, swap that in below; the rest of the architecture is unchanged.

---

## 1. Project Goal

Build a complete, runnable quantitative trading system for equities listed on the **Casablanca Stock Exchange (Bourse de Casablanca / CSE)**. The system must:

1. Fetch and store historical and (as close to) real-time market data for CSE-listed stocks and indices.
2. Generate trading signals using one or more quantitative strategies, with **human-readable reasoning** attached to every signal/trade.
3. Backtest those strategies with realistic assumptions (fees, slippage, liquidity).
4. Given an amount of capital **X** and a risk tolerance **Y**, output a **recommended portfolio** (allocation across CSE tickers, including cash).
5. Provide a **GUI/dashboard** that shows:
   - Live/historical trades with the reasoning behind each one
   - Market evolution (price, volume, index charts)
   - The recommended portfolio for the given X (capital) and Y (risk level)
6. Be modular enough that strategies, data sources, and risk models can be swapped independently.

This is for research/decision-support purposes — the system is **not** a licensed financial advisor and must surface that disclaimer in the GUI.

---

## 2. Data Sources

Primary candidates to evaluate and wire up (use whichever actually returns clean, reliable CSE data — test all before committing):

- `https://github.com/Fredysessie/Casabourse.git` — scraper/wrapper specifically for Bourse de Casablanca data. Investigate what endpoints/pages it scrapes, what fields it returns (OHLCV, real-time quotes, index levels), and its rate limits / fragility (it may depend on the casablanca-bourse.com website structure).
- `https://github.com/rongardF/tvdatafeed.git` — unofficial TradingView data feed; check whether CSE tickers are actually available on TradingView under a `CSEMA`/`MASI` exchange symbol before relying on it.
- Fallback/supplementary sources to evaluate if the above are insufficient or unstable:
  - Official Bourse de Casablanca website (casablanca-bourse.com) — historical data exports / daily bulletins (PDF/CSV)
  - AMMC (Moroccan market regulator) disclosures
  - Investing.com / Yahoo Finance / Google Finance for MASI index and large-cap CSE tickers (coverage is often partial — verify per ticker)
  - Wafa Bourse, BMCE Capital Bourse, Attijari Intermédiation, or other Moroccan brokers' public data pages

**Requirements for the data layer:**
- Build a `DataProvider` abstraction (interface) so strategies don't care which underlying source is used.
- Implement at least two concrete providers (e.g., `CasabourseProvider`, `TVDataFeedProvider`) behind that interface, with automatic fallback if one fails.
- Cache data locally (SQLite or Parquet/CSV files) to avoid re-fetching and to support fast backtests.
- Handle and log: missing data, stale quotes, corporate actions (splits, dividends) if available, and trading halts.
- Normalize all instruments to a common schema: `{ticker, date, open, high, low, close, volume, currency}`.
- Add a scheduled fetch job (e.g., cron-like or APScheduler) for end-of-day data at minimum; intraday only if a source actually supports it for CSE.

---

## 3. System Architecture

```
data/
  providers/        # DataProvider implementations (Casabourse, tvdatafeed, fallback)
  storage/           # local cache (SQLite/Parquet), schema migrations
strategies/
  base.py            # Strategy interface: generate_signals(data) -> list[Signal]
  momentum.py
  mean_reversion.py
  factor_model.py     # optional: value/quality/momentum factor scoring for CSE universe
backtest/
  engine.py           # vectorized or event-driven backtester
  metrics.py           # Sharpe, max drawdown, CAGR, win rate, turnover
  costs.py             # commissions, slippage, bid-ask spread assumptions for CSE liquidity
risk/
  portfolio_optimizer.py   # given X (capital) and Y (risk tolerance) -> target weights
  position_sizing.py       # per-trade sizing, stop-loss/max-drawdown rules
explainability/
  reasoning.py         # turns each signal's underlying features into a plain-language explanation
gui/
  app.py               # dashboard entry point
  views/
    trades_view         # trade log with reasoning column
    market_view          # price/volume/index charts
    portfolio_view        # recommended allocation for X, Y
live/ (optional)
  scheduler.py          # periodic re-evaluation of signals/portfolio
config/
  settings.yaml         # universe of tickers, risk profiles, fees, data source priority
tests/
README.md
```

---

## 4. Strategy & Signal Requirements

Implement at least **two independent, simple-but-real strategies** (avoid black-box complexity for a first version), for example:

1. **Momentum/trend-following**: e.g., moving-average crossover or N-day price momentum ranking across the CSE universe.
2. **Mean reversion**: e.g., z-score of price vs. rolling mean, or RSI-based oversold/overbought signals.

Optionally a third **factor/score-based** strategy combining valuation (P/E, dividend yield if data available) and momentum to rank the CSE universe.

For every generated signal/trade, the system must record:
- Ticker, date/time, signal type (buy/sell/hold), strategy that produced it
- The **specific numeric triggers** (e.g., "20-day MA crossed above 50-day MA", "RSI = 24, below threshold 30")
- A **plain-language explanation string** assembled from those triggers, surfaced in the GUI (no opaque "model says buy" — always show the "why")
- Confidence/score if the strategy produces one

---

## 5. Backtesting Requirements

- Walk-forward or rolling-window backtest, not just a single in-sample run.
- Apply realistic Moroccan market constraints: settlement (T+3 historically — verify current rule), minimum lot sizes if applicable, transaction fees/commissions typical of CSE brokers, and a liquidity penalty for thinly traded tickers (CSE has many low-volume names — don't assume infinite liquidity).
- Output standard metrics: CAGR, Sharpe ratio, max drawdown, win rate, average trade return, turnover.
- Compare each strategy against a buy-and-hold MASI benchmark.
- Store backtest results so the GUI can display historical "what would have happened" alongside live recommendations.

---

## 6. Portfolio Recommendation (given X = capital, Y = risk tolerance)

Build a `portfolio_optimizer` that takes:
- `X`: amount of capital (in MAD or user-selected currency)
- `Y`: risk tolerance, expressed as either a simple categorical scale (Conservative / Balanced / Aggressive) or a numeric target volatility / max-drawdown constraint

And outputs:
- A recommended set of CSE tickers with weights and computed share quantities for capital X (respecting min lot sizes / whole-share constraints — no fractional shares unless the CSE supports it)
- Expected portfolio metrics: estimated volatility, expected return range, max historical drawdown for this allocation, diversification across sectors if sector data is available
- A cash buffer if full deployment isn't appropriate for the chosen risk level

Suggested methodology options to implement (pick one as default, document the others as configurable):
- Mean-variance optimization (Markowitz) with a risk-aversion parameter mapped from Y
- Risk parity (equal risk contribution) for lower-risk profiles
- Simple rule-based allocation (e.g., max single-position weight, sector caps) layered on top of either of the above for a first version if full optimization is too heavy

The optimizer must reuse the same signal/strategy outputs as the trading engine — the recommended portfolio should be explainable using the same `reasoning.py` module (i.e., "this stock is included because of strong momentum + acceptable volatility contribution").

---

## 7. GUI Requirements

Build a dashboard (Streamlit, Dash, or a lightweight React + Flask/FastAPI backend — choose based on what's fastest to ship a working v1) with at least three views:

1. **Trades view**
   - Table/log of historical and current signals/trades
   - Each row expandable to show the reasoning text and the underlying indicator values/chart snippet
   - Filter by ticker, date range, strategy, signal type

2. **Market evolution view**
   - Price chart (candlestick or line) per ticker and for the MASI index, with volume
   - Overlay of the indicators each strategy uses (e.g., moving averages, RSI) so the user can visually verify the reasoning
   - Backtest equity curve vs. benchmark

3. **Portfolio recommendation view**
   - Inputs: capital amount (X) and risk tolerance (Y) — sliders/dropdowns
   - Output: allocation table (ticker, weight, shares, MAD value), pie/bar chart of allocation, expected risk/return summary, and the reasoning for each included position
   - A visible disclaimer that this is a research tool, not financial advice

---

## 8. Non-Functional Requirements

- **Logging**: every data fetch, signal generation, and trade decision logged with timestamps.
- **Config-driven**: ticker universe, fees, risk profiles, and data source priority should live in a config file, not hardcoded.
- **Testability**: unit tests for indicators, the backtester's PnL math, and the optimizer's weight math (weights sum to 1, respect constraints).
- **Reproducibility**: backtest results must be reproducible from cached data (pin data snapshot dates).
- **Error handling**: graceful degradation if a data source is down (fallback provider, or clearly flagged stale data in the GUI rather than a silent crash).
- **Disclaimer**: the GUI and any generated reports must state this is not licensed investment advice.

---

## 9. Deliverables

1. Working codebase matching the structure in Section 3, runnable locally with a documented `setup.sh` / `requirements.txt` / `README.md`.
2. At least one populated local data cache (sample CSE tickers + MASI index) to demo without live network access.
3. A running GUI (`python gui/app.py` or equivalent) that loads the demo data and shows all three views.
4. A short `STRATEGY.md` documenting the implemented strategies, their parameters, and known limitations (especially around CSE data sparsity/liquidity).
5. Backtest report (markdown or HTML) comparing each strategy to MASI buy-and-hold.

---

## 10. Suggested Build Order (for the agent executing this prompt)

1. Stand up the `DataProvider` interface and get **one** working data source returning clean OHLCV for at least 5–10 liquid CSE tickers + MASI index, cached locally.
2. Implement one simple strategy end-to-end (e.g., MA crossover) with reasoning generation.
3. Build the backtester and validate the strategy against MASI buy-and-hold.
4. Add the second strategy.
5. Build the portfolio optimizer (start rule-based/simple, upgrade to mean-variance if time allows).
6. Build the GUI, wiring in real outputs from steps 2–5 (no mock data in the final version).
7. Add the second data provider as a fallback and test failure handling.
8. Write README, STRATEGY.md, and tests.

---

### Open questions to resolve before/while building (flag these rather than guessing silently):
- Exact ticker universe to cover (all CSE-listed names vs. a liquid subset, e.g., MASI 20 constituents)
- Currency assumption (MAD) and whether FX is in scope at all
- Whether intraday data is actually available for CSE through either repo, or if this is necessarily an end-of-day system
- Whether fractional shares are allowed (Casablanca Bourse min lot/round-lot rules)
