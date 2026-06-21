"""Market view: price/volume/indicator charts and the backtest equity curves."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from ...strategies import indicators as ind
from ..state import backtests, index_levels, load_prices


def render() -> None:
    st.subheader("Market Evolution")
    prices = load_prices()
    if not prices:
        st.info("No cached data. Build the cache first.")
        return

    idx = index_levels()
    if not idx.empty:
        main = idx[idx["code"].isin(["MASI", "MSI20"])]
        if not main.empty:
            cols = st.columns(len(main))
            for col, (_, r) in zip(cols, main.iterrows()):
                col.metric(str(r["index"]), f"{r['value']:,.2f}",
                           f"{r['change_pct']:+.2f}% today")

    ticker = st.selectbox("Instrument", sorted(prices))
    o = prices[ticker].sort_values("date")
    close = o.set_index("date")["adj_close"]

    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, row_heights=[0.6, 0.2, 0.2],
        vertical_spacing=0.03, subplot_titles=(f"{ticker} — price & moving averages",
                                               "Volume (shares)", "RSI(14)"))
    fig.add_trace(go.Candlestick(x=o["date"], open=o["open"], high=o["high"],
                                 low=o["low"], close=o["close"], name="OHLC"), row=1, col=1)
    fig.add_trace(go.Scatter(x=close.index, y=ind.sma(close, 20), name="SMA20",
                             line=dict(width=1, color="#1f77b4")), row=1, col=1)
    fig.add_trace(go.Scatter(x=close.index, y=ind.sma(close, 50), name="SMA50",
                             line=dict(width=1, color="#ff7f0e")), row=1, col=1)
    _, up, lo = ind.bollinger(close, 20, 2.0)
    fig.add_trace(go.Scatter(x=close.index, y=up, name="Boll+", line=dict(width=0.5, color="gray"),
                             showlegend=False), row=1, col=1)
    fig.add_trace(go.Scatter(x=close.index, y=lo, name="Boll-", line=dict(width=0.5, color="gray"),
                             fill="tonexty", fillcolor="rgba(150,150,150,0.08)",
                             showlegend=False), row=1, col=1)
    fig.add_trace(go.Bar(x=o["date"], y=o["volume"], name="Volume",
                         marker_color="lightgray"), row=2, col=1)
    fig.add_trace(go.Scatter(x=close.index, y=ind.rsi(close, 14), name="RSI",
                             line=dict(width=1, color="purple")), row=3, col=1)
    fig.add_hline(y=70, row=3, col=1, line_dash="dot", line_color="red")
    fig.add_hline(y=30, row=3, col=1, line_dash="dot", line_color="green")
    fig.update_layout(height=720, xaxis_rangeslider_visible=False,
                      margin=dict(t=40, b=10), legend=dict(orientation="h", y=1.02))
    st.plotly_chart(fig, width='stretch')

    st.markdown("#### Strategy equity vs buy-and-hold benchmark")
    st.caption("Walk-forward backtest, net of CSE fees + slippage + liquidity caps, "
               "T+2 settlement. Benchmark = equal-weight buy-and-hold of the cached "
               "liquid universe (a transparent proxy for MASI).")
    bt = backtests()
    if not bt:
        return
    ef = go.Figure()
    bench = bt["benchmark"]
    ef.add_trace(go.Scatter(x=bench.index, y=bench.values, name="CSE-Composite (buy & hold)",
                            line=dict(color="black", width=2)))
    for name, d in bt["strategies"].items():
        ef.add_trace(go.Scatter(x=d["equity"].index, y=d["equity"].values, name=name))
    ef.update_layout(height=380, yaxis_title="Equity (MAD)", margin=dict(t=10),
                     legend=dict(orientation="h", y=1.1))
    st.plotly_chart(ef, width='stretch')

    rows = []
    for name, d in bt["strategies"].items():
        m = d["metrics"]
        rows.append({
            "Strategy": name,
            "CAGR": f"{m['cagr']*100:.1f}%",
            "Sharpe": f"{m['sharpe']:.2f}",
            "Max DD": f"{m['max_drawdown']*100:.1f}%",
            "Vol": f"{m['ann_vol']*100:.1f}%",
            "Win%": f"{m['win_rate']*100:.0f}%",
            "Trades": m["n_round_trips"],
            "Turnover": f"{m['annual_turnover']:.1f}x",
            "vs Bench": f"{m.get('excess_cagr', 0)*100:+.1f}%",
        })
    bench_cagr = next(iter(bt["strategies"].values()))["metrics"].get("benchmark_cagr", 0) * 100
    st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
    st.caption(f"Benchmark CAGR over the same window: {bench_cagr:.1f}%.")
