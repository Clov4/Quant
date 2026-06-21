"""The CSE instrument/index universe, loaded from the real reference CSVs.

``config/instruments.csv``  -> Nom, Symbole, Instrument_id, Secteur   (113 names)
``config/indices.csv``      -> Catégorie, Indice, Code_Index, Index_id (MASI, ...)

``Instrument_id`` is the same internal id the Casablanca Bourse history API filters
on (verified: IAM -> 510), so we can map ticker -> id offline and skip the slow
per-instrument lookup.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ..config import Config


@dataclass(frozen=True)
class Instrument:
    ticker: str
    name: str
    instrument_id: int | None
    sector: str


class Universe:
    """Lookup helpers over the instrument and index reference tables."""

    def __init__(self, instruments: pd.DataFrame, indices: pd.DataFrame):
        self._instruments = instruments
        self._indices = indices
        self._by_ticker: dict[str, Instrument] = {}
        for _, r in instruments.iterrows():
            iid = r["instrument_id"]
            self._by_ticker[r["ticker"]] = Instrument(
                ticker=r["ticker"],
                name=r["name"],
                instrument_id=int(iid) if pd.notna(iid) else None,
                sector=r["sector"],
            )

    # -- instruments -------------------------------------------------------
    def __contains__(self, ticker: str) -> bool:
        return ticker in self._by_ticker

    def get(self, ticker: str) -> Instrument | None:
        return self._by_ticker.get(ticker)

    def instrument_id(self, ticker: str) -> int | None:
        inst = self._by_ticker.get(ticker)
        return inst.instrument_id if inst else None

    def sector(self, ticker: str) -> str:
        inst = self._by_ticker.get(ticker)
        return inst.sector if inst else "Unknown"

    def name(self, ticker: str) -> str:
        inst = self._by_ticker.get(ticker)
        return inst.name if inst else ticker

    @property
    def tickers(self) -> list[str]:
        return list(self._by_ticker.keys())

    def sectors(self, tickers: list[str] | None = None) -> dict[str, str]:
        ts = tickers if tickers is not None else self.tickers
        return {t: self.sector(t) for t in ts}

    @property
    def instruments_frame(self) -> pd.DataFrame:
        return self._instruments.copy()

    # -- indices -----------------------------------------------------------
    def index_id(self, code: str) -> int | None:
        row = self._indices[self._indices["code"] == code]
        if row.empty:
            return None
        return int(row.iloc[0]["index_id"])

    @property
    def indices_frame(self) -> pd.DataFrame:
        return self._indices.copy()


def load_universe(cfg: Config) -> Universe:
    """Load instruments + indices from the CSV paths in *cfg*."""
    inst_path: Path = cfg.path("universe.instruments_csv")
    idx_path: Path = cfg.path("universe.indices_csv")

    instruments = pd.read_csv(inst_path)
    instruments = instruments.rename(
        columns={
            "Nom": "name",
            "Symbole": "ticker",
            "Instrument_id": "instrument_id",
            "Secteur": "sector",
        }
    )
    instruments["ticker"] = instruments["ticker"].astype(str).str.strip()
    instruments["sector"] = instruments["sector"].fillna("Unknown").astype(str).str.strip()

    indices = pd.read_csv(idx_path)
    indices = indices.rename(
        columns={
            "Catégorie": "category",
            "Indice": "name",
            "Code_Index": "code",
            "Index_id": "index_id",
        }
    )
    indices["code"] = indices["code"].astype(str).str.strip()

    return Universe(instruments, indices)
