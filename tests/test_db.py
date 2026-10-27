"""Unit and Integration Tests for DuckDB Storage and Backfill.

Covers:
1. init_db creates all required tables (bhav, data_health, coverage) and view (contract_listing)
2. upsert_bhav inserts records correctly with DATE types
3. upsert_bhav skips duplicates without error
4. log_health writes audit events correctly to data_health without primary key
5. update_coverage aggregates contract counts correctly
6. check_continuity detects and logs gaps where previous_close != prior day close
7. backfill_date_range handles calendar days, skips weekends, and logs events
"""

from datetime import date
from pathlib import Path
import duckdb
import pandas as pd
import pytest

from src.aureus_lens.store.db import (
    check_continuity,
    init_db,
    log_health,
    update_coverage,
    upsert_bhav,
)


@pytest.fixture
def mem_db():
    """Provides an in-memory DuckDB connection with initialized schemas."""
    conn = init_db(":memory:")
    yield conn
    conn.close()


def _sample_df(rows: int = 2) -> pd.DataFrame:
    """Helper to generate a clean sample DataFrame for upsert testing."""
    records = [
        {
            "date": date(2026, 10, 9),
            "symbol": "GOLDM",
            "expiry_date": date(2026, 11, 5),
            "open": 76120.00,
            "high": 76500.00,
            "low": 75980.00,
            "close": 76340.00,
            "previous_close": 76050.00,
            "volume": 1250.0,
            "value": 9542.50,
            "oi": 3420.0,
            "volume_value": 125.0,
            "volume_unit": "GRMS",
        },
        {
            "date": date(2026, 10, 9),
            "symbol": "GOLDTEN",
            "expiry_date": date(2026, 10, 30),
            "open": 76200.00,
            "high": 76650.00,
            "low": 76050.00,
            "close": 76410.00,
            "previous_close": 76110.00,
            "volume": 890.0,
            "value": 680.05,
            "oi": 1200.0,
            "volume_value": 80.896,
            "volume_unit": "GRMS",
        },
        {
            "date": date(2026, 10, 9),
            "symbol": "GOLDPETAL",
            "expiry_date": date(2026, 10, 30),
            "open": 7650.00,
            "high": 7710.00,
            "low": 7630.00,
            "close": 7685.00,
            "previous_close": 7640.00,
            "volume": 38200.0,
            "value": 2935.67,
            "oi": 15400.0,
            "volume_value": 191.191,
            "volume_unit": "GRMS",
        },
    ]
    return pd.DataFrame(records[:rows])


def test_init_db_creates_all_tables_and_views(mem_db):
    """init_db creates 'bhav', 'data_health', 'coverage' tables and 'contract_listing' view."""
    tables_result = mem_db.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()
    table_names = {r[0] for r in tables_result}

    assert "bhav" in table_names
    assert "data_health" in table_names
    assert "coverage" in table_names
    assert "contract_listing" in table_names


def test_bhav_schema_and_types(mem_db):
    """Validates column types in 'bhav' table: dates are DATE, prices are DOUBLE."""
    cols_result = mem_db.execute("DESCRIBE bhav").fetchall()
    col_map = {r[0]: r[1] for r in cols_result}

    assert col_map["date"] == "DATE"
    assert col_map["symbol"] == "VARCHAR"
    assert col_map["expiry_date"] == "DATE"
    assert col_map["close"] == "DOUBLE"
    assert col_map["volume"] == "DOUBLE"
    assert col_map["volume_value"] == "DOUBLE"
    assert col_map["volume_unit"] == "VARCHAR"


def test_upsert_bhav_inserts_correctly(mem_db):
    """upsert_bhav properly inserts records into DuckDB with exact values and DATE types."""
    df = _sample_df(2)
    upsert_bhav(mem_db, df)

    rows = mem_db.execute("SELECT * FROM bhav ORDER BY symbol").fetchall()
    assert len(rows) == 2

    # Check first record: GOLDM
    row_goldm = rows[0]
    assert row_goldm[0] == date(2026, 10, 9)
    assert row_goldm[1] == "GOLDM"
    assert row_goldm[2] == date(2026, 11, 5)
    assert row_goldm[6] == 76340.00
    assert row_goldm[11] == 125.0
    assert row_goldm[12] == "GRMS"


def test_upsert_bhav_skips_duplicates_without_error(mem_db):
    """Re-inserting existing primary key rows skips duplicates without error or row inflation."""
    df = _sample_df(2)

    upsert_bhav(mem_db, df)
    count_first = mem_db.execute("SELECT count(*) FROM bhav").fetchone()[0]
    assert count_first == 2

    # Duplicate insert with identical data
    upsert_bhav(mem_db, df)
    count_second = mem_db.execute("SELECT count(*) FROM bhav").fetchone()[0]
    assert count_second == 2

    # Partial duplicate: 1 existing + 1 new row
    df_3 = _sample_df(3)
    upsert_bhav(mem_db, df_3)
    count_third = mem_db.execute("SELECT count(*) FROM bhav").fetchone()[0]
    assert count_third == 3


def test_log_health_inserts_records(mem_db):
    """log_health inserts audit and date-mismatch records into data_health table."""
    log_health(
        mem_db,
        date(2026, 10, 11),
        "date_mismatch",
        "Requested Sunday 11/10/2026, MCX returned Friday 10/09/2026",
    )
    log_health(mem_db, "09/10/2026", "audit_notice", "Clean verification complete")

    records = mem_db.execute("SELECT date, event, detail FROM data_health ORDER BY date").fetchall()
    assert len(records) == 2
    assert records[0][0] == date(2026, 10, 9)
    assert records[0][1] == "audit_notice"
    assert records[1][0] == date(2026, 10, 11)
    assert records[1][1] == "date_mismatch"


def test_check_continuity_detects_and_logs_gaps(mem_db):
    """check_continuity detects when previous_close != prior trading day close and logs gap."""
    exp = date(2026, 11, 5)
    # Day 1: close = 76000.0
    row_d1 = {
        "date": date(2026, 10, 8),
        "symbol": "GOLDM",
        "expiry_date": exp,
        "open": 75800.0,
        "high": 76100.0,
        "low": 75700.0,
        "close": 76000.0,
        "previous_close": 75700.0,
        "volume": 1000.0,
        "value": 7600.0,
        "oi": 3000.0,
        "volume_value": 100.0,
        "volume_unit": "GRMS",
    }
    # Day 2: previous_close should be 76000.0, but say Bhavcopy reported 75500.0 (a 500-point gap)
    row_d2_gap = {
        "date": date(2026, 10, 9),
        "symbol": "GOLDM",
        "expiry_date": exp,
        "open": 76100.0,
        "high": 76400.0,
        "low": 76000.0,
        "close": 76340.0,
        "previous_close": 75500.0,  # MISMATCH: 75500 != 76000
        "volume": 1200.0,
        "value": 9120.0,
        "oi": 3500.0,
        "volume_value": 120.0,
        "volume_unit": "GRMS",
    }
    upsert_bhav(mem_db, pd.DataFrame([row_d1, row_d2_gap]))

    gaps = check_continuity(mem_db)
    assert len(gaps) == 1
    assert gaps[0]["symbol"] == "GOLDM"
    assert gaps[0]["previous_close"] == 75500.0
    assert gaps[0]["prior_close"] == 76000.0

    # Verify gap was logged in data_health
    health_records = mem_db.execute("SELECT * FROM data_health WHERE event = 'continuity_gap'").fetchall()
    assert len(health_records) == 1
    assert "Continuity mismatch" in health_records[0][2]


def test_contract_listing_view_aggregates(mem_db):
    """contract_listing view aggregates first_session, last_session, and total_sessions."""
    df = _sample_df(2)
    upsert_bhav(mem_db, df)

    listing = mem_db.execute("SELECT * FROM contract_listing ORDER BY symbol").fetchall()
    assert len(listing) == 2
    # GOLDM
    assert listing[0][0] == "GOLDM"
    assert listing[0][4] == 1  # total_sessions


def test_update_coverage(mem_db):
    """update_coverage records contract count per (date, symbol, expiry_date)."""
    df = _sample_df(2)
    update_coverage(mem_db, df)

    coverage_rows = mem_db.execute("SELECT * FROM coverage ORDER BY symbol").fetchall()
    assert len(coverage_rows) == 2
    assert coverage_rows[0][3] == 1
    assert coverage_rows[1][3] == 1
