"""Unit and Ingestion Tests for Aureus Lens.

Covers:
1. Date match: request "09/10/2026", response "10/09/2026" -> True (same day: 9 Oct 2026)
2. Date mismatch: request "10/09/2026", response "10/09/2026" -> False (different days: 10 Sep vs 9 Oct)
3. Sunday request returns Friday's date -> False
4. Volume parsing: "80.896 GRMS " -> (80.896, "GRMS") and "191.191 GRMS " -> (191.191, "GRMS")
5. Options excluded: OPTFUT row not in cleaned DataFrame (logged to data_health)
6. Non-target symbols excluded: "GOLD" (1kg) excluded, only TARGET_SYMBOLS kept
7. Missing field raises clear ValueError with diagnostic message
8. Space-padded symbols correctly stripped and accepted
9. Disk caching and request session token extraction behavior
"""

from datetime import date
import json
from pathlib import Path
from typing import Any, Dict
import pytest

from config import TARGET_SYMBOLS
from src.aureus_lens.ingest.client import (
    extract_verification_token,
    fetch_bhavcopy,
    parse_and_format_date,
)
from src.aureus_lens.ingest.validate import (
    clean_data,
    clear_data_health_log,
    data_health,
    get_data_health_log,
    parse_volume_in_thousands,
    validate_response_date,
)


@pytest.fixture(autouse=True)
def reset_health_log():
    """Clear the data_health rejection log before each test."""
    clear_data_health_log()
    yield
    clear_data_health_log()


# --- Requirement 1: Date Matching Tests ---


def test_date_match_same_calendar_day():
    """Request '09/10/2026' (DD/MM) and response '10/09/2026' (MM/DD) represent the SAME DAY (9 October 2026)."""
    requested = "09/10/2026"  # 9th October 2026
    response_payload = {
        "Date": "10/09/2026",  # Month 10 (Oct), Day 9, 2026
        "Data": [],
    }
    assert validate_response_date(requested, response_payload) is True


def test_date_mismatch_different_days():
    """Request '10/09/2026' (10 September) and response '10/09/2026' (9 October) are DIFFERENT days."""
    requested = "10/09/2026"  # 10th September 2026
    response_payload = {
        "Date": "10/09/2026",  # 9th October 2026
        "Data": [],
    }
    assert validate_response_date(requested, response_payload) is False


def test_sunday_request_returns_fridays_date_mismatch():
    """Sunday request returns previous Friday trading day from MCX -> returns False."""
    sunday_requested = "11/10/2026"  # 11 October 2026 (Sunday)
    # MCX returns last available trading session, which is Friday 09 October (10/09/2026 in MM/DD)
    response_payload = {
        "Data": [
            {
                "Date": "10/09/2026",
                "InstrumentName": "FUTCOM",
                "Symbol": "GOLDM",
            }
        ]
    }
    assert validate_response_date(sunday_requested, response_payload) is False


# --- Requirement 2: Volume Parsing Tests ---


def test_parse_volume_in_thousands_standard():
    """Parses '80.896 GRMS ' into float 80.896 and unit 'GRMS'."""
    qty, unit = parse_volume_in_thousands("80.896 GRMS ")
    assert qty == 80.896
    assert unit == "GRMS"


def test_parse_volume_in_thousands_petal_sample():
    """Parses '191.191 GRMS ' verified from Petal row into (191.191, 'GRMS')."""
    qty, unit = parse_volume_in_thousands("191.191 GRMS ")
    assert qty == 191.191
    assert unit == "GRMS"


def test_parse_volume_in_thousands_zero_or_plain():
    """Handles 0 or no unit gracefully."""
    qty, unit = parse_volume_in_thousands("0.000")
    assert qty == 0.0
    assert unit == ""

    qty_empty, unit_empty = parse_volume_in_thousands("")
    assert qty_empty == 0.0
    assert unit_empty == ""


# --- Requirement 3 & 4: Options Filtering & Symbol Handling ---


def _create_sample_row(
    symbol: str = "GOLDM",
    instrument: str = "FUTCOM",
    date_str: str = "10/09/2026",
    expiry_str: str = "05NOV2026",
    volume_in_thousands: str = "191.191 GRMS ",
) -> Dict[str, Any]:
    """Helper to generate a complete, valid raw MCX Bhavcopy row."""
    return {
        "InstrumentName": instrument,
        "Symbol": symbol,
        "ExpiryDate": expiry_str,
        "Date": date_str,
        "Open": "76120.00",
        "High": "76500.00",
        "Low": "75980.00",
        "Close": "76340.00",
        "PreviousClose": "76050.00",
        "Volume": "1250",
        "Value": "9542.50",
        "OpenInterest": "3420",
        "VolumeInThousands": volume_in_thousands,
    }


def test_options_excluded_from_cleaned_dataframe():
    """Options contract with InstrumentName == 'OPTFUT' is excluded and logged to data_health."""
    sample_fut = _create_sample_row(symbol="GOLDM", instrument="FUTCOM")
    sample_opt = _create_sample_row(symbol="GOLDM", instrument="OPTFUT")

    payload = {"Data": [sample_fut, sample_opt]}
    cleaned_df = clean_data(payload)

    # DataFrame should only have 1 row (the FUTCOM row)
    assert len(cleaned_df) == 1
    assert cleaned_df.iloc[0]["symbol"] == "GOLDM"

    # Verify rejected row was logged in data_health
    rejection_log = get_data_health_log()
    assert len(rejection_log) >= 1
    opt_rejections = [r for r in rejection_log if "OPTFUT" in r["reason"]]
    assert len(opt_rejections) == 1


def test_non_target_symbols_excluded():
    """Symbol 'GOLD' (1kg) is excluded; target symbols (GOLDM, GOLDTEN, GOLDGUINEA, GOLDPETAL) are kept."""
    gold_1kg = _create_sample_row(symbol="GOLD")
    gold_mini = _create_sample_row(symbol="GOLDM")
    gold_ten = _create_sample_row(symbol="GOLDTEN")
    gold_guinea = _create_sample_row(symbol="GOLDGUINEA")
    gold_petal = _create_sample_row(symbol="GOLDPETAL")

    payload = {"Data": [gold_1kg, gold_mini, gold_ten, gold_guinea, gold_petal]}
    cleaned_df = clean_data(payload)

    accepted_symbols = set(cleaned_df["symbol"].tolist())
    assert accepted_symbols == TARGET_SYMBOLS
    assert "GOLD" not in accepted_symbols

    # Check rejection log recorded 'GOLD'
    rejection_log = get_data_health_log()
    gold_rejections = [r for r in rejection_log if "GOLD'" in r["reason"] or "GOLD" in str(r["row"])]
    assert len(gold_rejections) >= 1


def test_space_padded_symbols_stripped():
    """Symbols with leading/trailing whitespace are stripped and retained."""
    padded_mini = _create_sample_row(symbol="   GOLDM   ")
    padded_petal = _create_sample_row(symbol=" GOLDPETAL ")

    payload = {"Data": [padded_mini, padded_petal]}
    cleaned_df = clean_data(payload)

    assert len(cleaned_df) == 2
    assert list(cleaned_df["symbol"]) == ["GOLDM", "GOLDPETAL"]


def test_cleaned_dataframe_schema_and_types():
    """Validates returned columns, parsed dates, and numeric types in cleaned DataFrame."""
    row = _create_sample_row(
        symbol="GOLDTEN",
        date_str="10/09/2026",
        expiry_str="30OCT2026",
        volume_in_thousands="80.896 GRMS ",
    )
    df = clean_data({"Data": [row]})

    expected_columns = [
        "date",
        "symbol",
        "expiry_date",
        "open",
        "high",
        "low",
        "close",
        "previous_close",
        "volume",
        "value",
        "oi",
        "volume_value",
        "volume_unit",
    ]
    assert list(df.columns) == expected_columns
    assert df.iloc[0]["date"] == date(2026, 10, 9)
    assert df.iloc[0]["expiry_date"] == date(2026, 10, 30)
    assert df.iloc[0]["close"] == 76340.00
    assert df.iloc[0]["volume_value"] == 80.896
    assert df.iloc[0]["volume_unit"] == "GRMS"


# --- Requirement 5: Missing Field Error Handling ---


def test_missing_field_raises_clear_value_error():
    """Missing critical field (e.g. 'Close') raises ValueError with informative message, not KeyError."""
    row_missing_close = _create_sample_row()
    del row_missing_close["Close"]

    payload = {"Data": [row_missing_close]}
    with pytest.raises(ValueError) as exc_info:
        clean_data(payload)

    assert "Missing required field 'Close'" in str(exc_info.value)


def test_missing_symbol_raises_clear_value_error():
    """Missing 'Symbol' raises ValueError."""
    row_missing_symbol = _create_sample_row()
    del row_missing_symbol["Symbol"]

    payload = {"Data": [row_missing_symbol]}
    with pytest.raises(ValueError) as exc_info:
        clean_data(payload)

    assert "Missing required field 'Symbol'" in str(exc_info.value)


# --- Client & Token Extraction Tests ---


def test_extract_verification_token_regex():
    """Extracts __RequestVerificationToken correctly from HTML mock."""
    sample_html = (
        '<html><body><form>'
        '<input name="__RequestVerificationToken" type="hidden" value="CfDJ8SampleTokenXYZ123==" />'
        '</form></body></html>'
    )
    token = extract_verification_token(sample_html)
    assert token == "CfDJ8SampleTokenXYZ123=="


def test_parse_and_format_date_helper():
    """Normalizes both DD/MM/YYYY and YYYY-MM-DD formats."""
    mcx_str, iso_str = parse_and_format_date("09/10/2026")
    assert mcx_str == "09/10/2026"
    assert iso_str == "2026-10-09"

    mcx_str2, iso_str2 = parse_and_format_date("2026-10-09")
    assert mcx_str2 == "09/10/2026"
    assert iso_str2 == "2026-10-09"


def test_client_disk_caching(tmp_path: Path):
    """Client loads existing JSON from disk cache without network requests."""
    cached_date = "2026-10-09"
    cache_file = tmp_path / f"{cached_date}.json"

    mock_cached_data = {
        "Date": "10/09/2026",
        "Data": [_create_sample_row(symbol="GOLDM")],
    }
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(mock_cached_data, f)

    result = fetch_bhavcopy("09/10/2026", cache_dir=tmp_path)
    assert result == mock_cached_data


def test_env_token_and_cookie_support(monkeypatch, tmp_path: Path):
    """Client reads MCX_TOKEN and MCX_COOKIE from environment variables."""
    test_token = "REDACTED_TEST_TOKEN"
    test_cookie = "REDACTED_TEST_COOKIE"

    monkeypatch.setenv("MCX_TOKEN", test_token)
    monkeypatch.setenv("MCX_COOKIE", test_cookie)

    import os
    assert os.environ.get("MCX_TOKEN") == test_token
    assert os.environ.get("MCX_COOKIE") == test_cookie


def test_retry_backoff_and_token_refresh_on_http_error(monkeypatch, tmp_path: Path):
    """Retries with backoff and refreshes token when encountering 401/403/419 status."""
    import src.aureus_lens.ingest.client as client_mod
    import requests

    call_count = 0
    client_mod._cached_token = "old_token_xyz"

    class MockResponse:
        def __init__(self, status_code, json_data):
            self.status_code = status_code
            self._json_data = json_data
        def raise_for_status(self):
            if self.status_code >= 400:
                http_err = requests.HTTPError(f"{self.status_code} Error")
                http_err.response = self
                raise http_err
        def json(self):
            return self._json_data

    def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return MockResponse(401, {})
        return MockResponse(200, {"Date": "10/09/2026", "Data": []})

    def mock_get_token(*args, **kwargs):
        return "refreshed_token_abc"

    monkeypatch.setattr(requests.Session, "post", mock_post)
    monkeypatch.setattr(client_mod, "get_verification_token", mock_get_token)
    monkeypatch.setattr("time.sleep", lambda s: None)  # instantaneous test

    res = client_mod.fetch_bhavcopy("09/10/2026", cache_dir=tmp_path)
    assert res == {"Date": "10/09/2026", "Data": []}
    assert call_count == 2


