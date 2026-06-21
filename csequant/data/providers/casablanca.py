"""Live provider scraping casablanca-bourse.com (real CSE end-of-day data).

The site is a Next.js app whose data comes from a Drupal JSON:API behind
``/api/proxy``. Three endpoints are used (all validated against the live site):

* build-id   : scraped from ``__NEXT_DATA__`` on the homepage (rotates ~hourly)
* snapshot   : ``/api/proxy/fr/api/bourse/dashboard/ticker`` (all instruments, live)
* history    : ``/api/proxy/fr/api/bourse_data/instrument_history`` (daily OHLCV,
               filtered by the instrument's internal id, paged 250/req)
* indices    : ``/api/proxy/fr/api/bourse/dashboard/grouped_index_watch`` (levels)

Notes / known fragilities (documented in README):
* The TLS chain is often unverifiable in CI/sandboxes -> ``verify_tls: false``.
* ``cumulVolumeEchange`` is MAD turnover; ``cumulTitresEchanges`` is share count.
* ``coursAjuste`` is the split/dividend-adjusted close (used for returns).
"""
from __future__ import annotations

import json
import re
import time

import pandas as pd
import requests

from ... import schema
from ...config import Config
from ...logging_conf import get_logger
from ..universe import Universe
from .base import DataProvider

log = get_logger(__name__)

_BASE = "https://www.casablanca-bourse.com"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
)
_HEADERS = {"User-Agent": _UA, "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"'}
_API_HEADERS = {**_HEADERS, "Accept": "application/vnd.api+json",
                "Content-Type": "application/vnd.api+json"}

# instrument_history attribute -> canonical schema column
_HIST_MAP = {
    "created": schema.DATE,
    "openingPrice": schema.OPEN,
    "highPrice": schema.HIGH,
    "lowPrice": schema.LOW,
    "closingPrice": schema.CLOSE,
    "coursAjuste": schema.ADJ_CLOSE,
    "cumulTitresEchanges": schema.VOLUME,
    "cumulVolumeEchange": schema.TURNOVER,
    "totalTrades": schema.TRADES,
}


class CasablancaBourseProvider(DataProvider):
    name = "casablanca"
    supports_snapshot = True

    def __init__(self, cfg: Config, universe: Universe):
        self.cfg = cfg
        self.universe = universe
        self.timeout = int(cfg.get("data.request_timeout", 30))
        self.verify = bool(cfg.get("data.verify_tls", False))
        self.sleep = float(cfg.get("data.rate_limit_sleep", 0.3))
        self.currency = cfg.currency
        self._build_id: str | None = None
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)
        if not self.verify:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # -- availability / build id ------------------------------------------
    def is_available(self) -> bool:
        return self.build_id() is not None

    def build_id(self, force: bool = False) -> str | None:
        if self._build_id and not force:
            return self._build_id
        try:
            r = self._session.get(f"{_BASE}/fr", timeout=self.timeout, verify=self.verify)
            m = re.search(
                r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', r.text
            )
            if not m:
                log.warning("casablanca: __NEXT_DATA__ not found (site layout changed?)")
                return None
            self._build_id = json.loads(m.group(1)).get("buildId")
            log.info("casablanca: build_id=%s", self._build_id)
            return self._build_id
        except Exception as e:  # network/parse failures are non-fatal
            log.warning("casablanca: build_id fetch failed: %s", e)
            return None

    # -- history -----------------------------------------------------------
    def get_ohlcv(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        sid = self.universe.instrument_id(ticker)
        if sid is None:
            log.warning("casablanca: no instrument_id for '%s' (not in universe CSV)", ticker)
            return self._empty()
        try:
            rows = self._fetch_history(sid, start, end)
        except Exception as e:
            log.warning("casablanca: history fetch failed for %s: %s", ticker, e)
            return self._empty()
        if not rows:
            return self._empty()

        df = pd.DataFrame(rows).rename(columns=_HIST_MAP)
        df[schema.TICKER] = ticker
        df[schema.CURRENCY] = self.currency
        df = schema.ensure_schema(df)
        log.info("casablanca: %s -> %d bars [%s..%s]", ticker, len(df),
                 df[schema.DATE].min().date() if len(df) else "-",
                 df[schema.DATE].max().date() if len(df) else "-")
        return df

    def _fetch_history(self, symbol_id: int, start: str, end: str) -> list[dict]:
        url = f"{_BASE}/api/proxy/fr/api/bourse_data/instrument_history"
        out: list[dict] = []
        offset, limit = 0, 250
        while True:
            params = [
                ("fields[instrument_history]",
                 "symbol,created,openingPrice,coursCourant,highPrice,lowPrice,"
                 "cumulTitresEchanges,cumulVolumeEchange,totalTrades,capitalisation,"
                 "coursAjuste,closingPrice,ratioConsolide"),
                ("include", "symbol"),
                ("sort[date-seance][path]", "created"),
                ("sort[date-seance][direction]", "DESC"),
                ("filter[instrument-history-class][condition][path]", "symbol.codeClasse.field_code"),
                ("filter[instrument-history-class][condition][value]", "1"),
                ("filter[instrument-history-class][condition][operator]", "="),
                ("filter[published]", "1"),
                ("page[offset]", str(offset)),
                ("page[limit]", str(limit)),
                ("filter[filter-date-start-vh][condition][path]", "field_seance_date"),
                ("filter[filter-date-start-vh][condition][operator]", ">="),
                ("filter[filter-date-start-vh][condition][value]", start),
                ("filter[filter-date-end-vh][condition][path]", "field_seance_date"),
                ("filter[filter-date-end-vh][condition][operator]", "<="),
                ("filter[filter-date-end-vh][condition][value]", end),
                ("filter[filter-historique-instrument-emetteur][condition][path]",
                 "symbol.meta.drupal_internal__target_id"),
                ("filter[filter-historique-instrument-emetteur][condition][operator]", "="),
                ("filter[filter-historique-instrument-emetteur][condition][value]", str(symbol_id)),
            ]
            r = self._session.get(url, params=params, headers=_API_HEADERS,
                                  timeout=self.timeout, verify=self.verify)
            if r.status_code != 200:
                log.warning("casablanca: history HTTP %s (offset=%d)", r.status_code, offset)
                break
            data = r.json().get("data", [])
            if not data:
                break
            out.extend(item["attributes"] for item in data)
            if len(data) < limit:
                break
            offset += limit
            time.sleep(self.sleep)
        return out

    # -- snapshot ----------------------------------------------------------
    def get_snapshot(self) -> pd.DataFrame:
        url = f"{_BASE}/api/proxy/fr/api/bourse/dashboard/ticker"
        try:
            r = self._session.get(url, params={"marche": 59, "class[]": [50]},
                                  timeout=self.timeout, verify=self.verify)
            if r.status_code != 200:
                log.warning("casablanca: snapshot HTTP %s", r.status_code)
                return pd.DataFrame()
            values = r.json()["data"]["values"]
        except Exception as e:
            log.warning("casablanca: snapshot failed: %s", e)
            return pd.DataFrame()

        df = pd.DataFrame(values)
        out = pd.DataFrame({
            "ticker": df.get("ticker"),
            "name": df.get("label"),
            "last": pd.to_numeric(df.get("field_cours_courant"), errors="coerce"),
            "change_pct": pd.to_numeric(df.get("field_var_veille"), errors="coerce"),
            "volume": pd.to_numeric(df.get("field_cumul_titres_echanges"), errors="coerce"),
            "turnover": pd.to_numeric(df.get("field_cumul_volume_echange"), errors="coerce"),
            "sector": df.get("sous_secteur"),
            "status": df.get("field_etat_cot_val"),
        })
        log.info("casablanca: snapshot of %d instruments", len(out))
        return out

    # -- indices -----------------------------------------------------------
    def get_index_snapshot(self) -> pd.DataFrame:
        url = f"{_BASE}/api/proxy/fr/api/bourse/dashboard/grouped_index_watch"
        try:
            r = self._session.get(url, headers=_API_HEADERS, timeout=self.timeout,
                                  verify=self.verify)
            if r.status_code != 200:
                return pd.DataFrame()
            data = r.json().get("data", [])
        except Exception as e:
            log.warning("casablanca: index snapshot failed: %s", e)
            return pd.DataFrame()

        rows = []
        for cat in data:
            for it in cat.get("items", []):
                rows.append({
                    "index": it.get("index"),
                    "code": (it.get("index_url") or "").rstrip("/").split("/")[-1],
                    "value": pd.to_numeric(it.get("field_index_value"), errors="coerce"),
                    "change_pct": pd.to_numeric(it.get("field_var_veille"), errors="coerce"),
                    "ytd_pct": pd.to_numeric(it.get("field_var_year"), errors="coerce"),
                    "category": cat.get("title"),
                })
        return pd.DataFrame(rows)
