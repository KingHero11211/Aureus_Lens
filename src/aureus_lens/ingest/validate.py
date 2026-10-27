"""Data Validation and Cleaning for MCX Bhavcopy.

Aureus Lens - Contract-Native Relative-Value Engine for MCX Gold Futures.
Hack in Hills '26 - Problem Statement 03
"""

from datetime import date, datetime
import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd

from config import TARGET_SYMBOLS

logger = logging.getLogger(__name__)

# Data health audit list for capturing and inspecting rejected rows
data_health: List[Dict[str, Any]] = []

# Required raw fields for valid records
REQUIRED_RAW_FIELDS = [
    "InstrumentName",
    "Symbol",
    "ExpiryDate",
    "Date",
    "Open",
    "High",
    "Low",
    "Close",
    "PreviousClose",
    "Volume",
    "Value",
    "VolumeInThousands",
]


def get_data_health_log() -> List[Dict[str, Any]]:
    """Return the list of recorded rejected rows."""
    return data_health


def clear_data_health_log() -> None:
    """Clear recorded rejected rows."""
    data_health.clear()


def parse_volume_in_thousands(raw_val: Any) -> Tuple[float, str]:
    """Parse VolumeInThousands string into float quantity and unit string.

    Example:
        "191.191 GRMS " -> (191.191, "GRMS")
        "80.896 GRMS "  -> (80.896, "GRMS")
        "0.000"         -> (0.0, "")
    """
    if raw_val is None:
        return 0.0, ""

    val_str = str(raw_val).strip()
    if not val_str:
        return 0.0, ""

    match = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]+)?$", val_str)
    if match:
        qty = float(match.group(1))
        unit = (match.group(2) or "").strip()
        return qty, unit

    # Fallback if there are multiple parts separated by whitespace
    parts = val_str.split()
    try:
        qty = float(parts[0])
        unit = parts[1] if len(parts) > 1 else ""
        return qty, unit
    except (ValueError, IndexError):
        raise ValueError(
            f"Invalid VolumeInThousands format: '{raw_val}'. Expected numeric value and optional unit."
        )


def _extract_response_date_str(response: Union[Dict[str, Any], List[Any]]) -> Optional[str]:
    """Extract raw date string from MCX response payload."""
    if isinstance(response, dict):
        if "Date" in response and isinstance(response["Date"], str):
            return response["Date"].strip()
        if "TradeDate" in response and isinstance(response["TradeDate"], str):
            return response["TradeDate"].strip()

        # Check inside 'Data' or 'd' payload
        records = response.get("Data") or response.get("d")
        if isinstance(records, list) and len(records) > 0 and isinstance(records[0], dict):
            for key in ("Date", "TradeDate", "date"):
                if key in records[0] and isinstance(records[0][key], str):
                    return records[0][key].strip()

    elif isinstance(response, list) and len(response) > 0 and isinstance(response[0], dict):
        for key in ("Date", "TradeDate", "date"):
            if key in response[0] and isinstance(response[0][key], str):
                return response[0][key].strip()

    return None


def validate_response_date(requested: str, response: Union[Dict[str, Any], List[Any]]) -> bool:
    """Validate that the response represents the exact same calendar date as requested.

    Rules:
        - Requested date format is DD/MM/YYYY (e.g. "09/10/2026" is 9th Oct 2026).
        - Response date format from MCX is MM/DD/YYYY (e.g. "10/09/2026" is 9th Oct 2026).
        - Returns True ONLY if they represent the same calendar day.
        - Returns False if MCX returned a previous trading day (e.g. holiday or weekend fallback).
    """
    if not requested or not response:
        return False

    req_str = requested.strip()
    req_date: date

    # Parse requested date as DD/MM/YYYY (with ISO YYYY-MM-DD fallback support)
    try:
        if "/" in req_str:
            req_date = datetime.strptime(req_str, "%d/%m/%Y").date()
        elif "-" in req_str:
            req_date = datetime.strptime(req_str, "%Y-%m-%d").date()
        else:
            return False
    except ValueError:
        return False

    resp_date_str = _extract_response_date_str(response)
    if not resp_date_str:
        return False

    # Parse response date as MM/DD/YYYY
    try:
        resp_date = datetime.strptime(resp_date_str, "%m/%d/%Y").date()
    except ValueError:
        return False

    return req_date == resp_date


def clean_data(response: Union[Dict[str, Any], List[Any]]) -> pd.DataFrame:
    """Clean and validate MCX Bhavcopy response.

    Processing Steps:
        1. Extract record rows from response dict/list.
        2. Validate existence of required fields (raises ValueError on missing fields).
        3. Strip whitespace from all symbols.
        4. Filter for InstrumentName == "FUTCOM" AND symbol in TARGET_SYMBOLS.
        5. Log all rejected rows to `data_health` with specific audit reasons.
        6. Parse ExpiryDate (format: %d%b%Y, e.g. "30OCT2026").
        7. Parse VolumeInThousands string into volume_value and volume_unit.
        8. Parse Date as MM/DD/YYYY into date objects.
        9. Return structured DataFrame with exact specified columns:
           [date, symbol, expiry_date, open, high, low, close, previous_close,
            volume, value, oi, volume_value, volume_unit]
    """
    # 1. Extract raw records list
    raw_records: List[Dict[str, Any]] = []
    if isinstance(response, dict):
        data_field = response.get("Data")
        if data_field is None:
            data_field = response.get("d")

        if isinstance(data_field, list):
            raw_records = data_field
        elif isinstance(data_field, dict) and "Data" in data_field:
            raw_records = data_field["Data"]
        elif not any(k in response for k in ("Data", "d")):
            # Empty response or unexpected schema
            raw_records = []
    elif isinstance(response, list):
        raw_records = response
    else:
        raise ValueError(f"Invalid response type: {type(response)}. Expected dict or list.")

    output_columns = [
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

    if not raw_records:
        return pd.DataFrame(columns=output_columns)

    valid_rows: List[Dict[str, Any]] = []

    for idx, raw_row in enumerate(raw_records):
        if not isinstance(raw_row, dict):
            reason = f"Record at index {idx} is not a dictionary: {type(raw_row)}"
            data_health.append({"row": raw_row, "reason": reason})
            logger.warning(reason)
            continue

        # 2. Check for missing fields gracefully (fail with clear ValueError)
        for req_field in REQUIRED_RAW_FIELDS:
            if req_field not in raw_row or raw_row[req_field] is None:
                raise ValueError(
                    f"Missing required field '{req_field}' in MCX Bhavcopy record at index {idx}: {raw_row}"
                )

        # Also support OpenInterest / OI
        oi_val = raw_row.get("OpenInterest")
        if oi_val is None:
            oi_val = raw_row.get("OI")
        if oi_val is None:
            raise ValueError(
                f"Missing required field 'OpenInterest'/'OI' in record at index {idx}: {raw_row}"
            )

        instrument = str(raw_row["InstrumentName"]).strip()
        raw_symbol = str(raw_row["Symbol"]).strip()

        # 3. Filter: InstrumentName == "FUTCOM"
        if instrument != "FUTCOM":
            reason = f"Rejected non-futures instrument '{instrument}' (expected 'FUTCOM')"
            data_health.append({"row": raw_row, "reason": reason})
            logger.debug(reason)
            continue

        # 4. Filter: symbol in TARGET_SYMBOLS
        if raw_symbol not in TARGET_SYMBOLS:
            reason = f"Rejected symbol '{raw_symbol}': not in TARGET_SYMBOLS {sorted(TARGET_SYMBOLS)}"
            data_health.append({"row": raw_row, "reason": reason})
            logger.debug(reason)
            continue

        # 5. Parse fields
        # Date as MM/DD/YYYY
        raw_date_str = str(raw_row["Date"]).strip()
        try:
            parsed_date = datetime.strptime(raw_date_str, "%m/%d/%Y").date()
        except ValueError as err:
            raise ValueError(
                f"Failed to parse Date '{raw_date_str}' with format MM/DD/YYYY in record: {err}"
            )

        # ExpiryDate as %d%b%Y (e.g. 30OCT2026)
        raw_expiry_str = str(raw_row["ExpiryDate"]).strip().upper()
        try:
            parsed_expiry = datetime.strptime(raw_expiry_str, "%d%b%Y").date()
        except ValueError as err:
            raise ValueError(
                f"Failed to parse ExpiryDate '{raw_expiry_str}' with format %d%b%Y in record: {err}"
            )

        # VolumeInThousands: (volume_value, volume_unit)
        volume_val, volume_unit = parse_volume_in_thousands(raw_row["VolumeInThousands"])

        # Numeric conversions
        try:
            open_px = float(raw_row["Open"])
            high_px = float(raw_row["High"])
            low_px = float(raw_row["Low"])
            close_px = float(raw_row["Close"])
            prev_close_px = float(raw_row["PreviousClose"])
            volume_num = float(raw_row["Volume"])
            value_num = float(raw_row["Value"])
            oi_num = float(oi_val)
        except (ValueError, TypeError) as err:
            raise ValueError(f"Numeric conversion error in record {raw_row}: {err}")

        valid_rows.append({
            "date": parsed_date,
            "symbol": raw_symbol,
            "expiry_date": parsed_expiry,
            "open": open_px,
            "high": high_px,
            "low": low_px,
            "close": close_px,
            "previous_close": prev_close_px,
            "volume": volume_num,
            "value": value_num,
            "oi": oi_num,
            "volume_value": volume_val,
            "volume_unit": volume_unit,
        })

    df = pd.DataFrame(valid_rows, columns=output_columns)
    return df
