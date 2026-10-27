"""Robust Statistical Signals and Rolling Z-Score Engine.

Aureus Lens - Contract-Native Relative-Value Engine for MCX Gold Futures.
Hack in Hills '26 - Phase 4 & Audit Refinement
"""

from typing import Optional
import numpy as np
import pandas as pd


def _rolling_mad(window_values: np.ndarray) -> float:
    """Calculate Median Absolute Deviation (MAD) of an array of values.

    MAD = median(|x - median(x)|) inside each window.
    """
    if len(window_values) == 0:
        return 0.0
    med = np.median(window_values)
    return float(np.median(np.abs(window_values - med)))


def compute_zscore(
    spread_series: pd.Series,
    window: int = 60,
    min_periods: int = 10,
    expiry_series: Optional[pd.Series] = None,
) -> pd.Series:
    """Compute robust rolling z-score using strictly lagged median and MAD.

    Formula:
        z_t = (spread_t - median_{t-1, w}) / (1.4826 * MAD_{t-1, w})

    Guarantees:
        - Strictly uses shift(1) on baseline median and MAD: today's value NEVER
          enters its own baseline.
        - MAD is computed as median(|x - median(x)|) inside each window.
        - Zero MAD returns NaN, never infinity.
        - Normal consistency scale factor: 1.4826.
        - Resets to NaN on a roll day (when expiry_series changes).

    Args:
        spread_series: Time series of relative-value spreads (e.g. in bps).
        window: Lookback window in trading days (default: 60).
        min_periods: Minimum observations required in shifted window (default: 10).
        expiry_series: Optional Series of contract expiries to detect roll days.

    Returns:
        pd.Series: Robust rolling z-score series matching input index.
    """
    if spread_series is None or len(spread_series) == 0:
        return pd.Series(dtype=float, index=spread_series.index if spread_series is not None else None)

    # 1. Strictly shift by 1 day so today's value t NEVER enters its own baseline
    shifted_spread = spread_series.shift(1)

    # 2. Rolling median over the lagged window
    rolling_median = shifted_spread.rolling(window=window, min_periods=min_periods).median()

    # 3. Rolling MAD over the lagged window
    rolling_mad = shifted_spread.rolling(window=window, min_periods=min_periods).apply(
        _rolling_mad,
        raw=True,
    )

    # 4. Normal consistency factor: 1.4826 * MAD
    normal_scale = 1.4826 * rolling_mad

    # 5. Compute z-score: (spread_t - median_{t-1, w}) / scale_{t-1, w}
    # Where scale is zero or NaN, return NaN
    with np.errstate(divide="ignore", invalid="ignore"):
        zscore = (spread_series - rolling_median) / normal_scale
        # Zero MAD or zero scale returns NaN, never inf
        zscore = zscore.replace([np.inf, -np.inf], np.nan)

    # 6. Reset to NaN on roll days (when expiry changes)
    if expiry_series is not None and len(expiry_series) == len(spread_series):
        roll_mask = (expiry_series != expiry_series.shift(1)) & expiry_series.shift(1).notna()
        zscore.loc[roll_mask] = np.nan

    zscore.name = "zscore"
    return zscore
