"""Tests for the DuckDB store, using the real fixture files."""

from datetime import date
from pathlib import Path

import pytest

from src.aureus_lens.ingest.bhav_loader import load_csv
from src.aureus_lens.store.db import BHAV_COLUMNS, init_db, read_bhav, store_load

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_A = FIXTURES / "format_a_09102026_sample.csv"
SAMPLE_B = FIXTURES / "format_b_20260121_sample.csv"


@pytest.fixture
def conn():
    c = init_db(":memory:")
    yield c
    c.close()


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchall()[0][0]


def test_tables_and_view_exist(conn):
    names = {r[0] for r in conn.execute(
        "SELECT table_name FROM information_schema.tables").fetchall()}
    assert {"bhav", "load_log", "reject_counts", "data_health", "contract_listing"} <= names


def test_bhav_columns_match_loader_schema(conn):
    cols = [r[0] for r in conn.execute("DESCRIBE bhav").fetchall()]
    assert cols == BHAV_COLUMNS


def test_primary_key_is_date_symbol_expiry(conn):
    pk = conn.execute(
        "SELECT constraint_column_names FROM duckdb_constraints() "
        "WHERE table_name = 'bhav' AND constraint_type = 'PRIMARY KEY'"
    ).fetchall()[0][0]
    assert list(pk) == ["date", "symbol", "expiry_date"]


def test_store_load_writes_rows_and_records(conn):
    result = load_csv(SAMPLE_A)
    assert store_load(conn, result) == 6
    assert count(conn, "bhav") == 6
    log = conn.execute("SELECT format, first_date, rows_kept, rows_rejected FROM load_log").fetchall()
    assert log == [("A", date(2026, 10, 9), 6, 5)]
    assert count(conn, "reject_counts") == 5


def test_reload_is_idempotent(conn):
    result = load_csv(SAMPLE_A)
    store_load(conn, result)
    first = read_bhav(conn)
    assert store_load(conn, result) == 0
    assert count(conn, "bhav") == 6
    assert count(conn, "load_log") == 1
    assert count(conn, "reject_counts") == 5
    assert read_bhav(conn).equals(first)


def test_zero_volume_row_round_trips(conn):
    store_load(conn, load_csv(SAMPLE_A))
    row = conn.execute(
        "SELECT open, close, zero_volume FROM bhav "
        "WHERE symbol = 'GOLDM' AND expiry_date = DATE '2027-04-05'"
    ).fetchall()[0]
    assert row == (None, 154999.0, True)


def test_two_files_two_dates(conn):
    store_load(conn, load_csv(SAMPLE_A))
    store_load(conn, load_csv(SAMPLE_B))
    dates = [r[0] for r in conn.execute("SELECT DISTINCT date FROM bhav ORDER BY 1").fetchall()]
    assert dates == [date(2026, 1, 21), date(2026, 10, 9)]
    assert count(conn, "load_log") == 2


def test_contract_listing_view(conn):
    store_load(conn, load_csv(SAMPLE_A))
    rows = conn.execute(
        "SELECT symbol, expiry_date, sessions FROM contract_listing ORDER BY 1, 2").fetchall()
    assert ("GOLDM", date(2026, 11, 5), 1) in rows
    assert len(rows) == 6
