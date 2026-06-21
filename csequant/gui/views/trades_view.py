"""Trades view: the signal/trade log with the reasoning behind each one."""
from __future__ import annotations

import streamlit as st

from ..state import all_signals


def render() -> None:
    st.subheader("Trades & Signals")
    st.caption("Every signal records the exact indicator values that triggered it — "
               "expand a row to read the plain-language reasoning.")

    df = all_signals()
    if df.empty:
        st.info("No signals yet. Build the data cache (`python -m scripts.build_cache`) "
                "or use **Refresh live data** in the sidebar.")
        return

    tickers = sorted(df["ticker"].unique())
    strategies = sorted(df["strategy"].unique())
    actions = sorted(df["action"].unique())
    c1, c2, c3, c4 = st.columns(4)
    sel_t = c1.multiselect("Ticker", tickers)
    sel_s = c2.multiselect("Strategy", strategies)
    sel_a = c3.multiselect("Action", actions)
    dmin, dmax = df["date"].min().date(), df["date"].max().date()
    dr = c4.date_input("Date range", (dmin, dmax), min_value=dmin, max_value=dmax)

    f = df
    if sel_t:
        f = f[f["ticker"].isin(sel_t)]
    if sel_s:
        f = f[f["strategy"].isin(sel_s)]
    if sel_a:
        f = f[f["action"].isin(sel_a)]
    if isinstance(dr, tuple) and len(dr) == 2:
        f = f[(f["date"].dt.date >= dr[0]) & (f["date"].dt.date <= dr[1])]

    buys = int((f["action"] == "BUY").sum())
    sells = int((f["action"] == "SELL").sum())
    m1, m2, m3 = st.columns(3)
    m1.metric("Signals", len(f))
    m2.metric("Buys", buys)
    m3.metric("Sells", sells)

    st.dataframe(
        f[["date", "ticker", "name", "strategy", "action", "score", "reason"]],
        width='stretch', hide_index=True, height=360,
        column_config={
            "date": st.column_config.DateColumn("Date"),
            "reason": st.column_config.TextColumn("Reasoning", width="large"),
        },
    )

    st.markdown("#### Reasoning detail (most recent 15)")
    for _, r in f.head(15).iterrows():
        icon = {"BUY": "🟢", "SELL": "🔴"}.get(r["action"], "⚪")
        with st.expander(f"{icon} {r['date'].date()} · {r['action']} **{r['ticker']}** "
                         f"· {r['strategy']} · score {r['score']}"):
            st.write(r["reason"])
            st.caption(f"{r['name']} — {r['sector']}")
