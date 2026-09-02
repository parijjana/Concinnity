from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from global_icebox import locations


@contextmanager
def temp_config():
    """Point CONCINNITY_CONFIG at a throwaway file so the real config is never touched."""
    previous = os.environ.get(locations.CONFIG_ENV)
    with tempfile.TemporaryDirectory() as tmp:
        os.environ[locations.CONFIG_ENV] = str(Path(tmp) / "config.json")
        try:
            yield Path(tmp)
        finally:
            if previous is None:
                os.environ.pop(locations.CONFIG_ENV, None)
            else:
                os.environ[locations.CONFIG_ENV] = previous


class LocationTests(unittest.TestCase):
    def test_missing_config_reads_as_empty(self) -> None:
        with temp_config():
            listed = locations.list_locations()
            self.assertEqual(listed["locations"], {})
            self.assertFalse(listed["config_exists"])

    def test_set_then_resolve_roundtrip(self) -> None:
        with temp_config() as tmp:
            root = tmp / "docs"
            (root / "sub").mkdir(parents=True)
            (root / "sub" / "plan.md").write_text("x", encoding="utf-8")
            locations.set_location("future_work", str(root))
            resolved = locations.resolve_location("future_work/sub/plan.md")
            self.assertEqual(Path(resolved["path"]), root / "sub" / "plan.md")
            self.assertTrue(resolved["exists"])

    def test_bare_name_resolves_to_the_root(self) -> None:
        with temp_config() as tmp:
            locations.set_location("docs", str(tmp))
            self.assertEqual(Path(locations.resolve_location("docs")["path"]), tmp)

    def test_windows_separators_in_a_reference_are_accepted(self) -> None:
        # The point of the whole module is that the two machines disagree about separators.
        with temp_config() as tmp:
            (tmp / "a").mkdir()
            (tmp / "a" / "b.md").write_text("x", encoding="utf-8")
            locations.set_location("docs", str(tmp))
            self.assertEqual(
                Path(locations.resolve_location(r"docs\a\b.md")["path"]), tmp / "a" / "b.md"
            )

    def test_unknown_location_names_the_known_ones(self) -> None:
        with temp_config() as tmp:
            locations.set_location("docs", str(tmp))
            with self.assertRaises(ValueError) as ctx:
                locations.resolve_location("missing/x.md")
            self.assertIn("docs", str(ctx.exception))

    def test_traversal_out_of_the_root_is_refused(self) -> None:
        with temp_config() as tmp:
            root = tmp / "docs"
            root.mkdir()
            locations.set_location("docs", str(root))
            with self.assertRaises(ValueError):
                locations.resolve_location("docs/../../etc/passwd")

    def test_separator_in_a_location_name_is_refused(self) -> None:
        with temp_config() as tmp:
            with self.assertRaises(ValueError):
                locations.set_location("a/b", str(tmp))

    def test_set_reports_the_previous_path(self) -> None:
        with temp_config() as tmp:
            locations.set_location("docs", str(tmp / "one"))
            second = locations.set_location("docs", str(tmp / "two"))
            self.assertEqual(Path(second["previous_path"]), tmp / "one")

    def test_a_root_that_does_not_exist_here_is_still_recorded(self) -> None:
        # The other machine's path is legitimately absent on this one.
        with temp_config():
            result = locations.set_location("windows_docs", r"C:\Users\someone\code")
            self.assertFalse(result["exists"])
            self.assertIn("windows_docs", locations.list_locations()["locations"])

    def test_remove_forgets_only_the_mapping(self) -> None:
        with temp_config() as tmp:
            root = tmp / "docs"
            root.mkdir()
            locations.set_location("docs", str(root))
            locations.remove_location("docs")
            self.assertEqual(locations.list_locations()["locations"], {})
            self.assertTrue(root.exists(), "removing a mapping must not touch the filesystem")

    def test_removing_an_unknown_location_raises(self) -> None:
        with temp_config():
            with self.assertRaises(ValueError):
                locations.remove_location("nope")

    def test_corrupt_config_is_refused_not_overwritten(self) -> None:
        with temp_config():
            path = locations.config_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ValueError):
                locations.list_locations()
            self.assertEqual(path.read_text(encoding="utf-8"), "{not json")

    def test_config_is_written_as_readable_sorted_json(self) -> None:
        with temp_config() as tmp:
            locations.set_location("zeta", str(tmp))
            locations.set_location("alpha", str(tmp))
            data = json.loads(locations.config_path().read_text(encoding="utf-8"))
            self.assertEqual(list(data["locations"]), ["alpha", "zeta"])


if __name__ == "__main__":
    unittest.main()
