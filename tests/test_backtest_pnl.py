"""Tests for round-trip PnL reconstruction and performance metrics."""
import numpy as np
import pandas as pd

from csequant.backtest import metrics as M


def _trade(date, ticker, side, shares, price, fees):
    return {"date": pd.Timestamp(date), "ticker": ticker, "side": side,
            "shares": shares, "gross": shares * price, "fees": fees}


def test_single_round_trip_pnl_folds_fees():
    # BUY 10 @100 (fees 10) -> eff entry 101; SELL 10 @110 (fees 10) -> eff exit 109
    trades = pd.DataFrame([
        _trade("2024-01-01", "AAA", "BUY", 10, 100.0, 10.0),
        _trade("2024-01-10", "AAA", "SELL", 10, 110.0, 10.0),
    ])
    rts = M.round_trips_from_trades(trades)
    assert len(rts) == 1
    row = rts.iloc[0]
    assert abs(row["entry_value"] - 1010.0) < 1e-9   # 10 * 101
    assert abs(row["exit_value"] - 1090.0) < 1e-9    # 10 * 109
    assert abs(row["pnl"] - 80.0) < 1e-9
    assert abs(row["return_pct"] - (1090.0 / 1010.0 - 1.0)) < 1e-9
    assert row["holding_days"] == 9


def test_fifo_partial_matching():
    trades = pd.DataFrame([
        _trade("2024-01-01", "AAA", "BUY", 10, 100.0, 0.0),
        _trade("2024-01-02", "AAA", "BUY", 10, 120.0, 0.0),
        _trade("2024-01-03", "AAA", "SELL", 15, 130.0, 0.0),
    ])
    rts = M.round_trips_from_trades(trades).sort_values("entry_date").reset_index(drop=True)
    # FIFO: 10 from the 100 lot, then 5 from the 120 lot
    assert len(rts) == 2
    assert rts.loc[0, "shares"] == 10 and abs(rts.loc[0, "pnl"] - 10 * 30) < 1e-9
    assert rts.loc[1, "shares"] == 5 and abs(rts.loc[1, "pnl"] - 5 * 10) < 1e-9


def test_win_rate_and_avg():
    rts = pd.DataFrame({"pnl": [10.0, -5.0, 20.0, -1.0], "return_pct": [0.1, -0.05, 0.2, -0.01]})
    assert M.win_rate(rts) == 0.5
    assert abs(M.avg_trade_return(rts) - np.mean([0.1, -0.05, 0.2, -0.01])) < 1e-9


def test_cagr_and_drawdown():
    # equity doubles over exactly 1 year of trading days
    eq = pd.Series(np.linspace(100, 200, 253))
    assert abs(M.cagr(eq, ppy=252) - 1.0) < 0.02
    eq2 = pd.Series([100, 150, 75, 120], dtype=float)
    assert abs(M.max_drawdown(eq2) - (75 / 150 - 1.0)) < 1e-9


def test_sharpe_sign_and_zero():
    flat = pd.Series([0.0] * 100)
    assert M.sharpe(flat) == 0.0
    pos = pd.Series([0.001] * 100)            # constant positive, zero vol
    assert M.sharpe(pos) == 0.0               # std 0 -> defined as 0
    rng = np.random.default_rng(0)
    good = pd.Series(rng.normal(0.001, 0.01, 1000))
    assert M.sharpe(good) > 0


def test_empty_trades_safe():
    rts = M.round_trips_from_trades(pd.DataFrame())
    assert rts.empty
    assert M.win_rate(rts) == 0.0
