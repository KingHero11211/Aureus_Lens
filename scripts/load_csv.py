"""Parse bhavcopy CSV files and print a per-file report.

Usage:
    python -m scripts.load_csv FILE [FILE ...]
"""

import argparse
import sys
from typing import List

from src.aureus_lens.ingest.csv_loader import LoadResult, load_csv


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
    args = parser.parse_args(argv)

    status = 0
    for path in args.paths:
        try:
            print(format_report(load_csv(path)))
        except (ValueError, OSError) as err:
            print(f"file:    {path}\nerror:   {err}")
            status = 1
        print()
    return status


if __name__ == "__main__":
    sys.exit(main())
