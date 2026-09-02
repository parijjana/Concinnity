from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import backup as backup_mod  # noqa: E402
import restore as restore_mod  # noqa: E402

from global_icebox.store import IceboxStore  # noqa: E402


def seeded_db(path: Path) -> IceboxStore:
    store = IceboxStore(path)
    a = store.add_idea(title="Alpha", description="first", target_type="project", tags=["x"])
    b = store.add_idea(title="Beta", description="second", target_type="project")
    store.record_comparison(idea_a_id=a["id"], idea_b_id=b["id"], winner="a",
                            rationale="alpha matters more")
    return store


class BackupRoundTripTests(unittest.TestCase):
    def test_dump_and_restore_preserves_every_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "icebox.db"
            seeded_db(src)
            before = backup_mod.table_counts(src)
            self.assertGreater(before["ideas"], 0)
            self.assertGreater(before["idea_comparisons"], 0)

            sql = tmp / "dump.sql"
            sql.write_text(backup_mod.dump_sql(src), encoding="utf-8")
            target = tmp / "restored.db"
            after = restore_mod.restore(sql, target)
            self.assertEqual(before, after)

    def test_restored_ratings_match_exactly(self) -> None:
        # Elo is order-dependent, so a restore that lost a comparison would be undetectable from
        # row counts alone -- compare the ratings themselves.
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "icebox.db"
            seeded_db(src)
            read = lambda p: sorted(  # noqa: E731
                sqlite3.connect(p).execute(
                    "select idea_id, rating from idea_ratings").fetchall())
            sql = tmp / "dump.sql"
            sql.write_text(backup_mod.dump_sql(src), encoding="utf-8")
            restore_mod.restore(sql, tmp / "restored.db")
            self.assertEqual(read(src), read(tmp / "restored.db"))

    def test_restore_refuses_to_overwrite_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "icebox.db"
            seeded_db(src)
            sql = tmp / "dump.sql"
            sql.write_text(backup_mod.dump_sql(src), encoding="utf-8")
            live = tmp / "live.db"
            seeded_db(live)
            original = live.read_bytes()
            with self.assertRaises(SystemExit):
                restore_mod.restore(sql, live)
            self.assertEqual(live.read_bytes(), original, "refusal must not touch the database")
            restore_mod.restore(sql, live, force=True)  # explicit opt-in still works

    def test_dump_is_deterministic_so_it_diffs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "icebox.db"
            seeded_db(src)
            self.assertEqual(backup_mod.dump_sql(src), backup_mod.dump_sql(src))

    def test_dump_does_not_write_to_the_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "icebox.db"
            seeded_db(src)
            before = src.stat().st_mtime_ns, src.read_bytes()
            backup_mod.dump_sql(src)
            self.assertEqual((src.stat().st_mtime_ns, src.read_bytes()), before)

    def test_backups_are_namespaced_by_host_so_two_machines_never_collide(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "icebox.db"
            seeded_db(src)
            dest = tmp / "backups"
            env = dict(os.environ, CONCINNITY_BACKUP_DIR=str(dest))
            for host in ("mac-mini", "windows-pc"):
                r = subprocess.run(
                    [sys.executable, str(ROOT / "scripts" / "backup.py"),
                     "--db", str(src), "--quiet"],
                    env=dict(env, CONCINNITY_HOST=host), capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((dest / "mac-mini" / "icebox.sql").exists())
            self.assertTrue((dest / "windows-pc" / "icebox.sql").exists())
            meta = json.loads((dest / "windows-pc" / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["host"], "windows-pc")
            self.assertEqual(meta["row_counts"]["ideas"], 2)

    def test_mdns_suffix_is_stripped_from_the_host_name(self) -> None:
        os.environ["CONCINNITY_HOST"] = "some-mac.local"
        try:
            self.assertEqual(backup_mod.host_name(), "some-mac")
        finally:
            del os.environ["CONCINNITY_HOST"]


if __name__ == "__main__":
    unittest.main()
