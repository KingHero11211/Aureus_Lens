"""Relative-Value Spread Calculation in Basis Points.

Aureus Lens - Contract-Native Relative-Value Engine for MCX Gold Futures.
Hack in Hills '26 - Phase 3
"""


def compute_spread_bps(ppg_small: float, ppg_ref: float) -> float:
    """Compute relative-value spread in basis points between a retail contract and reference contract.

    Formula:
        spread_bps = 10,000 * (ppg_small - ppg_ref) / ppg_ref

    Args:
        ppg_small: Normalized (and carry-adjusted) price of retail contract (e.g. GOLDTEN, GOLDPETAL).
        ppg_ref: Normalized price of benchmark reference contract (e.g. GOLDM).

    Returns:
        float: Spread in basis points (1 bp = 0.01%).
               Positive indicates retail trading at a premium to reference.
               Negative indicates retail trading at a discount.
    """
    if ppg_ref <= 0:
        raise ValueError(f"Reference PPG price must be strictly positive, got: {ppg_ref}")

    return 10_000.0 * (ppg_small - ppg_ref) / ppg_ref
