"""Optional fallback provider backed by the unofficial `tvdatafeed` library.

This is **off by default** and best-effort: CSE coverage on TradingView is not
guaranteed, and `tvdatafeed` typically needs a TradingView login for anything
beyond a small history. The provider degrades gracefully — if the library is not
installed or the symbol is unavailable, it reports unavailable / returns empty
and the DataService falls back to another source.

Enable by installing the lib and adding ``tvdatafeed`` to ``data.source_priority``.
Configure the exchange/symbol mapping under ``data.tvdatafeed`` in settings.yaml.
"""
from __future__ import annotations

import pandas as pd

from ... import schema
from ...config import Config
from ...logging_conf import get_logger
from .base import DataProvider

log = get_logger(__name__)


class TVDataFeedProvider(DataProvider):
    name = "tvdatafeed"
    supports_snapshot = False

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.exchange = cfg.get("data.tvdatafeed.exchange", "CSEMA")
        self.currency = cfg.currency
        self._tv = None
        try:
            from tvDatafeed import TvDatafeed  # type: ignore

            user = cfg.get("data.tvdatafeed.username")
            pwd = cfg.get("data.tvdatafeed.password")
            self._tv = TvDatafeed(user, pwd) if user else TvDatafeed()
            log.info("tvdatafeed: initialised (exchange=%s)", self.exchange)
        except Exception as e:
            log.info("tvdatafeed: unavailable (%s) — provider disabled", e)
            self._tv = None

    def is_available(self) -> bool:
        return self._tv is not None

    def get_ohlcv(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        if self._tv is None:
            return self._empty()
        try:
            from tvDatafeed import Interval  # type: ignore

            raw = self._tv.get_hist(
                symbol=ticker, exchange=self.exchange,
                interval=Interval.in_daily, n_bars=5000,
            )
            if raw is None or raw.empty:
                log.info("tvdatafeed: no data for %s:%s", self.exchange, ticker)
                return self._empty()
            df = raw.reset_index().rename(
                columns={"datetime": schema.DATE, "open": schema.OPEN,
                         "high": schema.HIGH, "low": schema.LOW, "close": schema.CLOSE,
                         "volume": schema.VOLUME}
            )
            df[schema.TICKER] = ticker
            df[schema.CURRENCY] = self.currency
            df = schema.ensure_schema(df)
            return df[(df[schema.DATE] >= start) & (df[schema.DATE] <= end)]
        except Exception as e:
            log.warning("tvdatafeed: fetch failed for %s: %s", ticker, e)
            return self._empty()
