"""Checks a pair must pass before a spread is reported as a signal."""

from typing import Any, List, Mapping, Optional, Tuple

import pandas as pd

from config import CONTRACT_SPECS

DEFAULT_COST_MARGIN = 2.0  # spread must be at least this multiple of cost


def _leg_reasons(leg: Mapping[str, Any], prev_oi: Optional[float]) -> List[str]:
    sym = leg["symbol"]
    reasons = []
    days = (leg["expiry_date"] - leg["date"]).days
    tender = CONTRACT_SPECS[sym]["tender_period_days"]
    if days <= tender:
        reasons.append(f"{sym} {leg['expiry_date']}: {days} days to expiry, inside {tender}-day tender buffer")
    if leg["volume_lots"] == 0:
        reasons.append(f"{sym} {leg['expiry_date']}: no trades (volume 0)")
    elif leg["close"] == leg["previous_close"] and prev_oi is not None and leg["oi_lots"] == prev_oi:
        reasons.append(f"{sym} {leg['expiry_date']}: close and OI unchanged from prior session")
    return reasons


def executability_gate(
    leg_a: Mapping[str, Any],
    leg_b: Mapping[str, Any],
    spread_bps: float,
    cost_bps: float,
    margin: float = DEFAULT_COST_MARGIN,
    carry_source: Optional[str] = None,
    prev_oi_a: Optional[float] = None,
    prev_oi_b: Optional[float] = None,
) -> Tuple[bool, List[str]]:
    """Return (passes, reasons). reasons lists every failing check; it is
    empty when the pair passes.

    Legs need date, symbol, expiry_date, close, previous_close, volume_lots
    and oi_lots. carry_source "none" fails a pair that needs carry.
    """
    reasons = _leg_reasons(leg_a, prev_oi_a) + _leg_reasons(leg_b, prev_oi_b)
    if carry_source == "none":
        reasons.append("no carry estimate for expiry alignment")
    if pd.isna(spread_bps):
        reasons.append("spread not available")
    elif abs(spread_bps) < margin * cost_bps:
        reasons.append(f"|spread| {abs(spread_bps):.2f} bps below {margin:g} x cost {cost_bps:.2f} bps")
    return not reasons, reasons
