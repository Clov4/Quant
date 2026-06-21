"""Cached data/compute layer shared by all GUI views.

Everything here reads from the local cache (offline) so the dashboard works with
no network. Streamlit caching keeps reruns fast. A "Refresh live data" action in
the sidebar can repopulate the cache via the DataService when a network is up.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ..backtest import Backtester, build_benchmark
from ..config import load_config
from ..data.service import DataService
from ..data.storage.cache import Cache
from ..data.universe import load_universe
from ..risk import PortfolioOptimizer
from ..strategies import all_strategy_names, build_strategy


@st.cache_resource
def get_config():
    return load_config()


@st.cache_resource
def get_universe():
    return load_universe(get_config())


@st.cache_data(show_spinner=False)
def load_prices() -> dict[str, pd.DataFrame]:
    cfg = get_config()
    c = Cache(cfg.path("data.cache_db"))
    prices = {t: c.load_ohlcv([t]) for t in c.cached_tickers()}
    c.close()
    return prices


@st.cache_data(show_spinner=False)
def load_snapshot():
    cfg = get_config()
    c = Cache(cfg.path("data.cache_db"))
    df, captured = c.load_snapshot()
    c.close()
    stale = True
    if captured:
        try:
            age = (pd.Timestamp.now() - pd.to_datetime(captured)).days
            stale = age > int(cfg.get("data.stale_after_days", 5))
        except Exception:
            stale = True
    return df, captured, stale


@st.cache_data(show_spinner=False)
def index_levels():
    """Best-effort live index levels (MASI, MASI 20); empty if offline."""
    try:
        svc = DataService.from_config(get_config())
        return svc.get_index_snapshot()
    except Exception:
        return pd.DataFrame()


@st.cache_data(show_spinner="Generating signals…")
def all_signals() -> pd.DataFrame:
    cfg, uni = get_config(), get_universe()
    prices = load_prices()
    rows = []
    for name in all_strategy_names():
        strat = build_strategy(name, cfg)
        for ticker, ohlcv in prices.items():
            if ohlcv is None or ohlcv.empty:
                continue
            for sig in strat.generate_signals(ohlcv, ticker):
                rows.append({
                    "date": pd.Timestamp(sig.date),
                    "ticker": ticker,
                    "name": uni.name(ticker),
                    "sector": uni.sector(ticker),
                    "strategy": sig.strategy,
                    "action": sig.action,
                    "score": round(sig.score, 4),
                    "reason": sig.reason,
                })
    df = pd.DataFrame(rows)
    return df.sort_values("date", ascending=False).reset_index(drop=True) if not df.empty else df


@st.cache_data(show_spinner="Running backtests…")
def backtests() -> dict:
    cfg = get_config()
    prices = load_prices()
    if not prices:
        return {}
    prices_long = pd.concat(prices.values(), ignore_index=True)
    bench = build_benchmark(prices_long, float(cfg.get("backtest.initial_capital", 100_000)))
    bt = Backtester(cfg)
    out = {"benchmark": bench, "strategies": {}}
    for name in all_strategy_names():
        res = bt.run(build_strategy(name, cfg), prices, benchmark=bench)
        out["strategies"][name] = {
            "equity": res.equity, "metrics": res.metrics,
            "trades": res.trades, "weights": res.weights,
        }
    return out


@st.cache_data(show_spinner="Optimising portfolio…")
def recommend_portfolio(capital: float, risk_profile: str):
    cfg, uni = get_config(), get_universe()
    opt = PortfolioOptimizer(cfg, uni)
    return opt.recommend(load_prices(), capital, risk_profile)


def refresh_live_cache(progress=None) -> str:
    """Repopulate the local cache from live sources. Returns a status string."""
    cfg = get_config()
    svc = DataService.from_config(cfg)
    tickers = cfg.demo_tickers
    start = cfg.get("data.history_start", "2023-01-01")
    end = pd.Timestamp.now().strftime("%Y-%m-%d")
    for i, t in enumerate(tickers):
        svc.get_ohlcv(t, start, end, refresh=True)
        if progress:
            progress((i + 1) / len(tickers), t)
    svc.get_snapshot(refresh=True)
    svc.cache.close()
    return f"Refreshed {len(tickers)} tickers up to {end}."
