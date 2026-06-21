"""Vectorised technical indicators (pure functions over pandas Series).

Kept dependency-free and side-effect-free so they are trivially unit-testable
(see tests/test_indicators.py).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, window: int) -> pd.Series:
    return s.rolling(window, min_periods=window).mean()


def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False, min_periods=span).mean()


def returns(s: pd.Series) -> pd.Series:
    return s.pct_change()


def log_returns(s: pd.Series) -> pd.Series:
    return np.log(s / s.shift(1))


def momentum(s: pd.Series, window: int) -> pd.Series:
    """Total return over the trailing *window* bars (e.g. 0.12 = +12%)."""
    return s / s.shift(window) - 1.0


def rolling_zscore(s: pd.Series, window: int) -> pd.Series:
    """(price - rolling mean) / rolling std — how many sigmas from the mean."""
    mean = s.rolling(window, min_periods=window).mean()
    std = s.rolling(window, min_periods=window).std(ddof=0)
    return (s - mean) / std.replace(0, np.nan)


def rsi(s: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's Relative Strength Index in [0, 100]."""
    delta = s.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    # When there are no losses the RSI is 100 by definition.
    out = out.where(avg_loss != 0, 100.0)
    return out


def bollinger(s: pd.Series, window: int = 20, k: float = 2.0):
    """Return (mid, upper, lower) Bollinger bands."""
    mid = sma(s, window)
    std = s.rolling(window, min_periods=window).std(ddof=0)
    return mid, mid + k * std, mid - k * std


def realized_vol(rets: pd.Series, window: int, periods_per_year: int = 252) -> pd.Series:
    """Annualised rolling volatility of a return series."""
    return rets.rolling(window, min_periods=window).std(ddof=0) * np.sqrt(periods_per_year)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range (Wilder)."""
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()


def drawdown(equity: pd.Series) -> pd.Series:
    """Fractional drawdown from the running peak (<= 0)."""
    peak = equity.cummax()
    return equity / peak - 1.0
