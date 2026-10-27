"""Export Bhavcopy Snapshot from DuckDB to Parquet.

Exports real data present in DuckDB to data/snapshot/bhav_snapshot.parquet.
Ground Rule 1: Never fabricate data. No hardcoded prices, turnover, or demo numbers.
If the database has no records, no snapshot is fabricated.

Usage:
    python -m scripts.generate_snapshot
"""

from pathlib import Path
import duckdb
import pandas as pd

from config import PROJECT_ROOT
from src.aureus_lens.store.db import DEFAULT_DB_PATH

SNAPSHOT_DIR = PROJECT_ROOT / "data" / "snapshot"
SNAPSHOT_PARQUET = SNAPSHOT_DIR / "bhav_snapshot.parquet"


def export_snapshot(db_path: str = DEFAULT_DB_PATH) -> int:
    """Export existing rows in DuckDB bhav table to Parquet without fabricating data."""
    db_file = Path(db_path)
    if not db_file.exists():
        print(f"[INFO] Database file does not exist at: {db_file}")
        return 0

    conn = duckdb.connect(database=str(db_file), read_only=True)
    try:
        df = conn.execute("SELECT * FROM bhav ORDER BY date ASC, symbol ASC").df()
    except Exception as e:
        print(f"[ERROR] Failed to query bhav table: {e}")
        conn.close()
        return 0
    finally:
        conn.close()

    if df.empty:
        print("[INFO] Database contains 0 rows in 'bhav'. No fake data generated per Ground Rule 1.")
        return 0

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(SNAPSHOT_PARQUET, index=False)
    print(f"[SUCCESS] Exported {len(df)} authentic records to: {SNAPSHOT_PARQUET}")
    return len(df)


def main() -> None:
    export_snapshot()


if __name__ == "__main__":
    main()
