"""Shared pytest fixtures — synthetic, deterministic, network-free."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from csequant import schema
from csequant.data.universe import Universe


@pytest.fixture
def synth_prices() -> dict[str, pd.DataFrame]:
    """Six seeded geometric-random-walk tickers, ~320 business days, canonical schema."""
    rng = np.random.default_rng(42)
    dates = pd.bdate_range("2023-01-02", periods=320)
    out: dict[str, pd.DataFrame] = {}
    for i, t in enumerate(["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]):
        ret = rng.normal(0.0004 + 0.0001 * i, 0.012, len(dates))
        close = 100 * np.exp(np.cumsum(ret))
        vol = rng.integers(10_000, 100_000, len(dates)).astype(float)
        df = pd.DataFrame({
            schema.DATE: dates,
            schema.TICKER: t,
            schema.OPEN: close * (1 + rng.normal(0, 0.002, len(dates))),
            schema.HIGH: close * (1 + np.abs(rng.normal(0, 0.005, len(dates)))),
            schema.LOW: close * (1 - np.abs(rng.normal(0, 0.005, len(dates)))),
            schema.CLOSE: close,
            schema.ADJ_CLOSE: close,
            schema.VOLUME: vol,
            schema.TURNOVER: close * vol,
            schema.TRADES: rng.integers(10, 100, len(dates)).astype(float),
            schema.CURRENCY: "MAD",
        })
        out[t] = schema.ensure_schema(df)
    return out


@pytest.fixture
def synth_universe() -> Universe:
    """A small universe with two sectors (for sector-cap tests)."""
    tickers = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
    sectors = ["Banks", "Banks", "Banks", "Mining", "Mining", "Food"]
    instruments = pd.DataFrame({
        "name": [f"Company {t}" for t in tickers],
        "ticker": tickers,
        "instrument_id": range(1, len(tickers) + 1),
        "sector": sectors,
    })
    indices = pd.DataFrame(
        {"category": ["main"], "name": ["MASI"], "code": ["MASI"], "index_id": [512335]}
    )
    return Universe(instruments, indices)
