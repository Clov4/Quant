"""Per-trade position sizing and risk guards.

Used by the optimizer (whole-share quantisation) and available to the engine/GUI
for stop-loss and max-drawdown kill-switch logic.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PositionSizer:
    lot_size: int = 1
    max_position_weight: float = 0.30

    # -- sizing ------------------------------------------------------------
    def fixed_fraction(self, capital: float, price: float, fraction: float) -> int:
        """Whole-share count for a fixed fraction of capital."""
        if price <= 0 or fraction <= 0:
            return 0
        target_value = capital * min(fraction, self.max_position_weight)
        return self._round_lot(target_value / price)

    def volatility_target(self, capital: float, price: float, ann_vol: float,
                          target_risk: float) -> int:
        """Size so the position's annual volatility ≈ target_risk * capital.

        Lower-volatility names get a larger weight; capped by ``max_position_weight``.
        """
        if price <= 0 or ann_vol <= 0:
            return 0
        weight = min(target_risk / ann_vol, self.max_position_weight)
        return self._round_lot(capital * weight / price)

    def _round_lot(self, shares: float) -> int:
        if shares <= 0:
            return 0
        return int(shares // self.lot_size) * self.lot_size

    # -- guards ------------------------------------------------------------
    @staticmethod
    def stop_loss_hit(entry_price: float, current_price: float, stop_pct: float) -> bool:
        if entry_price <= 0:
            return False
        return (current_price / entry_price - 1.0) <= -abs(stop_pct)

    @staticmethod
    def take_profit_hit(entry_price: float, current_price: float, target_pct: float) -> bool:
        if entry_price <= 0:
            return False
        return (current_price / entry_price - 1.0) >= abs(target_pct)

    @staticmethod
    def drawdown_breached(equity_peak: float, equity_now: float, max_dd: float) -> bool:
        """True if the running drawdown exceeds *max_dd* (a portfolio kill-switch)."""
        if equity_peak <= 0:
            return False
        return (equity_now / equity_peak - 1.0) <= -abs(max_dd)
