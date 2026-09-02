from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from global_icebox.store import IceboxStore
from global_icebox.tasks import TaskError, TaskStore


@contextmanager
def temp_tasks():
    with tempfile.TemporaryDirectory() as tmp:
        yield TaskStore(IceboxStore(Path(tmp) / "icebox.db"))


def a_task(tasks: TaskStore, title="Do the thing", **kw):
    return tasks.add_task(title=title, description="because it needs doing", **kw)


class TaskModelTests(unittest.TestCase):
    def test_a_new_task_is_open_and_in_the_tasks_lane(self) -> None:
        with temp_tasks() as tasks:
            task = a_task(tasks, repo="Concinnity", location="future_work/work-plane.md")
            self.assertEqual(task["status"], "open")
            self.assertEqual(task["lane"], "tasks")
            self.assertEqual(task["repo"], "Concinnity")
            self.assertFalse(task["blocked"])

    def test_the_happy_path_runs_end_to_end(self) -> None:
        with temp_tasks() as tasks:
            t = a_task(tasks)
            self.assertEqual(tasks.claim_task(t["id"], "agent-a")["status"], "claimed")
            self.assertEqual(tasks.start_task(t["id"])["status"], "in_progress")
            self.assertEqual(
                tasks.mark_code_complete(t["id"], "gha:1")["status"], "code_complete")
            self.assertEqual(tasks.accept_task(t["id"], "owner")["status"], "accepted")

    def test_code_complete_requires_a_ci_run(self) -> None:
        # The owner's rule: code_complete is written only by a verified gate, never narration.
        with temp_tasks() as tasks:
            t = a_task(tasks)
            tasks.claim_task(t["id"], "agent-a")
            with self.assertRaises(TaskError) as ctx:
                tasks.mark_code_complete(t["id"], "   ")
            self.assertIn("ci_run is required", str(ctx.exception))

    def test_no_other_transition_can_reach_code_complete(self) -> None:
        with temp_tasks() as tasks:
            t = a_task(tasks)
            tasks.claim_task(t["id"], "agent-a")
            # accept and reiterate both demand code_complete first, so nothing can skip the gate.
            with self.assertRaises(TaskError):
                tasks.accept_task(t["id"], "owner")
            with self.assertRaises(TaskError):
                tasks.reiterate_task(t["id"], "owner", "again")

    def test_accept_and_reiterate_are_owner_only(self) -> None:
        with temp_tasks() as tasks:
            t = a_task(tasks)
            tasks.claim_task(t["id"], "agent-a")
            tasks.mark_code_complete(t["id"], "gha:1")
            with self.assertRaises(TaskError) as ctx:
                tasks.accept_task(t["id"], "")
            self.assertIn("owner-only", str(ctx.exception))
            with self.assertRaises(TaskError):
                tasks.reiterate_task(t["id"], "", "note")

    def test_reiterate_creates_a_superseding_task(self) -> None:
        with temp_tasks() as tasks:
            t = a_task(tasks, repo="pellucid")
            tasks.claim_task(t["id"], "agent-a")
            tasks.mark_code_complete(t["id"], "gha:1")
            result = tasks.reiterate_task(t["id"], "owner", "the sync model is wrong")
            self.assertEqual(result["original"]["status"], "reiterate")
            self.assertEqual(result["successor"]["status"], "open")
            self.assertEqual(result["successor"]["repo"], "pellucid")
            rels = tasks.store.list_idea_relationships(idea_id=result["successor"]["id"])
            self.assertTrue(any(r["relationship_type"] == "supersedes" for r in rels))

    def test_reiterate_requires_a_note(self) -> None:
        with temp_tasks() as tasks:
            t = a_task(tasks)
            tasks.claim_task(t["id"], "agent-a")
            tasks.mark_code_complete(t["id"], "gha:1")
            with self.assertRaises(TaskError):
                tasks.reiterate_task(t["id"], "owner", "  ")

    def test_a_live_claim_blocks_a_second_claimant(self) -> None:
        with temp_tasks() as tasks:
            t = a_task(tasks)
            tasks.claim_task(t["id"], "agent-a")
            with self.assertRaises(TaskError) as ctx:
                tasks.claim_task(t["id"], "agent-b")
            self.assertIn("agent-a", str(ctx.exception))

    def test_an_expired_lease_makes_a_task_reclaimable(self) -> None:
        # The lease is what lets an abandoned agent's task be picked up without anyone noticing
        # it died -- so an expired one must NOT keep the task locked.
        with temp_tasks() as tasks:
            t = a_task(tasks)
            tasks.claim_task(t["id"], "agent-a", lease_minutes=1)
            past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
            tasks._write(t["id"], {"lease_expires_at": past})
            self.assertTrue(tasks.get_task(t["id"])["lease_expired"])
            self.assertEqual(tasks.claim_task(t["id"], "agent-b")["claimed_by"], "agent-b")

    def test_claim_requires_an_identity(self) -> None:
        with temp_tasks() as tasks:
            t = a_task(tasks)
            with self.assertRaises(TaskError):
                tasks.claim_task(t["id"], "  ")

    def test_release_returns_a_task_to_the_pool(self) -> None:
        with temp_tasks() as tasks:
            t = a_task(tasks)
            tasks.claim_task(t["id"], "agent-a")
            released = tasks.release_task(t["id"], "ran out of context")
            self.assertEqual(released["status"], "released")
            self.assertIsNone(released["claimed_by"])
            self.assertEqual(tasks.claim_task(t["id"], "agent-b")["status"], "claimed")

    def test_blocked_is_derived_from_depends_on_not_stored(self) -> None:
        with temp_tasks() as tasks:
            first = a_task(tasks, title="First", task_key="T-1")
            second = a_task(tasks, title="Second", depends_on=["T-1"])
            self.assertTrue(tasks.get_task(second["id"])["blocked"])
            with self.assertRaises(TaskError) as ctx:
                tasks.claim_task(second["id"], "agent-a")
            self.assertIn("blocked by", str(ctx.exception))
            # Only acceptance clears a dependency -- code_complete is not accepted.
            tasks.claim_task(first["id"], "agent-a")
            tasks.mark_code_complete(first["id"], "gha:1")
            self.assertTrue(tasks.get_task(second["id"])["blocked"])
            tasks.accept_task(first["id"], "owner")
            self.assertFalse(tasks.get_task(second["id"])["blocked"])

    def test_a_dependency_on_an_unknown_task_blocks(self) -> None:
        with temp_tasks() as tasks:
            t = a_task(tasks, depends_on=["NOPE-1"])
            decorated = tasks.get_task(t["id"])
            self.assertTrue(decorated["blocked"])
            self.assertEqual(decorated["blocked_by"][0]["reason"], "unknown task")

    def test_terminal_tasks_are_hidden_unless_asked_for(self) -> None:
        with temp_tasks() as tasks:
            t = a_task(tasks)
            tasks.claim_task(t["id"], "agent-a")
            tasks.mark_code_complete(t["id"], "gha:1")
            tasks.accept_task(t["id"], "owner")
            self.assertEqual(tasks.list_tasks(), [])
            self.assertEqual(len(tasks.list_tasks(include_terminal=True)), 1)

    def test_an_accepted_task_does_not_read_as_claimed(self) -> None:
        with temp_tasks() as tasks:
            t = a_task(tasks)
            tasks.claim_task(t["id"], "agent-a")
            tasks.mark_code_complete(t["id"], "gha:1")
            accepted = tasks.accept_task(t["id"], "owner")
            self.assertEqual(accepted["claimed_by"], "agent-a", "who did the work is kept")
            self.assertFalse(accepted["claim_is_live"], "but the claim is not live")

    def test_an_idea_is_not_a_task(self) -> None:
        with temp_tasks() as tasks:
            idea = tasks.store.add_idea(title="An idea", description="not a task",
                                        target_type="project", lane="project_ideas")
            with self.assertRaises(TaskError):
                tasks.get_task(idea["id"])

    def test_task_statuses_are_rejected_outside_the_tasks_lane(self) -> None:
        with temp_tasks() as tasks:
            with self.assertRaises(ValueError):
                tasks.store.add_idea(title="x", description="y", target_type="project",
                                     lane="project_ideas", status="open")

    def test_idea_statuses_are_rejected_inside_the_tasks_lane(self) -> None:
        with temp_tasks() as tasks:
            with self.assertRaises(ValueError):
                tasks.store.add_idea(title="x", description="y", target_type="feature",
                                     lane="tasks", status="icebox")

    def test_tasks_rank_on_the_existing_h2h_board(self) -> None:
        # The reason for extending the lane model rather than adding a subsystem: ranking,
        # ratings and history work on tasks with no changes at all.
        with temp_tasks() as tasks:
            first = a_task(tasks, title="First")
            second = a_task(tasks, title="Second")
            tasks.store.record_comparison(idea_a_id=first["id"], idea_b_id=second["id"],
                                          winner="a", rationale="first matters more")
            board = tasks.store.list_priorities(lane="tasks")
            self.assertEqual(board[0]["title"], "First")
            self.assertGreater(board[0]["rating"], board[1]["rating"])


if __name__ == "__main__":
    unittest.main()
