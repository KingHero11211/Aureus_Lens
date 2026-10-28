"""Tests for in-memory upload path and absence of market data in the repository."""

from datetime import date
import os
from pathlib import Path
import subprocess

import pandas as pd
from pandas.testing import assert_frame_equal
import pytest

from app import views
from config import PROJECT_ROOT
from src.aureus_lens.ingest.bhav_loader import load_csv
from src.aureus_lens.ingest.uploader import process_uploaded_files
from src.aureus_lens.reconcile import check_continuity, continuity_events
from src.aureus_lens.store.db import (
    init_db,
    read_bhav,
    replace_health_events,
    store_load,
)
from tests.conftest import OCT_DIR
from tests.fixtures_data import ensure_fixtures

ensure_fixtures()


@pytest.fixture(scope="module")
def oct_fixture_paths():
    return sorted(OCT_DIR.glob("*.csv"))


def test_upload_loads_fixtures_same_as_cli(oct_fixture_paths):
    # 1. In-memory upload path
    derived_upload, reports = process_uploaded_files(oct_fixture_paths)

    assert len(reports) == 4
    for r in reports:
        assert r.status == "Loaded"
        assert r.rows_kept == 24
        assert r.date_match == "Match"

    # 2. CLI loader path into in-memory store
    conn = init_db(":memory:")
    try:
        for p in oct_fixture_paths:
            res = load_csv(p)
            store_load(conn, res)
        bhav = read_bhav(conn)
        cont = check_continuity(bhav)
        replace_health_events(conn, "continuity", continuity_events(cont))
        derived_cli = views.derive(views.read_store(conn), origin="CLI loader")
    finally:
        conn.close()

    # Compare derived results
    assert_frame_equal(derived_upload.normalized, derived_cli.normalized)
    assert_frame_equal(derived_upload.pairs, derived_cli.pairs)
    assert_frame_equal(derived_upload.carry, derived_cli.carry)
    assert_frame_equal(derived_upload.continuity, derived_cli.continuity)
    assert_frame_equal(derived_upload.load_log, derived_cli.load_log)


def test_duplicate_files_refused_by_checksum(oct_fixture_paths):
    p = oct_fixture_paths[0]
    content = p.read_bytes()

    # Two files with identical content
    files = [
        (p.name, content),
        (f"copy_of_{p.name}", content),
    ]

    derived, reports = process_uploaded_files(files)
    assert len(reports) == 2
    assert reports[0].status == "Loaded"
    assert reports[0].rows_kept == 24
    assert reports[1].status == "Refused: duplicate file"
    assert reports[1].rows_kept == 0
    assert "Duplicate content matches" in reports[1].detail


def test_mismatched_filename_date_refused(oct_fixture_paths):
    p = oct_fixture_paths[-1]  # 09 Oct 2026 file
    content = p.read_bytes()

    # Intentionally misname file for 08 Oct 2026
    misnamed = ("BhavCopyDateWise_08102026.csv", content)

    derived, reports = process_uploaded_files([misnamed])
    assert len(reports) == 1
    assert reports[0].status == "Refused: date mismatch"
    assert reports[0].rows_kept == 0
    assert "Mismatch" in reports[0].date_match
    assert "not stored" in reports[0].detail


def test_nothing_written_to_disk_during_upload(oct_fixture_paths, tmp_path):
    data_dir = PROJECT_ROOT / "data"

    def dir_state(path: Path):
        if not path.exists():
            return {}
        return {p: p.stat().st_mtime for p in path.glob("**/*") if p.is_file()}

    before = dir_state(data_dir)

    # Process uploads
    derived, reports = process_uploaded_files(oct_fixture_paths)
    assert len(reports) == 4

    after = dir_state(data_dir)
    assert before == after, "Files in data/ changed during in-memory upload processing"


def test_no_market_data_files_in_repo():
    cmd = ["git", "ls-files"]
    res = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True, check=True)
    tracked_files = [line.strip() for line in res.stdout.splitlines() if line.strip()]

    # Fail on any tracked CSV, parquet or duckdb file
    bad_extensions = [f for f in tracked_files if f.lower().endswith((".csv", ".parquet", ".duckdb"))]
    assert bad_extensions == [], f"Found tracked market data files: {bad_extensions}"

    # Also confirm grep -iE 'csv|parquet|duckdb' returns nothing on tracked files
    pattern_matches = [
        f for f in tracked_files
        if any(token in f.lower() for token in ["csv", "parquet", "duckdb"])
    ]
    assert pattern_matches == [], f"Found files matching data patterns: {pattern_matches}"
