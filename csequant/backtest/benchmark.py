"""Reconstruct a buy-and-hold CSE benchmark from the cached constituents.

The official MASI daily history is not reliably reachable (the index time-series
endpoint's id-mapping is unstable — see README §Data). Instead we build a
transparent, fully-offline **equal-weight buy-and-hold composite** of the cached
liquid universe as a proxy for MASI. Cap-weighting is supported if a caps mapping
is supplied; equal-weight is the documented default.
"""
from __future__ import annotations

import pandas as pd

from .. import schema


def build_benchmark(
    prices_long: pd.DataFrame,
    initial_capital: float = 100_000.0,
    weighting: str = "equal",
    caps: dict[str, float] | None = None,
    name: str = "CSE-COMPOSITE",
) -> pd.Series:
    """Return a buy-and-hold equity curve for the universe in *prices_long*.

    Equal MAD is allocated to each name that has a price on the first common date,
    then held (no rebalancing) — a genuine buy-and-hold benchmark.
    """
    wide = schema.to_wide(prices_long, schema.ADJ_CLOSE).dropna(how="all")
    if wide.empty:
        return pd.Series(dtype=float, name=name)

    first = wide.index[0]
    valid = wide.columns[wide.loc[first].notna()]
    if len(valid) == 0:
        return pd.Series(dtype=float, name=name)

    if weighting == "cap" and caps:
        w = pd.Series({t: caps.get(t, 0.0) for t in valid}, dtype=float)
        if w.sum() <= 0:
            w = pd.Series(1.0, index=valid)
    else:  # equal weight
        w = pd.Series(1.0, index=valid)
    w = w / w.sum()

    alloc = initial_capital * w
    shares = alloc / wide.loc[first, valid]
    equity = (wide[valid].ffill() * shares).sum(axis=1)
    equity.name = name
    return equity
