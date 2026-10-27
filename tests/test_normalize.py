"""Normalization to rupees per gram of 999 gold."""

import pytest

from src.aureus_lens.core.normalize import add_ppg999, normalize_ppg999, per_gram
from tests.conftest import row


@pytest.mark.parametrize("symbol, close, expected", [
    ("GOLDM", 150000.0, 15060.30),     # 150000 / 10 x 999 / 995
    ("GOLDTEN", 150600.0, 15060.00),   # 150600 / 10
    ("GOLDGUINEA", 120480.0, 15060.00),  # 120480 / 8
    ("GOLDPETAL", 15060.0, 15060.00),  # 15060 / 1
])
def test_hand_checked_values(symbol, close, expected):
    assert round(normalize_ppg999({"symbol": symbol, "close": close}), 2) == expected


def test_real_rows_9_oct(oct_bhav):
    # Closes from BhavCopyDateWise_09102026.csv, 30 Oct 2026 expiry.
    assert normalize_ppg999(row(oct_bhav, "2026-10-09", "GOLDTEN", "2026-10-30")) == 15045.9
    assert normalize_ppg999(row(oct_bhav, "2026-10-09", "GOLDGUINEA", "2026-10-30")) == 15093.75
    assert normalize_ppg999(row(oct_bhav, "2026-10-09", "GOLDPETAL", "2026-10-30")) == 15101.0
    goldm = row(oct_bhav, "2026-10-09", "GOLDM", "2026-11-05")
    assert normalize_ppg999(goldm) == pytest.approx(150130 / 10 * 999 / 995)


def test_vectorized_matches_row_version(oct_bhav):
    expected = oct_bhav.apply(normalize_ppg999, axis=1)
    assert (add_ppg999(oct_bhav) - expected).abs().max() < 1e-9


def test_per_gram_ignores_purity():
    assert per_gram("GOLDM", 150130.0) == 15013.0


def test_padded_symbol_accepted():
    assert normalize_ppg999({"symbol": "GOLDPETAL   ", "close": 15101.0}) == 15101.0


@pytest.mark.parametrize("bad", [{"symbol": "GOLD", "close": 1.0}, {"close": 1.0}, {"symbol": "GOLDM"}])
def test_bad_rows_raise(bad):
    with pytest.raises(ValueError):
        normalize_ppg999(bad)
