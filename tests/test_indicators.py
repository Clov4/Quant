"""Tests for the technical indicators."""
import numpy as np
import pandas as pd

from csequant.strategies import indicators as ind


def test_sma_known_values():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    out = ind.sma(s, 3)
    assert np.isnan(out.iloc[0]) and np.isnan(out.iloc[1])
    assert out.iloc[2] == 2.0  # mean(1,2,3)
    assert out.iloc[4] == 4.0  # mean(3,4,5)


def test_momentum():
    s = pd.Series([100.0, 110.0, 121.0])
    out = ind.momentum(s, 1)
    assert abs(out.iloc[1] - 0.10) < 1e-9
    assert abs(out.iloc[2] - 0.10) < 1e-9


def test_rsi_bounds_and_extremes():
    up = pd.Series(np.linspace(100, 200, 60))      # strictly rising
    down = pd.Series(np.linspace(200, 100, 60))    # strictly falling
    rsi_up = ind.rsi(up, 14).dropna()
    rsi_down = ind.rsi(down, 14).dropna()
    assert (rsi_up >= 0).all() and (rsi_up <= 100).all()
    assert rsi_up.iloc[-1] > 95     # all gains -> RSI ~100
    assert rsi_down.iloc[-1] < 5    # all losses -> RSI ~0


def test_zscore_constant_series_is_nan():
    s = pd.Series([5.0] * 30)
    z = ind.rolling_zscore(s, 10)
    assert z.dropna().empty or np.isnan(z.iloc[-1])  # zero std -> undefined


def test_zscore_sign():
    s = pd.Series(list(np.linspace(10, 20, 25)) + [12.0])  # last dips below mean
    z = ind.rolling_zscore(s, 20)
    assert z.iloc[-1] < 0


def test_drawdown_non_positive():
    eq = pd.Series([100, 120, 90, 130, 110], dtype=float)
    dd = ind.drawdown(eq)
    assert (dd <= 1e-12).all()
    assert abs(dd.iloc[2] - (90 / 120 - 1)) < 1e-9


def test_atr_positive():
    n = 40
    high = pd.Series(np.linspace(10, 12, n))
    low = high - 0.5
    close = high - 0.2
    atr = ind.atr(high, low, close, 14).dropna()
    assert (atr > 0).all()
