"""Mean reversion: RSI + price z-score with entry/exit hysteresis.

Enter long when the name looks oversold (RSI below its oversold band *or* price a
few sigma below its rolling mean); exit back to flat once it has reverted (RSI
back above the overbought band *or* z-score back to/above the exit level).
The position is held between those events (stateful), not re-decided every bar.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import schema
from . import indicators as ind
from .base import Strategy, register


@register
class MeanReversionStrategy(Strategy):
    name = "mean_reversion"
    defaults = {
        "rsi_period": 14,
        "rsi_oversold": 30.0,
        "rsi_overbought": 70.0,
        "zscore_window": 20,
        "zscore_entry": -1.5,
        "zscore_exit": 0.0,
    }

    def compute(self, ohlcv: pd.DataFrame) -> pd.DataFrame:
        df = ohlcv.sort_values(schema.DATE).set_index(schema.DATE)
        close = df[schema.ADJ_CLOSE].astype(float)

        rsi = ind.rsi(close, int(self.params["rsi_period"]))
        z = ind.rolling_zscore(close, int(self.params["zscore_window"]))

        entry = (z <= float(self.params["zscore_entry"])) | (rsi <= float(self.params["rsi_oversold"]))
        exit_ = (z >= float(self.params["zscore_exit"])) | (rsi >= float(self.params["rsi_overbought"]))

        # Stateful long position: 1 on entry, 0 on exit, hold in between.
        state = pd.Series(np.nan, index=close.index)
        state[entry] = 1.0
        state[exit_] = 0.0          # exit takes precedence if both fire on a bar
        signal = state.ffill().fillna(0.0)

        return pd.DataFrame(
            {
                "signal": signal,
                "score": -z,        # the more oversigma, the stronger the buy
                "rsi": rsi,
                "zscore": z,
            },
            index=close.index,
        )

    def _static_triggers(self) -> dict:
        return {
            "rsi_period": int(self.params["rsi_period"]),
            "rsi_oversold": float(self.params["rsi_oversold"]),
            "rsi_overbought": float(self.params["rsi_overbought"]),
            "z_window": int(self.params["zscore_window"]),
        }
