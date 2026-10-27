"""Carry estimated from the GOLDM curve, and expiry alignment."""

import math
from datetime import date
from typing import Optional, Tuple

import pandas as pd

from config import STAGGERED_DELIVERY_DAYS
from src.aureus_lens.core.normalize import add_ppg999

CARRY_COLUMNS = ["date", "carry", "carry_source", "carry_date", "near_expiry", "far_expiry"]


def eligible_goldm(rows: pd.DataFrame, trade_date: date,
                   buffer_days: int = STAGGERED_DELIVERY_DAYS) -> pd.DataFrame:
    """Return GOLDM rows on trade_date with volume and OI, expiring more than
    buffer_days calendar days later, sorted by expiry."""
    g = rows[(rows["symbol"] == "GOLDM") & (rows["date"] == trade_date)
             & (rows["volume_lots"] > 0) & (rows["oi_lots"] > 0)]
    days = g["expiry_date"].map(lambda e: (e - trade_date).days)
    return g[days > buffer_days].sort_values("expiry_date")


def carry_on(rows: pd.DataFrame, trade_date: date,
             buffer_days: int = STAGGERED_DELIVERY_DAYS) -> Optional[Tuple[float, date, date]]:
    """Return (annual continuous carry, near expiry, far expiry) from the two
    nearest eligible GOLDM expiries on trade_date, or None if fewer than two."""
    g = eligible_goldm(rows, trade_date, buffer_days)
    if len(g) < 2:
        return None
    near, far = g.iloc[0], g.iloc[1]
    ppg = add_ppg999(g.iloc[:2])
    years = (far["expiry_date"] - near["expiry_date"]).days / 365.0
    return math.log(ppg.iloc[1] / ppg.iloc[0]) / years, near["expiry_date"], far["expiry_date"]


def carry_series(bhav: pd.DataFrame, buffer_days: int = STAGGERED_DELIVERY_DAYS,
                 max_stale_sessions: int = 5) -> pd.DataFrame:
    """Return one row per stored session with carry (per year, continuous).

    carry_source is "empirical" when that session's GOLDM curve gives a value,
    "stale" when the last empirical value from at most max_stale_sessions
    earlier sessions is reused, and "none" otherwise. Each value depends only
    on rows dated on or before its session.
    """
    out = []
    last = None  # (carry, date, near, far, session index)
    for i, d in enumerate(sorted(bhav["date"].unique())):
        res = carry_on(bhav, d, buffer_days)
        if res is not None:
            last = (res[0], d, res[1], res[2], i)
            out.append((d, res[0], "empirical", d, res[1], res[2]))
        elif last is not None and i - last[4] <= max_stale_sessions:
            out.append((d, last[0], "stale", last[1], last[2], last[3]))
        else:
            out.append((d, float("nan"), "none", None, None, None))
    return pd.DataFrame(out, columns=CARRY_COLUMNS)


def adjust_to_expiry(ppg: float, carry: float, days_diff: int) -> float:
    """Return ppg moved along the curve by days_diff calendar days, rupees per gram."""
    if ppg < 0:
        raise ValueError(f"price cannot be negative: {ppg}")
    return float(ppg * math.exp(carry * days_diff / 365.0))
