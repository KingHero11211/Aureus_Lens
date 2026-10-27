"""Cost model against the hand-checked example in config.

The rates are UNVERIFIED; these tests check the arithmetic, not the rates.
At Rs 1,000,000: buy 69.56, sell 149.56, round trip 219.12.
"""

import pytest

from src.aureus_lens.core.costs import (
    compute_buy_costs,
    pair_cost_bps,
    compute_roundtrip_costs,
    compute_sell_costs,
)


def test_hand_checked_turnover_1m_buy_costs():
    """Validates buy-side cost decomposition on ₹1,000,000 turnover."""
    res = compute_buy_costs(1_000_000.0)

    assert res["brokerage"] == 20.00
    assert res["exchange_fee"] == 21.00
    assert res["sebi_fee"] == 1.00
    assert res["gst"] == 7.56
    assert res["stamp_duty"] == 20.00
    assert res["total"] == 69.56


def test_hand_checked_turnover_1m_sell_costs():
    """Validates sell-side cost decomposition on ₹1,000,000 turnover."""
    res = compute_sell_costs(1_000_000.0)

    assert res["brokerage"] == 20.00
    assert res["exchange_fee"] == 21.00
    assert res["sebi_fee"] == 1.00
    assert res["gst"] == 7.56
    assert res["ctt"] == 100.00
    assert res["total"] == 149.56


def test_hand_checked_turnover_1m_roundtrip_costs():
    """Validates combined round-trip costs and basis points burden on ₹1M leg turnover."""
    res = compute_roundtrip_costs(1_000_000.0, 1_000_000.0)

    assert res["buy_total"] == 69.56
    assert res["sell_total"] == 149.56
    assert res["total_rupees"] == 219.12
    # 219.12 / 1,000,000 * 10,000 = 2.1912 bps
    assert res["total_bps"] == pytest.approx(2.19, abs=0.01)


def test_pair_cost_bps_hand_checked():
    # Two legs, each bought and sold once at Rs 1,000,000:
    # 2 x (69.56 + 149.56) / 1,000,000 x 10,000 = 4.3824 bps
    assert pair_cost_bps(1_000_000.0) == pytest.approx(4.3824)
