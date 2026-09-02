"""The tasks lane: registering, ranking, claiming, and driving work through its status model.

Work-plane Step 2, 2026-08-28. Tasks are rows in `ideas` with `lane = "tasks"`, not a new
table, because the plan's instruction was to extend the existing lane model rather than bolt on
a subsystem — and the payoff is concrete: the H2H board, ranking runs and rating history all
work on tasks with no changes at all, since they already scope by lane.

The status model (section 3):

    open ──► claimed ──► in_progress ──► code_complete ──► accepted
                 │              │
                 │              └──► reiterate ──► new task (supersedes)
                 └──► released (lease expired / agent gave up)

Two constraints from the owner are enforced here rather than documented and hoped for:

- `code_complete` is written ONLY by `mark_code_complete`, which requires a CI run reference.
  No other transition can reach that status, and it cannot be reached without evidence.
- `accepted` and `reiterate` are owner-only transitions, and both refuse to run unless the
  caller identifies itself as the owner.

`blocked` is not a status. It is orthogonal and derived from `depends_on`, so it is computed on
read; storing it would let it drift out of agreement with the dependencies that define it.
"""

from __future__ import annotations

import json
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any

from global_icebox.store import (
    IceboxStore,
    TASK_STATUSES,
    normalize_tags,
    optional_text,
    row_to_idea,
    utc_now,
)

TASK_LANE = "tasks"
DEFAULT_LEASE_MINUTES = 120

# Which statuses each transition may start from. Written as data so the model is readable in
# one place and every tool checks it the same way.
TRANSITIONS: dict[str, set[str]] = {
    "claim": {"open", "released"},
    "start": {"claimed"},
    "release": {"claimed", "in_progress"},
    "code_complete": {"claimed", "in_progress"},
    "accept": {"code_complete"},
    "reiterate": {"code_complete"},
}

TERMINAL = {"accepted", "reiterate"}


class TaskError(ValueError):
    """A refused transition or a malformed task. Separate so callers can present it plainly."""


def _json_list(values: list[str] | None) -> str:
    if not values:
        return "[]"
    cleaned = [str(v).strip() for v in values if str(v).strip()]
    return json.dumps(cleaned)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def lease_expired(task: dict[str, Any], now: datetime | None = None) -> bool:
    expires = _parse_ts(task.get("lease_expires_at"))
    if expires is None:
        return False
    return (now or datetime.now(timezone.utc)) >= expires


class TaskStore:
    """Task operations over an IceboxStore. Shared by the MCP server and the CLI.

    One implementation, two front doors — per the standing requirement that internal tools
    expose a CLI as well as an MCP server, without the two drifting apart.
    """

    def __init__(self, store: IceboxStore | None = None) -> None:
        self.store = store or IceboxStore()

    # --- reading -------------------------------------------------------------------

    def get_task(self, task_id: str) -> dict[str, Any]:
        task = self._raw(task_id)
        return self._decorate(task, self._index())

    def _raw(self, task_id: str) -> dict[str, Any]:
        idea = self.store.get_idea(task_id)
        if idea.get("lane") != TASK_LANE:
            raise TaskError(f"{task_id} is not a task (lane={idea.get('lane')!r})")
        return idea

    def _index(self) -> dict[str, dict[str, Any]]:
        """Every task by id AND by task key, so depends_on may name either."""
        self.store.initialize()
        with closing(self.store.connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM ideas WHERE lane = ?", (TASK_LANE,)
            ).fetchall()
        index: dict[str, dict[str, Any]] = {}
        for row in rows:
            task = row_to_idea(row)
            index[task["id"]] = task
            key = task.get("external_item_key")
            if key:
                index.setdefault(key, task)
        return index

    def _decorate(self, task: dict[str, Any], index: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """Add the derived fields: blocked, its reasons, and lease expiry."""
        blockers: list[dict[str, str]] = []
        for ref in task.get("depends_on") or []:
            dep = index.get(ref)
            if dep is None:
                blockers.append({"ref": ref, "reason": "unknown task"})
            elif dep["status"] != "accepted":
                blockers.append({"ref": ref, "title": dep["title"], "reason": dep["status"]})
        task = dict(task)
        task["blocked"] = bool(blockers)
        task["blocked_by"] = blockers
        task["lease_expired"] = lease_expired(task)
        # A claim is only live while the task is actually being worked. Retaining claimed_by
        # after acceptance is deliberate -- it records who did the work -- but rendering that
        # as a live claim would misreport a finished task as occupied.
        task["claim_is_live"] = (
            bool(task.get("claimed_by"))
            and not task["lease_expired"]
            and task["status"] in ("claimed", "in_progress")
        )
        return task

    def list_tasks(
        self,
        status: str | None = None,
        project: str | None = None,
        repo: str | None = None,
        claimed_by: str | None = None,
        blocked: bool | None = None,
        include_terminal: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if status is not None and status not in TASK_STATUSES:
            raise TaskError(f"status must be one of: {', '.join(sorted(TASK_STATUSES))}")
        index = self._index()
        tasks = [self._decorate(t, index) for t in index.values() if t["lane"] == TASK_LANE]
        # _index maps ids AND keys onto the same objects; dedupe by id.
        seen: set[str] = set()
        unique = []
        for task in tasks:
            if task["id"] in seen:
                continue
            seen.add(task["id"])
            unique.append(task)
        tasks = unique
        if status is not None:
            tasks = [t for t in tasks if t["status"] == status]
        elif not include_terminal:
            tasks = [t for t in tasks if t["status"] not in TERMINAL]
        if project is not None:
            tasks = [t for t in tasks if (t.get("target_project") or "") == project]
        if repo is not None:
            tasks = [t for t in tasks if (t.get("repo") or "") == repo]
        if claimed_by is not None:
            tasks = [t for t in tasks if (t.get("claimed_by") or "") == claimed_by]
        if blocked is not None:
            tasks = [t for t in tasks if t["blocked"] is blocked]
        tasks.sort(key=lambda t: (t["status"], t["created_at"]))
        return tasks[: max(1, limit)]

    # --- writing -------------------------------------------------------------------

    def add_task(
        self,
        title: str,
        description: str,
        project: str | None = None,
        repo: str | None = None,
        location: str | None = None,
        recommended_capabilities: list[str] | None = None,
        depends_on: list[str] | None = None,
        links: list[str] | None = None,
        source: str | None = None,
        task_key: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        record = self.store.add_idea(
            title=title,
            description=description,
            target_type="feature",
            target_project=project,
            lane=TASK_LANE,
            status="open",
            tags=normalize_tags(tags),
            external_item_key=optional_text(task_key),
            external_source=optional_text(source),
        )
        self._write(
            record["id"],
            {
                "repo": optional_text(repo),
                "location": optional_text(location),
                "recommended_capabilities": _json_list(recommended_capabilities),
                "depends_on": _json_list(depends_on),
                "links": _json_list(links),
                "source": optional_text(source),
            },
        )
        return self.get_task(record["id"])

    def _write(self, task_id: str, fields: dict[str, Any]) -> None:
        fields = {**fields, "updated_at": utc_now()}
        assignments = ", ".join(f"{k} = :{k}" for k in fields)
        self.store.initialize()
        with closing(self.store.connect()) as connection:
            with connection:
                connection.execute(
                    f"UPDATE ideas SET {assignments} WHERE id = :id",
                    {**fields, "id": task_id},
                )

    def _require(self, task_id: str, transition: str) -> dict[str, Any]:
        task = self._raw(task_id)
        allowed = TRANSITIONS[transition]
        if task["status"] not in allowed:
            raise TaskError(
                f"cannot {transition} a task in status {task['status']!r}; "
                f"allowed from: {', '.join(sorted(allowed))}"
            )
        return task

    def claim_task(
        self,
        task_id: str,
        claimed_by: str,
        lease_minutes: int = DEFAULT_LEASE_MINUTES,
    ) -> dict[str, Any]:
        who = optional_text(claimed_by)
        if not who:
            raise TaskError("claimed_by is required — an unattributed claim tells nobody anything")
        task = self._raw(task_id)
        if task["status"] in ("claimed", "in_progress"):
            # A live claim is honoured; an expired lease is not. The lease is what makes an
            # abandoned agent's task reclaimable without anyone having to notice it died.
            if not lease_expired(task):
                raise TaskError(
                    f"already claimed by {task['claimed_by']!r} until {task['lease_expires_at']}"
                )
        elif task["status"] not in TRANSITIONS["claim"]:
            raise TaskError(
                f"cannot claim a task in status {task['status']!r}; "
                f"allowed from: {', '.join(sorted(TRANSITIONS['claim']))}"
            )
        decorated = self._decorate(task, self._index())
        if decorated["blocked"]:
            reasons = ", ".join(b.get("title", b["ref"]) + f" ({b['reason']})"
                                for b in decorated["blocked_by"])
            raise TaskError(f"blocked by: {reasons}")
        now = datetime.now(timezone.utc)
        self._write(task_id, {
            "status": "claimed",
            "claimed_by": who,
            "claimed_at": now.isoformat(),
            "lease_expires_at": (now + timedelta(minutes=max(1, lease_minutes))).isoformat(),
        })
        return self.get_task(task_id)

    def start_task(self, task_id: str) -> dict[str, Any]:
        # Not in the plan's tool list, but the status diagram has claimed -> in_progress and
        # nothing else could perform it, so the model would be unreachable without it.
        self._require(task_id, "start")
        self._write(task_id, {"status": "in_progress"})
        return self.get_task(task_id)

    def release_task(self, task_id: str, reason: str | None = None) -> dict[str, Any]:
        self._require(task_id, "release")
        self._write(task_id, {
            "status": "released",
            "claimed_by": None,
            "claimed_at": None,
            "lease_expires_at": None,
            "promotion_notes": optional_text(reason),
        })
        return self.get_task(task_id)

    def mark_code_complete(self, task_id: str, ci_run: str) -> dict[str, Any]:
        run = optional_text(ci_run)
        if not run:
            raise TaskError(
                "ci_run is required. code_complete is written only by a verified CI gate, so a "
                "transition with no run reference is exactly the narration the model excludes."
            )
        self._require(task_id, "code_complete")
        self._write(task_id, {
            "status": "code_complete",
            "ci_run": run,
            "verified_at": utc_now(),
        })
        return self.get_task(task_id)

    def accept_task(self, task_id: str, owner: str) -> dict[str, Any]:
        self._require_owner(owner, "accept")
        self._require(task_id, "accept")
        self._write(task_id, {"status": "accepted"})
        return self.get_task(task_id)

    def reiterate_task(self, task_id: str, owner: str, note: str) -> dict[str, Any]:
        self._require_owner(owner, "reiterate")
        note_text = optional_text(note)
        if not note_text:
            raise TaskError("note is required — a reiteration without a reason cannot be acted on")
        original = self._require(task_id, "reiterate")
        successor = self.add_task(
            title=original["title"],
            description=f"{note_text}\n\nReiteration of: {original['title']}\n"
                        f"{original['description']}",
            project=original.get("target_project"),
            repo=original.get("repo"),
            location=original.get("location"),
            recommended_capabilities=original.get("recommended_capabilities"),
            depends_on=original.get("depends_on"),
            links=original.get("links"),
            source=original.get("source"),
            tags=original.get("tags"),
        )
        self._write(task_id, {"status": "reiterate", "promotion_notes": note_text})
        # The successor supersedes the original, using the relationship vocabulary that
        # already exists rather than inventing a task-only link type.
        self.store.add_idea_relationship(
            source_idea_id=successor["id"],
            target_idea_id=task_id,
            relationship_type="supersedes",
            notes=note_text,
        )
        return {"original": self.get_task(task_id), "successor": self.get_task(successor["id"])}

    @staticmethod
    def _require_owner(owner: str | None, transition: str) -> None:
        if not optional_text(owner):
            raise TaskError(
                f"{transition} is an owner-only transition (work-plane section 3) and requires "
                "an explicit owner. An agent must not accept its own work."
            )
