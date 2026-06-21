"""DataService — the single entry point strategies/backtests/GUI use for data.

Responsibilities:
* build the provider chain from ``data.source_priority``;
* serve OHLCV with cache-first reads and write-back of freshly fetched data;
* fall back automatically when a provider returns nothing;
* expose the market snapshot with a staleness flag for the GUI.

The rest of the system never imports a concrete provider — only this service.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from .. import schema
from ..config import Config, load_config
from ..logging_conf import get_logger
from .providers.base import DataProvider
from .providers.casablanca import CasablancaBourseProvider
from .providers.offline import OfflineCacheProvider
from .storage.cache import Cache
from .universe import Universe, load_universe

log = get_logger(__name__)


class DataService:
    def __init__(self, cfg: Config, universe: Universe, cache: Cache,
                 providers: list[DataProvider]):
        self.cfg = cfg
        self.universe = universe
        self.cache = cache
        self.providers = providers
        self.stale_after_days = int(cfg.get("data.stale_after_days", 5))
        log.info("DataService ready (providers: %s)",
                 ", ".join(p.name for p in providers))

    # -- construction ------------------------------------------------------
    @classmethod
    def from_config(cls, cfg: Config | None = None) -> "DataService":
        cfg = cfg or load_config()
        universe = load_universe(cfg)
        cache = Cache(cfg.path("data.cache_db"))
        providers = cls._build_providers(cfg, universe, cache)
        return cls(cfg, universe, cache, providers)

    @staticmethod
    def _build_providers(cfg: Config, universe: Universe, cache: Cache) -> list[DataProvider]:
        out: list[DataProvider] = []
        for name in cfg.get("data.source_priority", ["offline", "casablanca"]):
            if name == "offline":
                out.append(OfflineCacheProvider(cache))
            elif name == "casablanca":
                out.append(CasablancaBourseProvider(cfg, universe))
            elif name == "tvdatafeed":
                from .providers.tvdatafeed_provider import TVDataFeedProvider
                out.append(TVDataFeedProvider(cfg))
            else:
                log.warning("Unknown data source '%s' in source_priority", name)
        return out

    # -- OHLCV -------------------------------------------------------------
    def get_ohlcv(self, ticker: str, start: str, end: str,
                  refresh: bool = False) -> pd.DataFrame:
        """Daily OHLCV for one ticker, cache-first with live fallback + write-back."""
        if not refresh:
            cached = self.cache.load_ohlcv([ticker], start, end)
            if self._covers(cached, end):
                return cached

        for prov in self.providers:
            if prov.name == "offline":
                continue  # cache already consulted above
            df = prov.get_ohlcv(ticker, start, end)
            if df is not None and not df.empty:
                self.cache.upsert_ohlcv(df)
                return self.cache.load_ohlcv([ticker], start, end)
            log.info("provider '%s' returned no data for %s; trying next", prov.name, ticker)

        # Everything failed live — return whatever the cache holds (possibly partial).
        return self.cache.load_ohlcv([ticker], start, end)

    def get_prices(self, tickers: list[str], start: str, end: str,
                   refresh: bool = False) -> pd.DataFrame:
        """Long OHLCV frame for several tickers (concatenated)."""
        frames = [self.get_ohlcv(t, start, end, refresh=refresh) for t in tickers]
        frames = [f for f in frames if not f.empty]
        if not frames:
            return schema.empty_ohlcv()
        return pd.concat(frames, ignore_index=True)

    def _covers(self, df: pd.DataFrame, end: str) -> bool:
        """True if cached data is non-empty and recent enough to skip a live fetch."""
        if df.empty:
            return False
        end_ts = pd.to_datetime(end)
        last = df[schema.DATE].max()
        # If the requested end is in the past, any data up to it is fine.
        if end_ts <= last:
            return True
        # Requested end is "today-ish": accept cache if it's within the stale window.
        return (end_ts - last).days <= self.stale_after_days

    # -- snapshot ----------------------------------------------------------
    def get_snapshot(self, refresh: bool = False) -> tuple[pd.DataFrame, str | None, bool]:
        """Return (snapshot_df, captured_at_iso, is_stale)."""
        if refresh:
            for prov in self.providers:
                if not getattr(prov, "supports_snapshot", False) or prov.name == "offline":
                    continue
                df = prov.get_snapshot()
                if df is not None and not df.empty:
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    self.cache.save_snapshot(df, now)
                    return df, now, False
        df, captured = self.cache.load_snapshot()
        return df, captured, self._is_stale(captured)

    def _is_stale(self, captured_at: str | None) -> bool:
        if not captured_at:
            return True
        try:
            ts = pd.to_datetime(captured_at)
        except Exception:
            return True
        return (datetime.now() - ts.to_pydatetime()) > timedelta(days=self.stale_after_days)

    def get_index_snapshot(self, refresh: bool = False) -> pd.DataFrame:
        for prov in self.providers:
            if prov.name == "casablanca":
                df = prov.get_index_snapshot()
                if df is not None and not df.empty:
                    return df
        return pd.DataFrame()

    # -- bulk build --------------------------------------------------------
    def build_cache(self, tickers: list[str], start: str, end: str) -> pd.DataFrame:
        """Force-fetch and cache history for *tickers*. Returns a coverage report."""
        for t in tickers:
            self.get_ohlcv(t, start, end, refresh=True)
        cov = self.cache.coverage()
        return cov[cov["ticker"].isin(tickers)] if not cov.empty else cov
