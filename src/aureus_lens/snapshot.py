"""Write and read the derived snapshot in data/snapshot/.

The snapshot holds only the tables the dashboard derives (see app.views.Derived),
never raw bhavcopy rows, plus a manifest.json describing what it was built from.
"""

import json
from pathlib import Path
from typing import Any, Dict

import pandas as pd

TABLES = ["normalized", "pairs", "carry", "continuity", "load_log", "refused", "value_summary"]

DATE_COLUMNS = {
    "normalized": ["date", "expiry_date"],
    "pairs": ["date", "expiry_a", "expiry_b"],
    "carry": ["date", "carry_date", "near_expiry", "far_expiry"],
    "continuity": ["date", "expiry_date"],
    "load_log": ["first_date", "last_date"],
    "refused": ["date"],
    "value_summary": ["date"],
}


def write_snapshot(derived, out_dir: Path, manifest: Dict[str, Any]) -> Dict[str, int]:
    """Write one parquet file per derived table and manifest.json. Returns rows per table."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = {}
    for name in TABLES:
        df = getattr(derived, name).copy()
        if name == "pairs":
            df["reasons"] = df["reasons"].map(list)
        df.to_parquet(out_dir / f"{name}.parquet", index=False)
        rows[name] = len(df)
    manifest = dict(manifest, tables=rows)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n",
                                           encoding="utf-8", newline="\n")
    return rows


def _dates(series: pd.Series) -> pd.Series:
    return series.map(lambda v: None if v is None or pd.isna(v) else pd.Timestamp(v).date())


def read_manifest(snapshot_dir: Path) -> Dict[str, Any]:
    return json.loads((Path(snapshot_dir) / "manifest.json").read_text(encoding="utf-8"))


def read_snapshot(snapshot_dir: Path):
    """Return an app.views.Derived built from the snapshot files."""
    from app.views import Derived

    snapshot_dir = Path(snapshot_dir)
    manifest = read_manifest(snapshot_dir)
    tables = {}
    for name in TABLES:
        df = pd.read_parquet(snapshot_dir / f"{name}.parquet")
        for col in DATE_COLUMNS[name]:
            if col in df.columns:
                df[col] = _dates(df[col])
        if name == "pairs" and not df.empty:
            df["reasons"] = df["reasons"].map(list)
        tables[name] = df
    origin = f"snapshot built {manifest['built_at']} from commit {manifest['code_commit'][:10]}"
    return Derived(origin=origin, **tables)
