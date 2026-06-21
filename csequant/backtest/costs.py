"""Transaction-cost and liquidity model for the Casablanca Stock Exchange.

The numbers are configurable assumptions (``config/settings.yaml`` -> ``costs``),
NOT official tariffs — tune them to your broker. A single trade of *notional* MAD
incurs:

    commission  = max(notional * commission_rate, commission_min)
    exchange    = notional * exchange_fee_rate         (Bourse de Casablanca)
    regulatory  = notional * regulatory_fee_rate       (AMMC)
    VAT (TVA)   = vat_rate * (commission + exchange + regulatory)
    slippage    = notional * slippage_bps / 1e4        (half-spread / impact)

Liquidity: you cannot trade more than ``liquidity_adv_frac`` of a name's trailing
average daily turnover in one day — this throttles thinly-traded CSE names.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..config import Config


@dataclass
class CostModel:
    commission_rate: float = 0.0040
    commission_min: float = 0.0
    exchange_fee_rate: float = 0.0010
    regulatory_fee_rate: float = 0.0002
    vat_rate: float = 0.10
    slippage_bps: float = 15.0
    liquidity_adv_frac: float = 0.10

    @classmethod
    def from_config(cls, cfg: Config) -> "CostModel":
        c = cfg.get("costs", {}) or {}
        return cls(
            commission_rate=float(c.get("commission_rate", 0.0040)),
            commission_min=float(c.get("commission_min", 0.0)),
            exchange_fee_rate=float(c.get("exchange_fee_rate", 0.0010)),
            regulatory_fee_rate=float(c.get("regulatory_fee_rate", 0.0002)),
            vat_rate=float(c.get("vat_rate", 0.10)),
            slippage_bps=float(c.get("slippage_bps", 15.0)),
            liquidity_adv_frac=float(c.get("liquidity_adv_frac", 0.10)),
        )

    # -- explicit costs (fees + taxes), excluding slippage -----------------
    def fees(self, notional: float) -> float:
        notional = abs(notional)
        commission = max(notional * self.commission_rate, self.commission_min)
        exchange = notional * self.exchange_fee_rate
        regulatory = notional * self.regulatory_fee_rate
        vat = self.vat_rate * (commission + exchange + regulatory)
        return commission + exchange + regulatory + vat

    def slippage(self, notional: float) -> float:
        return abs(notional) * self.slippage_bps / 1e4

    def total_cost(self, notional: float) -> float:
        """All-in cost (fees + taxes + slippage) for a trade of *notional* MAD."""
        return self.fees(notional) + self.slippage(notional)

    def exec_price(self, mid_price: float, side: str) -> float:
        """Execution price after slippage: worse for the taker on both sides."""
        slip = self.slippage_bps / 1e4
        return mid_price * (1 + slip) if side == "BUY" else mid_price * (1 - slip)

    def max_tradable_notional(self, avg_daily_turnover: float) -> float:
        """Max MAD that may be traded in one name in one day (liquidity cap)."""
        if avg_daily_turnover is None or avg_daily_turnover <= 0:
            return float("inf")
        return avg_daily_turnover * self.liquidity_adv_frac
