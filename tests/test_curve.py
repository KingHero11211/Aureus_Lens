"""Unit tests for curve analysis, empirical carry, expiry adjustment, and RV spread.

Aureus Lens - Phase 3 & Audit Tests
"""

from datetime import date, timedelta
import math
import duckdb
import pandas as pd
import pytest

from src.aureus_lens.core.curve import adjust_to_expiry, compute_carry
from src.aureus_lens.core.spread import compute_spread_bps
from src.aureus_lens.store.db import BHAV_COLUMNS, init_db

# TODO(step 3): the prices below are invented; replace with real GOLDM rows.
_RENAME = {"volume": "volume_lots", "value": "value_lakhs", "oi": "oi_lots",
           "volume_value": "volume_000s"}


def upsert_bhav(conn, df):
    df = df.rename(columns=_RENAME).assign(zero_volume=False, source_file="test")
    conn.register("incoming", df[BHAV_COLUMNS])
    conn.execute("INSERT OR REPLACE INTO bhav SELECT * FROM incoming")
    conn.unregister("incoming")


@pytest.fixture
def test_db():
    """Initializes in-memory database with test quotes."""
    conn = init_db(":memory:")
    yield conn
    conn.close()


def test_compute_carry_empirical_two_expiries(test_db):
    """Computes empirical annual carry from two liquid GOLDM expiries on the same date."""
    trade_date = date(2026, 10, 9)
    e1_expiry = date(2026, 11, 5)
    e2_expiry = date(2026, 12, 5)

    quotes = [
        {
            "date": trade_date,
            "symbol": "GOLDM",
            "expiry_date": e1_expiry,
            "open": 76000.0,
            "high": 76500.0,
            "low": 75900.0,
            "close": 76000.0,
            "previous_close": 75800.0,
            "volume": 1200.0,
            "value": 9120.0,
            "oi": 3500.0,
            "volume_value": 120.0,
            "volume_unit": "GRMS",
        },
        {
            "date": trade_date,
            "symbol": "GOLDM",
            "expiry_date": e2_expiry,
            "open": 76400.0,
            "high": 76800.0,
            "low": 76300.0,
            "close": 76450.0,
            "previous_close": 76200.0,
            "volume": 850.0,
            "value": 6498.0,
            "oi": 2100.0,
            "volume_value": 85.0,
            "volume_unit": "GRMS",
        },
    ]
    upsert_bhav(test_db, pd.DataFrame(quotes))

    carry, mode = compute_carry(test_db, trade_date)
    assert mode == "empirical"
    assert carry is not None

    days = (e2_expiry - e1_expiry).days
    expected_carry = math.log(76450.0 / 76000.0) / (days / 365.0)
    assert carry == pytest.approx(expected_carry, rel=1e-5)


def test_compute_carry_excludes_expiry_inside_tender_buffer(test_db):
    """A GOLDM expiry inside its tender buffer is excluded from carry estimation."""
    trade_date = date(2026, 11, 3)
    # E1 is Nov 5 (only 2 days away <= 3 days tender buffer) -> MUST BE EXCLUDED
    e1_tender = date(2026, 11, 5)
    e2_eligible = date(2026, 12, 5)

    quotes = [
        {
            "date": trade_date,
            "symbol": "GOLDM",
            "expiry_date": e1_tender,
            "open": 76000.0,
            "high": 76500.0,
            "low": 75900.0,
            "close": 76000.0,
            "previous_close": 75800.0,
            "volume": 1200.0,
            "value": 9120.0,
            "oi": 3500.0,
            "volume_value": 120.0,
            "volume_unit": "GRMS",
        },
        {
            "date": trade_date,
            "symbol": "GOLDM",
            "expiry_date": e2_eligible,
            "open": 76400.0,
            "high": 76800.0,
            "low": 76300.0,
            "close": 76450.0,
            "previous_close": 76200.0,
            "volume": 850.0,
            "value": 6498.0,
            "oi": 2100.0,
            "volume_value": 85.0,
            "volume_unit": "GRMS",
        },
    ]
    upsert_bhav(test_db, pd.DataFrame(quotes))

    # Since E1 is inside tender, only 1 eligible contract remains -> returns (None, 'none')
    carry, mode = compute_carry(test_db, trade_date)
    assert carry is None
    assert mode == "none"


def test_compute_carry_future_price_change_does_not_alter_past_carry(test_db):
    """Confirm zero look-ahead: altering future price data does not change prior carry."""
    t1 = date(2026, 10, 9)
    t2 = date(2026, 10, 10)
    e1 = date(2026, 11, 5)
    e2 = date(2026, 12, 5)

    # Day 1 quotes
    d1_quotes = [
        {"date": t1, "symbol": "GOLDM", "expiry_date": e1, "open": 76000.0, "high": 76500.0, "low": 75900.0, "close": 76000.0, "previous_close": 75800.0, "volume": 1000.0, "value": 7600.0, "oi": 3000.0, "volume_value": 100.0, "volume_unit": "GRMS"},
        {"date": t1, "symbol": "GOLDM", "expiry_date": e2, "open": 76400.0, "high": 76800.0, "low": 76300.0, "close": 76450.0, "previous_close": 76200.0, "volume": 800.0, "value": 6116.0, "oi": 2000.0, "volume_value": 80.0, "volume_unit": "GRMS"},
    ]
    upsert_bhav(test_db, pd.DataFrame(d1_quotes))

    carry_before, mode_before = compute_carry(test_db, t1)

    # Insert massive shock on future date t2
    d2_quotes = [
        {"date": t2, "symbol": "GOLDM", "expiry_date": e1, "open": 99000.0, "high": 99500.0, "low": 98900.0, "close": 99000.0, "previous_close": 76000.0, "volume": 5000.0, "value": 49500.0, "oi": 9000.0, "volume_value": 500.0, "volume_unit": "GRMS"},
        {"date": t2, "symbol": "GOLDM", "expiry_date": e2, "open": 105000.0, "high": 106000.0, "low": 104000.0, "close": 105000.0, "previous_close": 76450.0, "volume": 4000.0, "value": 42000.0, "oi": 8000.0, "volume_value": 400.0, "volume_unit": "GRMS"},
    ]
    upsert_bhav(test_db, pd.DataFrame(d2_quotes))

    # Recalculate carry for t1 -> MUST BE STRICTLY UNCHANGED
    carry_after, mode_after = compute_carry(test_db, t1)
    assert carry_after == carry_before
    assert mode_after == mode_before


def test_adjust_to_expiry_positive_carry_later_date():
    """Later target date gives a higher adjusted price when carry is positive."""
    ppg = 15060.0
    carry = 0.065  # Positive carry
    days_diff = 30  # Later date (target > contract expiry)

    adj = adjust_to_expiry(ppg, carry, days_diff)
    assert adj > ppg
    assert adj == pytest.approx(ppg * math.exp(carry * (30 / 365.0)))


def test_compute_spread_bps_calculations():
    """Tests basis point relative-value calculation and error handling."""
    ppg_ref = 15060.0

    assert compute_spread_bps(15060.0, ppg_ref) == 0.0
    assert compute_spread_bps(ppg_ref * 1.01, ppg_ref) == pytest.approx(100.0)
    assert compute_spread_bps(ppg_ref * 0.995, ppg_ref) == pytest.approx(-50.0)

    with pytest.raises(ValueError):
        compute_spread_bps(15060.0, 0.0)
    with pytest.raises(ValueError):
        compute_spread_bps(15060.0, -100.0)
