"""Integration tests for the backtest engine and benchmark."""
import numpy as np

from csequant.backtest import Backtester, build_benchmark
from csequant.backtest.costs import CostModel
from csequant.config import load_config
from csequant.strategies import build_strategy


def test_engine_runs_and_is_consistent(synth_prices):
    cfg = load_config()
    bt = Backtester(cfg)
    res = bt.run(build_strategy("momentum", cfg), synth_prices)

    # equity starts at the configured capital and is never NaN
    cap = float(cfg.get("backtest.initial_capital"))
    assert abs(res.equity.iloc[0] - cap) < 1e-6
    assert not res.equity.isna().any()
    assert (res.equity > 0).all()

    # daily weights (incl. cash) sum to ~1 on the vast majority of bars
    wsum = res.weights.fillna(0).sum(axis=1)
    assert (wsum.between(0.95, 1.05)).mean() > 0.95

    # trade blotter is well-formed
    if not res.trades.empty:
        assert set(res.trades["side"].unique()) <= {"BUY", "SELL"}
        assert (res.trades["shares"] > 0).all()


def test_costs_reduce_returns(synth_prices):
    cfg = load_config()
    free = Backtester(cfg, CostModel(commission_rate=0, exchange_fee_rate=0,
                                     regulatory_fee_rate=0, vat_rate=0, slippage_bps=0))
    pricey = Backtester(cfg, CostModel(commission_rate=0.02, slippage_bps=100))
    strat = "momentum"
    r_free = free.run(build_strategy(strat, cfg), synth_prices)
    r_cost = pricey.run(build_strategy(strat, cfg), synth_prices)
    # higher costs cannot improve terminal equity
    assert r_cost.equity.iloc[-1] <= r_free.equity.iloc[-1] + 1e-6


def test_benchmark_buy_and_hold(synth_prices):
    import pandas as pd
    long = pd.concat(synth_prices.values(), ignore_index=True)
    bench = build_benchmark(long, initial_capital=100_000.0)
    assert abs(bench.iloc[0] - 100_000.0) < 1.0
    assert not bench.isna().any()
    assert np.isfinite(bench.iloc[-1])
