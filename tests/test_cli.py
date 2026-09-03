from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from global_icebox.cli import main


class CliTests(unittest.TestCase):
    """The CLI is a front door, not a second implementation — so these assert it reaches the
    same store and enforces the same rules, not that it has its own behaviour."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self._tmp.name) / "icebox.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--db", self.db, *argv])
        return code, out.getvalue(), err.getvalue()

    def add(self, title="A task", **flags) -> dict:
        argv = ["--json", "task", "add", title, "a description"]
        for flag, value in flags.items():
            argv += [flag, value]
        code, out, err = self.run_cli(*argv)
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def test_add_then_list_round_trips_through_the_real_store(self) -> None:
        self.add("Ship the lane", **{"--repo": "Concinnity", "--key": "WP-002"})
        code, out, _ = self.run_cli("--json", "task", "list")
        self.assertEqual(code, 0)
        tasks = json.loads(out)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["repo"], "Concinnity")

    def test_human_output_is_the_default(self) -> None:
        self.add("Ship the lane")
        code, out, _ = self.run_cli("task", "list")
        self.assertEqual(code, 0)
        self.assertIn("Ship the lane", out)
        self.assertNotIn("{", out, "default output should be human-readable, not JSON")

    def test_the_full_lifecycle_is_reachable_from_the_shell(self) -> None:
        task = self.add("Ship the lane")
        tid = task["id"]
        for argv in (("task", "claim", tid, "--by", "agent-a"),
                     ("task", "start", tid),
                     ("task", "code-complete", tid, "--ci-run", "gha:9"),
                     ("task", "accept", tid, "--owner", "animesh")):
            code, _, err = self.run_cli(*argv)
            self.assertEqual(code, 0, f"{argv}: {err}")
        code, out, _ = self.run_cli("--json", "task", "show", tid)
        self.assertEqual(json.loads(out)["status"], "accepted")

    def test_a_refused_transition_exits_nonzero_with_a_readable_error(self) -> None:
        task = self.add("Ship the lane")
        code, _, err = self.run_cli("task", "code-complete", task["id"], "--ci-run", "gha:9")
        self.assertEqual(code, 1)
        self.assertIn("cannot code_complete", err)
        self.assertNotIn("Traceback", err)

    def test_the_ci_gate_and_owner_rules_hold_on_the_cli_too(self) -> None:
        task = self.add("Ship the lane")
        self.run_cli("task", "claim", task["id"], "--by", "agent-a")
        code, _, err = self.run_cli("task", "code-complete", task["id"], "--ci-run", "")
        self.assertEqual(code, 1)
        self.assertIn("ci_run is required", err)
        self.run_cli("task", "code-complete", task["id"], "--ci-run", "gha:9")
        code, _, err = self.run_cli("task", "accept", task["id"], "--owner", "")
        self.assertEqual(code, 1)
        self.assertIn("owner-only", err)

    def test_task_update_edits_only_what_was_typed(self) -> None:
        task = self.add("Before", **{"--key": "ED-1"})
        code, _, err = self.run_cli("task", "update", task["id"], "--title", "After")
        self.assertEqual(code, 0, err)
        code, out, _ = self.run_cli("--json", "task", "show", task["id"])
        after = json.loads(out)
        self.assertEqual(after["title"], "After")
        # An omitted flag must not blank the field it names.
        self.assertEqual(after["description"], "a description")
        self.assertEqual(after["external_item_key"], "ED-1")

    def test_update_with_no_fields_is_refused(self) -> None:
        task = self.add("Before")
        code, _, err = self.run_cli("task", "update", task["id"])
        self.assertEqual(code, 1)
        self.assertIn("nothing to update", err)

    def test_task_update_refuses_an_idea(self) -> None:
        code, out, _ = self.run_cli("--json", "idea", "add", "An idea", "not a task")
        idea_id = json.loads(out)["id"]
        code, _, err = self.run_cli("task", "update", idea_id, "--title", "nope")
        self.assertEqual(code, 1)
        self.assertIn("not a task", err)

    def test_idea_update_promote_and_relate(self) -> None:
        code, out, _ = self.run_cli("--json", "idea", "add", "First", "one")
        a = json.loads(out)["id"]
        code, out, _ = self.run_cli("--json", "idea", "add", "Second", "two")
        b = json.loads(out)["id"]
        code, _, err = self.run_cli("idea", "update", a, "--title", "First edited",
                                    "--tag", "alpha")
        self.assertEqual(code, 0, err)
        code, out, _ = self.run_cli("--json", "idea", "show", a)
        self.assertEqual(json.loads(out)["title"], "First edited")
        self.assertEqual(json.loads(out)["tags"], ["alpha"])
        code, _, err = self.run_cli("idea", "relate", a, b, "related_to", "--notes", "same area")
        self.assertEqual(code, 0, err)
        code, out, _ = self.run_cli("--json", "idea", "relations", "--idea", a)
        self.assertEqual(len(json.loads(out)), 1)
        code, _, err = self.run_cli("idea", "promote", b, "--notes", "starting")
        self.assertEqual(code, 0, err)

    def test_rank_history_is_readable_from_the_shell(self) -> None:
        a = self.add("First")["id"]
        b = self.add("Second")["id"]
        self.run_cli("rank", "record", a, b, "a", "--rationale", "first is clearer")
        code, out, _ = self.run_cli("rank", "history")
        self.assertEqual(code, 0)
        self.assertIn("first is clearer", out)
        code, out, _ = self.run_cli("--json", "rank", "history")
        self.assertEqual(len(json.loads(out)), 1)

    def test_every_mcp_tool_is_reachable_from_the_cli(self) -> None:
        # A1 of INTERNAL_TOOL_STANDARD.md: the whole tool surface, not a convenient subset.
        # This test is what stops the CLI quietly falling behind the MCP server again.
        import re
        from pathlib import Path as P
        root = P(__file__).resolve().parents[1] / "src" / "global_icebox"
        tools = set(re.findall(r"@mcp\.tool\(\)\s*\ndef (\w+)", (root / "__main__.py").read_text()))
        cli = (root / "cli.py").read_text()
        missing = sorted(t for t in tools if t not in cli)
        self.assertEqual(missing, [], f"MCP tools with no CLI path: {missing}")

    def test_ideas_and_ranking_are_reachable_too(self) -> None:
        # The requirement is the whole tool surface, not a convenient subset.
        code, out, err = self.run_cli("--json", "idea", "add", "An idea", "worth ranking")
        self.assertEqual(code, 0, err)
        code, out, _ = self.run_cli("--json", "idea", "list", "--lane", "project_ideas")
        self.assertEqual(len(json.loads(out)), 1)
        a = self.add("First")["id"]
        b = self.add("Second")["id"]
        code, _, err = self.run_cli("rank", "record", a, b, "a", "--rationale", "first wins")
        self.assertEqual(code, 0, err)
        code, out, _ = self.run_cli("--json", "rank", "list", "--lane", "tasks")
        board = json.loads(out)
        self.assertEqual(board[0]["title"], "First")


if __name__ == "__main__":
    unittest.main()
