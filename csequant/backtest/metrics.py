"""Performance metrics and FIFO round-trip reconstruction.

The round-trip logic folds fees + slippage into *effective* per-share prices so a
trade's return is exactly its realised cash-on-cash result — this is the PnL math
covered by tests/test_backtest_pnl.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_PPY = 252


# --- return / risk metrics --------------------------------------------------
def total_return(equity: pd.Series) -> float:
    if len(equity) < 2 or equity.iloc[0] == 0:
        return 0.0
    return float(equity.iloc[-1] / equity.iloc[0] - 1.0)


def cagr(equity: pd.Series, ppy: int = DEFAULT_PPY) -> float:
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return 0.0
    years = (len(equity) - 1) / ppy
    if years <= 0:
        return 0.0
    return float((equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0)


def ann_vol(returns: pd.Series, ppy: int = DEFAULT_PPY) -> float:
    r = returns.dropna()
    if r.empty:
        return 0.0
    return float(r.std(ddof=0) * np.sqrt(ppy))


def sharpe(returns: pd.Series, ppy: int = DEFAULT_PPY, rf: float = 0.0) -> float:
    r = returns.dropna()
    if r.empty:
        return 0.0
    excess = r - rf / ppy
    sd = excess.std(ddof=0)
    if sd < 1e-12:          # degenerate / ~constant returns -> undefined, report 0
        return 0.0
    return float(excess.mean() / sd * np.sqrt(ppy))


def sortino(returns: pd.Series, ppy: int = DEFAULT_PPY, rf: float = 0.0) -> float:
    r = returns.dropna()
    if r.empty:
        return 0.0
    excess = r - rf / ppy
    downside = excess[excess < 0].std(ddof=0)
    if not np.isfinite(downside) or downside < 1e-12:
        return 0.0
    return float(excess.mean() / downside * np.sqrt(ppy))


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    dd = equity / equity.cummax() - 1.0
    return float(dd.min())


def calmar(equity: pd.Series, ppy: int = DEFAULT_PPY) -> float:
    mdd = abs(max_drawdown(equity))
    return float(cagr(equity, ppy) / mdd) if mdd > 0 else 0.0


# --- round trips (FIFO) -----------------------------------------------------
def round_trips_from_trades(trades: pd.DataFrame) -> pd.DataFrame:
    """Match BUY/SELL executions FIFO into closed round trips.

    *trades* needs columns: date, ticker, side ('BUY'/'SELL'), shares, gross, fees.
    Effective per-share price folds fees in: buy = (gross+fees)/shares,
    sell = (gross-fees)/shares.
    """
    cols = ["ticker", "entry_date", "exit_date", "shares",
            "entry_value", "exit_value", "pnl", "return_pct", "holding_days"]
    if trades is None or trades.empty:
        return pd.DataFrame(columns=cols)

    rows = []
    for ticker, grp in trades.sort_values("date").groupby("ticker"):
        lots: list[dict] = []  # open buy lots: {shares, price, date}
        for tr in grp.itertuples(index=False):
            shares = float(tr.shares)
            if shares <= 0:
                continue
            if tr.side == "BUY":
                eff = (float(tr.gross) + float(tr.fees)) / shares
                lots.append({"shares": shares, "price": eff, "date": tr.date})
            elif tr.side == "SELL":
                eff = (float(tr.gross) - float(tr.fees)) / shares
                remaining = shares
                while remaining > 1e-9 and lots:
                    lot = lots[0]
                    matched = min(remaining, lot["shares"])
                    entry_val = matched * lot["price"]
                    exit_val = matched * eff
                    rows.append({
                        "ticker": ticker,
                        "entry_date": lot["date"],
                        "exit_date": tr.date,
                        "shares": matched,
                        "entry_value": entry_val,
                        "exit_value": exit_val,
                        "pnl": exit_val - entry_val,
                        "return_pct": (exit_val / entry_val - 1.0) if entry_val else 0.0,
                        "holding_days": (pd.Timestamp(tr.date) - pd.Timestamp(lot["date"])).days,
                    })
                    lot["shares"] -= matched
                    remaining -= matched
                    if lot["shares"] <= 1e-9:
                        lots.pop(0)
    return pd.DataFrame(rows, columns=cols)


def win_rate(round_trips: pd.DataFrame) -> float:
    if round_trips is None or round_trips.empty:
        return 0.0
    return float((round_trips["pnl"] > 0).mean())


def avg_trade_return(round_trips: pd.DataFrame) -> float:
    if round_trips is None or round_trips.empty:
        return 0.0
    return float(round_trips["return_pct"].mean())


def annual_turnover(trades: pd.DataFrame, equity: pd.Series, ppy: int = DEFAULT_PPY) -> float:
    """Traded notional per year as a multiple of average equity."""
    if trades is None or trades.empty or equity.empty:
        return 0.0
    traded = trades["gross"].abs().sum()
    avg_eq = equity.mean()
    years = max((len(equity) - 1) / ppy, 1e-9)
    return float(traded / avg_eq / years) if avg_eq else 0.0


# --- summary ----------------------------------------------------------------
def summary(
    equity: pd.Series,
    trades: pd.DataFrame | None = None,
    ppy: int = DEFAULT_PPY,
    benchmark_equity: pd.Series | None = None,
) -> dict:
    returns = equity.pct_change()
    rts = round_trips_from_trades(trades) if trades is not None else pd.DataFrame()
    out = {
        "total_return": total_return(equity),
        "cagr": cagr(equity, ppy),
        "ann_vol": ann_vol(returns, ppy),
        "sharpe": sharpe(returns, ppy),
        "sortino": sortino(returns, ppy),
        "max_drawdown": max_drawdown(equity),
        "calmar": calmar(equity, ppy),
        "n_round_trips": int(len(rts)),
        "win_rate": win_rate(rts),
        "avg_trade_return": avg_trade_return(rts),
        "annual_turnover": annual_turnover(trades, equity, ppy) if trades is not None else 0.0,
    }
    if benchmark_equity is not None and not benchmark_equity.empty:
        bench = benchmark_equity.reindex(equity.index).ffill()
        bret = bench.pct_change()
        out["benchmark_cagr"] = cagr(bench, ppy)
        out["benchmark_total_return"] = total_return(bench)
        out["benchmark_max_drawdown"] = max_drawdown(bench)
        out["excess_cagr"] = out["cagr"] - out["benchmark_cagr"]
        joined = pd.concat([returns, bret], axis=1).dropna()
        if len(joined) > 2 and joined.iloc[:, 1].std(ddof=0) > 0:
            cov = joined.cov().iloc[0, 1]
            out["beta"] = float(cov / joined.iloc[:, 1].var(ddof=0))
            out["correlation"] = float(joined.iloc[:, 0].corr(joined.iloc[:, 1]))
    return out
