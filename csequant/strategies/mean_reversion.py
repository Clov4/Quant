"""Mean reversion: RSI + price z-score with entry/exit hysteresis.

Enter long when the name looks oversold (RSI below its oversold band *or* price a
few sigma below its rolling mean); exit back to flat once it has reverted. The
position is held between those events (stateful), not re-decided every bar.

Two regime-aware refinements (both config-driven, both causal — no look-ahead):

* ``zscore_exit`` defaults to ``1.0`` (not ``0.0``): we let the reversion overshoot
  the mean before exiting, so the captured move covers the round-trip costs
  instead of selling exactly at the mean and giving the edge back to fees.
* an optional **regime filter** (``regime_filter``) refuses to buy a falling name
  while its price is still far above its long-term trend — fading a strong uptrend
  is the wrong bet. Blocked entries are surfaced as explicit ``NO ENTRY`` signals
  so the reasoning stays transparent.

Even with both refinements this strategy remains a *loser* on a persistent bull
market (see STRATEGY.md) — the goal is to limit the damage, not manufacture alpha.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import schema
from ..explainability.reasoning import explain_blocked_entry
from . import indicators as ind
from .base import Signal, Strategy, register


@register
class MeanReversionStrategy(Strategy):
    name = "mean_reversion"
    defaults = {
        "rsi_period": 14,
        "rsi_oversold": 30.0,
        "rsi_overbought": 70.0,
        "zscore_window": 20,
        "zscore_entry": -1.5,
        "zscore_exit": 1.0,          # let reversion overshoot the mean before exiting
        # --- regime filter (off by default in code for back-compat; on in config) ---
        "regime_ma": 200,            # long trend window
        "regime_max_premium": 0.10,  # block entries when price > MA(regime_ma)*(1+this)
        "regime_filter": False,
    }

    def compute(self, ohlcv: pd.DataFrame) -> pd.DataFrame:
        df = ohlcv.sort_values(schema.DATE).set_index(schema.DATE)
        close = df[schema.ADJ_CLOSE].astype(float)

        rsi = ind.rsi(close, int(self.params["rsi_period"]))
        z = ind.rolling_zscore(close, int(self.params["zscore_window"]))

        entry = (z <= float(self.params["zscore_entry"])) | (rsi <= float(self.params["rsi_oversold"]))
        exit_ = (z >= float(self.params["zscore_exit"])) | (rsi >= float(self.params["rsi_overbought"]))

        # Regime filter: don't enter while the price is euphorically above its long
        # trend. fillna(False) keeps it causal — no entry until MA(regime_ma) exists.
        if bool(self.params.get("regime_filter", False)):
            ma_reg = close.rolling(int(self.params["regime_ma"]),
                                   min_periods=int(self.params["regime_ma"])).mean()
            not_euphoric = close < ma_reg * (1.0 + float(self.params["regime_max_premium"]))
            entry = entry & not_euphoric.fillna(False)

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
        t = {
            "rsi_period": int(self.params["rsi_period"]),
            "rsi_oversold": float(self.params["rsi_oversold"]),
            "rsi_overbought": float(self.params["rsi_overbought"]),
            "z_window": int(self.params["zscore_window"]),
        }
        if bool(self.params.get("regime_filter", False)):
            t["regime_ma"] = int(self.params["regime_ma"])
            t["regime_max_premium"] = float(self.params["regime_max_premium"])
        return t

    def generate_signals(self, ohlcv: pd.DataFrame, ticker: str | None = None) -> list[Signal]:
        """BUY/SELL transitions, plus explicit ``NO ENTRY`` events when the regime
        filter blocks an otherwise-valid oversold entry (kept transparent)."""
        signals = super().generate_signals(ohlcv, ticker)
        if not bool(self.params.get("regime_filter", False)):
            return signals

        if ticker is None:
            ticker = ohlcv[schema.TICKER].iloc[0] if schema.TICKER in ohlcv else "?"
        df = ohlcv.sort_values(schema.DATE).set_index(schema.DATE)
        close = df[schema.ADJ_CLOSE].astype(float)
        rsi = ind.rsi(close, int(self.params["rsi_period"]))
        z = ind.rolling_zscore(close, int(self.params["zscore_window"]))
        raw_entry = (z <= float(self.params["zscore_entry"])) | (rsi <= float(self.params["rsi_oversold"]))

        regime_ma = int(self.params["regime_ma"])
        ma_reg = close.rolling(regime_ma, min_periods=regime_ma).mean()
        premium = close / ma_reg - 1.0
        euphoric = close >= ma_reg * (1.0 + float(self.params["regime_max_premium"]))  # NaN -> False
        blocked = (raw_entry & euphoric).fillna(False)
        starts = blocked & ~blocked.shift(1, fill_value=False)   # first bar of each block

        for date in close.index[starts.to_numpy()]:
            triggers = {**self._static_triggers(),
                        "rsi": float(rsi.loc[date]), "zscore": float(z.loc[date]),
                        "regime_premium": float(premium.loc[date])}
            score = float(-z.loc[date]) if pd.notna(z.loc[date]) else 0.0
            signals.append(Signal(ticker, pd.Timestamp(date), "NO ENTRY", self.name,
                                  score, triggers, explain_blocked_entry(triggers)))

        signals.sort(key=lambda s: s.date)
        return signals
