"""Core analytical engine for Aureus Lens.

Includes normalization, carry alignment, spread calculation,
robust signals, executability gating, and waterfall attribution.
"""

from src.aureus_lens.core.curve import adjust_to_expiry, compute_carry
from src.aureus_lens.core.gate import executability_gate
from src.aureus_lens.core.normalize import normalize_ppg999
from src.aureus_lens.core.signals import compute_zscore
from src.aureus_lens.core.spread import compute_spread_bps
from src.aureus_lens.core.waterfall import compute_waterfall

__all__ = [
    "normalize_ppg999",
    "compute_carry",
    "adjust_to_expiry",
    "compute_spread_bps",
    "compute_zscore",
    "executability_gate",
    "compute_waterfall",
]
