"""Load MCX bhavcopy CSV files in either of the two known layouts.

Format A is the MCX website download (BhavCopyDateWise_DDMMYYYY.csv).
Format B is the Samco download (YYYYMMDD_MCX.csv). Both map to SCHEMA.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import numpy as np
import pandas as pd

from config import TARGET_SYMBOLS

# Source column -> schema column, per format.
FORMAT_COLUMNS: Dict[str, Dict[str, str]] = {
    "A": {
        "Date": "date",
        "Instrument Name": "instrument",
        "Symbol": "symbol",
        "Expiry Date": "expiry_date",
        "Option Type": "option_type",
        "Strike Price": "strike",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Previous Close": "previous_close",
        "Volume(Lots)": "volume_lots",
        "Volume(In 000's)": "volume_000s_raw",
        "Value(Lacs)": "value_lakhs",
        "Open Interest(Lots)": "oi_lots",
    },
    "B": {
        "DATE": "date",
        "INSTRUMENTNAME": "instrument",
        "SYMBOL": "symbol",
        "EXPIRY_DATE": "expiry_date",
        "OPTIONTYPE": "option_type",
        "STRIKEPRICE": "strike",
        "OPEN": "open",
        "HIGH": "high",
        "LOW": "low",
        "CLOSE": "close",
        "PREVIOUS_CLOSE": "previous_close",
        "VOLUME_IN_LOTS": "volume_lots",
        "VOLUME_IN_000_S": "volume_000s_raw",
        "VALUE_IN_LAKHS": "value_lakhs",
        "OPEN_INTEREST_IN_LOTS": "oi_lots",
    },
}

# Columns the loader needs. Option type and strike are not used for futures.
REQUIRED = [
    "date", "instrument", "symbol", "expiry_date", "open", "high", "low",
    "close", "previous_close", "volume_lots", "volume_000s_raw",
    "value_lakhs", "oi_lots",
]

EXPIRY_FORMATS = {"A": "%d%b%Y", "B": "%d %b %Y"}

SCHEMA = [
    "date", "symbol", "expiry_date", "open", "high", "low", "close",
    "previous_close", "volume_lots", "volume_000s", "volume_unit",
    "value_lakhs", "oi_lots", "zero_volume",
]

REJECT_COLUMNS = ["line", "instrument", "symbol", "expiry_date", "reason"]


@dataclass
class LoadResult:
    path: Path
    format: str
    rows: pd.DataFrame     # SCHEMA columns, target futures only
    rejects: pd.DataFrame  # REJECT_COLUMNS, one row per rejected source row


# File name patterns of the two downloads, and the date format inside them.
FILENAME_DATES = [
    (re.compile(r"BhavCopyDateWise_(\d{8})", re.I), "%d%m%Y"),
    (re.compile(r"^(\d{8})_MCX", re.I), "%Y%m%d"),
]


def filename_date(path: Union[str, Path]) -> Optional[date]:
    """Return the trade date encoded in a download's file name, or None."""
    name = Path(path).name
    for pattern, fmt in FILENAME_DATES:
        m = pattern.search(name)
        if m:
            try:
                return datetime.strptime(m.group(1), fmt).date()
            except ValueError:
                return None
    return None


def detect_format(columns: List[str]) -> str:
    """Return "A" or "B" for a header, or raise ValueError naming missing columns."""
    cols = {c.strip() for c in columns}
    missing_by_format = {}
    for fmt, mapping in FORMAT_COLUMNS.items():
        needed = [src for src, dst in mapping.items() if dst in REQUIRED]
        missing = [c for c in needed if c not in cols]
        if not missing:
            return fmt
        missing_by_format[fmt] = missing
    closest = min(missing_by_format, key=lambda f: len(missing_by_format[f]))
    raise ValueError(
        f"Unknown bhavcopy header. Closest is format {closest}, "
        f"missing columns: {missing_by_format[closest]}"
    )


def _to_schema(raw: pd.DataFrame, fmt: str) -> pd.DataFrame:
    """Rename and parse every row. Unparseable fields become NaN/NaT."""
    df = raw.rename(columns=lambda c: c.strip()).rename(columns=FORMAT_COLUMNS[fmt])
    df = df.apply(lambda s: s.str.strip())

    out = pd.DataFrame(index=df.index)
    out["instrument"] = df["instrument"]
    out["symbol"] = df["symbol"]
    out["date"] = pd.to_datetime(df["date"], format="%d %b %Y", errors="coerce").dt.date
    out["expiry_date"] = pd.to_datetime(
        df["expiry_date"].str.title(), format=EXPIRY_FORMATS[fmt], errors="coerce"
    ).dt.date

    for col in ["open", "high", "low", "close", "previous_close", "value_lakhs"]:
        out[col] = pd.to_numeric(df[col].replace("", np.nan), errors="coerce")
    for col in ["volume_lots", "oi_lots"]:
        out[col] = pd.to_numeric(df[col].replace("", np.nan), errors="coerce")

    # "191.191 GRMS" -> 191.191, "GRMS"
    parts = df["volume_000s_raw"].str.extract(r"^([0-9.]+)\s*([A-Za-z]*)$")
    out["volume_000s"] = pd.to_numeric(parts[0], errors="coerce")
    out["volume_unit"] = parts[1].fillna("")

    # Format A leaves OHLC blank on zero-volume rows; format B writes 0.
    out["zero_volume"] = out["volume_lots"] == 0
    for col in ["open", "high", "low"]:
        out.loc[out["zero_volume"] & (out[col] == 0), col] = np.nan
    return out


def _reject_reasons(df: pd.DataFrame) -> pd.Series:
    """Return the first failing reason per row, or None for rows to keep."""
    checks = [
        (df["instrument"] != "FUTCOM", "instrument " + df["instrument"]),
        (df["symbol"] == "GOLD", "GOLD 1 kg contract excluded"),
        (~df["symbol"].isin(TARGET_SYMBOLS), "symbol not targeted"),
        (df["date"].isna(), "unparseable date"),
        (df["expiry_date"].isna(), "unparseable expiry date"),
    ]
    for col in ["close", "previous_close", "volume_lots", "value_lakhs", "oi_lots"]:
        checks.append((df[col].isna(), f"missing or non-numeric {col}"))

    reasons = pd.Series(None, index=df.index, dtype=object)
    for mask, reason in reversed(checks):  # earlier checks take priority
        reasons = reasons.mask(mask, reason)
    return reasons


def load_csv(path: Union[str, Path, Any], filename: Optional[str] = None) -> LoadResult:
    """Parse one bhavcopy CSV from a path or file-like stream.

    Returns a LoadResult whose rows hold FUTCOM rows for TARGET_SYMBOLS in
    SCHEMA units: prices in rupees per quote unit, volume and OI in lots,
    volume_000s in thousands of volume_unit, value in lakhs of rupees.
    Every other source row appears in rejects with a reason.
    """
    if isinstance(path, (str, Path)) and not hasattr(path, "read"):
        path_obj = Path(path)
        raw = pd.read_csv(path_obj, dtype=str, keep_default_na=False)
    else:
        name = filename or getattr(path, "name", "uploaded.csv")
        path_obj = Path(name)
        raw = pd.read_csv(path, dtype=str, keep_default_na=False)

    fmt = detect_format(list(raw.columns))
    parsed = _to_schema(raw, fmt)

    reasons = _reject_reasons(parsed)
    keep = reasons.isna()

    rejects = parsed.loc[~keep, ["instrument", "symbol", "expiry_date"]].copy()
    rejects.insert(0, "line", rejects.index + 2)  # 1-based, after the header
    rejects["reason"] = reasons[~keep]

    rows = parsed.loc[keep, SCHEMA].reset_index(drop=True)
    for col in ["volume_lots", "oi_lots"]:
        rows[col] = rows[col].astype("int64")
    return LoadResult(path_obj, fmt, rows, rejects[REJECT_COLUMNS].reset_index(drop=True))


load_bhav = load_csv

