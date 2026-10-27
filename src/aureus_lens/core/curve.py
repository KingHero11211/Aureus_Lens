"""Term Structure, Empirical Carry, and Expiry Adjustment Engine.

Aureus Lens - Contract-Native Relative-Value Engine for MCX Gold Futures.
Hack in Hills '26 - Phase 3 & Audit Refinement
"""

from datetime import date, datetime
import math
from typing import Optional, Tuple, Union

import duckdb

from config import STAGGERED_DELIVERY_DAYS
from src.aureus_lens.core.normalize import normalize_ppg999


def _parse_query_date(val: Union[str, date, datetime]) -> date:
    """Parse date into standard date object."""
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        clean_str = val.strip()
        if "/" in clean_str:
            return datetime.strptime(clean_str, "%d/%m/%Y").date()
        return datetime.strptime(clean_str, "%Y-%m-%d").date()

    raise ValueError(f"Cannot parse date '{val}'. Expected 'YYYY-MM-DD' or 'DD/MM/YYYY'.")


def compute_carry(
    conn: duckdb.DuckDBPyConnection,
    date_val: Union[str, date, datetime],
    theoretical_fallback: Optional[float] = None,
    tender_buffer_days: int = STAGGERED_DELIVERY_DAYS,
) -> Tuple[Optional[float], str]:
    """Compute annualised continuous carry rate from liquid GOLDM futures contracts.

    Audit Requirements:
        1. Exclude any GOLDM expiry inside its tender buffer ((expiry - trade_date).days <= buffer).
        2. Strictly zero look-ahead: only data for that specific trade date is used.
        3. Requires at least 2 eligible liquid expiries (E1 < E2 with volume_lots > 0 and oi_lots > 0).
        4. carry_source must be one of: 'empirical', 'stale', 'theoretical', or 'none'.
           'none' indicates insufficient data and suppresses trading signals.

    Returns:
        (carry, "empirical") if at least 2 eligible liquid expiries exist.
        (theoretical_fallback, "theoretical") if insufficient data and fallback provided.
        (None, "none") if insufficient data and no fallback provided.
    """
    trade_date = _parse_query_date(date_val)

    # Query liquid GOLDM expiries strictly on this trade date
    query = """
        SELECT
            expiry_date,
            close,
            volume_lots,
            oi_lots
        FROM bhav
        WHERE date = ?::DATE
          AND symbol = 'GOLDM'
          AND volume_lots > 0
          AND oi_lots > 0
        ORDER BY expiry_date ASC;
    """
    rows = conn.execute(query, [trade_date]).fetchall()

    # Filter out expiries inside the tender buffer
    eligible_rows = []
    for r in rows:
        exp_d = r[0]
        days_to_exp = (exp_d - trade_date).days
        if days_to_exp > tender_buffer_days:
            eligible_rows.append(r)

    if len(eligible_rows) < 2:
        if theoretical_fallback is not None:
            return float(theoretical_fallback), "theoretical"
        return None, "none"

    # Nearest liquid eligible expiry (E1) and next liquid eligible expiry (E2)
    e1_expiry, e1_close = eligible_rows[0][0], float(eligible_rows[0][1])
    e2_expiry, e2_close = eligible_rows[1][0], float(eligible_rows[1][1])

    days_between = (e2_expiry - e1_expiry).days
    if days_between <= 0:
        if theoretical_fallback is not None:
            return float(theoretical_fallback), "theoretical"
        return None, "none"

    ppg_e1 = normalize_ppg999({"symbol": "GOLDM", "close": e1_close})
    ppg_e2 = normalize_ppg999({"symbol": "GOLDM", "close": e2_close})

    if ppg_e1 <= 0 or ppg_e2 <= 0:
        if theoretical_fallback is not None:
            return float(theoretical_fallback), "theoretical"
        return None, "none"

    # Continuous annualised carry rate
    carry_annual = math.log(ppg_e2 / ppg_e1) / (days_between / 365.0)
    return carry_annual, "empirical"


def adjust_to_expiry(ppg: float, carry: float, days_diff: int) -> float:
    """Adjust a normalized PPG price along the forward curve to match a target expiry.

    Formula:
        adjusted_ppg = ppg * exp(carry * (days_diff / 365.0))

    Args:
        ppg: Normalized price per gram at reference expiry.
        carry: Annualised continuous carry rate.
        days_diff: Days difference (target_date - contract_expiry).days.
                   A later date gives a higher adjusted price when carry is positive.

    Returns:
        float: Expiry-aligned normalized price per gram.
    """
    if ppg < 0:
        raise ValueError(f"PPG price cannot be negative: {ppg}")

    if days_diff == 0 or carry == 0.0:
        return float(ppg)

    return float(ppg * math.exp(carry * (days_diff / 365.0)))
