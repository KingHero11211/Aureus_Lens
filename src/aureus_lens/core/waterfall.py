"""Break a quoted gap into purity, carry, tick-floor and cost steps."""

from typing import Dict, List

import numpy as np

STAGES = ["raw", "purity", "carry", "tick floor", "cost", "edge"]


def compute_waterfall(raw_gap_bps: float, purity_gap_bps: float, carry_gap_bps: float,
                      tick_floor_bps: float, cost_bps: float) -> List[Dict[str, float]]:
    """Return the six stages as dicts with stage, value (bps after the step)
    and delta (bps change made by the step).

    raw, purity and carry are the gap after each adjustment. Tick floor and
    cost then shrink the gap toward zero in that order, never past it, so the
    edge keeps the sign of the carry-adjusted gap or is zero. The deltas of
    purity through cost sum to edge - raw.
    """
    tick, cost = abs(tick_floor_bps), abs(cost_bps)
    gap = carry_gap_bps
    sign = float(np.sign(gap))
    tick_used = min(tick, abs(gap))
    cost_used = min(cost, abs(gap) - tick_used)
    after_tick = gap - sign * tick_used
    edge = after_tick - sign * cost_used

    values = [raw_gap_bps, purity_gap_bps, carry_gap_bps, after_tick, edge, edge]
    deltas = [0.0, purity_gap_bps - raw_gap_bps, carry_gap_bps - purity_gap_bps,
              after_tick - carry_gap_bps, edge - after_tick, 0.0]
    return [{"stage": s, "value": v, "delta": d} for s, v, d in zip(STAGES, values, deltas)]
