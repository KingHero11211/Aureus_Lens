"""Continuity and value checks on stored bhav rows, and the data notes report."""

from datetime import date, timedelta
from typing import List

import numpy as np
import pandas as pd

from config import CONTRACT_SPECS

VALUE_TOLERANCE = 0.005  # relative, reported vs implied value
PRICE_TOLERANCE = 0.005  # rupees, previous_close vs prior close

SMALL = ["GOLDTEN", "GOLDGUINEA", "GOLDPETAL"]


def implied_value_lakhs(rows: pd.DataFrame) -> pd.Series:
    """Return lots x lot grams x close per quote gram, in lakhs of rupees."""
    lot_g = rows["symbol"].map(lambda s: CONTRACT_SPECS[s]["lot_size_grams"])
    quote_g = rows["symbol"].map(lambda s: CONTRACT_SPECS[s]["quote_grams"])
    return rows["volume_lots"] * lot_g * rows["close"] / quote_g / 1e5


def _weekdays_between(a: date, b: date) -> int:
    """Return the number of Monday-Friday dates strictly between a and b."""
    return int(np.busday_count(a + timedelta(days=1), b)) if b > a else 0


def check_continuity(bhav: pd.DataFrame) -> pd.DataFrame:
    """Compare each row's previous_close with the contract's close on the prior stored session.

    Returns one row per bhav row with a status:
      ok          previous_close equals prior close (within PRICE_TOLERANCE)
      gap         adjacent sessions and the prices differ
      unchecked   weekdays are missing between the two stored sessions; with
                  no holiday calendar a holiday cannot be told from a missing file
      new         adjacent sessions and the contract is absent from the earlier one
      first       the row is on the first stored session
    """
    cols = ["date", "symbol", "expiry_date", "previous_close", "prior_date",
            "prior_close", "status", "detail"]
    if bhav.empty:
        return pd.DataFrame(columns=cols)

    sessions = sorted(bhav["date"].unique())
    prior_of = {d: (sessions[i - 1] if i else None) for i, d in enumerate(sessions)}
    closes = bhav.set_index(["date", "symbol", "expiry_date"])["close"]

    out = []
    for r in bhav.itertuples(index=False):
        prior = prior_of[r.date]
        prior_close = np.nan
        if prior is None:
            status, detail = "first", "first stored session"
        elif _weekdays_between(prior, r.date):
            status = "unchecked"
            detail = (f"{_weekdays_between(prior, r.date)} weekdays between "
                      f"stored sessions {prior} and {r.date}")
        elif (prior, r.symbol, r.expiry_date) not in closes.index:
            status, detail = "new", f"not present on prior stored session {prior}"
        else:
            prior_close = float(closes[(prior, r.symbol, r.expiry_date)])
            if abs(r.previous_close - prior_close) > PRICE_TOLERANCE:
                status = "gap"
                detail = f"previous_close {r.previous_close} != close {prior_close} on {prior}"
            else:
                status, detail = "ok", ""
        out.append((r.date, r.symbol, r.expiry_date, r.previous_close, prior,
                    prior_close, status, detail))
    return pd.DataFrame(out, columns=cols)


def continuity_events(cont: pd.DataFrame) -> pd.DataFrame:
    """Return data_health rows for gap, unchecked and new statuses."""
    flagged = cont[cont["status"].isin(["gap", "unchecked", "new"])]
    return pd.DataFrame({
        "date": flagged["date"],
        "symbol": flagged["symbol"],
        "expiry_date": flagged["expiry_date"],
        "event": "continuity_" + flagged["status"],
        "detail": flagged["detail"],
    })


def value_check(bhav: pd.DataFrame) -> pd.DataFrame:
    """Return active rows with reported value, value implied at close, and the
    value range implied at low and high, all in lakhs.

    in_range is True when the reported value lies within lots x [low, high];
    every trade happens inside that range, so a row outside it is a unit or
    parsing error. rel_diff (vs close) is informational: it grows with the
    intraday range.
    """
    active = bhav[~bhav["zero_volume"]].copy()
    active["implied_lakhs"] = implied_value_lakhs(active)
    active["low_lakhs"] = implied_value_lakhs(active.assign(close=active["low"]))
    active["high_lakhs"] = implied_value_lakhs(active.assign(close=active["high"]))
    active["rel_diff"] = active["value_lakhs"] / active["implied_lakhs"] - 1
    # 0.01 lakh slack for rounding in the file
    active["in_range"] = (active["value_lakhs"] >= active["low_lakhs"] - 0.01) & (
        active["value_lakhs"] <= active["high_lakhs"] + 0.01)
    return active[["date", "symbol", "expiry_date", "value_lakhs", "implied_lakhs",
                   "low_lakhs", "high_lakhs", "rel_diff", "in_range"]]


def _cell(v) -> str:
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat()
    return str(v)


def _table(df: pd.DataFrame) -> List[str]:
    if df.empty:
        return ["(none)"]
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in df.itertuples(index=False):
        lines.append("| " + " | ".join(_cell(v) for v in row) + " |")
    return lines


def render_data_notes(bhav: pd.DataFrame, load_log: pd.DataFrame,
                      reject_counts: pd.DataFrame, cont: pd.DataFrame,
                      refused: pd.DataFrame = None) -> str:
    """Return docs/data_notes.md as a string. Output depends only on the inputs."""
    out = [
        "# Data notes",
        "",
        "Generated by `python -m scripts.load_csv`. Do not edit by hand.",
        "",
        "## Files loaded",
        "",
    ]
    out += _table(load_log.sort_values("source_file"))
    out += ["", "## Files not stored", ""]
    out += _table(refused if refused is not None else pd.DataFrame())
    out += ["", "## Rejected rows by reason", ""]
    out += _table(reject_counts.sort_values(["source_file", "reason"]))

    if bhav.empty:
        out += ["", "No rows in the store.", ""]
        return "\n".join(out)

    sessions = sorted(bhav["date"].unique())
    out += ["", "## Sessions", "",
            f"{len(sessions)} sessions stored, {sessions[0]} to {sessions[-1]}.", ""]

    per = bhav.groupby(["date", "symbol"]).agg(
        contracts=("expiry_date", "size"),
        zero_volume=("zero_volume", "sum"),
        value_crore=("value_lakhs", lambda v: round(v.sum() / 100, 2)),
    ).reset_index()
    out += ["## Value per symbol (Rs crore, all expiries)", ""]
    out += _table(per)

    small = (bhav[bhav["symbol"].isin(SMALL)].groupby("date")["value_lakhs"].sum() / 100).round(2)
    out += ["", "## GOLDTEN + GOLDGUINEA + GOLDPETAL value (Rs crore)", ""]
    out += _table(small.rename("value_crore").reset_index())

    vc = value_check(bhav)
    summary = vc.groupby(["date", "symbol"]).agg(
        active_contracts=("rel_diff", "size"),
        in_low_high_range=("in_range", "sum"),
        max_abs_diff_vs_close_pct=("rel_diff", lambda d: round(d.abs().max() * 100, 3)),
    ).reset_index()
    out += ["", "## Reported value vs lots x lot grams x price / quote grams", "",
            "Zero-volume rows are excluded. A reported value outside the range "
            "implied by low and high would indicate a unit or parsing error. "
            "The difference against close is shown for information; it grows "
            "with the intraday range.", ""]
    out += _table(summary)
    bad = vc[~vc["in_range"]]
    out += ["", f"Rows outside the low-high range: {len(bad)}", ""]
    if not bad.empty:
        out += _table(bad.round(2))
        out += [""]
    over = vc[vc["rel_diff"].abs() > VALUE_TOLERANCE]
    out += [f"Rows more than {VALUE_TOLERANCE:.1%} from the value implied at close: {len(over)}", ""]
    if not over.empty:
        out += _table(over[["date", "symbol", "expiry_date", "value_lakhs", "implied_lakhs", "rel_diff"]]
                      .round({"implied_lakhs": 2, "rel_diff": 5}))
        out += [""]

    out += ["## Continuity (previous_close vs prior stored close)", ""]
    out += _table(cont["status"].value_counts().sort_index().rename("rows").reset_index())
    for status in ["gap", "unchecked"]:
        sub = cont[cont["status"] == status]
        detail = sub.groupby("detail").size().rename("rows").reset_index() if status == "unchecked" \
            else sub[["date", "symbol", "expiry_date", "detail"]]
        out += ["", f"### {status}", ""]
        out += _table(detail)
    out += [""]
    return "\n".join(out)
