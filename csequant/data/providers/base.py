"""The :class:`DataProvider` interface.

Strategies and the backtester depend only on this contract, never on a concrete
source. A provider's job is to return data already normalised to the canonical
OHLCV schema (:mod:`csequant.schema`). Providers should be *quiet on failure*:
return an empty frame and let the :class:`~csequant.data.service.DataService`
fall back to the next provider, raising :class:`ProviderError` only for
programmer errors.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from ... import schema


class ProviderError(RuntimeError):
    """Unrecoverable provider misuse (not a transient network failure)."""


class DataProvider(ABC):
    #: short, stable identifier used in config ``source_priority`` and logs
    name: str = "base"

    #: whether this provider can serve an intraday/EOD market snapshot
    supports_snapshot: bool = False

    @abstractmethod
    def is_available(self) -> bool:
        """Cheap check of whether this provider can currently serve data."""

    @abstractmethod
    def get_ohlcv(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        """Return daily OHLCV for *ticker* over [start, end] in the canonical schema.

        On any failure return an empty (schema-shaped) frame rather than raising.
        """

    def get_snapshot(self) -> pd.DataFrame:
        """Return a current market snapshot (one row per instrument), or empty."""
        return pd.DataFrame()

    def get_index_snapshot(self) -> pd.DataFrame:
        """Return current index levels (MASI, MASI 20, ...), or empty."""
        return pd.DataFrame()

    # -- helpers for subclasses -------------------------------------------
    @staticmethod
    def _empty() -> pd.DataFrame:
        return schema.empty_ohlcv()
