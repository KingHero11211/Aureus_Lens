"""Waterfall stages. The hand check uses 9 Oct 2026 GOLDTEN (30 Oct) vs
GOLDM (5 Nov): raw 21.9143, purity -18.2134, carry 0.0182 bps."""

import pytest

from src.aureus_lens.core.waterfall import compute_waterfall


def values(stages):
    return {s["stage"]: s for s in stages}


def test_stage_order():
    assert [s["stage"] for s in compute_waterfall(1, 2, 3, 0.1, 0.2)] == [
        "raw", "purity", "carry", "tick floor", "cost", "edge"]


def test_hand_checked_goldten_vs_goldm():
    st = values(compute_waterfall(21.9143, -18.2134, 0.0182, 0.13, 4.3824))
    assert st["purity"]["delta"] == pytest.approx(-40.1277)
    assert st["carry"]["delta"] == pytest.approx(18.2316)
    assert st["tick floor"]["delta"] == pytest.approx(-0.0182)  # tick uses up the gap
    assert st["cost"]["delta"] == 0.0
    assert st["edge"]["value"] == 0.0


def test_positive_gap_clears_friction():
    # GOLDPETAL vs GOLDTEN, 30 Oct expiry, 9 Oct: 36.6213 bps, no purity or carry step.
    st = values(compute_waterfall(36.6213, 36.6213, 36.6213, 0.7287, 4.3824))
    assert st["edge"]["value"] == pytest.approx(36.6213 - 0.7287 - 4.3824)


def test_negative_gap_keeps_sign():
    # GOLDGUINEA vs GOLDPETAL, 29 Jan 2027 expiry, 9 Oct: about -19.58 bps.
    st = values(compute_waterfall(-19.58, -19.58, -19.58, 0.73, 4.3824))
    assert st["tick floor"]["delta"] == pytest.approx(0.73)
    assert st["edge"]["value"] == pytest.approx(-19.58 + 0.73 + 4.3824)


@pytest.mark.parametrize("gap", [3.0, -3.0, 0.0])
def test_edge_floored_at_zero(gap):
    st = values(compute_waterfall(gap, gap, gap, 0.73, 4.3824))
    assert st["edge"]["value"] == 0.0


@pytest.mark.parametrize("args", [(21.9, -18.2, 0.02, 0.13, 4.38), (36.6, 36.6, 36.6, 0.73, 4.38),
                                  (-19.6, -19.6, -19.6, 0.73, 4.38), (3.0, 3.0, 3.0, 0.73, 4.38)])
def test_deltas_sum_to_edge_minus_raw(args):
    st = compute_waterfall(*args)
    assert sum(s["delta"] for s in st) == pytest.approx(st[-1]["value"] - st[0]["value"])
