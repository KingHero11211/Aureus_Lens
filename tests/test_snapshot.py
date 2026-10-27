"""Snapshot build and read-back, on the real October 2026 fixtures.

The store and snapshot are written to a temporary directory, never to data/.
"""

import hashlib
import json
import re
from datetime import date

import pandas as pd
import pytest

from app import views
from scripts.build_snapshot import main as build_main
from src.aureus_lens.ingest.csv_loader import FORMAT_COLUMNS, load_csv
from src.aureus_lens.snapshot import TABLES, read_snapshot
from src.aureus_lens.store.db import init_db, store_load
from tests.conftest import OCT_DIR

FIXTURES = sorted(OCT_DIR.glob("*.csv"))


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("snap")
    db, out = tmp / "store.duckdb", tmp / "snapshot"
    conn = init_db(db)
    for p in FIXTURES:
        store_load(conn, load_csv(p))
    conn.close()
    assert build_main(["--db", str(db), "--out", str(out), "--raw", str(OCT_DIR)]) == 0
    return views.derive(views.open_store(db)), read_snapshot(out), out


def every_view(d):
    out = [views.data_health_view(d), views.normalized_view(d), views.coverage_view(d), views.backtest_view(d)]
    for day in d.sessions:
        out.append(views.scanner_view(d, day))
        for o in views.pair_options(d, day).itertuples():
            out.append(views.waterfall_view(d, day, o.kind, o.leg_a, o.expiry_a, o.leg_b))
    return out


def test_snapshot_pages_match_store_pages(built):
    from_store, from_snapshot, _ = built
    a, b = every_view(from_store), every_view(from_snapshot)
    assert len(a) == len(b) > 100
    for va, vb in zip(a, b):
        assert (va.title, va.source, va.date_range, va.unit, va.carry_source, va.messages) == \
               (vb.title, vb.source, vb.date_range, vb.unit, vb.carry_source, vb.messages)
        assert list(va.tables) == list(vb.tables)
        for name in va.tables:
            pd.testing.assert_frame_equal(va.tables[name].reset_index(drop=True),
                                          vb.tables[name].reset_index(drop=True), check_dtype=False)


def test_origin_names_the_snapshot(built):
    _, from_snapshot, _ = built
    assert from_snapshot.origin.startswith("snapshot built ")
    assert "Read from: snapshot built" in views.normalized_view(from_snapshot).labels()


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


# Trade date, symbol and expiry identify a contract and session; every derived
# table needs them as keys. All other raw fields (prices, volume, value, OI,
# instrument, option type, strike) must not appear.
KEY_FIELDS = {"date", "symbol", "expirydate"}


def test_no_raw_bhavcopy_field_names(built):
    _, _, out = built
    raw = {_norm(c) for fmt in FORMAT_COLUMNS.values() for c in fmt} - KEY_FIELDS
    assert {"instrumentname", "close", "previousclose", "volumelots", "openinterestlots"} <= raw
    for name in TABLES:
        cols = list(pd.read_parquet(out / f"{name}.parquet").columns)
        assert "Instrument Name" not in cols and "INSTRUMENTNAME" not in cols
        clash = [c for c in cols if _norm(c) in raw]
        assert not clash, (name, clash)


def test_manifest_records_sources_sessions_commit_and_time(built):
    _, _, out = built
    m = json.loads((out / "manifest.json").read_text())
    names = [s["file"] for s in m["source_files"]]
    assert names == sorted(p.name for p in FIXTURES)
    for s in m["source_files"]:
        assert s["sha256"] == hashlib.sha256((OCT_DIR / s["file"]).read_bytes()).hexdigest()
    assert m["sessions"] == ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-09"]
    assert re.fullmatch(r"[0-9a-f]{40}", m["code_commit"])
    assert isinstance(m["code_tree_clean"], bool)
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00", m["built_at"])
    assert set(m["tables"]) == set(TABLES)


def test_build_fails_without_store(tmp_path, capsys):
    assert build_main(["--db", str(tmp_path / "none.duckdb"), "--out", str(tmp_path / "s")]) == 1
    assert "store not found" in capsys.readouterr().out


def test_load_data_prefers_store_then_snapshot(built, tmp_path):
    _, _, out = built
    d = views.load_data(tmp_path / "absent.duckdb", out)
    assert d.origin.startswith("snapshot built ") and d.sessions[-1] == date(2026, 10, 9)
    assert views.load_data(tmp_path / "absent.duckdb", tmp_path / "absent").empty
