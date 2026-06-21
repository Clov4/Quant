"""Event-driven, share-level walk-forward backtester for a long-only CSE sleeve.

The engine consumes a strategy's desired exposures and simulates a real account:
whole-share orders, broker/exchange fees + VAT + slippage (CostModel), a per-name
daily liquidity cap based on trailing turnover, and **T+settlement cash** (sale
proceeds are not available to re-deploy until they settle). It marks to market
every bar and produces an equity curve, a trade blotter, a daily weights matrix,
and a metrics summary versus the benchmark.

It is "walk-forward" in the sense that every decision at date *t* uses only data
up to and including *t* (indicators are causal; no look-ahead).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .. import schema
from ..config import Config
from ..logging_conf import get_logger
from ..strategies.base import Strategy
from . import metrics as M
from .costs import CostModel

log = get_logger(__name__)


@dataclass
class BacktestResult:
    name: str
    equity: pd.Series
    returns: pd.Series
    weights: pd.DataFrame
    trades: pd.DataFrame
    metrics: dict
    benchmark: pd.Series | None = None
    meta: dict = field(default_factory=dict)


class Backtester:
    def __init__(self, cfg: Config, cost_model: CostModel | None = None):
        self.cfg = cfg
        self.cm = cost_model or CostModel.from_config(cfg)
        self.initial_capital = float(cfg.get("backtest.initial_capital", 100_000))
        self.ppy = int(cfg.get("market.trading_days_per_year", 252))
        self.settlement = int(cfg.get("market.settlement_days", 2))
        self.lot = max(int(cfg.get("market.default_lot_size", 1)), 1)
        self.rebalance_rule = str(cfg.get("backtest.rebalance", "W-FRI"))
        self.warmup = int(cfg.get("backtest.warmup_days", 60))
        self.max_weight = float(cfg.get("backtest.max_position_weight", 0.30))
        self.adv_window = 20  # trailing bars for the liquidity (ADV) estimate

    # -- public ------------------------------------------------------------
    def run(
        self,
        strategy: Strategy,
        prices_by_ticker: dict[str, pd.DataFrame],
        benchmark: pd.Series | None = None,
    ) -> BacktestResult:
        prices_long = pd.concat(
            [p for p in prices_by_ticker.values() if p is not None and not p.empty],
            ignore_index=True,
        )
        P = schema.to_wide(prices_long, schema.ADJ_CLOSE).ffill()
        TO = schema.to_wide(prices_long, schema.TURNOVER)
        ADV = TO.rolling(self.adv_window, min_periods=1).mean()
        calendar = list(P.index)

        E = strategy.exposures(prices_by_ticker)
        if E.empty:
            raise ValueError("Strategy produced no exposures (need more data?)")
        E = E.reindex(index=P.index).ffill().fillna(0.0)
        tickers = [t for t in P.columns if t in E.columns]
        P, E, ADV = P[tickers], E[tickers], ADV.reindex(columns=tickers)

        rebal = self._rebalance_dates(calendar)
        warmup_date = calendar[min(self.warmup, len(calendar) - 1)]

        cash = self.initial_capital
        positions: dict[str, int] = {t: 0 for t in tickers}
        pending: list[tuple[int, float]] = []   # (settle_index, cash_amount)
        trades: list[dict] = []
        equity_curve: dict[pd.Timestamp, float] = {}
        weight_rows: dict[pd.Timestamp, dict] = {}

        for i, date in enumerate(calendar):
            price = P.loc[date]

            # 1) release settled sale proceeds
            ready = [a for (s, a) in pending if s <= i]
            if ready:
                cash += sum(ready)
                pending = [(s, a) for (s, a) in pending if s > i]

            # 2) rebalance
            if date in rebal and date >= warmup_date:
                equity_now = self._equity(cash, positions, price, pending)
                target_w = self._target_weights(E.loc[date], price)
                cash = self._rebalance(
                    i, date, cash, positions, pending, trades,
                    price, ADV.loc[date], target_w, equity_now,
                )

            # 3) mark to market
            eq = self._equity(cash, positions, price, pending)
            equity_curve[date] = eq
            weight_rows[date] = self._weights_row(cash, positions, price, eq, pending)

        equity = pd.Series(equity_curve).sort_index()
        equity.name = strategy.name
        returns = equity.pct_change()
        weights = pd.DataFrame(weight_rows).T.sort_index()
        trades_df = pd.DataFrame(
            trades,
            columns=["date", "ticker", "side", "shares", "price", "gross", "fees", "reason"],
        )
        summary = M.summary(equity, trades_df, self.ppy, benchmark)
        log.info("Backtest[%s]: CAGR=%.1f%% Sharpe=%.2f maxDD=%.1f%% trades=%d",
                 strategy.name, summary["cagr"] * 100, summary["sharpe"],
                 summary["max_drawdown"] * 100, len(trades_df))
        return BacktestResult(
            name=strategy.name, equity=equity, returns=returns, weights=weights,
            trades=trades_df, metrics=summary, benchmark=benchmark,
            meta={"tickers": tickers, "rebalance": self.rebalance_rule,
                  "settlement_days": self.settlement},
        )

    # -- helpers -----------------------------------------------------------
    def _rebalance_dates(self, calendar: list[pd.Timestamp]) -> set[pd.Timestamp]:
        idx = pd.DatetimeIndex(calendar)
        rule = self.rebalance_rule.upper()
        if rule.startswith("D"):
            return set(idx)
        freq = "M" if rule.startswith("M") else "W"
        period = idx.to_period(freq)
        last = pd.Series(idx, index=period).groupby(level=0).max()
        return set(pd.DatetimeIndex(last.values))

    def _target_weights(self, exposure: pd.Series, price: pd.Series) -> pd.Series:
        active = exposure[(exposure > 0) & price.notna()]
        if active.empty:
            return pd.Series(0.0, index=exposure.index)
        w = active / active.sum()
        w = w.clip(upper=self.max_weight)   # excess over the cap stays in cash
        return w.reindex(exposure.index).fillna(0.0)

    def _rebalance(self, i, date, cash, positions, pending, trades,
                   price, adv, target_w, equity_now) -> float:
        # desired whole-share targets
        targets: dict[str, int] = {}
        for t in target_w.index:
            px = price[t]
            if not np.isfinite(px) or px <= 0:
                targets[t] = positions[t]
                continue
            raw = target_w[t] * equity_now / px
            targets[t] = int(math.floor(raw / self.lot) * self.lot)

        # liquidity cap on the size of each order
        def capped_delta(t) -> int:
            delta = targets[t] - positions[t]
            max_notional = self.cm.max_tradable_notional(adv.get(t, np.nan))
            if np.isfinite(max_notional):
                max_shares = int(math.floor(max_notional / price[t] / self.lot) * self.lot)
                if delta > 0:
                    delta = min(delta, max_shares)
                else:
                    delta = max(delta, -max_shares)
            return delta

        # SELLs first (proceeds settle T+settlement)
        for t in target_w.index:
            delta = capped_delta(t)
            if delta < 0:
                shares = -delta
                exec_px = self.cm.exec_price(price[t], "SELL")
                gross = shares * exec_px
                fees = self.cm.fees(gross)
                positions[t] += delta
                pending.append((i + self.settlement, gross - fees))
                trades.append(_trade(date, t, "SELL", shares, exec_px, gross, fees,
                                     "exit / trim toward target"))

        # BUYs with settled cash only
        buys = [t for t in target_w.index if capped_delta(t) > 0]
        buys.sort(key=lambda t: target_w[t], reverse=True)
        for t in buys:
            delta = capped_delta(t)
            exec_px = self.cm.exec_price(price[t], "BUY")
            # shrink to what settled cash affords (price + fees)
            affordable = int(math.floor(cash / (exec_px * (1 + self.cm.commission_rate
                              + self.cm.exchange_fee_rate + self.cm.regulatory_fee_rate) + 1e-9)
                              / self.lot) * self.lot)
            shares = min(delta, max(affordable, 0))
            if shares <= 0:
                continue
            gross = shares * exec_px
            fees = self.cm.fees(gross)
            cost = gross + fees
            if cost > cash:
                continue
            cash -= cost
            positions[t] += shares
            trades.append(_trade(date, t, "BUY", shares, exec_px, gross, fees,
                                 "enter / add toward target"))
        return cash

    def _equity(self, cash, positions, price, pending) -> float:
        held = sum(positions[t] * price[t] for t in positions
                   if np.isfinite(price[t]) and positions[t])
        unsettled = sum(a for _, a in pending)
        return float(cash + held + unsettled)

    def _weights_row(self, cash, positions, price, equity, pending) -> dict:
        if equity <= 0:
            return {"cash": 1.0}
        row = {t: (positions[t] * price[t] / equity)
               for t in positions if np.isfinite(price[t]) and positions[t]}
        unsettled = sum(a for _, a in pending)
        row["cash"] = (cash + unsettled) / equity
        return row


def _trade(date, ticker, side, shares, price, gross, fees, reason) -> dict:
    return {
        "date": date, "ticker": ticker, "side": side, "shares": int(shares),
        "price": round(float(price), 4), "gross": round(float(gross), 2),
        "fees": round(float(fees), 2), "reason": reason,
    }
