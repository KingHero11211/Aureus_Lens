"""DuckDB Storage and Schema Management for Aureus Lens.

Contract-Native Relative-Value Engine for MCX Gold Futures.
Hack in Hills '26 - Phase 2 & Audit Refinement
"""

from datetime import date, datetime
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH: str = "data/aureus.duckdb"

BHAV_COLUMNS = [
    "date",
    "symbol",
    "expiry_date",
    "open",
    "high",
    "low",
    "close",
    "previous_close",
    "volume",
    "value",
    "oi",
    "volume_value",
    "volume_unit",
]


def init_db(path: str = DEFAULT_DB_PATH) -> duckdb.DuckDBPyConnection:
    """Initialize DuckDB database and create required tables and views.

    Tables:
        - bhav: Cleaned Bhavcopy futures quotes with primary key (date, symbol, expiry_date)
        - data_health: Audit logging for rejection events, date mismatches, and warnings (no PK)
        - coverage: Record tracking per trading day, symbol, and contract expiry
    Views:
        - contract_listing: Aggregated session count and lifespan per (symbol, expiry_date)
    """
    if path != ":memory:":
        db_path = Path(path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect(database=path)

    # 1. bhav table (Primary key on date, symbol, expiry_date)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bhav (
            date DATE,
            symbol VARCHAR,
            expiry_date DATE,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            previous_close DOUBLE,
            volume DOUBLE,
            value DOUBLE,
            oi DOUBLE,
            volume_value DOUBLE,
            volume_unit VARCHAR,
            PRIMARY KEY (date, symbol, expiry_date)
        );
        """
    )

    # 2. data_health table (no primary key, audit event log)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS data_health (
            date DATE,
            event VARCHAR,
            detail VARCHAR
        );
        """
    )

    # 3. coverage table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS coverage (
            date DATE,
            symbol VARCHAR,
            expiry_date DATE,
            row_count INTEGER,
            PRIMARY KEY (date, symbol, expiry_date)
        );
        """
    )

    # 4. contract_listing view
    conn.execute(
        """
        CREATE OR REPLACE VIEW contract_listing AS
        SELECT
            symbol,
            expiry_date,
            MIN(date) AS first_session,
            MAX(date) AS last_session,
            COUNT(*) AS total_sessions
        FROM bhav
        GROUP BY symbol, expiry_date;
        """
    )

    logger.info("DuckDB initialized successfully at %s", path)
    return conn


def get_connection(path: str = DEFAULT_DB_PATH) -> duckdb.DuckDBPyConnection:
    """Return an initialized connection to the DuckDB database."""
    return init_db(path)


def close_db(conn: duckdb.DuckDBPyConnection) -> None:
    """Safely close DuckDB connection."""
    if conn:
        try:
            conn.close()
        except Exception as e:
            logger.warning("Error closing DuckDB connection: %s", e)


def upsert_bhav(conn: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> None:
    """Insert DataFrame records into 'bhav' table, skipping duplicates.

    Uses DuckDB's primary key constraint on (date, symbol, expiry_date)
    with INSERT OR IGNORE semantics.
    """
    if df is None or df.empty:
        return

    missing_cols = [col for col in BHAV_COLUMNS if col not in df.columns]
    if missing_cols:
        raise ValueError(f"DataFrame missing required bhav columns: {missing_cols}")

    work_df = df[BHAV_COLUMNS].copy()

    # Ensure dates are stored as date objects (DuckDB DATE type)
    work_df["date"] = pd.to_datetime(work_df["date"]).dt.date
    work_df["expiry_date"] = pd.to_datetime(work_df["expiry_date"]).dt.date

    conn.execute(
        """
        INSERT OR IGNORE INTO bhav
        SELECT
            date::DATE,
            symbol::VARCHAR,
            expiry_date::DATE,
            open::DOUBLE,
            high::DOUBLE,
            low::DOUBLE,
            close::DOUBLE,
            previous_close::DOUBLE,
            volume::DOUBLE,
            value::DOUBLE,
            oi::DOUBLE,
            volume_value::DOUBLE,
            volume_unit::VARCHAR
        FROM work_df;
        """
    )


def update_coverage(conn: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> None:
    """Update coverage table from DataFrame row count per (date, symbol, expiry_date)."""
    if df is None or df.empty:
        return

    work_df = df[["date", "symbol", "expiry_date"]].copy()
    work_df["date"] = pd.to_datetime(work_df["date"]).dt.date
    work_df["expiry_date"] = pd.to_datetime(work_df["expiry_date"]).dt.date

    conn.execute(
        """
        INSERT INTO coverage (date, symbol, expiry_date, row_count)
        SELECT
            date::DATE,
            symbol::VARCHAR,
            expiry_date::DATE,
            count(*)::INTEGER AS row_count
        FROM work_df
        GROUP BY date, symbol, expiry_date
        ON CONFLICT (date, symbol, expiry_date)
        DO UPDATE SET row_count = excluded.row_count;
        """
    )


def log_health(
    conn: duckdb.DuckDBPyConnection,
    date_val: Union[date, datetime, str],
    event: str,
    detail: str,
) -> None:
    """Log an audit event or error into data_health table (no primary key)."""
    parsed_date: date
    if isinstance(date_val, str):
        date_clean = date_val.strip()
        if "/" in date_clean:
            parsed_date = datetime.strptime(date_clean, "%d/%m/%Y").date()
        else:
            parsed_date = datetime.strptime(date_clean, "%Y-%m-%d").date()
    elif isinstance(date_val, datetime):
        parsed_date = date_val.date()
    elif isinstance(date_val, date):
        parsed_date = date_val
    else:
        raise ValueError(f"Unsupported date type for log_health: {type(date_val)}")

    conn.execute(
        "INSERT INTO data_health (date, event, detail) VALUES (?::DATE, ?, ?);",
        [parsed_date, str(event), str(detail)],
    )


def check_continuity(conn: duckdb.DuckDBPyConnection) -> List[Dict[str, Any]]:
    """Continuity check: verify previous_close equals the close of prior trading day.

    Checks:
        For every (symbol, expiry_date) across ordered dates, verifies whether
        previous_close on day t equals close on day t-1.
        Logs any detected gaps to data_health with event='continuity_gap'.

    Returns:
        List of detected continuity gap records.
    """
    query = """
        WITH lagged AS (
            SELECT
                date,
                symbol,
                expiry_date,
                close,
                previous_close,
                LAG(close) OVER (PARTITION BY symbol, expiry_date ORDER BY date ASC) AS prior_close,
                LAG(date) OVER (PARTITION BY symbol, expiry_date ORDER BY date ASC) AS prior_date
            FROM bhav
        )
        SELECT
            date,
            symbol,
            expiry_date,
            previous_close,
            prior_close,
            prior_date
        FROM lagged
        WHERE prior_close IS NOT NULL
          AND ABS(previous_close - prior_close) > 0.01
        ORDER BY date ASC, symbol ASC;
    """
    gaps = conn.execute(query).fetchall()
    results = []

    for gap in gaps:
        d, sym, exp, prev_c, prior_c, prior_d = gap
        detail = (
            f"Continuity mismatch on {sym} exp {exp}: previous_close={prev_c} != "
            f"prior close={prior_c} on {prior_d}"
        )
        log_health(conn, d, "continuity_gap", detail)
        results.append({
            "date": d,
            "symbol": sym,
            "expiry_date": exp,
            "previous_close": prev_c,
            "prior_close": prior_c,
            "prior_date": prior_d,
            "detail": detail,
        })

    return results
