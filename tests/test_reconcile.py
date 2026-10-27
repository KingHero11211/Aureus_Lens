"""Tests for continuity, value checks, data notes and the load command."""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from config import RAW_DIR
from scripts.load_csv import main as load_main
from src.aureus_lens.ingest.csv_loader import load_csv
from src.aureus_lens.reconcile import (
    _weekdays_between,
    check_continuity,
    continuity_events,
    render_data_notes,
    value_check,
)
from src.aureus_lens.store.db import init_db, read_bhav, store_load

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_A = FIXTURES / "format_a_09102026_sample.csv"
SAMPLE_B = FIXTURES / "format_b_20260121_sample.csv"
FULL_FILES = sorted(RAW_DIR.glob("*.csv")) if RAW_DIR.exists() else []


def loaded(*paths):
    conn = init_db(":memory:")
    for p in paths:
        store_load(conn, load_csv(p))
    return conn


def adjacent_session_pairs():
    """Pairs of stored dates in data/raw/ with no weekday between them."""
    if not FULL_FILES:
        return []
    dates = sorted({d for p in FULL_FILES for d in load_csv(p).rows["date"]})
    return [(a, b) for a, b in zip(dates, dates[1:]) if _weekdays_between(a, b) == 0]


# Weekday counting (calendar arithmetic only)

@pytest.mark.parametrize("a, b, expected", [
    (date(2026, 10, 9), date(2026, 10, 12), 0),   # Fri -> Mon
    (date(2026, 10, 8), date(2026, 10, 9), 0),    # Thu -> Fri
    (date(2026, 10, 7), date(2026, 10, 9), 1),    # Wed -> Fri, Thu missing
    (date(2026, 1, 21), date(2026, 10, 9), 186),
])
def test_weekdays_between(a, b, expected):
    assert _weekdays_between(a, b) == expected


# Continuity

def test_first_session_rows_are_marked_first():
    cont = check_continuity(read_bhav(loaded(SAMPLE_B)))
    assert set(cont["status"]) == {"first"}
    assert continuity_events(cont).empty


def test_missing_weekdays_mark_rows_unchecked_not_gap():
    cont = check_continuity(read_bhav(loaded(SAMPLE_A, SAMPLE_B)))
    later = cont[cont["date"] == date(2026, 10, 9)]
    assert set(later["status"]) == {"unchecked"}
    assert later["detail"].str.contains("186 weekdays").all()
    events = continuity_events(cont)
    assert set(events["event"]) == {"continuity_unchecked"}
    assert len(events) == 6


def test_continuity_empty_store():
    assert check_continuity(read_bhav(init_db(":memory:"))).empty


@pytest.mark.skipif(not adjacent_session_pairs(),
                    reason="NOT RUN: no two adjacent trading sessions in data/raw/")
def test_continuity_on_adjacent_real_sessions():
    conn = loaded(*FULL_FILES)
    cont = check_continuity(read_bhav(conn))
    for _, b in adjacent_session_pairs():
        day = cont[cont["date"] == b]
        assert set(day["status"]) <= {"ok", "gap", "new"}
        # Report gaps rather than fail on them; they are data findings.
        print(b, day["status"].value_counts().to_dict())


# Value check

def test_sample_values_within_low_high_range():
    vc = value_check(read_bhav(loaded(SAMPLE_A, SAMPLE_B)))
    assert len(vc) == 10
    assert vc["in_range"].all()


@pytest.mark.skipif(not FULL_FILES, reason="NOT RUN: no files in data/raw/")
def test_full_file_values_within_low_high_range():
    vc = value_check(read_bhav(loaded(*FULL_FILES)))
    assert vc["in_range"].all(), vc[~vc["in_range"]]


# Data notes

def test_notes_are_deterministic_and_complete(tmp_path):
    conn = loaded(SAMPLE_A, SAMPLE_B)
    args = (read_bhav(conn), conn.execute("SELECT * FROM load_log").df(),
            conn.execute("SELECT * FROM reject_counts").df())
    cont = check_continuity(args[0])
    a, b = render_data_notes(*args, cont), render_data_notes(*args, cont)
    assert a == b
    for heading in ["## Files loaded", "## Rejected rows by reason", "## Sessions",
                    "## Value per symbol", "## Continuity"]:
        assert heading in a
    assert "Rows outside the low-high range: 0" in a


def test_notes_for_empty_store():
    conn = init_db(":memory:")
    notes = render_data_notes(read_bhav(conn), conn.execute("SELECT * FROM load_log").df(),
                              conn.execute("SELECT * FROM reject_counts").df(),
                              check_continuity(read_bhav(conn)))
    assert "No rows in the store." in notes


def test_notes_never_contain_unreconciled_mcx_figure(tmp_path):
    notes = tmp_path / "n.md"
    load_main([str(SAMPLE_A), str(SAMPLE_B), "--db", str(tmp_path / "s.duckdb"), "--notes", str(notes)])
    text = notes.read_text()
    assert "5,563" not in text and "5563" not in text


# Load command

def test_load_command_is_idempotent(tmp_path, capsys):
    db, n1, n2 = tmp_path / "s.duckdb", tmp_path / "n1.md", tmp_path / "n2.md"
    files = [str(SAMPLE_A), str(SAMPLE_B)]
    assert load_main(files + ["--db", str(db), "--notes", str(n1)]) == 0
    first = capsys.readouterr().out
    assert load_main(files + ["--db", str(db), "--notes", str(n2)]) == 0
    second = capsys.readouterr().out
    assert first.count("stored:  6 new rows") == 1 and "stored:  5 new rows" in first
    assert second.count("stored:  0 new rows") == 2
    assert n1.read_text() == n2.read_text()

    conn = init_db(db)
    assert conn.execute("SELECT COUNT(*) FROM bhav").fetchall()[0][0] == 11
    assert conn.execute("SELECT COUNT(*) FROM data_health").fetchall()[0][0] == 6
    conn.close()


def test_dry_run_writes_nothing(tmp_path):
    db = tmp_path / "s.duckdb"
    assert load_main([str(SAMPLE_A), "--db", str(db), "--dry-run"]) == 0
    assert not db.exists()


@pytest.mark.skipif(not FULL_FILES, reason="NOT RUN: no files in data/raw/")
def test_notes_show_small_contract_total_for_21012026(tmp_path):
    if not any("2101" in p.name or "20260121" in p.name for p in FULL_FILES):
        pytest.skip("NOT RUN: no 21 Jan 2026 file in data/raw/")
    notes = tmp_path / "n.md"
    load_main([str(p) for p in FULL_FILES] + ["--db", str(tmp_path / "s.duckdb"), "--notes", str(notes)])
    assert "| 2026-01-21 | 8239.66 |" in notes.read_text()


def test_file_named_for_another_date_is_refused(tmp_path, capsys):
    # The real 8 Oct download held 9 Oct rows. Reproduce with the 9 Oct sample.
    misnamed = tmp_path / "BhavCopyDateWise_08102026.csv"
    misnamed.write_bytes(SAMPLE_A.read_bytes())
    db, notes = tmp_path / "s.duckdb", tmp_path / "n.md"
    for _ in range(2):
        assert load_main([str(misnamed), "--db", str(db), "--notes", str(notes)]) == 1
    assert "file name says 2026-10-08, rows are dated 2026-10-09; not stored" in capsys.readouterr().out
    conn = init_db(db)
    assert conn.execute("SELECT COUNT(*) FROM bhav").fetchall()[0][0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM data_health WHERE event = 'file_refused'").fetchall()[0][0] == 1
    conn.close()
    assert "BhavCopyDateWise_08102026.csv: file name says" in notes.read_text()
