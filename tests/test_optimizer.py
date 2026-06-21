"""Tests for the portfolio optimizer's weight/share maths and constraints."""
from csequant.config import load_config
from csequant.risk import PortfolioOptimizer


def _check_invariants(rec, capital, max_w, max_sector):
    # weights + cash sum to 1
    wsum = sum(p.weight for p in rec.positions)
    assert abs(wsum + rec.cash_weight - 1.0) < 1e-6
    # value + cash == capital (whole-share rounding leaves it consistent)
    invested = sum(p.value for p in rec.positions)
    assert abs(invested + rec.cash_value - capital) < 1.0
    # whole shares only
    assert all(float(p.shares).is_integer() and p.shares > 0 for p in rec.positions)
    # per-name cap (allow a little rounding slack)
    assert all(p.weight <= max_w + 0.02 for p in rec.positions)
    # sector caps
    by_sector: dict[str, float] = {}
    for p in rec.positions:
        by_sector[p.sector] = by_sector.get(p.sector, 0.0) + p.weight
    assert all(w <= max_sector + 0.03 for w in by_sector.values())


def test_mean_variance_invariants(synth_prices, synth_universe):
    cfg = load_config()
    opt = PortfolioOptimizer(cfg, synth_universe)
    capital = 100_000.0
    prof = cfg.risk_profile("Balanced")
    rec = opt.recommend(synth_prices, capital, "Balanced",
                        candidates=list(synth_prices.keys()))
    assert rec.method == "mean_variance"
    _check_invariants(rec, capital, prof["max_weight"], prof["max_sector_weight"])


def test_risk_parity_invariants(synth_prices, synth_universe):
    cfg = load_config()
    opt = PortfolioOptimizer(cfg, synth_universe)
    capital = 80_000.0
    prof = cfg.risk_profile("Conservative")
    rec = opt.recommend(synth_prices, capital, "Conservative",
                        candidates=list(synth_prices.keys()))
    assert rec.method == "risk_parity"
    _check_invariants(rec, capital, prof["max_weight"], prof["max_sector_weight"])
    # Conservative keeps at least its minimum cash buffer.
    assert rec.cash_weight >= prof["min_cash"] - 0.05


def test_vol_target_respected(synth_prices, synth_universe):
    cfg = load_config()
    opt = PortfolioOptimizer(cfg, synth_universe)
    rec = opt.recommend(synth_prices, 100_000.0, "Aggressive",
                        candidates=list(synth_prices.keys()))
    target = cfg.risk_profile("Aggressive")["target_vol"]
    # realised expected vol should not materially exceed the target
    assert rec.expected_vol <= target * 1.15


def test_risk_tolerance_changes_cash(synth_prices, synth_universe):
    cfg = load_config()
    opt = PortfolioOptimizer(cfg, synth_universe)
    cons = opt.recommend(synth_prices, 100_000.0, "Conservative",
                         candidates=list(synth_prices.keys()))
    aggr = opt.recommend(synth_prices, 100_000.0, "Aggressive",
                         candidates=list(synth_prices.keys()))
    # A conservative profile should hold more cash than an aggressive one.
    assert cons.cash_weight >= aggr.cash_weight


def test_positions_have_reasons(synth_prices, synth_universe):
    cfg = load_config()
    rec = PortfolioOptimizer(cfg, synth_universe).recommend(
        synth_prices, 100_000.0, "Balanced", candidates=list(synth_prices.keys()))
    assert all(p.reason and p.ticker in p.reason for p in rec.positions)
