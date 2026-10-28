"""In-memory processing of user-uploaded MCX bhavcopy CSV files.

Parses files directly from memory into an in-memory DuckDB store.
Performs checksum deduplication, date matching against filenames,
and derives all analytics in-session without writing anything to disk.
"""

from dataclasses import dataclass
from datetime import date
import hashlib
import io
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd

from app.views import Derived, Store, derive, read_store
from src.aureus_lens.ingest.bhav_loader import filename_date, load_csv
from src.aureus_lens.reconcile import check_continuity, continuity_events
from src.aureus_lens.store.db import (
    init_db,
    log_refused_file,
    read_bhav,
    replace_health_events,
    store_load,
)


@dataclass
class FileUploadReport:
    name: str
    format: str
    internal_date: str
    rows_kept: int
    rejects: int
    reject_reasons: Dict[str, int]
    date_match: str
    status: str
    checksum: str
    detail: str


def _get_bytes(f: Any) -> Tuple[str, bytes]:
    """Extract (filename, content_bytes) from a path, UploadedFile, or tuple."""
    if isinstance(f, tuple) and len(f) == 2:
        name, content = f
        if isinstance(content, str):
            content = content.encode("utf-8")
        elif hasattr(content, "read"):
            content = content.read()
        return str(name), bytes(content)

    if isinstance(f, (str, Path)):
        p = Path(f)
        return p.name, p.read_bytes()

    name = getattr(f, "name", "uploaded.csv")
    if hasattr(f, "getvalue"):
        return str(name), f.getvalue()
    if hasattr(f, "read"):
        pos = f.tell() if hasattr(f, "tell") else None
        b = f.read()
        if pos is not None and hasattr(f, "seek"):
            f.seek(pos)
        return str(name), bytes(b)

    raise ValueError(f"Unsupported file input type: {type(f)}")


def process_uploaded_files(
    files: List[Any],
) -> Tuple[Derived, List[FileUploadReport]]:
    """Process uploaded Bhavcopy CSV files in memory.

    Accepts a list of file paths, UploadedFile objects, or (name, bytes) tuples.
    Returns (Derived, List[FileUploadReport]).
    """
    reports: List[FileUploadReport] = []
    seen_checksums: Dict[str, str] = {}
    conn = init_db(":memory:")

    try:
        for f in files:
            name, content_bytes = _get_bytes(f)
            checksum = hashlib.sha256(content_bytes).hexdigest()

            # 1. Deduplication by checksum
            if checksum in seen_checksums:
                first_name = seen_checksums[checksum]
                reports.append(
                    FileUploadReport(
                        name=name,
                        format="Unknown",
                        internal_date="none",
                        rows_kept=0,
                        rejects=0,
                        reject_reasons={},
                        date_match="Duplicate",
                        status="Refused: duplicate file",
                        checksum=checksum,
                        detail=f"Duplicate content matches {first_name}",
                    )
                )
                named = filename_date(name)
                log_refused_file(
                    conn,
                    name,
                    named,
                    f"duplicate file (checksum matches {first_name})",
                )
                continue

            seen_checksums[checksum] = name

            # 2. Parse CSV from memory
            try:
                stream = io.StringIO(content_bytes.decode("utf-8", errors="replace"))
                result = load_csv(stream, filename=name)
            except Exception as err:
                reports.append(
                    FileUploadReport(
                        name=name,
                        format="Unknown",
                        internal_date="none",
                        rows_kept=0,
                        rejects=0,
                        reject_reasons={},
                        date_match="Unknown",
                        status="Refused: parse error",
                        checksum=checksum,
                        detail=str(err),
                    )
                )
                log_refused_file(conn, name, filename_date(name), f"parse error: {err}")
                continue

            # 3. Date extraction and match check
            named = filename_date(name)
            found_dates = sorted(set(result.rows["date"]))
            internal_str = ", ".join(d.isoformat() for d in found_dates) if found_dates else "none"

            reject_counts = {
                str(k): int(v) for k, v in result.rejects["reason"].value_counts().items()
            }

            if named is not None and found_dates and set(found_dates) != {named}:
                date_match = f"Mismatch (file says {named}, rows dated {internal_str})"
                detail = f"file name says {named}, rows are dated {internal_str}; not stored"
                reports.append(
                    FileUploadReport(
                        name=name,
                        format=f"Format {result.format}",
                        internal_date=internal_str,
                        rows_kept=0,
                        rejects=len(result.rejects),
                        reject_reasons=reject_counts,
                        date_match=date_match,
                        status="Refused: date mismatch",
                        checksum=checksum,
                        detail=detail,
                    )
                )
                log_refused_file(conn, name, named, detail)
                continue

            date_match = "Match" if named is not None else "No date in filename"

            # 4. Store valid load in memory
            store_load(conn, result)
            reports.append(
                FileUploadReport(
                    name=name,
                    format=f"Format {result.format}",
                    internal_date=internal_str,
                    rows_kept=len(result.rows),
                    rejects=len(result.rejects),
                    reject_reasons=reject_counts,
                    date_match=date_match,
                    status="Loaded",
                    checksum=checksum,
                    detail=f"Stored {len(result.rows)} rows",
                )
            )

        # 5. Continuity and derived tables
        bhav = read_bhav(conn)
        if not bhav.empty:
            cont = check_continuity(bhav)
            replace_health_events(conn, "continuity", continuity_events(cont))
            store = read_store(conn)
            derived = derive(store, origin="Uploaded files")
        else:
            store = read_store(conn)
            derived = derive(store, origin="")

        return derived, reports
    finally:
        conn.close()
