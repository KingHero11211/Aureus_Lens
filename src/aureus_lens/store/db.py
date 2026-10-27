"""DuckDB store for bhavcopy rows, load records and data health events."""

from pathlib import Path
from typing import Union

import duckdb
import pandas as pd

from src.aureus_lens.ingest.csv_loader import SCHEMA, LoadResult

DEFAULT_DB_PATH: str = "data/aureus.duckdb"

BHAV_COLUMNS = SCHEMA + ["source_file"]

_DDL = """
CREATE TABLE IF NOT EXISTS bhav (
    date DATE NOT NULL,
    symbol VARCHAR NOT NULL,
    expiry_date DATE NOT NULL,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE NOT NULL,
    previous_close DOUBLE NOT NULL,
    volume_lots BIGINT NOT NULL,
    volume_000s DOUBLE,
    volume_unit VARCHAR,
    value_lakhs DOUBLE NOT NULL,
    oi_lots BIGINT NOT NULL,
    zero_volume BOOLEAN NOT NULL,
    source_file VARCHAR NOT NULL,
    PRIMARY KEY (date, symbol, expiry_date)
);
CREATE TABLE IF NOT EXISTS load_log (
    source_file VARCHAR PRIMARY KEY,
    format VARCHAR NOT NULL,
    first_date DATE,
    last_date DATE,
    rows_kept INTEGER NOT NULL,
    rows_rejected INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS reject_counts (
    source_file VARCHAR NOT NULL,
    reason VARCHAR NOT NULL,
    n INTEGER NOT NULL,
    PRIMARY KEY (source_file, reason)
);
CREATE TABLE IF NOT EXISTS data_health (
    date DATE NOT NULL,
    symbol VARCHAR,
    expiry_date DATE,
    event VARCHAR NOT NULL,
    detail VARCHAR NOT NULL
);
CREATE OR REPLACE VIEW contract_listing AS
SELECT symbol, expiry_date,
       MIN(date) AS first_session, MAX(date) AS last_session,
       COUNT(*) AS sessions
FROM bhav GROUP BY symbol, expiry_date;
"""


def init_db(path: Union[str, Path] = DEFAULT_DB_PATH) -> duckdb.DuckDBPyConnection:
    """Open the store at path (":memory:" allowed) and create missing tables."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(path))
    for stmt in _DDL.split(";"):
        if stmt.strip():
            conn.execute(stmt)
    return conn


def store_load(conn: duckdb.DuckDBPyConnection, result: LoadResult) -> int:
    """Write one parsed file. Returns the number of bhav rows not seen before.

    Reloading the same file replaces its rows and records, so repeated loads
    leave the store unchanged.
    """
    source = result.path.name
    rows = result.rows.assign(source_file=source)[BHAV_COLUMNS]
    before = conn.execute("SELECT COUNT(*) FROM bhav").fetchall()[0][0]

    conn.register("incoming", rows)
    conn.execute("INSERT OR REPLACE INTO bhav SELECT * FROM incoming")
    conn.unregister("incoming")

    dates = sorted(result.rows["date"])
    conn.execute("DELETE FROM load_log WHERE source_file = ?", [source])
    conn.execute(
        "INSERT INTO load_log VALUES (?, ?, ?, ?, ?, ?)",
        [source, result.format, dates[0] if dates else None,
         dates[-1] if dates else None, len(result.rows), len(result.rejects)],
    )
    conn.execute("DELETE FROM reject_counts WHERE source_file = ?", [source])
    for reason, n in result.rejects["reason"].value_counts().items():
        conn.execute("INSERT INTO reject_counts VALUES (?, ?, ?)", [source, reason, int(n)])

    return conn.execute("SELECT COUNT(*) FROM bhav").fetchall()[0][0] - before


def read_bhav(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Return all bhav rows ordered by date, symbol, expiry."""
    df = conn.execute("SELECT * FROM bhav ORDER BY date, symbol, expiry_date").df()
    for col in ["date", "expiry_date"]:
        df[col] = pd.to_datetime(df[col]).dt.date
    return df


def replace_health_events(
    conn: duckdb.DuckDBPyConnection, source: str, events: pd.DataFrame
) -> None:
    """Replace all data_health rows whose event starts with source."""
    conn.execute("DELETE FROM data_health WHERE event LIKE ?", [source + "%"])
    if events.empty:
        return
    conn.register("events", events[["date", "symbol", "expiry_date", "event", "detail"]])
    conn.execute("INSERT INTO data_health SELECT * FROM events")
    conn.unregister("events")
