"""Turn the numeric triggers behind a decision into a human-readable explanation.

Design rule for the whole system: *no opaque "the model says buy"*. Every signal
and every portfolio inclusion carries the specific numbers that produced it, and
this module renders those numbers as a sentence the GUI can show verbatim.

``triggers`` is a flat dict the strategy fills, e.g.::

    {"fast_window": 20, "fast_ma": 102.3, "slow_window": 50, "slow_ma": 99.8,
     "mom_window": 90, "momentum": 0.123}

The functions below pick whichever keys are present and phrase them; unknown keys
are ignored, so strategies can add context freely.
"""
from __future__ import annotations

from typing import Any


def _pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def _num(x: float, dp: int = 2) -> str:
    return f"{x:,.{dp}f}"


def _clauses(t: dict[str, Any]) -> list[str]:
    """Build explanation fragments from any recognised triggers present."""
    out: list[str] = []

    # Moving-average crossover
    if {"fast_window", "slow_window", "fast_ma", "slow_ma"} <= t.keys():
        rel = "above" if t["fast_ma"] >= t["slow_ma"] else "below"
        gap = (t["fast_ma"] / t["slow_ma"] - 1.0) if t["slow_ma"] else 0.0
        out.append(
            f"{int(t['fast_window'])}-day MA ({_num(t['fast_ma'])}) is {rel} the "
            f"{int(t['slow_window'])}-day MA ({_num(t['slow_ma'])}) by {_pct(abs(gap))}"
        )

    # Trailing momentum
    if {"mom_window", "momentum"} <= t.keys():
        thr = t.get("mom_threshold")
        tail = f" (threshold {_pct(thr)})" if thr is not None else ""
        out.append(f"{int(t['mom_window'])}-day momentum is {_pct(t['momentum'])}{tail}")

    # RSI
    if "rsi" in t:
        period = int(t.get("rsi_period", 14))
        clause = f"RSI({period}) = {t['rsi']:.1f}"
        if "rsi_oversold" in t and t["rsi"] <= t["rsi_oversold"]:
            clause += f", below the oversold threshold of {t['rsi_oversold']:.0f}"
        elif "rsi_overbought" in t and t["rsi"] >= t["rsi_overbought"]:
            clause += f", above the overbought threshold of {t['rsi_overbought']:.0f}"
        out.append(clause)

    # Z-score / mean reversion
    if "zscore" in t:
        win = int(t.get("z_window", 20))
        side = "below" if t["zscore"] < 0 else "above"
        out.append(
            f"price is {abs(t['zscore']):.1f}σ {side} its {win}-day mean"
        )

    # Volatility context
    if "volatility" in t:
        out.append(f"annualised volatility ≈ {_pct(t['volatility'])}")

    return out


def explain_signal(strategy: str, action: str, triggers: dict[str, Any]) -> str:
    """Render a BUY/SELL/HOLD explanation, e.g.

    "BUY (momentum): 20-day MA (102.30) is above the 50-day MA (99.80) by +2.5%;
     90-day momentum is +12.3%."
    """
    clauses = _clauses(triggers)
    body = "; ".join(clauses) if clauses else "trigger conditions met"
    return f"{action} ({strategy}): {body}."


def explain_no_signal(strategy: str, triggers: dict[str, Any]) -> str:
    clauses = _clauses(triggers)
    body = "; ".join(clauses) if clauses else "no trigger conditions met"
    return f"HOLD ({strategy}): {body}."


def explain_stance(strategy: str, triggers: dict[str, Any]) -> str:
    """Describe a name's *current* favourable stance (used by the optimizer to say
    why a name is currently selected), from its latest indicator values."""
    clauses = _clauses(triggers)
    body = "; ".join(clauses) if clauses else "currently favoured"
    return f"selected by {strategy} ({body})"


def explain_allocation(
    ticker: str,
    weight: float,
    *,
    sector: str | None = None,
    expected_return: float | None = None,
    volatility: float | None = None,
    risk_contribution: float | None = None,
    signal_reasons: list[str] | None = None,
) -> str:
    """Explain why *ticker* is in the recommended portfolio at *weight*."""
    parts = [f"{ticker} at {weight * 100:.1f}% of capital"]
    if sector:
        parts.append(f"sector: {sector}")
    if expected_return is not None:
        parts.append(f"expected return {_pct(expected_return)} p.a.")
    if volatility is not None:
        parts.append(f"volatility {_pct(volatility)}")
    if risk_contribution is not None:
        parts.append(f"contributes {risk_contribution * 100:.0f}% of portfolio risk")
    base = "; ".join(parts) + "."
    if signal_reasons:
        base += " Signals: " + " | ".join(signal_reasons)
    return base
