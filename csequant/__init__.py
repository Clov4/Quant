"""csequant — a quantitative trading research system for the Casablanca Stock Exchange (CSE).

The package is organised into independent, swappable layers (see README §Architecture):

    data/         data providers, local cache, and the DataService orchestrator
    strategies/   indicators, signal-generating strategies, Strategy/Signal contracts
    backtest/     cost model, walk-forward engine, performance metrics, benchmark
    risk/         portfolio optimizer (X capital, Y risk) and position sizing
    explainability/  plain-language reasoning attached to every signal/allocation
    gui/          Streamlit dashboard (trades / market / portfolio views)
    live/         scheduled end-of-day refresh

This is a research / decision-support tool. It is NOT licensed investment advice.
"""

__version__ = "0.1.0"

DISCLAIMER = (
    "This software is a research and decision-support tool for the Casablanca Stock "
    "Exchange. It is NOT licensed investment advice. Market data may be delayed, "
    "incomplete, or stale. Do your own research and consult a licensed professional "
    "before trading."
)
