"""Unit tests for price normalization (PPG999).

Verifies hand-checked values from MCX specifications:
- GOLDM close 150,000 -> 15,060.30
- GOLDTEN close 150,600 -> 15,060.00
- GOLDGUINEA close 120,480 -> 15,060.00
- GOLDPETAL close 15,060 -> 15,060.00
"""

import pandas as pd
import pytest

from src.aureus_lens.core.normalize import normalize_ppg999


def test_hand_checked_goldm_normalization():
    """GOLDM close 150,000 -> 15,060.30 (quoted per 10g, 995 purity converted to 999)."""
    row = {"symbol": "GOLDM", "close": 150000.0}
    ppg = normalize_ppg999(row)
    # (150000 / 10) * (999 / 995) = 15060.3015...
    assert round(ppg, 2) == 15060.30
    assert ppg == pytest.approx(15060.30, abs=0.01)


def test_hand_checked_goldten_normalization():
    """GOLDTEN close 150,600 -> 15,060.00 (quoted per 10g, 999 purity)."""
    row = {"symbol": "GOLDTEN", "close": 150600.0}
    ppg = normalize_ppg999(row)
    assert round(ppg, 2) == 15060.00


def test_hand_checked_goldguinea_normalization():
    """GOLDGUINEA close 120,480 -> 15,060.00 (quoted per 8g, 999 purity)."""
    row = {"symbol": "GOLDGUINEA", "close": 120480.0}
    ppg = normalize_ppg999(row)
    assert round(ppg, 2) == 15060.00


def test_hand_checked_goldpetal_normalization():
    """GOLDPETAL close 15,060 -> 15,060.00 (quoted per 1g, 999 purity)."""
    row = {"symbol": "GOLDPETAL", "close": 15060.0}
    ppg = normalize_ppg999(row)
    assert round(ppg, 2) == 15060.00


def test_normalize_with_pandas_series():
    """Supports pandas Series and capitalized keys."""
    series = pd.Series({"Symbol": "GOLDM", "Close": 76340.0})
    ppg = normalize_ppg999(series)
    expected = (76340.0 / 10.0) * (999.0 / 995.0)
    assert ppg == pytest.approx(expected)


def test_normalize_with_custom_object():
    """Supports objects with symbol and close attributes."""
    class ContractQuote:
        def __init__(self, symbol: str, close: float):
            self.symbol = symbol
            self.close = close

    quote = ContractQuote("GOLDTEN", 76410.0)
    ppg = normalize_ppg999(quote)
    assert ppg == 7641.0


def test_normalize_space_padded_symbol():
    """Strips whitespace from symbol before normalizing."""
    row = {"symbol": "  GOLDPETAL  ", "close": 7685.0}
    ppg = normalize_ppg999(row)
    assert ppg == 7685.0


def test_normalize_unsupported_symbol_raises_value_error():
    """Rejects non-target symbols (e.g. 1kg GOLD, SILVER)."""
    row = {"symbol": "GOLD", "close": 7600000.0}
    with pytest.raises(ValueError) as exc:
        normalize_ppg999(row)
    assert "Unsupported contract symbol 'GOLD'" in str(exc.value)


def test_normalize_missing_fields_raises_value_error():
    """Missing symbol or close raises ValueError."""
    with pytest.raises(ValueError):
        normalize_ppg999({"close": 150000.0})

    with pytest.raises(ValueError):
        normalize_ppg999({"symbol": "GOLDM"})
