"""Executability Gate and Hard Suppressions Engine.

Aureus Lens - Contract-Native Relative-Value Engine for MCX Gold Futures.
Hack in Hills '26 - Phase 4 & Audit Refinement
"""

from datetime import date, datetime
from typing import Any, List, Mapping, Optional, Tuple, Union
import pandas as pd


def _get_val(row: Union[Mapping[str, Any], pd.Series, Any], *keys: str, default: Any = None) -> Any:
    """Helper to retrieve value from dict, Series, or object across case variants."""
    for key in keys:
        if isinstance(row, (dict, Mapping, pd.Series)):
            if key in row and row[key] is not None:
                return row[key]
        elif hasattr(row, key):
            val = getattr(row, key)
            if val is not None:
                return val
    return default


def _parse_date(val: Any) -> Optional[date]:
    """Parse date or return date object."""
    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        val_clean = val.strip()
        try:
            if "/" in val_clean:
                return datetime.strptime(val_clean, "%d/%m/%Y").date()
            return datetime.strptime(val_clean, "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def executability_gate(
    row_small: Union[Mapping[str, Any], pd.Series, Any],
    row_ref: Union[Mapping[str, Any], pd.Series, Any],
    spread_bps: float,
    cost_bps: float,
    tender_days_threshold: int = 3,
) -> Tuple[bool, List[str]]:
    """Evaluate hard suppressions to determine trade executability.

    Returns all failing reasons, not just the first.

    Hard Suppression Rules:
        1. Inside Tender Buffer:
           Evaluates days to tender start (expiry_date - trade_date <= tender_days_threshold).
        2. Stale Price:
           volume == 0, OR (close == previous_close with unchanged OI).
        3. Cost Hurdle:
           |spread_bps| < 2 * cost_bps.

    Returns:
        (True, ["Executable"]) if all gates pass.
        (False, [reason1, reason2, ...]) if any hard suppressions trigger.
    """
    reasons: List[str] = []

    sym_small = str(_get_val(row_small, "symbol", "Symbol", default="SmallContract")).strip()
    sym_ref = str(_get_val(row_ref, "symbol", "Symbol", default="RefContract")).strip()

    # 1. Tender Buffer Check
    for row, sym in [(row_small, sym_small), (row_ref, sym_ref)]:
        days_to_expiry = _get_val(row, "days_to_expiry", "days_to_exp")
        trade_d = _parse_date(_get_val(row, "date", "Date"))
        expiry_d = _parse_date(_get_val(row, "expiry_date", "ExpiryDate"))

        days_remaining = None
        if days_to_expiry is not None:
            days_remaining = float(days_to_expiry)
        elif trade_d and expiry_d:
            days_remaining = (expiry_d - trade_d).days

        if days_remaining is not None and days_remaining <= tender_days_threshold:
            reasons.append(
                f"Inside tender buffer for {sym} ({days_remaining:.0f} days to expiry <= {tender_days_threshold} days threshold)"
            )

    # 2. Stale Price Check: volume == 0, OR (close == previous_close with unchanged OI)
    for row, sym in [(row_small, sym_small), (row_ref, sym_ref)]:
        vol = _get_val(row, "volume", "Volume")
        close_px = _get_val(row, "close", "Close")
        prev_close_px = _get_val(row, "previous_close", "PreviousClose", "prev_close")
        oi = _get_val(row, "oi", "OpenInterest", "OI")
        prev_oi = _get_val(row, "previous_oi", "prev_oi", "PrevOI")

        is_stale = False
        stale_detail = ""

        if vol is not None:
            try:
                v_num = float(vol)
                if v_num == 0.0:
                    is_stale = True
                    stale_detail = f"volume == 0 on {sym}"
            except (ValueError, TypeError):
                pass

        if not is_stale and close_px is not None and prev_close_px is not None:
            try:
                c_num = float(close_px)
                pc_num = float(prev_close_px)
                if c_num == pc_num:
                    if oi is not None and prev_oi is not None:
                        if float(oi) == float(prev_oi):
                            is_stale = True
                            stale_detail = f"close unchanged ({c_num}) with unchanged OI ({oi}) on {sym}"
                    else:
                        # If prev_oi not provided, unchanged close with 0 volume was already checked
                        pass
            except (ValueError, TypeError):
                pass

        if is_stale:
            reasons.append(f"Stale price: {stale_detail}")

    # 3. Minimum Cost Hurdle: |spread_bps| < 2 * cost_bps
    hurdle = 2.0 * float(cost_bps)
    if abs(float(spread_bps)) < hurdle:
        reasons.append(
            f"Sub-hurdle spread (|{spread_bps:.2f}| bps < 2x cost {hurdle:.2f} bps)"
        )

    if not reasons:
        return True, ["Executable"]

    return False, reasons
