"""Data for each dashboard page, without Streamlit.

derive() computes every table the pages use from the store. The pages read
only those derived tables, so the same pages run from the DuckDB store or
from the committed snapshot. Every page function returns a View, which
always carries its source files, date range and unit.
"""

import inspect
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import duckdb
import numpy as np
import pandas as pd

from config import (
    BROKERAGE_MAX_PER_ORDER,
    BROKERAGE_RATE_PCT,
    CARRY_MIN_SESSIONS,
    CTT_SELL_PCT,
    EXCHANGE_TRANSACTION_CHARGE_PCT,
    GST_PCT,
    PROJECT_ROOT,
    SEBI_TURNOVER_FEE_PCT,
    STAMP_DUTY_BUY_PCT,
)
from src.aureus_lens.core.curve import carry_series
from src.aureus_lens.core.normalize import add_ppg999
from src.aureus_lens.core.pairs import build_pairs
from src.aureus_lens.core.waterfall import compute_waterfall
from src.aureus_lens.reconcile import _weekdays_between, check_continuity, value_check
from src.aureus_lens.store.db import read_bhav

EMPTY = ("No data: neither the store nor the snapshot is present. Load CSV files with: "
         "python -m scripts.load_csv data/raw/*.csv")
NO_SIGNAL = "No actionable signal"
VERIFICATION_MD = PROJECT_ROOT / "docs" / "VERIFICATION.md"

# Thresholds come from the code, not from this module.
Z_WINDOW = inspect.signature(build_pairs).parameters["window"].default
Z_MIN_PERIODS = inspect.signature(build_pairs).parameters["min_periods"].default
Z_THRESHOLD = inspect.signature(build_pairs).parameters["z_threshold"].default

KIND_LABEL = {
    "small_small": "same expiry, small vs small",
    "small_goldm": "small vs GOLDM (depends on purity assumption)",
}
PAIR_KEYS = ["kind", "leg_a", "leg_b", "expiry_a"]


@dataclass
class View:
    title: str
    source: str
    date_range: str
    unit: str
    carry_source: Optional[str] = None
    messages: List[str] = field(default_factory=list)
    tables: Dict[str, pd.DataFrame] = field(default_factory=dict)
    empty: bool = False
    origin: str = ""

    def labels(self) -> str:
        parts = [f"Source: {self.source}", f"Dates: {self.date_range}", f"Unit: {self.unit}"]
        if self.carry_source:
            parts.append(f"carry_source: {self.carry_source}")
        if self.origin:
            parts.append(f"Read from: {self.origin}")
        return " | ".join(parts)


@dataclass
class Store:
    bhav: pd.DataFrame
    load_log: pd.DataFrame
    refused: pd.DataFrame


@dataclass
class Derived:
    """Tables the pages need. None of them holds raw bhavcopy rows."""
    origin: str
    normalized: pd.DataFrame     # date, symbol, expiry_date, ppg999, lots_traded, zero_volume, source_file
    pairs: pd.DataFrame          # build_pairs output plus baseline
    carry: pd.DataFrame          # carry_series output
    continuity: pd.DataFrame     # date, symbol, expiry_date, status
    load_log: pd.DataFrame
    refused: pd.DataFrame        # date, detail
    value_summary: pd.DataFrame  # date, in_range, active

    @property
    def empty(self) -> bool:
        return self.normalized.empty

    @property
    def sessions(self) -> List:
        return sorted(self.normalized["date"].unique()) if not self.empty else []


def read_store(conn: duckdb.DuckDBPyConnection) -> Store:
    """Return the tables derive() needs from an open connection."""
    return Store(
        read_bhav(conn),
        conn.execute("SELECT * FROM load_log ORDER BY first_date, source_file").df(),
        conn.execute("SELECT date, detail FROM data_health "
                     "WHERE event = 'file_refused' ORDER BY date").df(),
    )


def open_store(path) -> Store:
    """Read the store read-only. A missing file gives an empty Store."""
    if not Path(path).exists():
        return Store(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    conn = duckdb.connect(str(path), read_only=True)
    try:
        return read_store(conn)
    finally:
        conn.close()


def baseline_counts(pairs: pd.DataFrame) -> pd.Series:
    """Return, per row, the number of earlier non-missing spreads in the same
    pair and expiry series: the history the z-score baseline can use."""
    ordered = pairs.sort_values("date")
    prior = ordered.groupby(PAIR_KEYS)["spread_bps"].transform(
        lambda s: s.notna().cumsum().shift(1, fill_value=0))
    return prior.reindex(pairs.index).astype(int)


def derive(store: Store, origin: str = "DuckDB store") -> Derived:
    """Compute every table the pages use."""
    b = store.bhav
    if b.empty:
        none = pd.DataFrame()
        return Derived(origin, none, none, none, none, none, none, none)
    normalized = pd.DataFrame({
        "date": b["date"], "symbol": b["symbol"], "expiry_date": b["expiry_date"],
        "ppg999": add_ppg999(b), "lots_traded": b["volume_lots"],
        "zero_volume": b["zero_volume"], "source_file": b["source_file"]})
    carry = carry_series(b)
    pairs = build_pairs(b, carry)
    pairs["baseline"] = baseline_counts(pairs)
    cont = check_continuity(b)[["date", "symbol", "expiry_date", "status"]]
    vc = value_check(b).groupby("date")["in_range"].agg(in_range="sum", active="size").reset_index()
    load_log = store.load_log.copy()
    for col in ["first_date", "last_date"]:
        load_log[col] = pd.to_datetime(load_log[col]).dt.date
    refused = store.refused.copy()
    if not refused.empty:
        refused["date"] = pd.to_datetime(refused["date"]).dt.date
    return Derived(origin, normalized.reset_index(drop=True), pairs, carry, cont.reset_index(drop=True),
                   load_log, refused, vc)


def load_data(store_path: Path, snapshot_dir: Path) -> Derived:
    """Return derived tables from the store if present, else the snapshot, else empty."""
    if Path(store_path).exists():
        return derive(open_store(store_path))
    from src.aureus_lens.snapshot import read_snapshot
    if (Path(snapshot_dir) / "manifest.json").exists():
        return read_snapshot(snapshot_dir)
    return derive(open_store(store_path), origin="")


def insufficient(have: int, need: int) -> str:
    return f"insufficient history ({have} of {need} sessions)"


def _source(normalized: pd.DataFrame) -> str:
    files = list(normalized.groupby("source_file")["date"].min().sort_values().index)
    return files[0] if len(files) == 1 else f"{files[0]} to {files[-1]} ({len(files)} files)"


def _dates(sessions) -> str:
    return f"{sessions[0]} to {sessions[-1]} ({len(sessions)} sessions)"


def _empty(title: str, unit: str) -> View:
    return View(title, "none", "none", unit, messages=[EMPTY], empty=True)


def not_run_items(path: Path = VERIFICATION_MD) -> pd.DataFrame:
    """Return the verification table rows whose result mentions NOT RUN."""
    if not path.exists():
        return pd.DataFrame(columns=["item", "check", "result"])
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("| ") and len(cells) >= 3 and re.search(r"(?<!Was )NOT RUN", cells[-1]):
            rows.append((cells[0], cells[1], cells[-1]))
    return pd.DataFrame(rows, columns=["item", "check", "result"])


def data_health_view(d: Derived) -> View:
    if d.empty:
        v = _empty("Data Health", "rows")
        v.tables["NOT RUN checks (docs/VERIFICATION.md)"] = not_run_items()
        return v
    vs = d.value_summary.set_index("date")
    files = d.load_log.copy()
    files["value check"] = files["first_date"].map(
        lambda day: f"{vs.loc[day, 'in_range']} of {vs.loc[day, 'active']} active rows within low-high range"
        if day in vs.index else "no active rows")
    files = files.rename(columns={"source_file": "file", "first_date": "date", "rows_kept": "rows kept",
                                  "rows_rejected": "rows rejected"})
    cont = d.continuity["status"].value_counts()
    counts = pd.DataFrame({"status": ["ok", "gap", "unchecked", "new", "first"]})
    counts["rows"] = counts["status"].map(lambda s: int(cont.get(s, 0)))
    return View(
        "Data Health", "load_log, data_health and bhav tables", _dates(d.sessions), "rows", origin=d.origin,
        tables={
            "Files loaded": files[["file", "date", "format", "rows kept", "rows rejected", "value check"]],
            "Files not stored": d.refused,
            "Continuity (previous close vs prior stored close)": counts,
            "NOT RUN checks (docs/VERIFICATION.md)": not_run_items(),
        },
    )


def normalized_view(d: Derived) -> View:
    unit = "rupees per gram of 999 gold"
    if d.empty:
        return _empty("Normalized View", unit)
    n = d.normalized.copy()
    n["ppg999"] = n["ppg999"].round(2)
    v = View("Normalized View", _source(n), _dates(d.sessions), unit, origin=d.origin,
             tables={"Price at 999, per gram": n[["date", "symbol", "expiry_date", "ppg999",
                                                   "lots_traded", "zero_volume"]]})
    if len(d.sessions) < 2:
        v.messages.append(f"Series view: {insufficient(len(d.sessions), 2)}")
    v.messages.append("Purity factors are UNVERIFIED (GOLDM 995, others 999).")
    return v


def z_display(pairs: pd.DataFrame) -> pd.Series:
    """Return the z-score as text, or an insufficient-history note while the
    baseline has fewer than Z_MIN_PERIODS sessions."""
    return pd.Series([
        insufficient(int(n), Z_MIN_PERIODS) if n < Z_MIN_PERIODS else ("NaN" if pd.isna(z) else f"{z:.2f}")
        for n, z in zip(pairs["baseline"], pairs["zscore"])], index=pairs.index)


def _carry_label(carry: pd.DataFrame) -> str:
    return ", ".join(f"{s} {n}" for s, n in carry["carry_source"].value_counts().sort_index().items())


def carry_display(carry: pd.DataFrame) -> pd.DataFrame:
    """Return carry per session, with the value replaced by an insufficient-history
    note until CARRY_MIN_SESSIONS sessions have an empirical value."""
    c = carry.sort_values("date").copy()
    c["valid_sessions"] = (c["carry_source"] == "empirical").cumsum()
    c["shown"] = c["valid_sessions"] >= CARRY_MIN_SESSIONS
    c["carry per year"] = [
        f"{v:.6f}" if ok and pd.notna(v) else
        ("none" if ok else insufficient(int(n), CARRY_MIN_SESSIONS))
        for v, ok, n in zip(c["carry"], c["shown"], c["valid_sessions"])]
    return c[["date", "carry per year", "carry_source", "near_expiry", "far_expiry", "valid_sessions", "shown"]]


def _day_source(d: Derived, day) -> str:
    return _source(d.normalized[d.normalized["date"] == day])


def scanner_view(d: Derived, date=None) -> View:
    if d.empty:
        return _empty("Spread Scanner", "bps")
    day = date or d.sessions[-1]
    p = d.pairs[d.pairs["date"] == day].copy()
    short = p["baseline"] < Z_MIN_PERIODS

    p["pair"] = p["leg_a"] + " " + p["expiry_a"].astype(str) + " vs " + p["leg_b"] + " " + p["expiry_b"].astype(str)
    p["gate"] = np.where(p["passes"], "pass", "fail")
    p["failing reasons"] = p["reasons"].map(lambda r: "; ".join(r) if len(r) else "")
    p["zscore"] = z_display(p)
    # Below the required history no row may count as a signal, whatever the code returned.
    p.loc[short, "signal"] = False
    cd = carry_display(d.carry).set_index("date")
    carry_ok = bool(cd.loc[day, "shown"])
    if not carry_ok:
        note = "carry " + insufficient(int(cd.loc[day, "valid_sessions"]), CARRY_MIN_SESSIONS)
        goldm = p["kind"] == "small_goldm"
        p["spread_bps"] = p["spread_bps"].astype(object)
        p.loc[goldm, "spread_bps"] = note
        p.loc[goldm, "gate"] = "not evaluated"
        p.loc[goldm, "failing reasons"] = note
        p.loc[goldm, "signal"] = False
    cols = ["pair", "spread_bps", "cost_bps", "carry_source", "gate", "failing reasons", "zscore", "signal"]

    v = View("Spread Scanner", _day_source(d, day), f"{day} (history: {_dates(d.sessions)})",
             "bps of leg b; cost is pair round trip; carry per year, continuous",
             carry_source=_carry_label(d.carry[d.carry["date"] == day]), origin=d.origin)
    for kind in ["small_small", "small_goldm"]:
        t = p[p["kind"] == kind][cols].copy()
        t["spread_bps"] = t["spread_bps"].map(lambda x: round(x, 2) if isinstance(x, float) else x)
        v.tables[KIND_LABEL[kind]] = t.round({"cost_bps": 2}).reset_index(drop=True)
    v.tables["Carry from GOLDM curve (per year, continuous)"] = (
        cd.reset_index()[lambda c: c["date"] <= day].drop(columns=["shown"]))

    if not p["signal"].any():
        reasons = []
        if short.any():
            reasons.append(f"z-score history below {Z_MIN_PERIODS} sessions on {int(short.sum())} pairs "
                           f"(longest {int(p['baseline'].max())} of {Z_MIN_PERIODS})")
        if not carry_ok:
            reasons.append(f"GOLDM pairs not evaluated: carry {insufficient(int(cd.loc[day, 'valid_sessions']), CARRY_MIN_SESSIONS)}")
        failed = p[~p["passes"] & (p["gate"] == "fail")]
        if not failed.empty:
            kinds = failed["reasons"].explode().dropna().map(_reason_kind).value_counts()
            reasons += [f"{k}: {c} pairs" for k, c in kinds.items()]
        if not short.all():
            reasons.append(f"|z-score| below {Z_THRESHOLD:g} on all pairs that pass the gate")
        v.messages.append(f"{NO_SIGNAL}. Reasons: " + "; ".join(reasons))
    return v


def _reason_kind(reason: str) -> str:
    if "x cost" in reason:
        return "below 2x cost"
    if "tender" in reason:
        return "inside tender buffer"
    if "volume 0" in reason or "unchanged" in reason:
        return "stale price"
    if "carry" in reason:
        return "no carry estimate"
    return reason


def pair_options(d: Derived, date) -> pd.DataFrame:
    p = d.pairs[d.pairs["date"] == date].copy()
    p["order"] = (p["kind"] != "small_small").astype(int)  # small-small pairs first
    p = p.sort_values(["order", "leg_a", "leg_b", "expiry_a"])
    return p[["kind", "leg_a", "expiry_a", "leg_b", "expiry_b"]].reset_index(drop=True)


def waterfall_view(d: Derived, date, kind, leg_a, expiry_a, leg_b) -> View:
    if d.empty:
        return _empty("Waterfall", "bps")
    pairs = d.pairs
    hit = pairs[(pairs["date"] == date) & (pairs["kind"] == kind) & (pairs["leg_a"] == leg_a)
                & (pairs["expiry_a"] == expiry_a) & (pairs["leg_b"] == leg_b)]
    if hit.empty:
        return View("Waterfall", "none", str(date), "bps", messages=["No such pair on this session."],
                    origin=d.origin)
    r = hit.iloc[0]
    v = View("Waterfall", _day_source(d, date), str(date), "bps of leg b",
             carry_source=r["carry_source"], origin=d.origin)
    if kind == "small_goldm":
        cd = carry_display(d.carry).set_index("date")
        if not cd.loc[date, "shown"]:
            v.messages.append("Carry step not shown: carry " + insufficient(
                int(cd.loc[date, "valid_sessions"]), CARRY_MIN_SESSIONS))
            return v
    if pd.isna(r["spread_bps"]):
        v.messages.append("Spread not available: no carry estimate to align expiries.")
        return v
    stages = pd.DataFrame(compute_waterfall(r["raw_bps"], r["purity_bps"], r["spread_bps"],
                                            r["tick_floor_bps"], r["cost_bps"]))
    stages["stage"] = stages["stage"].replace({"edge": "executable edge"})
    v.tables[f"{leg_a} {expiry_a} vs {leg_b} {r['expiry_b']}"] = stages.round(4)
    v.messages.append("Tick sizes and cost rates are UNVERIFIED. The edge is not a finding: "
                      f"{insufficient(int(r['baseline']), Z_MIN_PERIODS)} for a z-score.")
    return v


def coverage_view(d: Derived) -> View:
    if d.empty:
        return _empty("Coverage", "sessions")
    listing = d.normalized.groupby(["symbol", "expiry_date"]).agg(
        first_session=("date", "min"), last_session=("date", "max"), sessions=("date", "size")).reset_index()
    s = d.sessions
    gaps = [(a, b, _weekdays_between(a, b)) for a, b in zip(s, s[1:]) if _weekdays_between(a, b)]
    gaps = pd.DataFrame(gaps, columns=["stored session", "next stored session", "weekdays missing"])
    gaps["status"] = "unchecked (holiday or missing file)"
    return View("Coverage", _source(d.normalized), _dates(s), "sessions", origin=d.origin,
                tables={"Sessions per contract": listing, "Gaps between stored sessions": gaps})


COST_RATES = [
    ("Brokerage", f"{BROKERAGE_RATE_PCT:.2%} capped at Rs {BROKERAGE_MAX_PER_ORDER:g} per order"),
    ("Exchange transaction charge", f"{EXCHANGE_TRANSACTION_CHARGE_PCT:.4%}"),
    ("CTT (sell side)", f"{CTT_SELL_PCT:.2%}"),
    ("Stamp duty (buy side)", f"{STAMP_DUTY_BUY_PCT:.3%}"),
    ("SEBI turnover fee", f"Rs {SEBI_TURNOVER_FEE_PCT * 1e7:g} per crore"),
    ("GST on brokerage, exchange charge and SEBI fee", f"{GST_PCT:.0%}"),
]


def backtest_view(d: Derived) -> View:
    v = View("Backtest", "PREREGISTRATION.md and config.py",
             _dates(d.sessions) if d.sessions else "none", "rates", origin=d.origin,
             messages=["Not run: awaiting contiguous history and pre-registration"])
    v.tables["Cost rates"] = pd.DataFrame(
        [(name, value, "UNVERIFIED") for name, value in COST_RATES], columns=["rate", "value", "status"])
    return v
