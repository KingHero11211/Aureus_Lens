"""Tests for the bhavcopy CSV loader.

Fixtures in tests/fixtures/ are rows copied unchanged from the source files.
Tests marked full_file need the complete downloads in data/raw/ and are
skipped (reported NOT RUN) when those files are absent.
"""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from config import RAW_DIR
from scripts.load_csv import main as load_csv_main
from src.aureus_lens.ingest.csv_loader import (
    FORMAT_COLUMNS,
    _to_schema,
    detect_format,
    load_csv,
)
from src.aureus_lens.reconcile import implied_value_lakhs

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_A = FIXTURES / "format_a_09102026_sample.csv"
SAMPLE_B = FIXTURES / "format_b_20260121_sample.csv"

FULL_A_0910 = RAW_DIR / "BhavCopyDateWise_09102026.csv"
FULL_A_2101 = RAW_DIR / "BhavCopyDateWise_21012026.csv"
FULL_B_2101 = RAW_DIR / "20260121_MCX.csv"


def needs(path: Path):
    return pytest.mark.skipif(not path.exists(), reason=f"NOT RUN: {path.name} not in data/raw/")


def source_row_count(path: Path) -> int:
    return len(pd.read_csv(path, dtype=str))


# Format detection

def test_detects_format_a():
    assert detect_format(list(pd.read_csv(SAMPLE_A, nrows=0).columns)) == "A"


def test_detects_format_b():
    assert detect_format(list(pd.read_csv(SAMPLE_B, nrows=0).columns)) == "B"


def test_unknown_header_names_missing_columns():
    header = [c for c in FORMAT_COLUMNS["A"] if c not in ("Close", "Value(Lacs)")]
    with pytest.raises(ValueError) as err:
        detect_format(header)
    assert "format A" in str(err.value)
    assert "Close" in str(err.value) and "Value(Lacs)" in str(err.value)


def test_unknown_header_raises_from_load_csv(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("foo,bar\n1,2\n")
    with pytest.raises(ValueError, match="missing columns"):
        load_csv(bad)


# Filtering and rejects

@pytest.mark.parametrize("path", [SAMPLE_A, SAMPLE_B])
def test_keeps_only_target_futures(path):
    result = load_csv(path)
    assert set(result.rows["symbol"]) == {"GOLDM", "GOLDTEN", "GOLDGUINEA", "GOLDPETAL"}


@pytest.mark.parametrize("path", [SAMPLE_A, SAMPLE_B])
def test_rejects_have_reasons(path):
    reasons = set(load_csv(path).rejects["reason"])
    assert reasons == {
        "instrument OPTFUT",
        "instrument FUTIDX",
        "instrument OPTIDX",
        "GOLD 1 kg contract excluded",
        "symbol not targeted",
    }


@pytest.mark.parametrize("path", [SAMPLE_A, SAMPLE_B])
def test_every_source_row_is_kept_or_rejected(path):
    result = load_csv(path)
    assert len(result.rows) + len(result.rejects) == source_row_count(path)


def test_reject_line_numbers_point_at_source(tmp_path):
    result = load_csv(SAMPLE_A)
    lines = SAMPLE_A.read_text().splitlines()
    gold = result.rejects.loc[result.rejects["reason"] == "GOLD 1 kg contract excluded"].iloc[0]
    assert '"GOLD         "' in lines[gold["line"] - 1]


def test_bad_number_in_target_row_is_rejected(tmp_path):
    # Copy of the real GOLDTEN row with Close blanked out.
    lines = SAMPLE_A.read_text().splitlines()
    row = next(l for l in lines if '"GOLDTEN      "' in l)
    fields = row.split('","')
    fields[9] = ""
    broken = tmp_path / "broken.csv"
    broken.write_text(lines[0] + "\n" + '","'.join(fields) + "\n")
    result = load_csv(broken)
    assert result.rows.empty
    assert list(result.rejects["reason"]) == ["missing or non-numeric close"]


# Field parsing

def test_space_padding_stripped():
    rows = load_csv(SAMPLE_A).rows
    assert "GOLDM" in set(rows["symbol"])
    assert rows["volume_unit"].eq("GRMS").all()


def test_format_a_values():
    rows = load_csv(SAMPLE_A).rows
    r = rows[(rows["symbol"] == "GOLDPETAL") & (rows["expiry_date"] == date(2026, 10, 30))].iloc[0]
    assert r["date"] == date(2026, 10, 9)
    assert r["close"] == 15101.0
    assert r["previous_close"] == 14930.0
    assert r["volume_lots"] == 191191
    assert r["volume_000s"] == 191.191
    assert r["value_lakhs"] == 28822.01
    assert r["oi_lots"] == 188357
    assert not r["zero_volume"]


def test_format_b_values():
    rows = load_csv(SAMPLE_B).rows
    r = rows[(rows["symbol"] == "GOLDM") & (rows["expiry_date"] == date(2026, 2, 5))].iloc[0]
    assert r["date"] == date(2026, 1, 21)
    assert r["open"] == 151400.0
    assert r["close"] == 153341.0
    assert r["volume_lots"] == 194833
    assert r["volume_000s"] == 19483.3
    assert r["value_lakhs"] == 3039553.36
    assert r["oi_lots"] == 42210


def test_format_a_blank_ohlc_is_nan_and_row_kept():
    rows = load_csv(SAMPLE_A).rows
    r = rows[(rows["symbol"] == "GOLDM") & (rows["expiry_date"] == date(2027, 4, 5))].iloc[0]
    assert r["zero_volume"]
    assert pd.isna(r["open"]) and pd.isna(r["high"]) and pd.isna(r["low"])
    assert r["close"] == 154999.0
    assert r["oi_lots"] == 4


def test_format_b_zero_ohlc_on_zero_volume_is_nan():
    # Format B writes 0 where format A leaves blanks. The only zero-volume
    # future in the sample is GOLD 1 kg, so check the mapping before filtering.
    raw = pd.read_csv(SAMPLE_B, dtype=str, keep_default_na=False)
    parsed = _to_schema(raw, "B")
    r = parsed[(parsed["symbol"] == "GOLD") & (parsed["instrument"] == "FUTCOM")].iloc[0]
    assert r["zero_volume"]
    assert pd.isna(r["open"]) and pd.isna(r["high"]) and pd.isna(r["low"])
    assert r["close"] == 188266.0


# Value reconciliation

def test_value_matches_lots_times_close_in_sample():
    rows = load_csv(SAMPLE_A).rows
    active = rows[~rows["zero_volume"]]
    rel = (active["value_lakhs"] / implied_value_lakhs(active) - 1).abs()
    assert (rel < 0.005).all(), rel.max()


@needs(FULL_A_0910)
def test_value_matches_lots_times_close_full_09102026():
    rows = load_csv(FULL_A_0910).rows
    active = rows[~rows["zero_volume"]]
    assert len(active) == 23
    rel = (active["value_lakhs"] / implied_value_lakhs(active) - 1).abs()
    assert (rel < 0.005).all(), rel.max()


@pytest.mark.parametrize("path", [
    pytest.param(FULL_A_2101, marks=needs(FULL_A_2101)),
    pytest.param(FULL_B_2101, marks=needs(FULL_B_2101)),
])
def test_small_contract_value_21012026(path):
    rows = load_csv(path).rows
    small = rows[rows["symbol"].isin(["GOLDTEN", "GOLDGUINEA", "GOLDPETAL"])]
    assert round(small["value_lakhs"].sum() / 100, 2) == 8239.66


@needs(FULL_A_2101)
@needs(FULL_B_2101)
def test_both_formats_agree_for_21012026():
    a = load_csv(FULL_A_2101).rows.sort_values(["symbol", "expiry_date"]).reset_index(drop=True)
    b = load_csv(FULL_B_2101).rows.sort_values(["symbol", "expiry_date"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)


# CLI

def test_cli_reports_both_samples(capsys):
    assert load_csv_main([str(SAMPLE_A), str(SAMPLE_B), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "format:  A" in out and "format:  B" in out
    assert "GOLD 1 kg contract excluded" in out


def test_cli_returns_error_on_unknown_header(tmp_path, capsys):
    bad = tmp_path / "bad.csv"
    bad.write_text("foo,bar\n1,2\n")
    assert load_csv_main([str(bad), "--dry-run"]) == 1
    assert "missing columns" in capsys.readouterr().out
