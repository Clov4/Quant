# csequant — Casablanca Stock Exchange Quant Research System

A complete, runnable quantitative **research and decision-support** system for
equities listed on the **Casablanca Stock Exchange (Bourse de Casablanca / CSE)**.
It fetches real market data, generates trading signals with **human-readable
reasoning**, backtests them with realistic CSE frictions, and recommends a
portfolio for a given capital **X** and risk tolerance **Y** — all surfaced in a
Streamlit dashboard.

> ⚠️ **Not financial advice.** This is a research tool. Market data may be
> delayed, incomplete, or stale. Do your own research and consult a licensed
> professional before trading.

---

## Highlights

- **Real CSE data**, no mocks: live end-of-day OHLCV for the liquid universe +
  intraday market snapshot + index levels, scraped from `casablanca-bourse.com`
  and cached locally (SQLite + parquet) for fast, offline, reproducible runs.
- **Explainable signals**: every signal records the exact indicator values that
  triggered it and renders them as a sentence — *no opaque "model says buy"*.
- **Three strategies** behind one interface: momentum (MA-crossover + trend
  filter), mean-reversion (RSI + z-score), and a cross-sectional factor model.
- **Realistic backtester**: whole-share orders, broker/exchange/AMMC fees + 10%
  VAT + slippage, a per-name daily liquidity cap from trailing turnover, and
  **T+2 settlement** cash mechanics. Walk-forward, no look-ahead.
- **Capital/risk-aware optimizer**: mean-variance (SLSQP), risk-parity, and
  rule-based methods; volatility targeting; per-name and sector caps; whole-share
  quantisation; an explained allocation for any (X, Y).
- **Streamlit GUI** with three views: Trades, Market, Portfolio.
- **Tested** (`pytest`) for indicator math, PnL/round-trip math, cost model, and
  optimizer constraints.

---

## Architecture

```
config/            settings.yaml (universe, fees, risk profiles, source priority)
                   instruments.csv / indices.csv  (real CSE reference data)
csequant/
  schema.py        the single canonical OHLCV schema every provider normalises to
  config.py        typed config loader; logging_conf.py
  data/
    providers/     DataProvider interface + Casablanca (live), Offline (cache), TV (opt.)
    storage/       SQLite cache (OHLCV, snapshot, metadata)
    service.py     DataService — provider chain, cache-first reads, fallback
    universe.py    instruments/indices + ticker→id + sector lookups
  strategies/      indicators.py, base.py (Strategy/Signal), momentum / mean_reversion / factor_model
  backtest/        costs.py, engine.py (event-driven), metrics.py, benchmark.py
  risk/            portfolio_optimizer.py (X,Y → weights → shares), position_sizing.py
  explainability/  reasoning.py — triggers → plain language
  gui/             app.py + views/{trades,market,portfolio}_view.py
  live/            scheduler.py — daily EOD refresh
  pipeline.py      headless build-cache / signals / backtest / report
  cli.py           `python -m csequant <command>`
scripts/           build_cache.py
tests/             pytest suite
reports/           generated backtest_report.md
```

Each layer is swappable: strategies depend only on the OHLCV schema, the engine
on the `Strategy` interface, the GUI on the `DataService`/optimizer outputs.

---

## Quick start

```bash
./setup.sh                 # venv + deps + build real cache + tests + report
# ...or manually:
pip install -e .           # or: pip install -r requirements.txt
python -m csequant build-cache
streamlit run csequant/gui/app.py
```

The dashboard is **offline-first**: once the cache is built (or if a demo cache is
bundled), every view works with no network. The sidebar's **Refresh live data**
button repopulates the cache when a network is available.

### CLI

```bash
python -m csequant build-cache                         # fetch + cache real EOD data
python -m csequant signals --ticker IAM --limit 10     # signals with reasoning
python -m csequant backtest                            # metrics vs benchmark
python -m csequant report                              # -> reports/backtest_report.md
python -m csequant recommend --capital 100000 --risk Balanced
python -m csequant gui                                 # launch the dashboard
python -m csequant.live.scheduler --hour 18 --minute 30   # daily EOD refresh
```

---

## Data sources (and what actually works)

The build prompt named two candidate sources; both were evaluated live:

| Source | Verdict |
|---|---|
| **`casablanca-bourse.com` (via the `casabourse` API shape)** | ✅ **Primary.** Real EOD OHLCV, market snapshot, and index levels. Used by `CasablancaBourseProvider`. |
| **`tvdatafeed` (unofficial TradingView)** | ⚠️ Optional/off by default. CSE coverage on TradingView is unverified and it generally needs a login. Implemented as a graceful best-effort fallback (`TVDataFeedProvider`). |
| yfinance / Google / Investing | ❌ Not reliable for CSE (e.g. `MASI` on Yahoo resolves to *Masimo Corp*, a US name). |

**Endpoints used** (all behind the site's `/api/proxy` JSON:API; a build-id is
scraped from the homepage and rotates ~hourly):
- `dashboard/ticker` — live market snapshot (all instruments)
- `bourse_data/instrument_history` — daily OHLCV, filtered by the instrument's
  internal id (mapped offline from `config/instruments.csv`)
- `dashboard/grouped_index_watch` — current index levels (MASI, MASI 20, …)

### Known data realities / fragilities (documented, not hidden)
- **TLS:** the site's certificate chain is often unverifiable in CI/sandboxes, so
  the provider uses `verify_tls: false` (configurable). This is a real fragility.
- **History depth:** the instrument-history API serves **~3 years (~738 sessions)**
  of EOD data — so this is an end-of-day system over a relatively short window.
- **No intraday history:** only EOD bars + a live snapshot are available for CSE.
- **MASI benchmark:** the official MASI *daily series* endpoint's id-mapping is
  unstable (returns empty), so the benchmark is a **transparent equal-weight
  buy-and-hold composite** of the cached liquid universe — a documented proxy for
  MASI, fully reproducible offline. Current MASI/MASI-20 *levels* are still shown
  live in the Market view. Wiring the official series is a future enhancement.

---

## Open questions from the prompt — resolved

| Question | Decision (configurable) |
|---|---|
| Ticker universe | Config-driven. Demo cache = ~18 liquid names (`universe.demo_tickers`); the full 113-instrument universe with sectors ships in `config/instruments.csv`. |
| Currency / FX | MAD only; FX out of scope. |
| Intraday vs EOD | **EOD** system (the source only serves daily history); a live intraday snapshot is shown for context. |
| Fractional shares | Not allowed — whole shares only, `default_lot_size: 1` (configurable per market). |
| Settlement | **T+2** default (`market.settlement_days`), modelled in the backtester. Historically T+3 — verify the current rule for your use. |

Everything above lives in `config/settings.yaml`, not in code.

---

## Testing

```bash
pytest -q
```

Covers indicator math (RSI bounds, SMA/momentum/z-score), the cost model
(commission floor, VAT, slippage direction, liquidity cap), FIFO round-trip PnL
and performance metrics, schema normalisation + cache round-trips, the engine
(cost monotonicity, weight consistency), and optimizer constraints (weights+cash
sum to 1, whole shares, per-name/sector caps, vol targeting, risk-profile
differentiation). All tests are synthetic and network-free.

See **[STRATEGY.md](STRATEGY.md)** for the strategy/cost/optimizer methodology and
a discussion of results and limitations, and **[reports/backtest_report.md](reports/backtest_report.md)**
for the latest run.

---

## License

MIT. Provided as-is for research/education. **Not** licensed investment advice.
