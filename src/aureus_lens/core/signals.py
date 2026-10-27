"""Rolling z-score of a spread against a lagged median and MAD."""

from typing import Optional

import numpy as np
import pandas as pd

MAD_SCALE = 1.4826  # makes MAD comparable to a standard deviation for normal data

# Both chosen by the team, not derived. With min_periods equal to the window,
# the first z-score needs 60 earlier sessions, so it appears on session 61.
Z_WINDOW = 60
Z_MIN_PERIODS = 60


def _mad(window: np.ndarray) -> float:
    """Return median(|x - median(x)|) of the non-NaN values in window."""
    window = window[~np.isnan(window)]
    if window.size == 0:
        return np.nan
    return float(np.median(np.abs(window - np.median(window))))


def compute_zscore(spread: pd.Series, window: int = Z_WINDOW, min_periods: int = Z_MIN_PERIODS,
                   expiry: Optional[pd.Series] = None) -> pd.Series:
    """Return z_t = (spread_t - median) / (1.4826 * MAD), unitless.

    Median and MAD come from the window ending the session before t
    (shift(1)), so a value never enters its own baseline. MAD is computed
    inside each window. Zero MAD gives NaN. If expiry is given, z is NaN on
    the first session after the expiry changes.
    """
    lagged = spread.shift(1)
    roll = lagged.rolling(window=window, min_periods=min_periods)
    median = roll.median()
    scale = MAD_SCALE * roll.apply(_mad, raw=True)

    z = (spread - median) / scale.where(scale > 0)
    if expiry is not None:
        rolled = (expiry != expiry.shift(1)) & expiry.shift(1).notna()
        z[rolled] = np.nan
    return z.rename("zscore")
