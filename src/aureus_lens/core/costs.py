"""Transaction costs per order, from the UNVERIFIED rates in config.

Hand check at Rs 1,000,000 turnover:
  buy:  brokerage 20 + exchange 21 + SEBI 1 + GST 7.56 + stamp 20  = 69.56
  sell: brokerage 20 + exchange 21 + SEBI 1 + GST 7.56 + CTT 100   = 149.56
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
    """Return buy-side cost components and total in rupees for turnover in rupees."""
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
    """Return sell-side cost components and total in rupees for turnover in rupees."""
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
    """Return buy, sell and round-trip totals in rupees, and total_bps of the larger turnover."""
    buy_res = compute_buy_costs(buy_turnover)
    sell_res = compute_sell_costs(sell_turnover)
    total_rupees = round(buy_res["total"] + sell_res["total"], 2)

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


def pair_cost_bps(notional: float = 1_000_000.0) -> float:
    """Return the cost of a pair trade in bps of one leg's notional (rupees).

    Each leg is bought once and sold once, so the pair pays two round trips.
    """
    one_leg = compute_buy_costs(notional)["total"] + compute_sell_costs(notional)["total"]
    return 2 * one_leg / notional * 10_000.0
