"""Statutory Transaction Cost Model for MCX Futures.

Implements official Indian commodity exchange transaction costs:
- Brokerage: min(0.03% of turnover, ₹20 per order)
- Exchange transaction fee: 0.0021%
- SEBI turnover fee: ₹10 per crore (0.0001%)
- GST: 18% on (brokerage + exchange charges + SEBI fee)
- Stamp Duty: 0.002% (buy side only)
- Commodities Transaction Tax (CTT): 0.01% (sell side only, non-agri)

Hand-Checked Benchmark:
  Turnover ₹1,000,000:
    Buy side:  Brokerage=20, Exchange=21, SEBI=1, GST=7.56, Stamp=20  -> Total = ₹69.56
    Sell side: Brokerage=20, Exchange=21, SEBI=1, GST=7.56, CTT=100    -> Total = ₹149.56
    Round-trip Total: ₹219.12 (2.19 bps)
"""

from typing import Dict

from config import (
    BROKERAGE_MAX_PER_ORDER,
    BROKERAGE_RATE_PCT,
    CTT_SELL_PCT,
    EXCHANGE_TRANSACTION_CHARGE_PCT,
    GST_PCT,
    SEBI_TURNOVER_FEE_PCT,
    STAMP_DUTY_BUY_PCT,
)


def compute_buy_costs(turnover: float) -> Dict[str, float]:
    """Compute detailed buy-side transaction costs for a given turnover."""
    t = float(turnover)
    brokerage = min(t * BROKERAGE_RATE_PCT, BROKERAGE_MAX_PER_ORDER)
    exchange_fee = t * EXCHANGE_TRANSACTION_CHARGE_PCT
    sebi_fee = t * SEBI_TURNOVER_FEE_PCT
    gst = (brokerage + exchange_fee + sebi_fee) * GST_PCT
    stamp_duty = t * STAMP_DUTY_BUY_PCT
    total = brokerage + exchange_fee + sebi_fee + gst + stamp_duty

    return {
        "turnover": t,
        "brokerage": round(brokerage, 2),
        "exchange_fee": round(exchange_fee, 2),
        "sebi_fee": round(sebi_fee, 2),
        "gst": round(gst, 2),
        "stamp_duty": round(stamp_duty, 2),
        "total": round(total, 2),
    }


def compute_sell_costs(turnover: float) -> Dict[str, float]:
    """Compute detailed sell-side transaction costs for a given turnover."""
    t = float(turnover)
    brokerage = min(t * BROKERAGE_RATE_PCT, BROKERAGE_MAX_PER_ORDER)
    exchange_fee = t * EXCHANGE_TRANSACTION_CHARGE_PCT
    sebi_fee = t * SEBI_TURNOVER_FEE_PCT
    gst = (brokerage + exchange_fee + sebi_fee) * GST_PCT
    ctt = t * CTT_SELL_PCT
    total = brokerage + exchange_fee + sebi_fee + gst + ctt

    return {
        "turnover": t,
        "brokerage": round(brokerage, 2),
        "exchange_fee": round(exchange_fee, 2),
        "sebi_fee": round(sebi_fee, 2),
        "gst": round(gst, 2),
        "ctt": round(ctt, 2),
        "total": round(total, 2),
    }


def compute_roundtrip_costs(
    buy_turnover: float,
    sell_turnover: float,
) -> Dict[str, float]:
    """Compute round-trip costs and aggregate basis points burden."""
    buy_res = compute_buy_costs(buy_turnover)
    sell_res = compute_sell_costs(sell_turnover)
    total_rupees = round(buy_res["total"] + sell_res["total"], 2)

    # Basis points burden relative to nominal leg turnover
    ref_turnover = max(buy_turnover, sell_turnover)
    total_bps = round((total_rupees / ref_turnover) * 10000.0, 2) if ref_turnover > 0 else 0.0

    return {
        "buy_total": buy_res["total"],
        "sell_total": sell_res["total"],
        "total_rupees": total_rupees,
        "total_bps": total_bps,
        "buy_breakdown": buy_res,
        "sell_breakdown": sell_res,
    }
