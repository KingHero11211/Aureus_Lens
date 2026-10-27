"""Shared fixtures: real rows for 5, 6, 7 and 9 Oct 2026.

The 8 Oct download was a copy of 9 Oct and is not used, so 7 Oct and 9 Oct
are consecutive stored sessions.
"""

from pathlib import Path

import pandas as pd
import pytest

from src.aureus_lens.ingest.csv_loader import load_csv

OCT_DIR = Path(__file__).parent / "fixtures" / "oct2026"


@pytest.fixture(scope="session")
def oct_bhav() -> pd.DataFrame:
    frames = [load_csv(p).rows for p in sorted(OCT_DIR.glob("*.csv"))]
    return pd.concat(frames, ignore_index=True)


def row(bhav: pd.DataFrame, day: str, symbol: str, expiry: str) -> pd.Series:
    d, e = pd.Timestamp(day).date(), pd.Timestamp(expiry).date()
    hit = bhav[(bhav["date"] == d) & (bhav["symbol"] == symbol) & (bhav["expiry_date"] == e)]
    assert len(hit) == 1, (day, symbol, expiry)
    return hit.iloc[0]
