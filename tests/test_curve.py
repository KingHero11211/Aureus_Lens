"""Carry from the GOLDM curve, on real October 2026 rows."""

import math
from datetime import date

import pandas as pd
import pytest

from src.aureus_lens.core.curve import adjust_to_expiry, carry_on, carry_series, eligible_goldm


def test_hand_checked_carry_9_oct(oct_bhav):
    # GOLDM 5 Nov 2026 close 150130, 4 Dec 2026 close 151460, 29 days apart:
    # ln(151460 / 150130) x 365 / 29 = 0.111010
    carry, near, far = carry_on(oct_bhav, date(2026, 10, 9))
    assert (near, far) == (date(2026, 11, 5), date(2026, 12, 4))
    assert carry == pytest.approx(0.111010, abs=1e-6)


def test_expiry_inside_buffer_excluded_5_oct(oct_bhav):
    # On 5 Oct the 5 Oct 2026 GOLDM contract still trades (151 lots) but
    # expires that day, so carry uses Nov and Dec:
    # ln(149315 / 148160) x 365 / 29 = 0.097737
    d = date(2026, 10, 5)
    traded = oct_bhav[(oct_bhav["date"] == d) & (oct_bhav["symbol"] == "GOLDM")]
    assert date(2026, 10, 5) in set(traded["expiry_date"])
    assert date(2026, 10, 5) not in set(eligible_goldm(oct_bhav, d)["expiry_date"])
    carry, near, _ = carry_on(oct_bhav, d)
    assert near == date(2026, 11, 5)
    assert carry == pytest.approx(0.097737, abs=1e-6)


def test_zero_volume_expiry_excluded(oct_bhav):
    # GOLDM 5 Apr 2027 has volume 0 on 9 Oct.
    assert date(2027, 4, 5) not in set(eligible_goldm(oct_bhav, date(2026, 10, 9))["expiry_date"])


def test_series_uses_no_later_data(oct_bhav):
    full = carry_series(oct_bhav).set_index("date")
    for d in sorted(oct_bhav["date"].unique()):
        upto = carry_series(oct_bhav[oct_bhav["date"] <= d]).set_index("date")
        assert upto.loc[d].equals(full.loc[d])


def test_series_all_empirical_for_october(oct_bhav):
    cs = carry_series(oct_bhav)
    assert list(cs["carry_source"]) == ["empirical"] * 4


def test_stale_when_curve_missing(oct_bhav):
    # Keep only one GOLDM expiry on 9 Oct: the 7 Oct value is reused.
    d = date(2026, 10, 9)
    drop = (oct_bhav["date"] == d) & (oct_bhav["symbol"] == "GOLDM") & (
        oct_bhav["expiry_date"] != date(2026, 11, 5))
    cs = carry_series(oct_bhav[~drop]).set_index("date")
    assert cs.loc[d, "carry_source"] == "stale"
    assert cs.loc[d, "carry_date"] == date(2026, 10, 7)
    assert cs.loc[d, "carry"] == cs.loc[date(2026, 10, 7), "carry"]


def test_none_without_any_curve(oct_bhav):
    cs = carry_series(oct_bhav[oct_bhav["symbol"] != "GOLDM"])
    assert set(cs["carry_source"]) == {"none"}
    assert cs["carry"].isna().all()


def test_adjust_to_expiry():
    assert adjust_to_expiry(15000.0, 0.1, 0) == 15000.0
    assert adjust_to_expiry(15000.0, 0.1, 365) == pytest.approx(15000.0 * math.e ** 0.1)
    assert adjust_to_expiry(15000.0, 0.1, -30) < 15000.0
    with pytest.raises(ValueError):
        adjust_to_expiry(-1.0, 0.1, 10)
