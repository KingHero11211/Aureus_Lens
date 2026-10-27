"""Convert quoted prices to rupees per gram of 999 gold."""

from typing import Any, Mapping

import pandas as pd

from config import CONTRACT_SPECS


def _spec(symbol: str) -> Mapping[str, Any]:
    try:
        return CONTRACT_SPECS[symbol.strip().upper()]
    except KeyError:
        raise ValueError(f"Unsupported symbol {symbol!r}; expected one of {sorted(CONTRACT_SPECS)}")


def per_gram(symbol: str, price: float) -> float:
    """Return price in rupees per gram at the contract's own purity (quote unit removed)."""
    return float(price) / _spec(symbol)["quote_grams"]


def normalize_ppg999(row: Mapping[str, Any]) -> float:
    """Return close in rupees per gram of 999 gold.

    row needs "symbol" and "close". Lot size does not enter: only the quote
    unit and purity (UNVERIFIED, see config) change the price per gram.
    """
    if row.get("symbol") is None or row.get("close") is None:
        raise ValueError(f"row needs symbol and close: {dict(row)}")
    spec = _spec(str(row["symbol"]))
    return per_gram(str(row["symbol"]), row["close"]) * 999.0 / spec["purity"]


def add_ppg999(df: pd.DataFrame, price_col: str = "close") -> pd.Series:
    """Return a Series of price_col in rupees per gram of 999 gold for each row."""
    quote = df["symbol"].map(lambda s: _spec(s)["quote_grams"])
    purity = df["symbol"].map(lambda s: _spec(s)["purity"])
    return df[price_col] / quote * 999.0 / purity
