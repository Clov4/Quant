"""Strategy / Signal contracts.

A :class:`Strategy` exposes two views of the same logic:

* :meth:`compute` (and :meth:`exposures`) — the *vectorised* view the backtester
  and optimizer consume: a per-bar desired long exposure in [0, 1] plus the
  trigger values behind it.
* :meth:`generate_signals` — the *discrete* view the GUI trade-log shows: a list
  of :class:`Signal` objects emitted when the stance changes, each carrying a
  plain-language ``reason`` built from those same triggers.

Long-only by design (shorting on the CSE central market is impractical for the
retail use-case this tool targets): exposure is 0 (flat) or up to 1 (fully long).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from .. import schema
from ..explainability.reasoning import explain_signal

BUY, SELL, HOLD = "BUY", "SELL", "HOLD"


@dataclass
class Signal:
    ticker: str
    date: pd.Timestamp
    action: str               # BUY | SELL | HOLD
    strategy: str
    score: float = 0.0        # strategy-defined strength/confidence
    triggers: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["date"] = pd.Timestamp(self.date).strftime("%Y-%m-%d")
        d["triggers"] = {
            k: (round(v, 4) if isinstance(v, float) else v)
            for k, v in self.triggers.items()
        }
        return d


class Strategy(ABC):
    name: str = "base"
    defaults: dict[str, Any] = {}

    def __init__(self, **params: Any):
        self.params = {**self.defaults, **params}

    # -- core (subclasses implement) --------------------------------------
    @abstractmethod
    def compute(self, ohlcv: pd.DataFrame) -> pd.DataFrame:
        """Per-ticker frame indexed by date with at least a ``signal`` column
        (desired long exposure in [0, 1]), a ``score`` column, and any trigger
        columns whose names match :mod:`csequant.explainability.reasoning`
        (``fast_ma``, ``slow_ma``, ``momentum``, ``rsi``, ``zscore``, ...)."""

    def _static_triggers(self) -> dict[str, Any]:
        """Window sizes / thresholds added to every signal's explanation."""
        return {}

    # -- vectorised views --------------------------------------------------
    def signals_frame(self, ohlcv: pd.DataFrame) -> pd.DataFrame:
        """compute() plus a derived ``action`` column from exposure transitions."""
        df = self.compute(ohlcv).copy()
        sig = df["signal"].fillna(0.0).clip(0, 1)
        prev = sig.shift(1).fillna(0.0)
        action = pd.Series(HOLD, index=df.index, dtype=object)
        action[(prev <= 0) & (sig > 0)] = BUY
        action[(prev > 0) & (sig <= 0)] = SELL
        df["action"] = action
        return df

    def exposures(self, prices_by_ticker: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """Wide (date x ticker) matrix of desired long exposures in [0, 1].

        Default: stack per-ticker :meth:`compute`. Cross-sectional strategies
        (e.g. the factor model) override this."""
        cols: dict[str, pd.Series] = {}
        for ticker, ohlcv in prices_by_ticker.items():
            if ohlcv is None or ohlcv.empty:
                continue
            cols[ticker] = self.compute(ohlcv)["signal"]
        if not cols:
            return pd.DataFrame()
        return pd.DataFrame(cols).sort_index().fillna(0.0).clip(0, 1)

    # -- discrete view (trade log) ----------------------------------------
    def generate_signals(self, ohlcv: pd.DataFrame, ticker: str | None = None) -> list[Signal]:
        if ticker is None:
            ticker = ohlcv[schema.TICKER].iloc[0] if schema.TICKER in ohlcv else "?"
        df = self.signals_frame(ohlcv)
        skip = {"signal", "score", "action"}
        trig_cols = [c for c in df.columns if c not in skip]
        out: list[Signal] = []
        for date, row in df[df["action"] != HOLD].iterrows():
            triggers: dict[str, Any] = dict(self._static_triggers())
            for c in trig_cols:
                v = row[c]
                if pd.notna(v):
                    triggers[c] = float(v)
            reason = explain_signal(self.name, str(row["action"]), triggers)
            score = float(row["score"]) if pd.notna(row.get("score")) else 0.0
            out.append(Signal(ticker, pd.Timestamp(date), str(row["action"]),
                              self.name, score, triggers, reason))
        return out


# --- registry ---------------------------------------------------------------
_REGISTRY: dict[str, type[Strategy]] = {}


def register(cls: type[Strategy]) -> type[Strategy]:
    _REGISTRY[cls.name] = cls
    return cls


def build_strategy(name: str, cfg=None) -> Strategy:
    if name not in _REGISTRY:
        raise KeyError(f"Unknown strategy '{name}'. Known: {list(_REGISTRY)}")
    params = {}
    if cfg is not None:
        params = cfg.get(f"strategies.{name}", {}) or {}
    return _REGISTRY[name](**params)


def all_strategy_names() -> list[str]:
    return list(_REGISTRY)
