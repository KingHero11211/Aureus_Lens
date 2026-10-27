"""Build data/snapshot/ from the DuckDB store.

Usage:
    python scripts/build_snapshot.py [--db PATH] [--out DIR] [--raw DIR]

Writes the derived tables the dashboard uses as parquet files and a
manifest.json with source file names, their SHA-256 checksums, the sessions
covered, the code commit and the build time. Raw rows are not written.
"""

import argparse
import hashlib
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.views import derive, open_store  # noqa: E402
from config import DATA_DIR, RAW_DIR  # noqa: E402
from src.aureus_lens.snapshot import write_snapshot  # noqa: E402
from src.aureus_lens.store.db import DEFAULT_DB_PATH  # noqa: E402


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=str(ROOT / DEFAULT_DB_PATH))
    parser.add_argument("--out", default=str(DATA_DIR / "snapshot"))
    parser.add_argument("--raw", default=str(RAW_DIR))
    args = parser.parse_args(argv)

    if not Path(args.db).exists():
        print(f"error:   store not found at {args.db}")
        return 1
    derived = derive(open_store(args.db))
    if derived.empty:
        print("error:   store has no rows; nothing to snapshot")
        return 1

    raw = Path(args.raw)
    sources = []
    for name in sorted(derived.load_log["source_file"]):
        path = raw / name
        if not path.exists():
            print(f"error:   source file {path} not found; cannot record its checksum")
            return 1
        sources.append({"file": name, "sha256": sha256(path)})
    refused = []
    for detail in derived.refused.get("detail", []):
        name = detail.split(":")[0]
        path = raw / name
        refused.append({"file": name, "sha256": sha256(path) if path.exists() else None, "reason": detail})

    manifest = {
        "source_files": sources,
        "refused_files": refused,
        "sessions": [d.isoformat() for d in derived.sessions],
        "code_commit": git("rev-parse", "HEAD"),
        "code_tree_clean": git("status", "--porcelain") == "",
        "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    rows = write_snapshot(derived, Path(args.out), manifest)
    print(f"snapshot: {args.out}")
    for name, n in rows.items():
        print(f"  {name:<14}{n:>6} rows")
    print(f"sessions: {', '.join(manifest['sessions'])}")
    print(f"commit:   {manifest['code_commit']} (clean tree: {manifest['code_tree_clean']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
