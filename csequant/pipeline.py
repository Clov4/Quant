"""Headless pipeline: build cache, generate signals, backtest, and write reports.

Pure functions (no Streamlit) shared by the CLI, the scheduler, and tests. The
GUI has its own cached wrappers but the logic lives here.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from . import DISCLAIMER, __version__
from .backtest import Backtester, build_benchmark
from .backtest import metrics as M
from .config import Config
from .data.service import DataService
from .data.storage.cache import Cache
from .data.universe import load_universe
from .logging_conf import get_logger
from .strategies import all_strategy_names, build_strategy

log = get_logger(__name__)


# --- data -------------------------------------------------------------------
def build_cache(cfg: Config, tickers: list[str] | None = None,
                start: str | None = None, end: str | None = None) -> pd.DataFrame:
    svc = DataService.from_config(cfg)
    tickers = tickers or cfg.demo_tickers
    start = start or cfg.get("data.history_start", "2023-01-01")
    end = end or date.today().isoformat()
    cov = svc.build_cache(tickers, start, end)
    svc.get_snapshot(refresh=True)
    # portable parquet export
    pdir = cfg.path("data.parquet_dir")
    pdir.mkdir(parents=True, exist_ok=True)
    svc.cache.load_ohlcv().to_parquet(pdir / "ohlcv.parquet", index=False)
    svc.cache.close()
    return cov


def load_cached_prices(cfg: Config) -> dict[str, pd.DataFrame]:
    c = Cache(cfg.path("data.cache_db"))
    prices = {t: c.load_ohlcv([t]) for t in c.cached_tickers()}
    c.close()
    return prices


# --- signals ----------------------------------------------------------------
def signals_table(cfg: Config, prices: dict[str, pd.DataFrame] | None = None) -> pd.DataFrame:
    uni = load_universe(cfg)
    prices = prices or load_cached_prices(cfg)
    rows = []
    for name in all_strategy_names():
        strat = build_strategy(name, cfg)
        for ticker, ohlcv in prices.items():
            if ohlcv is None or ohlcv.empty:
                continue
            for sig in strat.generate_signals(ohlcv, ticker):
                d = sig.to_dict()
                d["name"] = uni.name(ticker)
                rows.append(d)
    df = pd.DataFrame(rows)
    return df.sort_values("date", ascending=False).reset_index(drop=True) if not df.empty else df


# --- backtests --------------------------------------------------------------
def run_all_backtests(cfg: Config, prices: dict[str, pd.DataFrame] | None = None) -> dict:
    prices = prices or load_cached_prices(cfg)
    if not prices:
        raise RuntimeError("No cached prices. Run `build-cache` first.")
    prices_long = pd.concat(prices.values(), ignore_index=True)
    bench = build_benchmark(prices_long, float(cfg.get("backtest.initial_capital", 100_000)))
    bt = Backtester(cfg)
    out = {"benchmark": bench, "strategies": {}}
    for name in all_strategy_names():
        out["strategies"][name] = bt.run(build_strategy(name, cfg), prices, benchmark=bench)
    return out


def run_backtest_window(cfg: Config, start: str | None, end: str | None,
                        prices: dict[str, pd.DataFrame] | None = None) -> dict:
    """Evaluate the strategies over a sub-window [start, end] for regime comparison.

    The engine still runs over the *full* history (so indicators are warmed up with
    the real prior data you'd have had at `start` — no look-ahead), then the equity
    curve, trades, and benchmark are sliced to the window and metrics recomputed.
    This reuses the engine and metrics; no separate backtest logic.
    """
    full = run_all_backtests(cfg, prices)
    ppy = int(cfg.get("market.trading_days_per_year", 252))
    s = pd.Timestamp(start) if start else None
    e = pd.Timestamp(end) if end else None
    bench_w = full["benchmark"].loc[s:e]

    out = {"benchmark": bench_w, "strategies": {}, "window": (start, end)}
    for name, res in full["strategies"].items():
        eq = res.equity.loc[s:e]
        tr = res.trades
        if not tr.empty:
            td = pd.to_datetime(tr["date"])
            if s is not None:
                tr = tr[td >= s]
            if e is not None:
                tr = tr[pd.to_datetime(tr["date"]) <= e]
        out["strategies"][name] = {
            "equity": eq, "trades": tr, "metrics": M.summary(eq, tr, ppy, bench_w),
        }
    return out


# --- report -----------------------------------------------------------------
def write_backtest_report(cfg: Config, out_path: str | Path | None = None) -> Path:
    results = run_all_backtests(cfg)
    bench = results["benchmark"]
    ppy = int(cfg.get("market.trading_days_per_year", 252))
    bench_m = M.summary(bench, None, ppy)

    out_path = Path(out_path) if out_path else (cfg.path("data.parquet_dir").parent.parent
                                                / "reports" / "backtest_report.md")
    out_path = out_path if out_path.is_absolute() else (Path.cwd() / out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    first = next(iter(results["strategies"].values()))
    start = first.equity.index[0].strftime("%Y-%m-%d")
    end = first.equity.index[-1].strftime("%Y-%m-%d")
    tickers = first.meta.get("tickers", [])

    def pct(x):
        return f"{x*100:.1f}%"

    lines = [
        f"# CSE Backtest Report",
        "",
        f"*Generated by csequant v{__version__}.* "
        f"Window **{start} → {end}** · {len(tickers)} instruments · "
        f"rebalance `{first.meta.get('rebalance')}` · settlement T+{first.meta.get('settlement_days')}.",
        "",
        "Universe: " + ", ".join(tickers),
        "",
        "## Summary vs buy-and-hold benchmark",
        "",
        "| Strategy | CAGR | Vol | Sharpe | Sortino | MaxDD | Calmar | Win% | Trades | Turnover | vs Bench |",
        "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|",
    ]
    for name, res in results["strategies"].items():
        m = res.metrics
        lines.append(
            f"| {name} | {pct(m['cagr'])} | {pct(m['ann_vol'])} | {m['sharpe']:.2f} | "
            f"{m['sortino']:.2f} | {pct(m['max_drawdown'])} | {m['calmar']:.2f} | "
            f"{pct(m['win_rate'])} | {m['n_round_trips']} | {m['annual_turnover']:.1f}x | "
            f"{pct(m.get('excess_cagr', 0))} |"
        )
    lines.append(
        f"| **Benchmark (buy&hold)** | {pct(bench_m['cagr'])} | {pct(bench_m['ann_vol'])} | "
        f"{bench_m['sharpe']:.2f} | {bench_m['sortino']:.2f} | {pct(bench_m['max_drawdown'])} | "
        f"{bench_m['calmar']:.2f} | — | — | — | — |"
    )

    lines += ["", "## Per-strategy detail", ""]
    for name, res in results["strategies"].items():
        m = res.metrics
        lines += [
            f"### {name}",
            "",
            f"- Total return: {pct(m['total_return'])} (benchmark {pct(bench_m['total_return'])})",
            f"- Beta to benchmark: {m.get('beta', float('nan')):.2f}, "
            f"correlation {m.get('correlation', float('nan')):.2f}",
            f"- Round-trip trades: {m['n_round_trips']}, "
            f"win rate {pct(m['win_rate'])}, avg trade {pct(m['avg_trade_return'])}",
            "",
            "Most recent trades:",
            "",
            "```",
            res.trades.tail(6).to_string(index=False) if not res.trades.empty else "(none)",
            "```",
            "",
        ]

    lines += [
        "## Methodology & limitations",
        "",
        "- **Costs:** broker commission, exchange + AMMC fees, 10% VAT on fees, and "
        "slippage are deducted on every trade; a per-name daily liquidity cap based on "
        "trailing turnover throttles thin names.",
        "- **Settlement:** sale proceeds are not available to redeploy until T+settlement.",
        "- **Benchmark:** an equal-weight buy-and-hold composite of the cached liquid "
        "universe — a transparent proxy for MASI (the official MASI daily series is not "
        "reliably reachable; see README §Data).",
        "- **History:** the exchange's instrument-history API serves ~3 years of EOD data, "
        "so this is an end-of-day system over a relatively short, mostly-bull window — "
        "interpret timing-strategy underperformance vs buy-and-hold in that light.",
        "",
        f"> {DISCLAIMER}",
        "",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Wrote backtest report -> %s", out_path)
    return out_path
