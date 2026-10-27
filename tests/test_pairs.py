"""Pair spreads on real October 2026 rows."""

from datetime import date

import pandas as pd
import pytest

from src.aureus_lens.core.curve import carry_series
from src.aureus_lens.core.pairs import build_pairs


@pytest.fixture(scope="module")
def pairs(oct_bhav):
    return build_pairs(oct_bhav, carry_series(oct_bhav))


def pick(pairs, d, kind, a, b, exp):
    hit = pairs[(pairs["date"] == d) & (pairs["kind"] == kind) & (pairs["leg_a"] == a)
                & (pairs["leg_b"] == b) & (pairs["expiry_a"] == exp)]
    assert len(hit) == 1
    return hit.iloc[0]


def test_pair_counts(pairs):
    # Per session: 6 shared small expiries x 3 small pairs, plus 18 small contracts vs GOLDM.
    assert pairs.groupby("date").size().tolist() == [36, 36, 36, 36]
    assert set(pairs["kind"]) == {"small_small", "small_goldm"}


def test_small_small_hand_checked(pairs):
    # 9 Oct, 30 Oct expiry: TEN 15045.9, GUINEA 15093.75, PETAL 15101 per gram.
    d, e = date(2026, 10, 9), date(2026, 10, 30)
    p = pick(pairs, d, "small_small", "GOLDPETAL", "GOLDTEN", e)
    assert p["spread_bps"] == pytest.approx(36.6213, abs=1e-4)
    assert p["raw_bps"] == p["purity_bps"] == p["spread_bps"]
    assert p["carry_source"] == "not needed"
    assert pick(pairs, d, "small_small", "GOLDGUINEA", "GOLDTEN", e)["spread_bps"] == pytest.approx(31.8027, abs=1e-4)
    assert pick(pairs, d, "small_small", "GOLDGUINEA", "GOLDPETAL", e)["spread_bps"] == pytest.approx(-4.8010, abs=1e-4)


def test_small_goldm_hand_checked(pairs):
    # 9 Oct GOLDTEN 30 Oct vs GOLDM 5 Nov (close 150130), carry 0.111010:
    # raw    10,000 x (15045.9 - 15013.0) / 15013.0                 = 21.9143
    # purity GOLDM at 999: 15013.0 x 999 / 995 = 15073.3527          -> -18.2134
    # carry  aligned 6 days earlier: x exp(0.111010 x -6 / 365)      = 15045.8726 -> 0.0182
    p = pick(pairs, date(2026, 10, 9), "small_goldm", "GOLDTEN", "GOLDM", date(2026, 10, 30))
    assert p["expiry_b"] == date(2026, 11, 5)
    assert p["raw_bps"] == pytest.approx(21.9143, abs=1e-4)
    assert p["purity_bps"] == pytest.approx(-18.2134, abs=1e-4)
    assert p["ppg_b_aligned"] == pytest.approx(15045.8726, abs=1e-4)
    assert p["spread_bps"] == pytest.approx(0.0182, abs=1e-4)
    assert p["carry_source"] == "empirical"
    assert p["edge_bps"] == 0.0
    assert not p["passes"]


def test_tick_floor_hand_checked(pairs):
    # One tick (1.0, UNVERIFIED) on each leg: 10,000 x (1/15101 + 1/150459) = 0.7287 bps
    p = pick(pairs, date(2026, 10, 9), "small_small", "GOLDPETAL", "GOLDTEN", date(2026, 10, 30))
    assert p["tick_floor_bps"] == pytest.approx(0.7287, abs=1e-4)
    assert p["cost_bps"] == pytest.approx(4.3824)


def test_no_signal_without_history(pairs):
    # Four sessions are fewer than min_periods, so every z-score is NaN.
    assert pairs["zscore"].isna().all()
    assert not pairs["signal"].any()


def test_signal_needs_zscore_as_well_as_gate(oct_bhav):
    p = build_pairs(oct_bhav, carry_series(oct_bhav), window=3, min_periods=3)
    last = p[p["date"] == date(2026, 10, 9)]
    assert last["zscore"].notna().any()
    assert (p["signal"] <= p["passes"]).all()
    assert (p.loc[p["signal"], "zscore"].abs() >= 2.0).all()


def test_no_carry_blocks_goldm_pairs_only(oct_bhav):
    no_curve = oct_bhav[oct_bhav["symbol"] != "GOLDM"]
    cs = carry_series(no_curve)
    p = build_pairs(no_curve, cs)
    assert set(p["kind"]) == {"small_small"}  # no eligible GOLDM to pair with
    assert p["spread_bps"].notna().all()
