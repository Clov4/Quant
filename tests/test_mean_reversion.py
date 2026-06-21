"""Tests for the mean-reversion fixes: delayed exit + regime filter (causal)."""
import numpy as np
import pandas as pd

from csequant import schema
from csequant.config import load_config
from csequant.strategies import build_strategy
from csequant.strategies.mean_reversion import MeanReversionStrategy


def _ohlcv(close: np.ndarray, ticker: str = "UPUP") -> pd.DataFrame:
    dates = pd.bdate_range("2022-01-03", periods=len(close))
    df = pd.DataFrame({
        schema.DATE: dates, schema.TICKER: ticker,
        schema.OPEN: close, schema.HIGH: close, schema.LOW: close,
        schema.CLOSE: close, schema.ADJ_CLOSE: close,
        schema.VOLUME: 1e5, schema.TURNOVER: close * 1e5, schema.TRADES: 50.0,
        schema.CURRENCY: "MAD",
    })
    return schema.ensure_schema(df)


# A strong uptrend (price ends far above its 200-day trend) with a sharp dip at the
# end that makes the name look oversold — the textbook "falling knife in a bull".
_EUPHORIC = np.concatenate([np.linspace(100, 300, 240), np.linspace(298, 255, 12)])


def test_zscore_exit_default_is_one():
    assert MeanReversionStrategy.defaults["zscore_exit"] == 1.0


def test_regime_filter_blocks_euphoric_entry():
    ohlcv = _ohlcv(_EUPHORIC)
    off = MeanReversionStrategy(regime_filter=False).compute(ohlcv)["signal"]
    on = MeanReversionStrategy(regime_filter=True).compute(ohlcv)["signal"]

    # Without the filter the dip triggers a long entry...
    assert off.max() == 1.0, "test series should trigger an entry without the filter"
    # ...but the regime filter blocks it because price is far above its 200-day trend.
    assert on.max() == 0.0

    # And the block is surfaced transparently as a NO ENTRY signal (no BUY).
    actions = [s.action for s in MeanReversionStrategy(regime_filter=True)
               .generate_signals(ohlcv, "UPUP")]
    assert "NO ENTRY" in actions
    assert "BUY" not in actions


def test_regime_filter_is_causal_during_warmup():
    # Falling series shorter than regime_ma: MA200 never exists, so a causal filter
    # (fillna(False)) must refuse every entry — never a forward-looking peek.
    short = _ohlcv(np.linspace(100, 60, 80))
    on = MeanReversionStrategy(regime_filter=True, regime_ma=200)
    assert on.compute(short)["signal"].max() == 0.0


def test_no_entry_reason_mentions_trend_premium():
    sigs = MeanReversionStrategy(regime_filter=True).generate_signals(_ohlcv(_EUPHORIC), "UPUP")
    blocked = [s for s in sigs if s.action == "NO ENTRY"]
    assert blocked
    reason = blocked[0].reason
    assert reason.startswith("NO ENTRY (mean_reversion):")
    assert "200-day trend" in reason and "regime filter blocks" in reason


def test_default_construction_preserves_old_behaviour(synth_prices):
    # With code defaults (regime_filter False) compute() must not add a regime block:
    s = MeanReversionStrategy()
    assert s.params["regime_filter"] is False
    frame = s.signals_frame(synth_prices["AAA"])
    assert list(frame.columns[:4]) == ["signal", "score", "rsi", "zscore"]


def test_other_strategies_unaffected(synth_prices):
    cfg = load_config()
    for name in ("momentum", "factor_model"):
        frame = build_strategy(name, cfg).signals_frame(synth_prices["AAA"])
        assert "signal" in frame.columns
        assert len(frame) == len(synth_prices["AAA"])
