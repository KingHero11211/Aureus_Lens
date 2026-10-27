"""Rolling z-score with a lagged median and MAD.

The real-data check uses the GOLDPETAL vs GOLDTEN spread (30 Oct 2026
expiry) on 5, 6, 7 and 9 Oct 2026. Other inputs are plain number series
that test the arithmetic; they are not prices.
"""

import numpy as np
import pandas as pd
import pytest

from src.aureus_lens.core.signals import compute_zscore

# 10,000 x (PETAL - TEN/10) / (TEN/10) from the October fixtures
PETAL_TEN = pd.Series([44.9704, 42.3343, 40.0604, 36.6213])


def test_hand_checked_real_spread():
    # Baseline for 9 Oct is 5-7 Oct: median 42.3343,
    # MAD = median(|2.6361|, 0, |2.2739|) = 2.2739,
    # z = (36.6213 - 42.3343) / (1.4826 x 2.2739) = -1.6946
    z = compute_zscore(PETAL_TEN, window=3, min_periods=3)
    assert z.iloc[:3].isna().all()
    assert z.iloc[3] == pytest.approx(-1.6946, abs=1e-3)


def test_default_window_gives_nan_on_four_sessions():
    assert compute_zscore(PETAL_TEN).isna().all()


def test_baseline_is_lagged():
    # Changing today's value must not change the baseline it is scored against.
    a = compute_zscore(pd.Series([1.0, 2.0, 3.0, 4.0, 100.0, 5.0]), window=5, min_periods=5)
    b = compute_zscore(pd.Series([1.0, 2.0, 3.0, 4.0, 100.0, 50.0]), window=5, min_periods=5)
    scale = 1.4826 * 1.0  # MAD of [1, 2, 3, 4, 100] is 1
    assert a.iloc[5] == pytest.approx((5.0 - 3.0) / scale)
    assert b.iloc[5] == pytest.approx((50.0 - 3.0) / scale)


def test_mad_inside_window_not_global():
    # Window [1, 2, 3, 4, 100]: median 3, MAD 1, so z for 5 is 2 / 1.4826.
    z = compute_zscore(pd.Series([1.0, 2.0, 3.0, 4.0, 100.0, 5.0]), window=5, min_periods=5)
    assert z.iloc[5] == pytest.approx(2.0 / 1.4826)


def test_zero_mad_gives_nan_not_inf():
    z = compute_zscore(pd.Series([10.0] * 6 + [25.0]), window=5, min_periods=5)
    assert pd.isna(z.iloc[6]) and not np.isinf(z).any()


def test_min_periods_below_window_uses_available_history():
    # The leading NaN from shift(1) stays in the window until it slides out.
    # MAD must ignore it, as the median does; before the fix this was NaN.
    z = compute_zscore(pd.Series([1.0, 2.0, 3.0, 4.0, 100.0, 5.0]), window=10, min_periods=5)
    assert z.iloc[5] == pytest.approx(2.0 / 1.4826)


def test_resets_on_expiry_change():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 100.0, 5.0, 6.0])
    exp = pd.Series(["a"] * 6 + ["b"])
    z = compute_zscore(s, window=5, min_periods=5, expiry=exp)
    assert not pd.isna(z.iloc[5]) and pd.isna(z.iloc[6])
