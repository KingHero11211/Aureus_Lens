"""Historical Ingestion and Backfill Engine for MCX Bhavcopy.

Iterates calendar ranges, skips weekends, enforces date matching,
logs anomalies to DuckDB data_health, and records coverage.
Features resumable execution: skips loaded dates and dates logged as no_data or date_mismatch.
Retries fetch_error on subsequent runs.
"""

from datetime import date, datetime, timedelta
import logging
from pathlib import Path
import time
from typing import Any, Dict, Optional, Set, Tuple, Union

import duckdb

from config import CACHE_DIR
from src.aureus_lens.ingest.client import fetch_bhavcopy, get_session
from src.aureus_lens.ingest.validate import (
    _extract_response_date_str,
    clean_data,
    validate_response_date,
)
from src.aureus_lens.store.db import (
    DEFAULT_DB_PATH,
    close_db,
    init_db,
    log_health,
    update_coverage,
    upsert_bhav,
)

logger = logging.getLogger(__name__)


def _parse_date_input(val: Union[str, date, datetime]) -> date:
    """Parse date input from various string formats or date objects."""
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        clean_str = val.strip()
        if "/" in clean_str:
            return datetime.strptime(clean_str, "%d/%m/%Y").date()
        elif "-" in clean_str:
            return datetime.strptime(clean_str, "%Y-%m-%d").date()

    raise ValueError(f"Cannot parse date '{val}'. Expected 'YYYY-MM-DD' or 'DD/MM/YYYY'.")


def backfill_date_range(
    start_date: str,
    end_date: str,
    db_path: str = DEFAULT_DB_PATH,
    conn: Optional[duckdb.DuckDBPyConnection] = None,
    cache_dir: Optional[Path] = None,
    rate_limit_delay: float = 1.0,
    force_refetch: bool = False,
) -> Dict[str, Any]:
    """Backfill MCX Bhavcopy data over a date range into DuckDB.

    Resumable Execution:
        - Automatically queries DuckDB to skip dates already loaded in 'bhav'.
        - Skips dates already recorded in 'data_health' as 'date_mismatch', 'no_data', or 'holiday'.
        - Dates with 'fetch_error' are NOT skipped and will be re-attempted.
        - Skips Saturdays and Sundays.
        - Enforces 1 request/second rate limiting.
    """
    start_d = _parse_date_input(start_date)
    end_d = _parse_date_input(end_date)

    if start_d > end_d:
        raise ValueError(f"Start date {start_d} must be <= end date {end_d}")

    should_close_conn = False
    if conn is None:
        conn = init_db(db_path)
        should_close_conn = True

    # Resumable tracking: load existing completed dates from database
    loaded_dates: Set[date] = set()
    skip_health_dates: Set[date] = set()

    if not force_refetch:
        try:
            bhav_dates = conn.execute("SELECT DISTINCT date FROM bhav").fetchall()
            loaded_dates = {r[0] for r in bhav_dates}

            health_dates = conn.execute(
                "SELECT DISTINCT date FROM data_health WHERE event IN ('date_mismatch', 'no_data', 'holiday')"
            ).fetchall()
            skip_health_dates = {r[0] for r in health_dates}
        except Exception as e:
            logger.warning("Could not query existing dates for resume check: %s", e)

    session = get_session()
    current_d = start_d
    stats = {
        "processed_days": 0,
        "already_loaded_skipped": 0,
        "health_skipped": 0,
        "skipped_weekends": 0,
        "date_mismatches": 0,
        "errors": 0,
        "total_rows_inserted": 0,
    }

    try:
        while current_d <= end_d:
            iso_str = current_d.strftime("%Y-%m-%d")
            mcx_date_str = current_d.strftime("%d/%m/%Y")

            # 1. Skip weekends (Saturday=5, Sunday=6)
            if current_d.weekday() >= 5:
                stats["skipped_weekends"] += 1
                current_d += timedelta(days=1)
                continue

            # 2. Resumable check: skip already loaded dates
            if current_d in loaded_dates:
                stats["already_loaded_skipped"] += 1
                current_d += timedelta(days=1)
                continue

            # 3. Resumable check: skip dates known to be mismatch, holiday, or no_data
            if current_d in skip_health_dates:
                stats["health_skipped"] += 1
                current_d += timedelta(days=1)
                continue

            stats["processed_days"] += 1

            # 4. Fetch raw data
            try:
                raw_response = fetch_bhavcopy(
                    mcx_date_str,
                    session=session,
                    cache_dir=cache_dir or CACHE_DIR,
                )
            except Exception as exc:
                stats["errors"] += 1
                detail = f"Fetch failed: {exc}"
                log_health(conn, current_d, "fetch_error", detail)
                print(f"{iso_str}: Fetch failed ({exc})")
                time.sleep(rate_limit_delay)
                current_d += timedelta(days=1)
                continue

            # 5. Date validation check
            if not validate_response_date(mcx_date_str, raw_response):
                stats["date_mismatches"] += 1
                resp_d = _extract_response_date_str(raw_response) or "missing_date"
                detail = f"Requested {mcx_date_str}, MCX returned {resp_d} (holiday or rollback)"
                log_health(conn, current_d, "date_mismatch", detail)
                skip_health_dates.add(current_d)
                print(f"{iso_str}: Date mismatch ({detail})")
                time.sleep(rate_limit_delay)
                current_d += timedelta(days=1)
                continue

            # 6. Clean data
            try:
                df = clean_data(raw_response)
            except Exception as clean_err:
                stats["errors"] += 1
                detail = f"Data clean failed: {clean_err}"
                log_health(conn, current_d, "clean_error", detail)
                print(f"{iso_str}: Clean failed ({clean_err})")
                time.sleep(rate_limit_delay)
                current_d += timedelta(days=1)
                continue

            # 7. Upsert to DuckDB and update coverage
            row_count = len(df)
            if row_count > 0:
                upsert_bhav(conn, df)
                update_coverage(conn, df)
                loaded_dates.add(current_d)
                symbol_count = df["symbol"].nunique()
                stats["total_rows_inserted"] += row_count
                print(f"{iso_str}: {row_count} rows, {symbol_count} symbols")
            else:
                log_health(conn, current_d, "no_data", "No target gold futures in raw payload")
                skip_health_dates.add(current_d)
                print(f"{iso_str}: 0 rows (no target gold futures)")

            # 8. Rate limit
            time.sleep(rate_limit_delay)
            current_d += timedelta(days=1)

    finally:
        if should_close_conn and conn:
            close_db(conn)

    return stats
