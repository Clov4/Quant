"""Factor / score-based ranking of the CSE universe.

Each name gets a composite score that rewards trailing momentum and penalises
volatility (a momentum + low-vol blend). Cross-sectionally, the top-N names are
held (equal sleeve exposure). This is the strategy the portfolio optimizer leans
on to pre-select candidates, and it is explainable with the same trigger values.

Optional value tilt: if a dividend-yield / earnings-yield column is supplied in
``config`` it can be folded into the score; by default only price-derived factors
are used because fundamentals are sparse for many CSE names (see STRATEGY.md).
"""
from __future__ import annotations

import pandas as pd

from .. import schema
from . import indicators as ind
from .base import Strategy, register


@register
class FactorModel(Strategy):
    name = "factor_model"
    defaults = {
        "momentum_lookback": 120,
        "vol_window": 60,
        "top_n": 10,
        "vol_penalty": 0.5,   # weight on the volatility penalty in the blended score
    }

    # -- per-ticker factor score ------------------------------------------
    def compute(self, ohlcv: pd.DataFrame) -> pd.DataFrame:
        df = ohlcv.sort_values(schema.DATE).set_index(schema.DATE)
        close = df[schema.ADJ_CLOSE].astype(float)

        mom = ind.momentum(close, int(self.params["momentum_lookback"]))
        vol = ind.realized_vol(ind.returns(close), int(self.params["vol_window"]))
        score = mom - float(self.params["vol_penalty"]) * vol

        # Standalone exposure (used by generate_signals and as an exposures()
        # fallback): long when momentum is positive.
        signal = (mom > 0).astype(float)
        return pd.DataFrame(
            {"signal": signal, "score": score, "momentum": mom, "volatility": vol},
            index=close.index,
        )

    def _static_triggers(self) -> dict:
        return {"mom_window": int(self.params["momentum_lookback"])}

    # -- cross-sectional selection ----------------------------------------
    def exposures(self, prices_by_ticker: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """Hold the top-N names by composite score on each bar (equal sleeve)."""
        scores: dict[str, pd.Series] = {}
        for ticker, ohlcv in prices_by_ticker.items():
            if ohlcv is None or ohlcv.empty:
                continue
            scores[ticker] = self.compute(ohlcv)["score"]
        if not scores:
            return pd.DataFrame()

        S = pd.DataFrame(scores).sort_index()
        ranks = S.rank(axis=1, ascending=False, method="first")
        top_n = int(self.params["top_n"])
        E = (ranks <= top_n).astype(float)
        return E.where(S.notna(), 0.0)
