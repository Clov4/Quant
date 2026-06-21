"""SQLite-backed cache for OHLCV history, the latest snapshot, and metadata.

Keeping a local cache (a) avoids re-fetching on every run, (b) makes backtests
fast and reproducible from a pinned snapshot, and (c) lets the GUI work with no
network at all (the bundled demo cache).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from ... import schema
from ...logging_conf import get_logger

log = get_logger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS ohlcv (
    ticker    TEXT NOT NULL,
    date      TEXT NOT NULL,           -- ISO 'YYYY-MM-DD'
    open      REAL, high REAL, low REAL, close REAL, adj_close REAL,
    volume    REAL, turnover REAL, trades REAL,
    currency  TEXT,
    PRIMARY KEY (ticker, date)
);
CREATE INDEX IF NOT EXISTS ix_ohlcv_ticker ON ohlcv(ticker);
CREATE TABLE IF NOT EXISTS snapshot (
    captured_at TEXT, ticker TEXT, name TEXT, last REAL, change_pct REAL,
    volume REAL, turnover REAL, sector TEXT, status TEXT
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

_OHLCV_COLS = schema.OHLCV_COLUMNS  # date, ticker, open, ... currency


class Cache:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.executescript(_DDL)
        self.conn.commit()

    # -- context manager ---------------------------------------------------
    def __enter__(self) -> "Cache":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    # -- OHLCV -------------------------------------------------------------
    def upsert_ohlcv(self, df: pd.DataFrame) -> int:
        """Insert-or-replace canonical OHLCV rows. Returns rows written."""
        if df is None or df.empty:
            return 0
        df = schema.ensure_schema(df)
        rows = [
            (
                r.ticker, r.date.strftime("%Y-%m-%d"),
                _f(r.open), _f(r.high), _f(r.low), _f(r.close), _f(r.adj_close),
                _f(r.volume), _f(r.turnover), _f(r.trades), r.currency,
            )
            for r in df.itertuples(index=False)
        ]
        self.conn.executemany(
            "INSERT OR REPLACE INTO ohlcv "
            "(ticker,date,open,high,low,close,adj_close,volume,turnover,trades,currency) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        self.conn.commit()
        log.info("cache: wrote %d OHLCV rows (%d tickers)", len(rows), df["ticker"].nunique())
        return len(rows)

    def load_ohlcv(
        self,
        tickers: list[str] | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        q = "SELECT ticker,date,open,high,low,close,adj_close,volume,turnover,trades,currency FROM ohlcv"
        clauses, params = [], []
        if tickers:
            clauses.append(f"ticker IN ({','.join('?' * len(tickers))})")
            params += list(tickers)
        if start:
            clauses.append("date >= ?")
            params.append(start)
        if end:
            clauses.append("date <= ?")
            params.append(end)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY ticker, date"
        df = pd.read_sql_query(q, self.conn, params=params)
        return schema.ensure_schema(df)

    def coverage(self) -> pd.DataFrame:
        """Per-ticker (min_date, max_date, n) coverage summary."""
        return pd.read_sql_query(
            "SELECT ticker, MIN(date) AS start, MAX(date) AS end, COUNT(*) AS bars "
            "FROM ohlcv GROUP BY ticker ORDER BY ticker",
            self.conn,
        )

    def cached_tickers(self) -> list[str]:
        cur = self.conn.execute("SELECT DISTINCT ticker FROM ohlcv ORDER BY ticker")
        return [r[0] for r in cur.fetchall()]

    # -- snapshot ----------------------------------------------------------
    def save_snapshot(self, df: pd.DataFrame, captured_at: str) -> None:
        if df is None or df.empty:
            return
        df = df.copy()
        df["captured_at"] = captured_at
        keep = ["captured_at", "ticker", "name", "last", "change_pct",
                "volume", "turnover", "sector", "status"]
        for c in keep:
            if c not in df.columns:
                df[c] = pd.NA
        self.conn.execute("DELETE FROM snapshot")
        df[keep].to_sql("snapshot", self.conn, if_exists="append", index=False)
        self.set_meta("last_snapshot_at", captured_at)
        self.conn.commit()
        log.info("cache: saved snapshot of %d instruments @ %s", len(df), captured_at)

    def load_snapshot(self) -> tuple[pd.DataFrame, str | None]:
        df = pd.read_sql_query("SELECT * FROM snapshot", self.conn)
        return df, self.get_meta("last_snapshot_at")

    # -- meta --------------------------------------------------------------
    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO meta (key,value) VALUES (?,?)", (key, str(value))
        )
        self.conn.commit()

    def get_meta(self, key: str) -> str | None:
        cur = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,))
        row = cur.fetchone()
        return row[0] if row else None


def _f(v) -> float | None:
    """Coerce a possibly-NA scalar to float-or-None for sqlite binding."""
    return None if pd.isna(v) else float(v)
