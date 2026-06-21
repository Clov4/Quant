"""The common, source-independent market-data schema.

Every :class:`~csequant.data.providers.base.DataProvider` normalises whatever it
scrapes into this single OHLCV schema so that strategies, the backtester, and the
optimizer never need to know which source produced the data.
"""
from __future__ import annotations

import pandas as pd

# --- canonical column names -------------------------------------------------
TICKER = "ticker"
DATE = "date"
OPEN = "open"
HIGH = "high"
LOW = "low"
CLOSE = "close"
ADJ_CLOSE = "adj_close"   # split/dividend-adjusted close (coursAjuste); used for returns
VOLUME = "volume"         # number of shares traded
TURNOVER = "turnover"     # value traded in MAD (used for the liquidity model)
TRADES = "trades"         # number of transactions
CURRENCY = "currency"

OHLCV_COLUMNS = [
    DATE, TICKER, OPEN, HIGH, LOW, CLOSE, ADJ_CLOSE, VOLUME, TURNOVER, TRADES, CURRENCY,
]

_NUMERIC = [OPEN, HIGH, LOW, CLOSE, ADJ_CLOSE, VOLUME, TURNOVER, TRADES]


def empty_ohlcv() -> pd.DataFrame:
    """Return an empty DataFrame with the canonical columns and dtypes."""
    df = pd.DataFrame(columns=OHLCV_COLUMNS)
    return ensure_schema(df)


def ensure_schema(df: pd.DataFrame, default_currency: str = "MAD") -> pd.DataFrame:
    """Coerce *df* to the canonical OHLCV schema.

    - guarantees all columns exist (missing numeric columns -> NaN);
    - coerces numeric columns to float and ``date`` to datetime;
    - fills ``adj_close`` from ``close`` where missing;
    - drops rows without a usable close; sorts by (ticker, date).
    """
    df = df.copy()
    for col in OHLCV_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA

    df[DATE] = pd.to_datetime(df[DATE], errors="coerce")
    for col in _NUMERIC:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df[CURRENCY] = df[CURRENCY].fillna(default_currency).replace("", default_currency)

    # Adjusted close falls back to the raw close when the source has no adjustment.
    df[ADJ_CLOSE] = df[ADJ_CLOSE].where(df[ADJ_CLOSE].notna() & (df[ADJ_CLOSE] > 0), df[CLOSE])

    df = df.dropna(subset=[DATE, CLOSE])
    df = df[OHLCV_COLUMNS].sort_values([TICKER, DATE]).reset_index(drop=True)
    return df


def to_wide(prices: pd.DataFrame, value: str = ADJ_CLOSE) -> pd.DataFrame:
    """Pivot a long OHLCV frame into a wide (date x ticker) matrix of *value*."""
    wide = prices.pivot_table(index=DATE, columns=TICKER, values=value, aggfunc="last")
    return wide.sort_index()
