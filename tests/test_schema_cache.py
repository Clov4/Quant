"""Tests for schema normalisation, the SQLite cache, and the offline provider."""
import pandas as pd

from csequant import schema
from csequant.data.providers.offline import OfflineCacheProvider
from csequant.data.storage.cache import Cache


def test_ensure_schema_coerces_and_fills():
    raw = pd.DataFrame({
        "date": ["2024-01-02", "2024-01-01", "bad-date"],
        "ticker": ["AAA", "AAA", "AAA"],
        "open": ["10.0", "9.5", "9.0"],
        "high": ["10.5", "9.8", "9.2"],
        "low": ["9.8", "9.3", "8.9"],
        "close": ["10.2", "9.6", None],   # last row has no close -> dropped
    })
    out = schema.ensure_schema(raw)
    assert list(out.columns) == schema.OHLCV_COLUMNS
    assert len(out) == 2                                  # bad/again rows dropped
    assert out["date"].is_monotonic_increasing           # sorted ascending
    assert (out["adj_close"] == out["close"]).all()       # adj_close filled from close
    assert out["currency"].eq("MAD").all()
    assert out["open"].dtype.kind == "f"                  # numeric coercion


def test_cache_roundtrip(tmp_path, synth_prices):
    db = tmp_path / "t.db"
    cache = Cache(db)
    aaa = synth_prices["AAA"]
    n = cache.upsert_ohlcv(aaa)
    assert n == len(aaa)
    back = cache.load_ohlcv(["AAA"])
    assert len(back) == len(aaa)
    assert abs(back["close"].iloc[-1] - aaa["close"].iloc[-1]) < 1e-6
    cov = cache.coverage()
    assert cov.loc[cov["ticker"] == "AAA", "bars"].iloc[0] == len(aaa)
    # idempotent upsert (INSERT OR REPLACE) doesn't duplicate
    cache.upsert_ohlcv(aaa)
    assert len(cache.load_ohlcv(["AAA"])) == len(aaa)
    cache.close()


def test_cache_date_filtering(tmp_path, synth_prices):
    cache = Cache(tmp_path / "t.db")
    cache.upsert_ohlcv(synth_prices["BBB"])
    sub = cache.load_ohlcv(["BBB"], start="2023-06-01", end="2023-06-30")
    assert not sub.empty
    assert sub["date"].min() >= pd.Timestamp("2023-06-01")
    assert sub["date"].max() <= pd.Timestamp("2023-06-30")
    cache.close()


def test_offline_provider(tmp_path, synth_prices):
    cache = Cache(tmp_path / "t.db")
    assert OfflineCacheProvider(cache).is_available() is False
    cache.upsert_ohlcv(synth_prices["CCC"])
    prov = OfflineCacheProvider(cache)
    assert prov.is_available() is True
    df = prov.get_ohlcv("CCC", "2023-01-01", "2025-01-01")
    assert not df.empty and set(df["ticker"]) == {"CCC"}
    cache.close()
