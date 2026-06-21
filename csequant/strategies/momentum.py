"""Momentum / trend-following: moving-average crossover with a momentum filter.

Go long when the fast MA is above the slow MA *and* trailing momentum is positive;
flat otherwise. This is deliberately simple and fully transparent.
"""
from __future__ import annotations

import pandas as pd

from .. import schema
from . import indicators as ind
from .base import Strategy, register


@register
class MomentumStrategy(Strategy):
    name = "momentum"
    defaults = {
        "fast_ma": 20,
        "slow_ma": 50,
        "momentum_lookback": 90,
        "momentum_threshold": 0.0,
    }

    def compute(self, ohlcv: pd.DataFrame) -> pd.DataFrame:
        df = ohlcv.sort_values(schema.DATE).set_index(schema.DATE)
        close = df[schema.ADJ_CLOSE].astype(float)

        fast = ind.sma(close, int(self.params["fast_ma"]))
        slow = ind.sma(close, int(self.params["slow_ma"]))
        mom = ind.momentum(close, int(self.params["momentum_lookback"]))
        thr = float(self.params["momentum_threshold"])

        long = (fast > slow) & (mom >= thr)
        return pd.DataFrame(
            {
                "signal": long.astype(float),
                "score": mom,
                "fast_ma": fast,
                "slow_ma": slow,
                "momentum": mom,
            },
            index=close.index,
        )

    def _static_triggers(self) -> dict:
        return {
            "fast_window": int(self.params["fast_ma"]),
            "slow_window": int(self.params["slow_ma"]),
            "mom_window": int(self.params["momentum_lookback"]),
            "mom_threshold": float(self.params["momentum_threshold"]),
        }
