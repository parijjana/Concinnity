#!/usr/bin/env python3
"""Back up the Concinnity database as replayable SQL text.

Backup, not sync. The database is per-machine by owner decision (2026-08-28) and must never be
merged between machines, so every dump is written under its own host directory. Two machines
therefore never write the same file and the backup can never quietly become a sync — while still
giving the cross-machine *visibility* of the register that the work-plane asks for separately.

Text rather than a copied .db file, for two reasons. It diffs and compresses, so the history of
the ranking board is legible in git. And the estate has a hard rule against copying a live SQLite
file: a copy taken mid-transaction, or a -wal/-shm pair out of step with its .db, is corrupt or
silently stale. `iterdump` reads through the connection, so it sees a consistent view.

Uses Python's own sqlite3 rather than the sqlite3 CLI, which is not reliably present on Windows —
the machine this portability work exists for.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from global_icebox import locations  # noqa: E402
from global_icebox.store import db_path  # noqa: E402

BACKUP_ENV = "CONCINNITY_BACKUP_DIR"


def host_name() -> str:
    # mDNS appends ".local" on macOS; it is noise, and it makes one machine look like two
    # depending on how the name was resolved. Same normalisation as Lore's identity.js.
    return (os.environ.get("CONCINNITY_HOST") or socket.gethostname()).removesuffix(".local")


def backup_root() -> Path:
    """Where dumps go. Env wins; otherwise the 'backup' location; otherwise under 'docs'."""
    override = os.environ.get(BACKUP_ENV)
    if override:
        return Path(override).expanduser()
    configured = locations.load_config()["locations"]
    if "backup" in configured:
        return Path(configured["backup"]).expanduser()
    if "docs" in configured:
        return Path(configured["docs"]).expanduser() / "concinnity-backup"
    raise SystemExit(
        f"No backup destination. Set {BACKUP_ENV}, or record a 'backup' or 'docs' location "
        "with set_location."
    )


def dump_sql(source: Path) -> str:
    if not source.exists():
        raise SystemExit(f"database not found: {source}")
    # Read-only URI: a backup must never be the thing that writes to the database.
    conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        return "\n".join(conn.iterdump()) + "\n"
    finally:
        conn.close()


def table_counts(source: Path) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        names = [r[0] for r in conn.execute(
            "select name from sqlite_master where type='table' order by name")]
        return {n: conn.execute(f'select count(*) from "{n}"').fetchone()[0] for n in names}
    finally:
        conn.close()


def git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", help="database to back up (default: the configured one)")
    ap.add_argument("--dest", help=f"backup root (default: ${BACKUP_ENV} or the docs location)")
    ap.add_argument("--commit", action="store_true", help="commit the dump if it changed")
    ap.add_argument("--push", action="store_true", help="push after committing")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    source = Path(args.db).expanduser() if args.db else db_path()
    root = Path(args.dest).expanduser() if args.dest else backup_root()
    host = host_name()
    out_dir = root / host
    out_dir.mkdir(parents=True, exist_ok=True)
    sql_path = out_dir / "icebox.sql"
    meta_path = out_dir / "meta.json"

    sql = dump_sql(source)
    counts = table_counts(source)
    unchanged = sql_path.exists() and sql_path.read_text(encoding="utf-8") == sql

    # Write the dump first and the metadata second, so metadata never describes a dump that is
    # not on disk yet. Both go through a temp file and a rename.
    for path, text in ((sql_path, sql), (meta_path, json.dumps({
        "host": host,
        "source_db": str(source),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "row_counts": counts,
        "restore": "uv run python scripts/restore.py <this-dir>/icebox.sql --db <target>",
    }, indent=2, sort_keys=True) + "\n")):
        tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)

    if not args.quiet:
        total = sum(counts.values())
        print(f"{'unchanged' if unchanged else 'updated'}: {sql_path} "
              f"({len(sql):,} bytes, {total} rows across {len(counts)} tables)")

    if args.commit:
        repo = git(["rev-parse", "--show-toplevel"], out_dir)
        if repo.returncode != 0:
            print(f"not a git repository: {out_dir} — dump written, not committed")
            return 0
        top = Path(repo.stdout.strip())
        git(["add", str(sql_path), str(meta_path)], top)
        staged = git(["diff", "--cached", "--quiet", "--", str(sql_path)], top)
        if staged.returncode == 0:
            # Only meta.json moved (its timestamp always changes); a commit would be pure noise.
            git(["restore", "--staged", str(meta_path)], top)
            if not args.quiet:
                print("no change to the dump — nothing committed")
            return 0
        msg = f"Concinnity backup ({host}): {counts.get('ideas', 0)} ideas"
        c = git(["commit", "-q", "-m", msg], top)
        if c.returncode != 0:
            print(c.stdout + c.stderr, file=sys.stderr)
            return 1
        if not args.quiet:
            print(f"committed: {msg}")
        if args.push:
            p = git(["push"], top)
            if p.returncode != 0:
                print(p.stdout + p.stderr, file=sys.stderr)
                return 1
            if not args.quiet:
                print("pushed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
