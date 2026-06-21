"""Tests for the plain-language reasoning engine."""
from csequant.explainability import (
    explain_allocation,
    explain_signal,
    explain_stance,
)


def test_explain_signal_momentum():
    triggers = {"fast_window": 20, "slow_window": 50, "fast_ma": 102.3, "slow_ma": 99.8,
                "mom_window": 90, "momentum": 0.123, "mom_threshold": 0.0}
    txt = explain_signal("momentum", "BUY", triggers)
    assert txt.startswith("BUY (momentum):")
    assert "20-day MA" in txt and "50-day MA" in txt
    assert "12.3%" in txt          # momentum rendered as a percentage


def test_explain_signal_mean_reversion():
    triggers = {"rsi": 24.1, "rsi_period": 14, "rsi_oversold": 30.0, "zscore": -1.8, "z_window": 20}
    txt = explain_signal("mean_reversion", "BUY", triggers)
    assert "RSI(14) = 24.1" in txt
    assert "oversold" in txt
    assert "1.8σ below" in txt


def test_explain_allocation_contains_key_facts():
    txt = explain_allocation("IAM", 0.15, sector="Telecom", expected_return=0.12,
                             volatility=0.20, risk_contribution=0.25,
                             signal_reasons=["selected by momentum (…)"])
    assert "IAM" in txt and "15.0%" in txt and "Telecom" in txt
    assert "Signals:" in txt


def test_explain_stance_no_action_word():
    txt = explain_stance("factor_model", {"mom_window": 120, "momentum": 0.4, "volatility": 0.3})
    assert txt.startswith("selected by factor_model")
    assert "120-day momentum" in txt


def test_unknown_triggers_are_ignored():
    txt = explain_signal("x", "SELL", {"totally_unknown": 1.0})
    assert "SELL (x):" in txt  # falls back gracefully
