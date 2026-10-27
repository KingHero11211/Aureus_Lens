"""Unit tests for Phase 4 & Audit Refinements.

Covers:
1. shift(1) strictly isolates today's value from its own rolling median and MAD baseline.
2. MAD is median(|x - median(x)|) inside each window.
   Exact test: window [1, 2, 3, 4, 100] followed by 5 gives median 3, MAD 1, z = 2/1.4826.
3. Zero MAD returns NaN, never infinity.
4. Z-scores reset to NaN on roll days (when expiry changes).
5. Executability gate returns ALL failing reasons, not just the first.
6. Gate suppressions: tender buffer, stale price (volume=0 or unchanged close & OI), sub-hurdle.
7. Waterfall stages: raw, purity, carry, tick floor, cost, edge.
   Deltas sum to final minus raw, edge floored at zero, sign preserved.
"""

from datetime import date
import numpy as np
import pandas as pd
import pytest

from src.aureus_lens.core.gate import executability_gate
from src.aureus_lens.core.signals import compute_zscore
from src.aureus_lens.core.waterfall import compute_waterfall


# --- Section F: Signals Tests ---


def test_mad_window_exact_values():
    """Test window [1, 2, 3, 4, 100] followed by 5 gives median 3, MAD 1, and z = 2/1.4826."""
    data = [1.0, 2.0, 3.0, 4.0, 100.0, 5.0]
    series = pd.Series(data)

    # Window of 5, min_periods 5
    z = compute_zscore(series, window=5, min_periods=5)

    # First 5 points should be NaN (shifted)
    assert z.iloc[:5].isna().all()

    # 6th point (index 5, value 5.0):
    # Lagged window is [1, 2, 3, 4, 100]
    # Median is 3.0
    # Deviations: |1-3|=2, |2-3|=1, |3-3|=0, |4-3|=1, |100-3|=97
    # Sorted deviations: [0, 1, 1, 2, 97] -> Median deviation (MAD) = 1.0
    # Expected scale = 1.4826 * 1.0 = 1.4826
    # Expected z = (5.0 - 3.0) / 1.4826 = 2.0 / 1.4826
    expected_z = 2.0 / 1.4826
    assert z.iloc[5] == pytest.approx(expected_z, rel=1e-5)


def test_zscore_zero_mad_returns_nan_never_infinity():
    """Zero MAD on constant series returns NaN, never infinity."""
    constant_data = [10.0] * 10 + [25.0]
    series = pd.Series(constant_data)

    z = compute_zscore(series, window=5, min_periods=5)
    # At index 10, lagged window is [10, 10, 10, 10, 10], MAD is 0.0 -> must be NaN, not inf
    assert pd.isna(z.iloc[10])
    assert not np.isinf(z.iloc[10])


def test_zscore_resets_to_nan_on_roll_day():
    """Z-score resets to NaN on roll days when the contract expiry changes."""
    spreads = pd.Series([10.0, 12.0, 11.0, 13.0, 14.0, 15.0, 16.0])
    expiries = pd.Series([
        date(2026, 10, 30),
        date(2026, 10, 30),
        date(2026, 10, 30),
        date(2026, 10, 30),
        date(2026, 11, 30),  # Roll day at index 4!
        date(2026, 11, 30),
        date(2026, 11, 30),
    ])

    z = compute_zscore(spreads, window=3, min_periods=3, expiry_series=expiries)

    # Index 3 is normal
    assert not pd.isna(z.iloc[3])

    # Index 4 is the roll day -> MUST be NaN
    assert pd.isna(z.iloc[4])

    # Index 5 resumes
    assert not pd.isna(z.iloc[5])


def test_zscore_shift1_proves_today_never_enters_baseline():
    """Proves today's value never enters its own baseline median or MAD."""
    baseline = [10.0, 11.5, 12.0, 13.5, 14.0, 15.5, 16.0, 17.5, 18.0, 19.5,
                20.0, 21.5, 22.0, 23.5, 24.0, 25.5, 26.0, 27.5, 28.0, 29.5]

    baseline_arr = np.array(baseline)
    expected_lagged_median = float(np.median(baseline_arr))
    expected_lagged_mad = float(np.median(np.abs(baseline_arr - expected_lagged_median)))
    expected_scale = 1.4826 * expected_lagged_mad

    # Case A: 21st value is 50.0
    series_a = pd.Series(baseline + [50.0])
    z_a = compute_zscore(series_a, window=20, min_periods=20)

    # Case B: 21st value is 5000.0 (extreme shock)
    series_b = pd.Series(baseline + [5000.0])
    z_b = compute_zscore(series_b, window=20, min_periods=20)

    # Lagged parameters must be strictly identical
    expected_z_a = (50.0 - expected_lagged_median) / expected_scale
    assert z_a.iloc[20] == pytest.approx(expected_z_a, rel=1e-5)

    expected_z_b = (5000.0 - expected_lagged_median) / expected_scale
    assert z_b.iloc[20] == pytest.approx(expected_z_b, rel=1e-5)

    # Ratio invariance test
    ratio_z = (z_b.iloc[20]) / (z_a.iloc[20])
    ratio_raw = (5000.0 - expected_lagged_median) / (50.0 - expected_lagged_median)
    assert ratio_z == pytest.approx(ratio_raw, rel=1e-6)


# --- Section G: Gate Tests ---


def test_gate_returns_all_failing_reasons():
    """Executability gate returns ALL failing reasons, not just the first."""
    # This row triggers BOTH tender buffer AND sub-hurdle spread
    row_small = {
        "symbol": "GOLDTEN",
        "date": date(2026, 10, 29),
        "expiry_date": date(2026, 10, 30),  # 1 day to expiry -> inside tender buffer!
        "volume": 500.0,
        "close": 76400.0,
        "previous_close": 76100.0,
    }
    row_ref = {
        "symbol": "GOLDM",
        "date": date(2026, 10, 29),
        "expiry_date": date(2026, 12, 5),
        "volume": 1200.0,
        "close": 76300.0,
        "previous_close": 76000.0,
    }

    # Spread 2.0 bps with cost 5.0 bps (hurdle 10.0 bps) -> sub-hurdle!
    passed, reasons = executability_gate(row_small, row_ref, spread_bps=2.0, cost_bps=5.0)

    assert passed is False
    assert isinstance(reasons, list)
    # Must contain AT LEAST 2 reasons: tender buffer AND sub-hurdle
    assert len(reasons) >= 2
    assert any("tender buffer" in r for r in reasons)
    assert any("Sub-hurdle" in r for r in reasons)


def test_gate_stale_price_with_unchanged_oi():
    """Suppresses when volume == 0, OR (close == previous_close with unchanged OI)."""
    # Case A: Volume == 0
    row_vol0 = {
        "symbol": "GOLDGUINEA",
        "date": date(2026, 10, 9),
        "expiry_date": date(2026, 11, 30),
        "volume": 0.0,
        "close": 61250.0,
        "previous_close": 61100.0,
    }
    row_ref = {
        "symbol": "GOLDM",
        "date": date(2026, 10, 9),
        "expiry_date": date(2026, 11, 5),
        "volume": 1200.0,
        "close": 76300.0,
        "previous_close": 76000.0,
    }
    passed, reasons = executability_gate(row_vol0, row_ref, spread_bps=25.0, cost_bps=5.0)
    assert passed is False
    assert any("volume == 0" in r for r in reasons)

    # Case B: Close unchanged AND OI unchanged
    row_unchanged_oi = {
        "symbol": "GOLDGUINEA",
        "date": date(2026, 10, 9),
        "expiry_date": date(2026, 11, 30),
        "volume": 10.0,
        "close": 61250.0,
        "previous_close": 61250.0,  # Unchanged close
        "oi": 500.0,
        "prev_oi": 500.0,  # Unchanged OI
    }
    passed_oi, reasons_oi = executability_gate(row_unchanged_oi, row_ref, spread_bps=25.0, cost_bps=5.0)
    assert passed_oi is False
    assert any("unchanged OI" in r for r in reasons_oi)


# --- Section H: Waterfall Tests ---


def test_waterfall_stages_and_delta_sum():
    """Stages are raw, purity, carry, tick floor, cost, edge. Deltas sum to final minus raw."""
    raw_gap = 50.0
    purity_gap = 45.0
    carry_gap = 42.0
    tick_floor = 1.5
    cost = 4.2

    stages = compute_waterfall(
        raw_gap_bps=raw_gap,
        purity_gap_bps=purity_gap,
        carry_gap_bps=carry_gap,
        tick_floor_bps=tick_floor,
        cost_bps=cost,
    )

    stage_names = [s["stage"] for s in stages]
    assert stage_names == ["raw", "purity", "carry", "tick floor", "cost", "edge"]

    final_edge = stages[5]["value"]
    raw_val = stages[0]["value"]

    # Deltas sum to final minus raw: sum(delta for stage != raw) == edge - raw
    sum_deltas = sum(s["delta"] for s in stages[1:5])
    assert sum_deltas == pytest.approx(final_edge - raw_val)

    # Edge floored at zero and never crosses zero
    assert final_edge >= 0.0
    assert final_edge == pytest.approx(42.0 - 1.5 - 4.2)


def test_waterfall_floors_edge_at_zero_when_friction_exceeds_spread():
    """Edge is floored at zero and never crosses zero when friction exceeds spread."""
    stages = compute_waterfall(
        raw_gap_bps=10.0,
        purity_gap_bps=5.0,
        carry_gap_bps=2.0,  # Only 2 bps carry gap
        tick_floor_bps=1.5,
        cost_bps=4.0,       # 1.5 + 4.0 = 5.5 bps friction > 2.0 bps gap
    )

    final_edge = stages[5]["value"]
    raw_val = stages[0]["value"]

    assert final_edge == 0.0
    sum_deltas = sum(s["delta"] for s in stages[1:5])
    assert sum_deltas == pytest.approx(final_edge - raw_val)
