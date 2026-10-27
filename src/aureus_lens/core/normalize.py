"""Price Normalization to ₹ per gram of 999 purity gold (PPG999).

Aureus Lens - Contract-Native Relative-Value Engine for MCX Gold Futures.
Hack in Hills '26 - Phase 3
"""

from typing import Any, Mapping, Union
import pandas as pd


def normalize_ppg999(row: Union[Mapping[str, Any], pd.Series, Any]) -> float:
    """Normalize contract price to ₹ per gram of 999 purity gold (PPG999).

    Contract Normalization Rules:
        - GOLDM:      close / 10 * (999 / 995)   (100g lot, quoted per 10g, 995 purity adjusted to 999)
        - GOLDTEN:    close / 10                 (10g lot, quoted per 10g, 999 purity)
        - GOLDGUINEA: close / 8                  (8g lot, quoted per 8g, 999 purity)
        - GOLDPETAL:  close / 1                  (1g lot, quoted per 1g, 999 purity)

    Args:
        row: Mapping (dict, pd.Series, or object) with 'symbol' and 'close' fields.

    Returns:
        float: Normalized price in ₹ per gram of 999 gold.
    """
    # Extract symbol
    symbol_raw = None
    if isinstance(row, (dict, Mapping, pd.Series)):
        symbol_raw = row.get("symbol")
        if symbol_raw is None:
            symbol_raw = row.get("Symbol")
    elif hasattr(row, "symbol"):
        symbol_raw = getattr(row, "symbol")
    elif hasattr(row, "Symbol"):
        symbol_raw = getattr(row, "Symbol")

    if symbol_raw is None:
        raise ValueError(f"Missing 'symbol' in row: {row}")

    symbol = str(symbol_raw).strip().upper()

    # Extract close price
    close_raw = None
    if isinstance(row, (dict, Mapping, pd.Series)):
        close_raw = row.get("close")
        if close_raw is None:
            close_raw = row.get("Close")
    elif hasattr(row, "close"):
        close_raw = getattr(row, "close")
    elif hasattr(row, "Close"):
        close_raw = getattr(row, "Close")

    if close_raw is None:
        raise ValueError(f"Missing 'close' in row: {row}")

    try:
        close = float(close_raw)
    except (ValueError, TypeError) as err:
        raise ValueError(f"Invalid close price '{close_raw}' in row: {err}")

    # Conversion logic
    if symbol == "GOLDM":
        return (close / 10.0) * (999.0 / 995.0)
    elif symbol == "GOLDTEN":
        return close / 10.0
    elif symbol == "GOLDGUINEA":
        return close / 8.0
    elif symbol == "GOLDPETAL":
        return close / 1.0
    else:
        raise ValueError(
            f"Unsupported contract symbol '{symbol}' for 999 purity normalization. "
            "Supported symbols: GOLDM, GOLDTEN, GOLDGUINEA, GOLDPETAL."
        )
