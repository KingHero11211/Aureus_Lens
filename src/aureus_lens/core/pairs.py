"""Pair spreads between the four contracts, with gate and waterfall per pair.

Two kinds of pair:
  small_small  GOLDTEN, GOLDGUINEA, GOLDPETAL with the same expiry date. Same
               purity and expiry, so no purity or carry assumption.
  small_goldm  each small contract against the eligible GOLDM expiry nearest
               to it, aligned with carry. Depends on the UNVERIFIED purity
               factor and the carry estimate, so it is secondary.
"""

import math
from itertools import combinations

import pandas as pd

from config import CONTRACT_SPECS
from src.aureus_lens.core.costs import pair_cost_bps
from src.aureus_lens.core.curve import adjust_to_expiry, eligible_goldm
from src.aureus_lens.core.gate import DEFAULT_COST_MARGIN, executability_gate
from src.aureus_lens.core.normalize import normalize_ppg999, per_gram
from src.aureus_lens.core.signals import Z_MIN_PERIODS, Z_WINDOW, compute_zscore
from src.aureus_lens.core.spread import compute_spread_bps
from src.aureus_lens.core.waterfall import compute_waterfall

SMALL = ["GOLDTEN", "GOLDGUINEA", "GOLDPETAL"]
DEFAULT_Z_THRESHOLD = 2.0  # a chosen parameter, to be fixed in PREREGISTRATION.md


def tick_floor_bps(leg_a, leg_b) -> float:
    """Return one tick on each leg in bps of that leg's quoted price, summed."""
    total = 0.0
    for leg in (leg_a, leg_b):
        spec = CONTRACT_SPECS[leg["symbol"]]
        total += spec["tick_size"] / leg["close"] * 10_000.0
    return total


def _pair_row(a, b, kind, carry, carry_source, cost, margin):
    pg_a, pg_b = per_gram(a["symbol"], a["close"]), per_gram(b["symbol"], b["close"])
    ppg_a, ppg_b = normalize_ppg999(a), normalize_ppg999(b)
    days = (a["expiry_date"] - b["expiry_date"]).days
    if days == 0:
        ppg_b_aligned = ppg_b
    elif pd.isna(carry):
        ppg_b_aligned = math.nan
    else:
        ppg_b_aligned = adjust_to_expiry(ppg_b, carry, days)

    raw = compute_spread_bps(pg_a, pg_b)
    purity = compute_spread_bps(ppg_a, ppg_b)
    spread = math.nan if pd.isna(ppg_b_aligned) else compute_spread_bps(ppg_a, ppg_b_aligned)
    tick = tick_floor_bps(a, b)
    if pd.isna(spread):
        edge = math.nan
    else:
        edge = compute_waterfall(raw, purity, spread, tick, cost)[-1]["value"]
    passes, reasons = executability_gate(
        a, b, spread, cost, margin, carry_source if days else None)
    return {
        "date": a["date"], "kind": kind,
        "leg_a": a["symbol"], "expiry_a": a["expiry_date"],
        "leg_b": b["symbol"], "expiry_b": b["expiry_date"],
        "ppg_a": ppg_a, "ppg_b": ppg_b, "ppg_b_aligned": ppg_b_aligned,
        "raw_bps": raw, "purity_bps": purity, "spread_bps": spread,
        "tick_floor_bps": tick, "cost_bps": cost, "edge_bps": edge,
        "carry": carry if days else math.nan,
        "carry_source": carry_source if days else "not needed",
        "passes": passes, "reasons": reasons,
    }


def build_pairs(bhav: pd.DataFrame, carry: pd.DataFrame,
                notional: float = 1_000_000.0, margin: float = DEFAULT_COST_MARGIN,
                window: int = Z_WINDOW, min_periods: int = Z_MIN_PERIODS,
                z_threshold: float = DEFAULT_Z_THRESHOLD) -> pd.DataFrame:
    """Return one row per pair per session. Spreads are in bps of leg_b
    (aligned to leg_a's expiry); a positive spread means leg_a is dearer.
    zscore is computed per pair and expiry over stored sessions.

    passes means the gate found no failing check. signal additionally needs
    |zscore| >= z_threshold: a gap that is large but usual for the pair is
    not a signal. A NaN zscore (too little history) never signals."""
    cost = pair_cost_bps(notional)
    carry_by_date = carry.set_index("date")
    rows = []
    for d, day in bhav.groupby("date"):
        c = carry_by_date.loc[d]
        small = day[day["symbol"].isin(SMALL)]
        for _, same in small.groupby("expiry_date"):
            for (_, a), (_, b) in combinations(same.sort_values("symbol").iterrows(), 2):
                rows.append(_pair_row(a, b, "small_small", math.nan, "not needed", cost, margin))
        goldm = eligible_goldm(day, d)
        for _, a in small.iterrows():
            if goldm.empty:
                continue
            gap = (goldm["expiry_date"] - a["expiry_date"]).map(lambda t: abs(t.days))
            b = goldm.loc[gap.idxmin()]
            rows.append(_pair_row(a, b, "small_goldm", c["carry"], c["carry_source"], cost, margin))

    pairs = pd.DataFrame(rows)
    if pairs.empty:
        return pairs
    pairs = pairs.sort_values(["kind", "leg_a", "leg_b", "expiry_a", "date"]).reset_index(drop=True)
    pairs["zscore"] = pairs.groupby(["kind", "leg_a", "leg_b", "expiry_a"])["spread_bps"].transform(
        lambda s: compute_zscore(s, window=window, min_periods=min_periods))
    pairs["signal"] = pairs["passes"] & (pairs["zscore"].abs() >= z_threshold)
    return pairs
