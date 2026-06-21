# Strategies, Costs, Optimizer & Backtest Methodology

This document describes the implemented strategies, their parameters, the cost and
liquidity model, the portfolio optimizer, the backtest mechanics, and — honestly —
the known limitations. All parameters live in `config/settings.yaml`.

---

## 1. Signals & reasoning

Every strategy implements one interface (`csequant/strategies/base.py`):

- `compute(ohlcv) → frame[signal, score, <triggers…>]` — the causal, per-bar view
  the backtester/optimizer use (`signal` = desired long exposure in `[0, 1]`).
- `exposures(prices) → date×ticker matrix` — portfolio-level desired exposures.
- `generate_signals(ohlcv, ticker) → [Signal]` — the discrete trade-log view; a
  `Signal` is emitted on each stance change and carries a **plain-language
  `reason`** assembled from the exact trigger values.

The system is **long-only** (shorting the CSE central market is impractical for the
retail decision-support use-case): exposure is flat (0) or long (up to 1).

### 1.1 Momentum / trend-following (`momentum`)
Go long when the fast MA is above the slow MA **and** trailing momentum clears a
threshold; flat otherwise.

| Param | Default | Meaning |
|---|--:|---|
| `fast_ma` | 20 | fast SMA window |
| `slow_ma` | 50 | slow SMA window |
| `momentum_lookback` | 90 | trailing-return window |
| `momentum_threshold` | 0.0 | minimum trailing return to be long |

> *Example reason:* “BUY (momentum): 20-day MA (102.30) is above the 50-day MA
> (99.80) by +2.5%; 90-day momentum is +12.3% (threshold +0.0%).”

### 1.2 Mean reversion (`mean_reversion`)
Enter long when oversold (RSI below its band **or** price several sigma below its
rolling mean); exit to flat once reverted. Position is **stateful** (held between
entry and exit, not re-decided each bar).

| Param | Default | Meaning |
|---|--:|---|
| `rsi_period` | 14 | Wilder RSI period |
| `rsi_oversold` / `rsi_overbought` | 30 / 70 | RSI entry/exit bands |
| `zscore_window` | 20 | rolling mean/σ window |
| `zscore_entry` / `zscore_exit` | −1.5 / 0.0 | z-score entry/exit |

> *Example reason:* “BUY (mean_reversion): RSI(14) = 24.1, below the oversold
> threshold of 30; price is 1.8σ below its 20-day mean.”

### 1.3 Factor model (`factor_model`)
Cross-sectional ranking of the universe by a composite score that rewards
momentum and penalises volatility; hold the top-N each bar.

| Param | Default | Meaning |
|---|--:|---|
| `momentum_lookback` | 120 | momentum factor window |
| `vol_window` | 60 | volatility window |
| `vol_penalty` | 0.5 | weight on the vol penalty in `score = mom − k·vol` |
| `top_n` | 10 | names held |

A value tilt (dividend/earnings yield) can be folded in later; it's omitted by
default because fundamentals are sparse for many CSE names.

---

## 2. Cost & liquidity model (`csequant/backtest/costs.py`)

A trade of `notional` MAD incurs (all configurable; **assumptions, not official
tariffs** — tune to your broker):

```
commission = max(notional · commission_rate, commission_min)   # default 0.40%
exchange   = notional · exchange_fee_rate                       # Bourse, 0.10%
regulatory = notional · regulatory_fee_rate                     # AMMC,  0.02%
VAT (TVA)  = vat_rate · (commission + exchange + regulatory)    # 10%
slippage   = notional · slippage_bps / 1e4                      # 15 bps half-spread
```

**Liquidity:** no more than `liquidity_adv_frac` (default 10%) of a name's trailing
average daily *turnover* may be traded per day — this throttles thin CSE names and
is applied as a hard cap on every order in the engine.

---

## 3. Backtester (`csequant/backtest/engine.py`)

Event-driven, **share-level**, long-only, walk-forward (every decision at date *t*
uses only data up to *t* — indicators are causal):

1. Desired exposures come from the strategy; on each rebalance date (default
   weekly, `W-FRI`) they become equal-weight target weights among active names,
   capped at `max_position_weight`.
2. Targets are converted to **whole-share** orders; each order is liquidity-capped.
3. Sells execute first; **proceeds settle T+`settlement_days` (default 2)** and are
   not available to redeploy until then. Buys use only settled cash.
4. Fees + slippage are charged on every fill; the book is marked to market daily.
5. Outputs: equity curve, daily weights, a trade blotter, and a metrics summary vs
   the benchmark.

**Metrics** (`metrics.py`): CAGR, annualised vol, Sharpe, Sortino, max drawdown,
Calmar, FIFO round-trip win-rate & average trade return, annual turnover, and
benchmark comparison (excess CAGR, beta, correlation).

**Benchmark** (`benchmark.py`): equal-weight **buy-and-hold** of the cached liquid
universe — a transparent MASI proxy (see README §Data for why the official MASI
series isn't used).

---

## 4. Portfolio optimizer (`csequant/risk/portfolio_optimizer.py`)

Given capital **X** and risk tolerance **Y** (a named profile):

1. **Candidates** come from the *same* strategy signals the engine uses (names
   currently held by the factor model / momentum), so the portfolio is explainable
   with the same reasoning.
2. **Estimates:** annualised mean returns (shrunk 50% toward the cross-sectional
   mean to reduce overfitting) and a **Ledoit-Wolf shrinkage** covariance.
3. **Method by profile:** mean-variance (SLSQP, risk-aversion from Y),
   risk-parity (equal risk contribution), or rule-based equal-weight.
4. **Constraints:** per-name `max_weight`, per-sector `max_sector_weight`, and a
   `min_cash` budget.
5. **Volatility targeting:** exposure is scaled so portfolio vol ≈ the profile's
   `target_vol`; the remainder becomes a cash buffer.
6. **Whole-share quantisation** for capital X (no fractional shares); reports
   expected return/vol, a 1-year range, historical max drawdown of the static
   allocation, per-position risk contribution, and a sector breakdown — each
   position with a reason.

### Risk-profile mapping (`config/settings.yaml`)
| Profile | Method | Target vol | Max name | Max sector | Min cash |
|---|---|--:|--:|--:|--:|
| Conservative | risk-parity | 8% | 15% | 30% | 30% |
| Balanced | mean-variance | 14% | 25% | 45% | 10% |
| Aggressive | mean-variance | 22% | 40% | 60% | 0% |

Observed effect (real cache, 100k MAD): Conservative → ~9 names, ~59% cash, ~6%
expected vol; Aggressive → ~4 names, ~21% cash, ~19% expected vol. The risk knob
demonstrably changes concentration, cash, and volatility.

---

## 5. Results (latest run) & how to read them

From `reports/backtest_report.md` (window **2023-06-19 → 2026-06-19**, 18 names,
weekly rebalance, T+2, net of all costs):

| Strategy | CAGR | Sharpe | MaxDD | Win% | vs Benchmark |
|---|--:|--:|--:|--:|--:|
| factor_model | 9.8% | 0.75 | −16.1% | 50% | −14.5% |
| momentum | 7.6% | 0.56 | −18.6% | 44% | −16.7% |
| mean_reversion | −12.6% | −0.99 | −35.8% | 34% | −36.8% |
| **Benchmark (buy & hold)** | **24.2%** | **1.41** | −18.6% | — | — |

**The strategies lag buy-and-hold — and that's an honest result, not a bug.** Over
this ~3-year window the CSE was in a strong, fairly persistent bull market
(benchmark +88.6% total, CAGR 24%). Timing strategies that sit in cash part of the
time, pay costs on turnover, and cap position sizes structurally give up upside in
such a regime (note their beta ≈ 0.5–0.7). Mean reversion fares worst because
fading a steadily rising market is precisely the wrong bet here.

What the strategies *do* provide: lower beta and (for factor/momentum) shallower
drawdowns than a single concentrated name, with fully explainable decisions. The
value of the framework is the **transparent, cost-aware, reproducible process** —
not a claim of outperformance in this particular regime.

---

## 6. Known limitations

- **Short history:** ~3 years of EOD data is available from the source — short for
  robust strategy inference, and dominated by one bull regime.
- **EOD only:** no intraday data for CSE; signals and fills are end-of-day.
- **Benchmark is a proxy** (equal-weight composite), not the official MASI series.
- **Cost/settlement numbers are assumptions** — set them to your broker's tariffs.
- **Liquidity:** many CSE names are thin; the ADV cap helps but real fills on small
  caps can be worse than modelled.
- **Expected returns are historical**, shrunk but still noisy; treat optimizer
  expectations as estimates, not forecasts.
- **Not investment advice.** Research and decision-support only.
