"""Executability gate on real October 2026 rows."""

from datetime import date

from src.aureus_lens.core.gate import executability_gate
from tests.conftest import row


def test_liquid_pair_wide_spread_passes(oct_bhav):
    a = row(oct_bhav, "2026-10-09", "GOLDPETAL", "2026-10-30")
    b = row(oct_bhav, "2026-10-09", "GOLDTEN", "2026-10-30")
    assert executability_gate(a, b, spread_bps=36.62, cost_bps=4.38) == (True, [])


def test_returns_every_failing_reason(oct_bhav):
    # GOLDM 5 Oct 2026 on its expiry day, GOLDM 5 Apr 2027 with no trades on
    # 9 Oct, a spread below the hurdle and no carry: four reasons.
    expiring = row(oct_bhav, "2026-10-05", "GOLDM", "2026-10-05")
    idle = row(oct_bhav, "2026-10-09", "GOLDM", "2027-04-05")
    ok, reasons = executability_gate(expiring, idle, spread_bps=5.0, cost_bps=4.38,
                                     carry_source="none")
    assert not ok
    assert len(reasons) == 4
    assert "0 days to expiry" in reasons[0]
    assert "volume 0" in reasons[1]
    assert "carry" in reasons[2]
    assert "below 2 x cost" in reasons[3]


def test_petal_uses_its_own_five_day_buffer(oct_bhav):
    # Real 30 Oct GOLDPETAL row with the trade date moved to 26 Oct: 4 days
    # to expiry fails PETAL's 5-day buffer but would pass a 3-day one.
    petal = row(oct_bhav, "2026-10-09", "GOLDPETAL", "2026-10-30").copy()
    petal["date"] = date(2026, 10, 26)
    ten = row(oct_bhav, "2026-10-09", "GOLDTEN", "2026-10-30").copy()
    ten["date"] = date(2026, 10, 26)
    ok, reasons = executability_gate(petal, ten, spread_bps=36.62, cost_bps=4.38)
    assert not ok
    assert reasons == ["GOLDPETAL 2026-10-30: 4 days to expiry, inside 5-day tender buffer"]


def test_unchanged_close_and_oi_is_stale(oct_bhav):
    a = row(oct_bhav, "2026-10-09", "GOLDTEN", "2026-10-30").copy()
    a["close"] = a["previous_close"]
    b = row(oct_bhav, "2026-10-09", "GOLDPETAL", "2026-10-30")
    ok, reasons = executability_gate(a, b, 36.62, 4.38, prev_oi_a=a["oi_lots"])
    assert not ok and "unchanged" in reasons[0]


def test_missing_spread_fails(oct_bhav):
    a = row(oct_bhav, "2026-10-09", "GOLDPETAL", "2026-10-30")
    b = row(oct_bhav, "2026-10-09", "GOLDTEN", "2026-10-30")
    assert executability_gate(a, b, float("nan"), 4.38) == (False, ["spread not available"])
