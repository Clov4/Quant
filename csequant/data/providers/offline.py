"""Offline provider: serves data straight from the local SQLite cache.

This is the provider that lets the whole system (GUI, backtests) run with no
network — it reads the bundled demo cache. It is also the natural first entry in
``source_priority`` so cached data short-circuits live fetches.
"""
from __future__ import annotations

import pandas as pd

from ..storage.cache import Cache
from .base import DataProvider


class OfflineCacheProvider(DataProvider):
    name = "offline"
    supports_snapshot = True

    def __init__(self, cache: Cache):
        self.cache = cache

    def is_available(self) -> bool:
        return len(self.cache.cached_tickers()) > 0

    def get_ohlcv(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        return self.cache.load_ohlcv([ticker], start, end)

    def get_snapshot(self) -> pd.DataFrame:
        df, _ = self.cache.load_snapshot()
        return df
