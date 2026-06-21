"""Portfolio view: recommended allocation for capital X and risk tolerance Y."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from ... import DISCLAIMER
from ..state import get_config, recommend_portfolio


def render() -> None:
    st.subheader("Portfolio Recommendation")
    cfg = get_config()
    profiles = cfg.risk_profile_names

    c1, c2 = st.columns(2)
    capital = c1.number_input("Capital X (MAD)", min_value=1000.0, value=100_000.0,
                              step=5000.0, format="%.0f")
    default_idx = profiles.index("Balanced") if "Balanced" in profiles else 0
    profile = c2.selectbox("Risk tolerance Y", profiles, index=default_idx)

    try:
        rec = recommend_portfolio(float(capital), profile)
    except Exception as e:  # pragma: no cover - GUI guard
        st.error(f"Could not build a recommendation: {e}")
        return

    if not rec.positions:
        st.warning("No positions selected for this profile/data window.")
        return

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Expected return (p.a.)", f"{rec.expected_return*100:.1f}%")
    m2.metric("Expected volatility", f"{rec.expected_vol*100:.1f}%")
    m3.metric("Cash buffer", f"{rec.cash_weight*100:.0f}%")
    m4.metric("Hist. max drawdown", f"{rec.historical_max_drawdown*100:.1f}%")
    st.caption(f"Expected 1-year range **{rec.expected_return_low*100:+.1f}% .. "
               f"{rec.expected_return_high*100:+.1f}%** · method: `{rec.method}` · "
               f"as of {rec.as_of}")

    df = rec.to_frame()
    left, right = st.columns([0.56, 0.44])
    with left:
        show = df[["ticker", "name", "sector", "weight", "shares", "value_mad", "price"]].copy()
        st.dataframe(
            show, width='stretch', hide_index=True, height=360,
            column_config={
                "weight": st.column_config.NumberColumn("Weight", format="%.1f%%"),
                "value_mad": st.column_config.NumberColumn("Value (MAD)", format="%.0f"),
                "price": st.column_config.NumberColumn("Price", format="%.2f"),
            },
        )
    with right:
        pie_df = pd.concat([
            df[["ticker", "value_mad"]],
            pd.DataFrame([{"ticker": "CASH", "value_mad": rec.cash_value}]),
        ], ignore_index=True)
        fig = px.pie(pie_df, values="value_mad", names="ticker", hole=0.4,
                     title="Capital allocation")
        fig.update_layout(height=360, margin=dict(t=40, b=0))
        st.plotly_chart(fig, width='stretch')

    if rec.sector_breakdown:
        sec = pd.DataFrame(
            [{"sector": s, "weight": w * 100} for s, w in rec.sector_breakdown.items()]
        ).sort_values("weight")
        sfig = px.bar(sec, x="weight", y="sector", orientation="h",
                      title="Sector exposure (% of capital)")
        sfig.update_layout(height=280, margin=dict(t=40, b=0), xaxis_title="", yaxis_title="")
        st.plotly_chart(sfig, width='stretch')

    st.markdown("#### Why each position?")
    for p in rec.positions:
        with st.expander(f"**{p.ticker}** · {p.weight*100:.1f}% · {p.shares} shares · "
                         f"{p.value:,.0f} MAD · {p.sector}"):
            st.write(p.reason)

    for n in rec.notes:
        st.caption("• " + n)
    st.warning(DISCLAIMER)
