"""CLI script to fetch, inspect, validate, and clean an MCX Bhavcopy day.

Usage:
    python -m scripts.fetch_day 09/10/2026
"""

from datetime import datetime
import sys
from typing import Any, Dict, List

from src.aureus_lens.ingest.client import fetch_bhavcopy, parse_and_format_date
from src.aureus_lens.ingest.validate import (
    _extract_response_date_str,
    clean_data,
    validate_response_date,
)


def run_fetch_day(date_arg: str) -> None:
    """Fetch MCX Bhavcopy, inspect all raw GOLD* symbols, and display cleaned summary."""
    print("=" * 70)
    print(f"Aureus Lens - Fetch & Inspect Bhavcopy for: {date_arg}")
    print("=" * 70)

    try:
        mcx_date_str, iso_date_str = parse_and_format_date(date_arg)
    except Exception as e:
        print(f"Error parsing date '{date_arg}': {e}")
        sys.exit(1)

    print(f"Request Date: {mcx_date_str} (ISO: {iso_date_str})")

    # 1. Fetch
    try:
        raw_response = fetch_bhavcopy(mcx_date_str)
    except Exception as exc:
        print(f"\n[ERROR] Failed to fetch Bhavcopy: {exc}")
        sys.exit(1)

    # 2. Extract raw records list
    raw_records: List[Dict[str, Any]] = []
    if isinstance(raw_response, dict):
        records = raw_response.get("Data") or raw_response.get("d")
        if isinstance(records, list):
            raw_records = records
    elif isinstance(raw_response, list):
        raw_records = raw_response

    print(f"Total raw records received: {len(raw_records)}")

    # 3. Specifically inspect all raw GOLD* symbols and InstrumentName
    print("\n" + "-" * 70)
    print("RAW GOLD* SYMBOLS FOUND IN BHAVCOPY (Auditing contract specifications):")
    print("-" * 70)

    gold_rows = []
    for row in raw_records:
        if isinstance(row, dict):
            sym = str(row.get("Symbol", "")).strip().upper()
            if "GOLD" in sym:
                inst = str(row.get("InstrumentName", "")).strip()
                expiry = str(row.get("ExpiryDate", "")).strip()
                close_px = row.get("Close", "N/A")
                vol = row.get("Volume", "N/A")
                gold_rows.append((inst, sym, expiry, close_px, vol))

    if gold_rows:
        for inst, sym, expiry, close_px, vol in gold_rows:
            print(
                f"  - Instrument: {inst:<8} | Symbol: {sym:<12} | "
                f"Expiry: {expiry:<10} | Close: {close_px} | Vol: {vol}"
            )

        # Check GOLDTEN confirmation
        goldten_futcom = [r for r in gold_rows if r[0] == "FUTCOM" and r[1] == "GOLDTEN"]
        if goldten_futcom:
            print(
                f"\n[CONFIRMED] GOLDTEN exists as FUTCOM ({len(goldten_futcom)} contract(s) found)."
            )
        else:
            print("\n[NOTE] GOLDTEN with InstrumentName == 'FUTCOM' was not found in this session.")
    else:
        print("  No GOLD* symbols found in raw payload.")

    # 4. Validate response date
    print("\n" + "-" * 70)
    print("DATE VALIDATION:")
    print("-" * 70)
    is_valid_date = validate_response_date(mcx_date_str, raw_response)
    resp_date_str = _extract_response_date_str(raw_response) or "N/A"
    print(f"  Requested Date : {mcx_date_str}")
    print(f"  Response Date  : {resp_date_str} (format: MM/DD/YYYY)")
    print(f"  Match Result   : {'VALID (Same Day)' if is_valid_date else 'MISMATCH (Holiday / Weekend rollback)'}")

    if not is_valid_date:
        print("\n[WARNING] Response date does not match requested date.")
        return

    # 5. Clean data for target gold futures
    print("\n" + "-" * 70)
    print("CLEANED TARGET CONTRACTS (GOLDM, GOLDTEN, GOLDGUINEA, GOLDPETAL):")
    print("-" * 70)

    df = clean_data(raw_response)
    if df.empty:
        print("No target contracts remained after filtering.")
        return

    print(f"Cleaned DataFrame Shape: {df.shape[0]} rows x {df.shape[1]} columns\n")
    display_cols = [
        "date",
        "symbol",
        "expiry_date",
        "close",
        "previous_close",
        "volume",
        "oi",
        "volume_value",
        "volume_unit",
    ]
    print(df[display_cols].to_string(index=False))
    print("=" * 70)


def main() -> None:
    if len(sys.argv) < 2:
        date_str = "09/10/2026"
        print(f"No date provided. Defaulting to: {date_str}\n")
    else:
        date_str = sys.argv[1]

    run_fetch_day(date_str)


if __name__ == "__main__":
    main()
