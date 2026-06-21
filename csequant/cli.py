"""Command-line interface: ``python -m csequant <command>``.

Commands:
    build-cache   fetch + cache real EOD data (and a parquet export)
    signals       print the most recent strategy signals with reasoning
    backtest      run all strategies and print a metrics table vs benchmark
    report        write reports/backtest_report.md
    recommend     print a portfolio for --capital and --risk
    gui           launch the Streamlit dashboard
"""
from __future__ import annotations

import argparse
import subprocess
import sys

import pandas as pd

from . import pipeline
from .config import PROJECT_ROOT, load_config
from .data.universe import load_universe
from .logging_conf import setup_logging
from .risk import PortfolioOptimizer


def _print_backtest_table(strat_metrics: dict) -> None:
    rows = []
    for name, m in strat_metrics.items():
        rows.append({
            "strategy": name, "CAGR": f"{m['cagr']*100:.1f}%",
            "vol": f"{m['ann_vol']*100:.1f}%", "Sharpe": f"{m['sharpe']:.2f}",
            "maxDD": f"{m['max_drawdown']*100:.1f}%", "win%": f"{m['win_rate']*100:.0f}%",
            "trades": m["n_round_trips"], "turn": f"{m['annual_turnover']:.1f}x",
            "vsBench": f"{m.get('excess_cagr', 0)*100:+.1f}%",
        })
    print(pd.DataFrame(rows).to_string(index=False))
    bench_cagr = next(iter(strat_metrics.values())).get("benchmark_cagr", 0) * 100
    print(f"\nBenchmark (buy & hold) CAGR: {bench_cagr:.1f}%")


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    setup_logging(cfg.get("logging.level", "INFO"), cfg.path("logging.file"))

    ap = argparse.ArgumentParser(prog="csequant", description="Casablanca SE quant CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build-cache", help="fetch + cache real EOD data")
    p_build.add_argument("--tickers", nargs="*")
    p_build.add_argument("--start")
    p_build.add_argument("--end")

    p_sig = sub.add_parser("signals", help="recent signals with reasoning")
    p_sig.add_argument("--limit", type=int, default=20)
    p_sig.add_argument("--ticker")

    sub.add_parser("backtest", help="metrics table vs benchmark")

    p_win = sub.add_parser("backtest-window",
                           help="backtest metrics over a date sub-window (regime test)")
    p_win.add_argument("--start", required=True)
    p_win.add_argument("--end", required=True)

    p_rep = sub.add_parser("report", help="write markdown backtest report")
    p_rep.add_argument("--out")

    p_rec = sub.add_parser("recommend", help="portfolio for capital X and risk Y")
    p_rec.add_argument("--capital", type=float, default=100_000)
    p_rec.add_argument("--risk", default="Balanced")

    sub.add_parser("gui", help="launch the Streamlit dashboard")

    args = ap.parse_args(argv)
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 30)

    if args.cmd == "build-cache":
        cov = pipeline.build_cache(cfg, args.tickers, args.start, args.end)
        print(cov.to_string(index=False) if not cov.empty else "(no data)")

    elif args.cmd == "signals":
        df = pipeline.signals_table(cfg)
        if args.ticker:
            df = df[df["ticker"] == args.ticker.upper()]
        cols = ["date", "ticker", "strategy", "action", "score", "reason"]
        print(df.head(args.limit)[cols].to_string(index=False) if not df.empty else "(no signals)")

    elif args.cmd == "backtest":
        res = pipeline.run_all_backtests(cfg)
        _print_backtest_table({name: r.metrics for name, r in res["strategies"].items()})

    elif args.cmd == "backtest-window":
        res = pipeline.run_backtest_window(cfg, args.start, args.end)
        n = len(next(iter(res["strategies"].values()))["equity"])
        print(f"Backtest window {args.start} → {args.end}  ({n} trading days, "
              f"indicators warmed up on prior history)\n")
        _print_backtest_table({name: d["metrics"] for name, d in res["strategies"].items()})

    elif args.cmd == "report":
        path = pipeline.write_backtest_report(cfg, args.out)
        print(f"Wrote {path}")

    elif args.cmd == "recommend":
        uni = load_universe(cfg)
        prices = pipeline.load_cached_prices(cfg)
        rec = PortfolioOptimizer(cfg, uni).recommend(prices, args.capital, args.risk)
        print(f"\nPortfolio for {args.capital:,.0f} MAD — {rec.risk_profile} ({rec.method}), "
              f"as of {rec.as_of}")
        print(f"Expected return {rec.expected_return*100:.1f}% p.a. "
              f"(range {rec.expected_return_low*100:+.1f}%..{rec.expected_return_high*100:+.1f}%), "
              f"vol {rec.expected_vol*100:.1f}%, cash {rec.cash_weight*100:.0f}%, "
              f"hist maxDD {rec.historical_max_drawdown*100:.1f}%\n")
        show = rec.to_frame()[["ticker", "name", "sector", "weight", "shares", "value_mad"]].copy()
        show["weight"] = (show["weight"] * 100).round(1)
        print(show.to_string(index=False))
        print(f"\nCash: {rec.cash_value:,.0f} MAD ({rec.cash_weight*100:.0f}%)")
        print(f"\n{rec.disclaimer}")

    elif args.cmd == "gui":
        app = PROJECT_ROOT / "csequant" / "gui" / "app.py"
        return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app)])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
