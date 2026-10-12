#!/usr/bin/env python3
"""Rebuild a Concinnity database from a SQL dump.

Deliberately refuses to overwrite an existing database without --force. Restoring the *other*
machine's dump over this machine's board would silently destroy rankings that exist nowhere else,
and that is exactly the accident a per-host backup layout is meant to make hard.
"""

from __future__ import annotations

import argparse
import hashlib
import json
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


def canonical_digest(db: Path) -> str:
    """sha256 of a canonical SQL dump (read-only), for comparing a restore with its source."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return hashlib.sha256(("\n".join(conn.iterdump()) + "\n").encode("utf-8")).hexdigest()
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dump")
    ap.add_argument("--db", required=True, help="database path to create")
    ap.add_argument("--force", action="store_true", help="replace an existing database")
    ap.add_argument("--verify-against", metavar="DB",
                    help="compare row counts and canonical-dump checksum with this database")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    counts = restore(Path(args.dump).expanduser(), Path(args.db).expanduser(), args.force)
    result = {"restored_to": args.db, "row_counts": counts}
    if args.verify_against:
        src = Path(args.verify_against).expanduser()
        src_counts = {}
        conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
        for (n,) in conn.execute("select name from sqlite_master where type='table' order by name"):
            src_counts[n] = conn.execute(f'select count(*) from "{n}"').fetchone()[0]
        conn.close()
        a, b = canonical_digest(src), canonical_digest(Path(args.db).expanduser())
        result.update(source_counts=src_counts, source_sha256=a, restored_sha256=b,
                      counts_match=src_counts == counts, checksum_match=a == b)
        ok = result["counts_match"] and result["checksum_match"]
        result["verified"] = ok
    if args.json:
        print(json.dumps(result, indent=2))
        return 0 if result.get("verified", True) else 1
    print(f"restored {sum(counts.values())} rows across {len(counts)} tables into {args.db}")
    for n, c in counts.items():
        print(f"  {n:28} {c}")
    if args.verify_against:
        print(f"source sha256   {result['source_sha256']}")
        print(f"restored sha256 {result['restored_sha256']}")
        print("VERIFIED: counts and checksum match" if result["verified"] else "MISMATCH")
        return 0 if result["verified"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
