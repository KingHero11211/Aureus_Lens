"""Unit tests for Section I: Statutory Transaction Cost Model.

Verifies exact hand-checked benchmarks:
- Turnover ₹1,000,000:
  - Brokerage: min(0.03%, ₹20) = ₹20.00
  - Exchange: 0.0021% = ₹21.00
  - SEBI: ₹10/crore = ₹1.00
  - GST: 18% of ₹42 = ₹7.56
  - Stamp duty (buy): 0.002% = ₹20.00
  - Buy Total: ₹69.56
  - CTT (sell): 0.01% = ₹100.00
  - Sell Total: ₹149.56
  - Round-trip Total: ₹219.12
"""

import pytest

from src.aureus_lens.core.costs import (
    compute_buy_costs,
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
