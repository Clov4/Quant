"""Streamlit dashboard entry point.

Run from the project root:

    streamlit run csequant/gui/app.py

Three views — Trades, Market, Portfolio — all driven by real cached CSE data.
"""
from __future__ import annotations

import pathlib
import sys

# Make the project importable when launched via `streamlit run path/to/app.py`
# (Streamlit puts the script's dir on sys.path, not the project root).
_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st  # noqa: E402

from csequant import DISCLAIMER, __version__  # noqa: E402
from csequant.gui.state import load_snapshot, refresh_live_cache  # noqa: E402
from csequant.gui.views import market_view, portfolio_view, trades_view  # noqa: E402

st.set_page_config(page_title="CSE Quant", page_icon="📈", layout="wide")

st.title("📈 Casablanca Stock Exchange — Quant Research Dashboard")
st.caption("Signals with their reasoning · market charts · capital/risk-based portfolio. "
           "Research and decision-support only — **not** licensed investment advice.")

with st.sidebar:
    st.header("Data")
    snap, captured, stale = load_snapshot()
    st.write(f"Instruments in snapshot: **{len(snap)}**" if snap is not None and len(snap)
             else "No snapshot cached")
    if captured:
        st.write(f"Captured: `{captured}`")
        st.error("⚠️ Snapshot is STALE") if stale else st.success("✅ Snapshot is fresh")
    st.divider()
    if st.button("🔄 Refresh live data", width='stretch',
                 help="Re-fetch EOD history + snapshot from casablanca-bourse.com"):
        bar = st.progress(0.0, text="starting…")
        try:
            msg = refresh_live_cache(lambda f, t: bar.progress(f, text=f"fetching {t}…"))
            st.cache_data.clear()
            st.success(msg)
        except Exception as e:
            st.error(f"Refresh failed (offline?): {e}")
    st.caption("Offline-first: the dashboard works from the local cache with no network.")
    st.divider()
    st.caption(f"csequant v{__version__}")

tab_trades, tab_market, tab_portfolio = st.tabs(
    ["📋 Trades & Signals", "📈 Market Evolution", "💼 Portfolio"]
)
with tab_trades:
    trades_view.render()
with tab_market:
    market_view.render()
with tab_portfolio:
    portfolio_view.render()

st.divider()
st.caption(DISCLAIMER)
