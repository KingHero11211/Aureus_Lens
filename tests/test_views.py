"""Dashboard view functions, tested without Streamlit.

Stores are built in memory from the real October 2026 fixtures. The smoke
test reads data/aureus.duckdb read-only and is skipped if it is absent.
"""

import re
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from app import views
from config import PROJECT_ROOT
from src.aureus_lens.ingest.csv_loader import load_csv
from src.aureus_lens.store.db import DEFAULT_DB_PATH, init_db, store_load
from tests.conftest import OCT_DIR

STORE_PATH = PROJECT_ROOT / DEFAULT_DB_PATH
ONE_DAY = OCT_DIR / "BhavCopyDateWise_09102026_futures.csv"


def make_store(paths):
    conn = init_db(":memory:")
    for p in paths:
        store_load(conn, load_csv(p))
    s = views.derive(views.read_store(conn))
    conn.close()
    return s


@pytest.fixture(scope="module")
def oct_store():
    return make_store(sorted(OCT_DIR.glob("*.csv")))


@pytest.fixture(scope="module")
def empty_store():
    return views.load_data(Path("does-not-exist.duckdb"), Path("no-snapshot-here"))


def all_views(store):
    d = store.sessions[-1]
    o = views.pair_options(store, d).iloc[0]
    return [views.data_health_view(store), views.normalized_view(store), views.scanner_view(store),
            views.waterfall_view(store, d, o["kind"], o["leg_a"], o["expiry_a"], o["leg_b"]),
            views.coverage_view(store), views.backtest_view(store)]


PAIR_TABLES = ["same expiry, small vs small", "small vs GOLDM (depends on purity assumption)"]


def pair_tables(view):
    return [view.tables[name] for name in PAIR_TABLES]


def numbers_in(frame: pd.DataFrame, col: str) -> bool:
    return frame[col].map(lambda v: bool(re.fullmatch(r"-?\d+(\.\d+)?", str(v)))).any()


def test_thresholds_read_from_code():
    from src.aureus_lens.core import signals
    assert views.Z_WINDOW == signals.Z_WINDOW == 60
    assert views.Z_MIN_PERIODS == signals.Z_MIN_PERIODS == 60
    assert views.Z_THRESHOLD == 2.0


def test_dashboard_and_code_agree_on_first_zscore():
    # Plain number series (not prices): 62 sessions of one pair.
    from src.aureus_lens.core.signals import compute_zscore
    spread = pd.Series([float(i % 7) for i in range(62)])
    pairs = pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=62).date, "kind": "small_small",
        "leg_a": "GOLDPETAL", "leg_b": "GOLDTEN", "expiry_a": date(2027, 1, 29),
        "spread_bps": spread, "zscore": compute_zscore(spread)})
    pairs["baseline"] = views.baseline_counts(pairs)
    shown = views.z_display(pairs)
    assert pairs["baseline"].iloc[59] == 59 and pairs["baseline"].iloc[60] == 60
    assert shown.iloc[59] == "insufficient history (59 of 60 sessions)"
    assert pd.isna(pairs["zscore"].iloc[59])
    assert shown.iloc[60] == f"{pairs['zscore'].iloc[60]:.2f}" and pd.notna(pairs["zscore"].iloc[60])
    # Wherever the code has a value the dashboard shows it, and only there.
    assert (pairs["zscore"].notna() == ~shown.str.startswith("insufficient")).all()


# Labels

def test_every_view_has_source_dates_and_unit(oct_store):
    for v in all_views(oct_store):
        label = v.labels()
        assert "Source: " in label and "Dates: " in label and "Unit: " in label
        assert v.source and v.date_range and v.unit


def test_carry_source_shown_where_carry_is_used(oct_store):
    by_title = {v.title: v for v in all_views(oct_store)}
    assert "carry_source: empirical" in by_title["Spread Scanner"].labels()
    assert "carry_source:" in by_title["Waterfall"].labels()


def test_source_range_ordered_by_date(oct_store):
    v = views.normalized_view(oct_store)
    assert v.source.startswith("BhavCopyDateWise_05102026") and "09102026" in v.source


# Empty state

def test_empty_store_shows_empty_state_on_every_page(empty_store):
    pages = [views.data_health_view(empty_store), views.normalized_view(empty_store),
             views.scanner_view(empty_store), views.waterfall_view(empty_store, None, None, None, None, None),
             views.coverage_view(empty_store)]
    for v in pages:
        assert v.empty and views.EMPTY in v.messages
        assert all(name.startswith("NOT RUN") for name in v.tables)
    bt = views.backtest_view(empty_store)
    assert bt.messages == ["Not run: awaiting contiguous history and pre-registration"]


# History rules

def test_zscore_column_shows_insufficient_history_not_numbers(oct_store):
    v = views.scanner_view(oct_store)
    small = v.tables["same expiry, small vs small"]
    # 9 Oct: each series has three earlier sessions (5, 6, 7 Oct).
    assert (small["zscore"] == "insufficient history (3 of 60 sessions)").all()
    for table in pair_tables(v):
        assert table["zscore"].str.startswith("insufficient history (").all()
        assert not numbers_in(table, "zscore")


def test_no_signal_below_window_even_if_code_would_signal(oct_store, monkeypatch):
    # Force the code path to mark signals; the view must still show none.
    real = views.build_pairs
    monkeypatch.setattr(views, "build_pairs",
                        lambda *a, **k: real(*a, **k).assign(signal=True, zscore=5.0))
    v = views.scanner_view(oct_store)
    for table in pair_tables(v):
        assert not table["signal"].any()
        assert not numbers_in(table, "zscore")


def test_one_session_normalized_view_says_insufficient():
    v = views.normalized_view(make_store([ONE_DAY]))
    assert "Series view: insufficient history (1 of 2 sessions)" in v.messages


# Scanner

def test_no_actionable_signal_with_reasons(oct_store):
    msg = views.scanner_view(oct_store).messages[0]
    assert msg.startswith("No actionable signal. Reasons: ")
    assert "z-score history below 60 sessions on 36 pairs (longest 3 of 60)" in msg
    assert "below 2x cost" in msg


def test_small_small_first_and_goldm_labelled(oct_store):
    names = list(views.scanner_view(oct_store).tables)
    assert names[:2] == PAIR_TABLES


def test_all_failing_reasons_listed(oct_store):
    t = views.scanner_view(oct_store, date(2026, 10, 9)).tables["same expiry, small vs small"]
    failed = t[t["gate"] == "fail"]
    assert not failed.empty and (failed["failing reasons"] != "").all()
    assert (t.loc[t["gate"] == "pass", "failing reasons"] == "").all()


# Waterfall

def test_waterfall_stage_order_and_values(oct_store):
    v = views.waterfall_view(oct_store, date(2026, 10, 9), "small_small",
                             "GOLDPETAL", date(2026, 10, 30), "GOLDTEN")
    stages = next(iter(v.tables.values()))
    assert list(stages["stage"]) == ["raw", "purity", "carry", "tick floor", "cost", "executable edge"]
    assert stages["value"].iloc[0] == pytest.approx(36.6213, abs=1e-4)
    assert stages["value"].iloc[-1] == pytest.approx(36.6213 - 0.7287 - 4.3824, abs=1e-3)


# Coverage and data health

def test_coverage_flags_missing_weekday_as_unchecked(oct_store):
    gaps = views.coverage_view(oct_store).tables["Gaps between stored sessions"]
    assert gaps.values.tolist() == [[date(2026, 10, 7), date(2026, 10, 9), 1,
                                     "unchecked (holiday or missing file)"]]


def test_data_health_continuity_counts(oct_store):
    counts = views.data_health_view(oct_store).tables[
        "Continuity (previous close vs prior stored close)"].set_index("status")["rows"]
    assert counts.to_dict() == {"ok": 47, "gap": 0, "unchecked": 24, "new": 1, "first": 24}


def test_not_run_items_parsed_from_verification():
    items = views.not_run_items()
    assert "1.10" in set(items["item"])
    assert "2.6" not in set(items["item"])  # passed since step 3


# Backtest

def test_backtest_lists_every_cost_rate_unverified(empty_store):
    t = views.backtest_view(empty_store).tables["Cost rates"]
    assert len(t) == 6 and (t["status"] == "UNVERIFIED").all()


def test_no_view_shows_unreconciled_mcx_figure(oct_store):
    for v in all_views(oct_store):
        text = " ".join(v.messages) + " ".join(t.to_string() for t in v.tables.values())
        assert "5,563" not in text and "5563" not in text


# Smoke test on the real store, read-only

@pytest.mark.skipif(not STORE_PATH.exists(), reason="NOT RUN: data/aureus.duckdb not present")
def test_smoke_real_store():
    before = STORE_PATH.stat().st_mtime
    store = views.derive(views.open_store(STORE_PATH))
    assert store.sessions
    for v in all_views(store):
        assert v.labels()
    assert STORE_PATH.stat().st_mtime == before


# Carry minimum sessions (CARRY_MIN_SESSIONS = 5)

SAMPLE_B = Path(__file__).parent / "fixtures" / "format_b_20260121_sample.csv"


def test_carry_min_sessions_in_config():
    from config import CARRY_MIN_SESSIONS
    assert CARRY_MIN_SESSIONS == 5


def test_single_session_carry_not_shown():
    v = views.scanner_view(make_store([ONE_DAY]))
    carry = v.tables["Carry from GOLDM curve (per year, continuous)"]
    assert carry["carry per year"].tolist() == ["insufficient history (1 of 5 sessions)"]
    goldm = v.tables["small vs GOLDM (depends on purity assumption)"]
    assert (goldm["spread_bps"] == "carry insufficient history (1 of 5 sessions)").all()
    assert (goldm["gate"] == "not evaluated").all()


def test_four_october_sessions_carry_not_shown(oct_store):
    carry = views.scanner_view(oct_store).tables["Carry from GOLDM curve (per year, continuous)"]
    assert carry["carry per year"].iloc[-1] == "insufficient history (4 of 5 sessions)"
    assert not carry["carry per year"].str.match(r"^-?\d").any()


def test_five_sessions_with_valid_carry_are_shown():
    # 21 Jan 2026 (format B sample: GOLDM Feb and Mar active) plus 5, 6, 7, 9 Oct.
    store = make_store([SAMPLE_B] + sorted(OCT_DIR.glob("*.csv")))
    v = views.scanner_view(store)
    carry = v.tables["Carry from GOLDM curve (per year, continuous)"].set_index("date")
    assert list(carry["carry_source"]) == ["empirical"] * 5
    assert carry.loc[date(2026, 10, 9), "carry per year"] == "0.111010"
    assert carry.loc[date(2026, 10, 7), "carry per year"].startswith("insufficient history (4 of 5")
    goldm = v.tables["small vs GOLDM (depends on purity assumption)"]
    assert goldm["spread_bps"].map(lambda x: isinstance(x, float)).all()


def test_waterfall_goldm_pair_hidden_below_carry_minimum(oct_store):
    v = views.waterfall_view(oct_store, date(2026, 10, 9), "small_goldm",
                             "GOLDTEN", date(2026, 10, 30), "GOLDM")
    assert not v.tables
    assert v.messages == ["Carry step not shown: carry insufficient history (4 of 5 sessions)"]
