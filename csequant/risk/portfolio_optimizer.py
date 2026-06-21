"""Capital- and risk-aware portfolio construction.

Given **X** (capital, MAD) and **Y** (risk tolerance — a named profile mapping to
constraints in ``config/settings.yaml``), produce a recommended allocation:

* candidate names come from the *same* strategy signals the trading engine uses
  (so the portfolio is explainable with the same reasoning);
* weights from one of three methods (mean-variance / risk-parity / rule-based),
  selected per risk profile;
* volatility targeting scales exposure to the profile's target vol (the rest is a
  cash buffer);
* weights are quantised to **whole shares** for capital X (no fractional shares on
  the CSE), respecting per-name and per-sector caps;
* every included position carries a plain-language reason.

Covariance uses Ledoit-Wolf shrinkage for stability on short/illiquid samples.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.covariance import LedoitWolf

from .. import DISCLAIMER, schema
from ..backtest import metrics as M
from ..config import Config
from ..data.universe import Universe
from ..explainability.reasoning import explain_allocation, explain_stance
from ..logging_conf import get_logger
from ..strategies import build_strategy

log = get_logger(__name__)


@dataclass
class Position:
    ticker: str
    name: str
    sector: str
    weight: float
    shares: int
    value: float
    price: float
    expected_return: float
    volatility: float
    risk_contribution: float
    reason: str


@dataclass
class PortfolioRecommendation:
    capital: float
    risk_profile: str
    method: str
    positions: list[Position]
    cash_value: float
    cash_weight: float
    expected_return: float
    expected_vol: float
    expected_return_low: float
    expected_return_high: float
    historical_max_drawdown: float
    sector_breakdown: dict[str, float]
    as_of: str
    notes: list[str] = field(default_factory=list)
    disclaimer: str = DISCLAIMER

    def to_frame(self) -> pd.DataFrame:
        rows = [{
            "ticker": p.ticker, "name": p.name, "sector": p.sector,
            "weight": p.weight, "shares": p.shares, "value_mad": p.value,
            "price": p.price, "exp_return": p.expected_return,
            "volatility": p.volatility, "risk_contribution": p.risk_contribution,
            "reason": p.reason,
        } for p in self.positions]
        return pd.DataFrame(rows)


class PortfolioOptimizer:
    def __init__(self, cfg: Config, universe: Universe):
        self.cfg = cfg
        self.universe = universe
        self.ppy = int(cfg.get("market.trading_days_per_year", 252))
        self.lot = max(int(cfg.get("market.default_lot_size", 1)), 1)

    # -- public ------------------------------------------------------------
    def recommend(
        self,
        prices_by_ticker: dict[str, pd.DataFrame],
        capital: float,
        risk_tolerance: str,
        candidates: list[str] | None = None,
        lookback: int = 504,
    ) -> PortfolioRecommendation:
        profile = self.cfg.risk_profile(risk_tolerance)
        method = profile.get("method", "mean_variance")
        max_w = float(profile.get("max_weight", 0.25))
        max_sector = float(profile.get("max_sector_weight", 0.45))
        min_cash = float(profile.get("min_cash", 0.10))
        target_vol = float(profile.get("target_vol", 0.14))
        lam = float(profile.get("risk_aversion", 5.0))
        budget = max(0.0, 1.0 - min_cash)
        notes: list[str] = []

        mu, Sigma, last_price, R = self._estimate_inputs(prices_by_ticker, lookback)
        if mu.empty:
            raise ValueError("No estimable price history for optimization")

        if candidates is None:
            candidates, signal_reasons = self._signal_candidates(prices_by_ticker)
        else:
            signal_reasons = {}
        cand = [t for t in candidates if t in mu.index]
        if len(cand) < 3:
            # fall back to the names with the strongest historical risk-adjusted return
            ranked = (mu / np.sqrt(np.diag(Sigma.loc[mu.index, mu.index]))).sort_values(ascending=False)
            cand = list(ranked.index[:max(5, len(cand))])
            notes.append("Few live signals — fell back to top historical risk-adjusted names.")

        mu_c, Sigma_c, price_c = mu[cand], Sigma.loc[cand, cand], last_price[cand]
        sector_map = {t: self.universe.sector(t) for t in cand}

        if method == "risk_parity":
            w = self._risk_parity(Sigma_c, max_w, budget)
            w = self._apply_sector_caps(w, sector_map, max_sector)
        elif method == "rule_based":
            w = self._rule_based(cand, max_w, sector_map, max_sector, budget)
        else:
            method = "mean_variance"
            w = self._mean_variance(mu_c, Sigma_c, lam, max_w, sector_map, max_sector, budget)

        # volatility targeting -> the rest becomes a cash buffer
        w, vol_scale = self._apply_vol_target(w, Sigma_c, target_vol)
        if vol_scale < 0.999:
            notes.append(f"Scaled exposure to {vol_scale*100:.0f}% to meet the "
                         f"{target_vol*100:.0f}% target volatility ({risk_tolerance}).")

        shares, values, actual_w, cash = self._quantize(w, price_c, capital)
        wv = pd.Series(actual_w).reindex(cand).fillna(0.0)

        exp_ret = float((mu_c * wv).sum())
        exp_vol = float(np.sqrt(wv.values @ Sigma_c.values @ wv.values))
        hist_dd = self._historical_dd(R[cand], wv)
        rc = self._risk_contributions(wv, Sigma_c)

        positions: list[Position] = []
        for t in cand:
            if shares.get(t, 0) <= 0:
                continue
            positions.append(Position(
                ticker=t, name=self.universe.name(t), sector=sector_map[t],
                weight=float(actual_w[t]), shares=int(shares[t]),
                value=float(values[t]), price=float(price_c[t]),
                expected_return=float(mu_c[t]),
                volatility=float(np.sqrt(Sigma_c.loc[t, t])),
                risk_contribution=float(rc.get(t, 0.0)),
                reason=explain_allocation(
                    t, float(actual_w[t]), sector=sector_map[t],
                    expected_return=float(mu_c[t]),
                    volatility=float(np.sqrt(Sigma_c.loc[t, t])),
                    risk_contribution=float(rc.get(t, 0.0)),
                    signal_reasons=signal_reasons.get(t),
                ),
            ))
        positions.sort(key=lambda p: p.weight, reverse=True)

        sector_breakdown: dict[str, float] = {}
        for p in positions:
            sector_breakdown[p.sector] = sector_breakdown.get(p.sector, 0.0) + p.weight

        as_of = max((p.sort_values(schema.DATE)[schema.DATE].iloc[-1]
                     for p in prices_by_ticker.values() if not p.empty)).strftime("%Y-%m-%d")
        notes.append("Expected return/vol are annualised estimates from historical "
                     "returns (Ledoit-Wolf shrinkage); not a forecast.")
        log.info("Recommendation[%s/%s]: %d positions, cash %.0f%%, expRet %.1f%%, expVol %.1f%%",
                 risk_tolerance, method, len(positions), (cash / capital) * 100,
                 exp_ret * 100, exp_vol * 100)
        return PortfolioRecommendation(
            capital=capital, risk_profile=risk_tolerance, method=method,
            positions=positions, cash_value=float(cash), cash_weight=float(cash / capital),
            expected_return=exp_ret, expected_vol=exp_vol,
            expected_return_low=exp_ret - exp_vol, expected_return_high=exp_ret + exp_vol,
            historical_max_drawdown=hist_dd, sector_breakdown=sector_breakdown,
            as_of=as_of, notes=notes,
        )

    # -- estimation --------------------------------------------------------
    def _estimate_inputs(self, prices_by_ticker, lookback):
        closes = {}
        for t, p in prices_by_ticker.items():
            if p is None or p.empty:
                continue
            closes[t] = p.sort_values(schema.DATE).set_index(schema.DATE)[schema.ADJ_CLOSE]
        if not closes:
            return pd.Series(dtype=float), pd.DataFrame(), pd.Series(dtype=float), pd.DataFrame()
        px = pd.DataFrame(closes).sort_index()
        if lookback:
            px = px.tail(lookback + 1)
        R = px.pct_change().dropna(how="all").dropna(axis=1, how="any")
        if R.shape[1] == 0:
            return pd.Series(dtype=float), pd.DataFrame(), px.iloc[-1], R
        mu = R.mean() * self.ppy
        grand = mu.mean()
        mu = grand + 0.5 * (mu - grand)   # 50% shrink toward the cross-sectional mean
        lw = LedoitWolf().fit(R.values)
        Sigma = pd.DataFrame(lw.covariance_ * self.ppy, index=R.columns, columns=R.columns)
        return mu, Sigma, px.iloc[-1], R

    def _signal_candidates(self, prices_by_ticker):
        """Candidate names = those a strategy currently holds (its last exposure row).

        The attached reason describes each name's *current* stance from its latest
        indicator values (not its last transition) — so it always reflects why the
        name is favoured right now."""
        cands: set[str] = set()
        reasons: dict[str, list[str]] = {}
        for name in ("factor_model", "momentum"):
            strat = build_strategy(name, self.cfg)
            E = strat.exposures(prices_by_ticker)
            if E.empty:
                continue
            on = list(E.iloc[-1][E.iloc[-1] > 0].index)
            cands.update(on)
            for t in on:
                if t not in prices_by_ticker:
                    continue
                frame = strat.signals_frame(prices_by_ticker[t])
                if frame.empty:
                    continue
                last = frame.iloc[-1]
                triggers = dict(strat._static_triggers())
                for col in frame.columns:
                    if col in ("signal", "score", "action"):
                        continue
                    val = last[col]
                    if pd.notna(val):
                        triggers[col] = float(val)
                reasons.setdefault(t, []).append(explain_stance(name, triggers))
        return list(cands), reasons

    # -- optimizers --------------------------------------------------------
    def _mean_variance(self, mu, Sigma, lam, max_w, sector_map, max_sector, budget):
        idx = list(mu.index)
        m, S = mu.values, Sigma.values

        def neg_util(w):
            return -(m @ w - 0.5 * lam * w @ S @ w)

        cons = [{"type": "eq", "fun": lambda w: w.sum() - budget}]
        for sec in set(sector_map.values()):
            mask = np.array([1.0 if sector_map[t] == sec else 0.0 for t in idx])
            cons.append({"type": "ineq", "fun": lambda w, mk=mask: max_sector - w @ mk})
        bounds = [(0.0, max_w)] * len(idx)
        w0 = np.full(len(idx), budget / len(idx))
        res = minimize(neg_util, w0, method="SLSQP", bounds=bounds, constraints=cons,
                       options={"maxiter": 500, "ftol": 1e-9})
        w = pd.Series(np.clip(res.x, 0, None), index=idx)
        if not res.success:
            log.warning("mean_variance SLSQP did not converge: %s", res.message)
        return w

    def _risk_parity(self, Sigma, max_w, budget):
        idx = list(Sigma.index)
        S = Sigma.values
        n = len(idx)

        def obj(w):
            port_var = w @ S @ w
            rc = w * (S @ w)
            return float(np.sum((rc - port_var / n) ** 2))

        cons = [{"type": "eq", "fun": lambda w: w.sum() - budget}]
        bounds = [(1e-4, max_w)] * n
        w0 = np.full(n, budget / n)
        res = minimize(obj, w0, method="SLSQP", bounds=bounds, constraints=cons,
                       options={"maxiter": 1000, "ftol": 1e-12})
        return pd.Series(res.x, index=idx)

    def _rule_based(self, cand, max_w, sector_map, max_sector, budget):
        w = pd.Series(budget / len(cand), index=cand).clip(upper=max_w)
        return self._apply_sector_caps(w, sector_map, max_sector)

    # -- post-processing ---------------------------------------------------
    @staticmethod
    def _apply_sector_caps(w, sector_map, max_sector):
        w = w.copy()
        for sec in set(sector_map.values()):
            members = [t for t in w.index if sector_map[t] == sec]
            s = w[members].sum()
            if s > max_sector and s > 0:
                w[members] *= max_sector / s
        return w

    @staticmethod
    def _apply_vol_target(w, Sigma, target_vol):
        pv = float(np.sqrt(w.values @ Sigma.values @ w.values))
        if pv <= 0:
            return w, 1.0
        scale = min(1.0, target_vol / pv)
        return w * scale, scale

    def _quantize(self, w, last_price, capital):
        shares, values = {}, {}
        for t, wt in w.items():
            px = float(last_price[t])
            sh = int(math.floor(wt * capital / px / self.lot) * self.lot) if px > 0 else 0
            shares[t] = sh
            values[t] = sh * px
        cash = capital - sum(values.values())
        actual_w = {t: (values[t] / capital if capital else 0.0) for t in values}
        return shares, values, actual_w, cash

    @staticmethod
    def _risk_contributions(wv, Sigma):
        w = wv.values
        port_var = float(w @ Sigma.values @ w)
        if port_var <= 0:
            return {t: 0.0 for t in wv.index}
        mrc = Sigma.values @ w
        rc = w * mrc / port_var
        return {t: float(v) for t, v in zip(wv.index, rc)}

    def _historical_dd(self, R_cand, wv):
        if R_cand.empty or wv.sum() == 0:
            return 0.0
        port_ret = (R_cand[wv.index] * wv).sum(axis=1)
        equity = (1.0 + port_ret).cumprod()
        return M.max_drawdown(equity)
