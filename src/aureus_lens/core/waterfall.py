"""Relative-Value Waterfall Attribution Engine.

Decomposes raw quote gaps across purity adjustment, carry alignment,
tick friction floor, and execution transaction costs.
"""

from typing import Any, Dict, List


def compute_waterfall(
    raw_gap_bps: float,
    purity_gap_bps: float,
    carry_gap_bps: float,
    tick_floor_bps: float,
    cost_bps: float,
) -> List[Dict[str, Any]]:
    """Compute relative-value spread waterfall stages from raw gap to net edge.

    Stages:
        1. raw:        Initial unadjusted quote gap in bps (quote-base scaling only)
        2. purity:     Gap after adjusting for contract purity (e.g. 995 -> 999)
        3. carry:      Gap after continuous carry alignment to reference expiry
        4. tick floor: Discrete tick quantization friction
        5. cost:       Total transaction costs (Exchange, CTT, GST, SEBI, Stamp)
        6. edge:       Net executable edge floored at zero (never crosses zero)

    Guarantees:
        - Sign is preserved (both positive premium and negative discount supported).
        - Edge is floored at zero and never crosses zero.
        - Deltas sum exactly to final minus raw: sum(delta for stage != raw) == edge - raw.

    Returns:
        List of stage dicts containing:
            - stage: Stage identifier string ('raw', 'purity', 'carry', 'tick floor', 'cost', 'edge')
            - value: Basis points level at this stage (also keyed as 'bps')
            - delta: Incremental contribution to final edge (also keyed as 'delta_bps')
    """
    raw = float(raw_gap_bps)
    purity = float(purity_gap_bps)
    carry = float(carry_gap_bps)
    tick = abs(float(tick_floor_bps))
    cost = abs(float(cost_bps))

    delta_purity = purity - raw
    delta_carry = carry - purity

    # Edge calculation preserving sign and floored at zero (never crosses zero)
    if carry >= 0:
        # Positive spread: friction reduces edge down to zero
        friction_total = tick + cost
        if carry >= friction_total:
            edge = carry - friction_total
            delta_tick = -tick
            delta_cost = -cost
        else:
            # Friction exceeds remaining spread: edge floored at zero
            edge = 0.0
            # Scale deductions proportionally so sum of deltas equals final - raw
            remaining = carry
            if friction_total > 0:
                delta_tick = -(tick / friction_total) * remaining
                delta_cost = -(cost / friction_total) * remaining
            else:
                delta_tick = 0.0
                delta_cost = 0.0
    else:
        # Negative spread (discount): friction increases edge up to zero
        friction_total = tick + cost
        if abs(carry) >= friction_total:
            edge = carry + friction_total
            delta_tick = tick
            delta_cost = cost
        else:
            edge = 0.0
            remaining = abs(carry)
            if friction_total > 0:
                delta_tick = (tick / friction_total) * remaining
                delta_cost = (cost / friction_total) * remaining
            else:
                delta_tick = 0.0
                delta_cost = 0.0

    stages = [
        {"stage": "raw", "value": raw, "bps": raw, "delta": 0.0, "delta_bps": 0.0},
        {"stage": "purity", "value": purity, "bps": purity, "delta": delta_purity, "delta_bps": delta_purity},
        {"stage": "carry", "value": carry, "bps": carry, "delta": delta_carry, "delta_bps": delta_carry},
        {"stage": "tick floor", "value": carry + delta_tick, "bps": carry + delta_tick, "delta": delta_tick, "delta_bps": delta_tick},
        {"stage": "cost", "value": carry + delta_tick + delta_cost, "bps": carry + delta_tick + delta_cost, "delta": delta_cost, "delta_bps": delta_cost},
        {"stage": "edge", "value": edge, "bps": edge, "delta": edge - raw, "delta_bps": edge - raw},
    ]

    return stages
