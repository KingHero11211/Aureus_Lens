"""Relative spread between two per-gram prices."""


def compute_spread_bps(ppg_a: float, ppg_b: float) -> float:
    """Return 10,000 x (ppg_a - ppg_b) / ppg_b in basis points; positive when a is dearer."""
    if ppg_b <= 0:
        raise ValueError(f"reference price must be positive, got {ppg_b}")
    return 10_000.0 * (ppg_a - ppg_b) / ppg_b
