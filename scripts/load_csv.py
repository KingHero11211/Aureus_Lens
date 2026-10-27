"""Load bhavcopy CSV files into the store and print a per-file report.

Usage:
    python -m scripts.load_csv FILE [FILE ...] [--db PATH] [--notes PATH] [--dry-run]

After loading, runs the continuity check over the whole store, logs flagged
rows to data_health and rewrites the data notes report.
"""

import argparse
import sys
from pathlib import Path
from typing import List

from config import PROJECT_ROOT
from src.aureus_lens.ingest.csv_loader import LoadResult, filename_date, load_csv
from src.aureus_lens.reconcile import check_continuity, continuity_events, render_data_notes
from src.aureus_lens.store.db import (
    DEFAULT_DB_PATH,
    init_db,
    log_refused_file,
    read_bhav,
    replace_health_events,
    store_load,
)

DEFAULT_NOTES = PROJECT_ROOT / "docs" / "data_notes.md"


def format_report(result: LoadResult) -> str:
    """Return a plain-text report: format, dates, kept rows, rejects, value in crore."""
    rows, rejects = result.rows, result.rejects
    dates = sorted({d.isoformat() for d in rows["date"]})
    lines = [
        f"file:    {result.path}",
        f"format:  {result.format}",
        f"dates:   {', '.join(dates) if dates else 'none'}",
        f"kept:    {len(rows)} rows",
    ]
    for sym, n in rows.groupby("symbol").size().items():
        zero = int(rows.loc[rows["symbol"] == sym, "zero_volume"].sum())
        lines.append(f"  {sym:<11}{n:>4} rows ({zero} zero-volume)")
    lines.append(f"rejected: {len(rejects)} rows")
    for reason, n in rejects["reason"].value_counts().items():
        lines.append(f"  {reason:<30}{n:>7}")
    lines.append("value (Rs crore):")
    for (sym, exp), v in rows.groupby(["symbol", "expiry_date"])["value_lakhs"].sum().items():
        lines.append(f"  {sym:<11}{exp.isoformat()}{v / 100:>12,.2f}")
    for sym, v in rows.groupby("symbol")["value_lakhs"].sum().items():
        lines.append(f"  {sym:<11}{'all':<10}{v / 100:>12,.2f}")
    return "\n".join(lines)


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--notes", default=str(DEFAULT_NOTES))
    parser.add_argument("--dry-run", action="store_true", help="parse and report only")
    args = parser.parse_args(argv)

    conn = None if args.dry_run else init_db(args.db)
    status = 0
    for path in args.paths:
        try:
            result = load_csv(path)
        except (ValueError, OSError) as err:
            print(f"file:    {path}\nerror:   {err}\n")
            status = 1
            continue
        print(format_report(result))
        named = filename_date(path)
        found = set(result.rows["date"])
        if named is not None and found and found != {named}:
            detail = (f"file name says {named}, rows are dated "
                      f"{', '.join(sorted(d.isoformat() for d in found))}; not stored")
            print(f"error:   {detail}\n")
            if conn is not None:
                log_refused_file(conn, Path(path).name, named, detail)
            status = 1
            continue
        if conn is not None:
            print(f"stored:  {store_load(conn, result)} new rows")
        print()

    if conn is None:
        return status

    bhav = read_bhav(conn)
    cont = check_continuity(bhav)
    replace_health_events(conn, "continuity", continuity_events(cont))
    print("continuity:", ", ".join(f"{k} {v}" for k, v in cont["status"].value_counts().sort_index().items()) or "no rows")

    notes = render_data_notes(
        bhav,
        conn.execute("SELECT * FROM load_log").df(),
        conn.execute("SELECT * FROM reject_counts").df(),
        cont,
        conn.execute("SELECT detail FROM data_health WHERE event = 'file_refused' ORDER BY 1").df(),
    )
    Path(args.notes).parent.mkdir(parents=True, exist_ok=True)
    Path(args.notes).write_text(notes, encoding="utf-8", newline="\n")
    print(f"notes:   {args.notes}")
    conn.close()
    return status


if __name__ == "__main__":
    sys.exit(main())
