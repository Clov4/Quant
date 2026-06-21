"""Tests for the CSE cost model."""
import math

from csequant.backtest.costs import CostModel


def test_fees_components_and_vat():
    cm = CostModel(commission_rate=0.004, commission_min=0.0, exchange_fee_rate=0.001,
                   regulatory_fee_rate=0.0002, vat_rate=0.10, slippage_bps=0.0)
    notional = 10_000.0
    commission = 40.0
    exchange = 10.0
    regulatory = 2.0
    vat = 0.10 * (commission + exchange + regulatory)
    assert abs(cm.fees(notional) - (commission + exchange + regulatory + vat)) < 1e-9


def test_commission_floor():
    cm = CostModel(commission_rate=0.001, commission_min=25.0, exchange_fee_rate=0.0,
                   regulatory_fee_rate=0.0, vat_rate=0.0, slippage_bps=0.0)
    # 0.1% of 1000 = 1 < floor 25 -> commission is the floor
    assert abs(cm.fees(1000.0) - 25.0) < 1e-9


def test_slippage_and_total():
    cm = CostModel(slippage_bps=15.0)
    assert abs(cm.slippage(10_000.0) - 15.0) < 1e-9
    assert abs(cm.total_cost(10_000.0) - (cm.fees(10_000.0) + 15.0)) < 1e-9


def test_exec_price_direction():
    cm = CostModel(slippage_bps=20.0)
    assert cm.exec_price(100.0, "BUY") > 100.0
    assert cm.exec_price(100.0, "SELL") < 100.0
    assert abs(cm.exec_price(100.0, "BUY") - 100.2) < 1e-9


def test_liquidity_cap():
    cm = CostModel(liquidity_adv_frac=0.10)
    assert cm.max_tradable_notional(1_000_000.0) == 100_000.0
    assert math.isinf(cm.max_tradable_notional(0.0))


def test_fees_symmetric_in_abs():
    cm = CostModel()
    assert cm.fees(-5000.0) == cm.fees(5000.0)
