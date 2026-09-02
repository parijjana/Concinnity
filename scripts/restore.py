#!/usr/bin/env python3
"""Rebuild a Concinnity database from a SQL dump.

Deliberately refuses to overwrite an existing database without --force. Restoring the *other*
machine's dump over this machine's board would silently destroy rankings that exist nowhere else,
and that is exactly the accident a per-host backup layout is meant to make hard.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


def restore(dump: Path, target: Path, force: bool = False) -> dict[str, int]:
    if not dump.exists():
        raise SystemExit(f"dump not found: {dump}")
    if target.exists() and not force:
        raise SystemExit(
            f"{target} already exists. Refusing to overwrite a live database — pass --force if "
            "you really mean to replace it, or restore to a new path and compare first."
        )
    if target.exists():
        target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    try:
        conn.executescript(dump.read_text(encoding="utf-8"))
        conn.commit()
        names = [r[0] for r in conn.execute(
            "select name from sqlite_master where type='table' order by name")]
        return {n: conn.execute(f'select count(*) from "{n}"').fetchone()[0] for n in names}
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dump")
    ap.add_argument("--db", required=True, help="database path to create")
    ap.add_argument("--force", action="store_true", help="replace an existing database")
    args = ap.parse_args()
    counts = restore(Path(args.dump).expanduser(), Path(args.db).expanduser(), args.force)
    print(f"restored {sum(counts.values())} rows across {len(counts)} tables into {args.db}")
    for n, c in counts.items():
        print(f"  {n:28} {c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
