"""Concinnity on the command line.

Standing requirement, owner 2026-09-02: every internal tool ships a CLI as well as an MCP
server. An MCP server is only reachable from a client that has it registered — over SSH, from a
plain terminal, from a script or a CI step, that client does not exist.

This is a front door, not a second implementation: every command calls the same IceboxStore and
TaskStore the MCP tools call, so the two cannot drift. Human-readable output by default,
`--json` everywhere for machines.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from global_icebox import locations
from global_icebox.store import IceboxStore
from global_icebox.tasks import TaskError, TaskStore

STATUS_ORDER = ["open", "claimed", "in_progress", "code_complete", "accepted", "reiterate",
                "released"]


def _out(data: Any, as_json: bool, render) -> None:
    if as_json:
        print(json.dumps(data, indent=2, sort_keys=True, default=str))
    else:
        render(data)


def _short(value: str | None, width: int) -> str:
    text = (value or "")
    return text if len(text) <= width else text[: width - 1] + "…"


def _task_line(task: dict[str, Any]) -> str:
    flags = []
    if task.get("blocked"):
        flags.append("BLOCKED")
    if task.get("claim_is_live"):
        flags.append(f"@{task['claimed_by']}")
    elif task.get("lease_expired") and task.get("claimed_by"):
        flags.append(f"lease-expired({task['claimed_by']})")
    suffix = ("  " + " ".join(flags)) if flags else ""
    key = task.get("external_item_key") or task["id"][:8]
    return f"  {task['status']:<14} {key:<12} {_short(task['title'], 52)}{suffix}"


def render_tasks(tasks: list[dict[str, Any]]) -> None:
    if not tasks:
        print("No tasks.")
        return
    by_status: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        by_status.setdefault(task["status"], []).append(task)
    print(f"{len(tasks)} task(s):")
    for status in STATUS_ORDER:
        for task in by_status.get(status, []):
            print(_task_line(task))


def render_task(task: dict[str, Any]) -> None:
    print(f"{task['title']}")
    print(f"  id          {task['id']}")
    if task.get("external_item_key"):
        print(f"  key         {task['external_item_key']}")
    print(f"  status      {task['status']}")
    for label, field in (("project", "target_project"), ("repo", "repo"),
                         ("location", "location"), ("source", "source"),
                         ("ci run", "ci_run"), ("verified", "verified_at")):
        if task.get(field):
            print(f"  {label:<11} {task[field]}")
    if task.get("claimed_by"):
        state = "live" if task.get("claim_is_live") else "EXPIRED"
        print(f"  claimed     {task['claimed_by']} ({state}, until {task.get('lease_expires_at')})")
    for label, field in (("capabilities", "recommended_capabilities"),
                         ("depends on", "depends_on"), ("links", "links"), ("tags", "tags")):
        if task.get(field):
            print(f"  {label:<11} {', '.join(task[field])}")
    if task.get("blocked"):
        for blocker in task["blocked_by"]:
            print(f"  BLOCKED BY  {blocker.get('title', blocker['ref'])} ({blocker['reason']})")
    print()
    print(task["description"])


def render_ideas(ideas: list[dict[str, Any]]) -> None:
    if not ideas:
        print("No ideas.")
        return
    print(f"{len(ideas)} idea(s):")
    for idea in ideas:
        print(f"  {idea['lane']:<14} {idea['id'][:8]}  {_short(idea['title'], 60)}")


def render_idea(idea: dict[str, Any]) -> None:
    print(idea["title"])
    print(f"  id          {idea['id']}")
    for label, field in (("lane", "lane"), ("status", "status"), ("type", "target_type"),
                         ("project", "target_project"), ("promoted", "promoted_at")):
        if idea.get(field):
            print(f"  {label:<11} {idea[field]}")
    if idea.get("tags"):
        print(f"  {'tags':<11} {', '.join(idea['tags'])}")
    print()
    print(idea["description"])


def render_relations(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("No relationships.")
        return
    for r in rows:
        note = f"  — {_short(r.get('notes'), 40)}" if r.get("notes") else ""
        print(f"  {r['source_idea_id'][:8]} {r['relationship_type']:<14} "
              f"{r['target_idea_id'][:8]}{note}")


def render_comparisons(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("No comparisons recorded yet.")
        return
    for r in rows:
        print(f"  {r.get('created_at', '')[:19]}  winner={r['winner']:<5} "
              f"{r['idea_a_id'][:8]} vs {r['idea_b_id'][:8]}"
              f"{'  ' + _short(r.get('rationale'), 44) if r.get('rationale') else ''}")


def render_runs(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("No published ranking runs.")
        return
    for r in rows:
        print(f"  {r.get('created_at', '')[:19]}  {r['id'][:8]}  {_short(r.get('name'), 48)}")


def render_priorities(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("Nothing ranked yet.")
        return
    for i, row in enumerate(rows, 1):
        rating = row.get("rating", row.get("elo_rating"))
        count = row.get("comparison_count", 0)
        print(f"  {i:>3}. {rating:>7.1f}  ({count:>2} cmp)  {_short(row['title'], 58)}")


def render_locations(payload: dict[str, Any]) -> None:
    print(f"config: {payload['config_path']}"
          f"{'' if payload['config_exists'] else '  (not created yet)'}")
    if not payload["locations"]:
        print("  no locations recorded — set one with: concinnity location set <name> <path>")
        return
    for name, info in payload["locations"].items():
        mark = "" if info["exists"] else "   (missing on this machine)"
        print(f"  {name:<16} {info['path']}{mark}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="concinnity",
        description="Register and rank work. The CLI twin of the Concinnity MCP server.",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--db", help="database path (default: the configured one)")
    sub = parser.add_subparsers(dest="command", required=True)

    # --- tasks ---
    t = sub.add_parser("task", help="the tasks lane").add_subparsers(dest="sub", required=True)

    p = t.add_parser("add", help="register a task")
    p.add_argument("title")
    p.add_argument("description")
    p.add_argument("--project")
    p.add_argument("--repo")
    p.add_argument("--location", help="portable reference, e.g. docs/plan.md")
    p.add_argument("--capability", action="append", dest="capabilities", default=[])
    p.add_argument("--depends-on", action="append", dest="depends_on", default=[])
    p.add_argument("--link", action="append", dest="links", default=[])
    p.add_argument("--source")
    p.add_argument("--key", dest="task_key", help="stable external task key, e.g. SYNC-020")
    p.add_argument("--tag", action="append", dest="tags", default=[])

    p = t.add_parser("list", help="list tasks")
    p.add_argument("--status", choices=STATUS_ORDER)
    p.add_argument("--project")
    p.add_argument("--repo")
    p.add_argument("--claimed-by")
    p.add_argument("--blocked", action="store_true", help="only blocked tasks")
    p.add_argument("--unblocked", action="store_true", help="only unblocked tasks")
    p.add_argument("--all", action="store_true", help="include accepted and reiterated tasks")
    p.add_argument("--limit", type=int, default=100)

    p = t.add_parser("show", help="one task in full")
    p.add_argument("task_id")

    p = t.add_parser("update", help="edit a task's mutable fields")
    p.add_argument("task_id")
    p.add_argument("--title")
    p.add_argument("--description")
    p.add_argument("--project", dest="target_project")
    p.add_argument("--tag", action="append", dest="tags",
                   help="replaces the tag list; repeat for several")

    p = t.add_parser("claim", help="claim an open task")
    p.add_argument("task_id")
    p.add_argument("--by", required=True, dest="claimed_by")
    p.add_argument("--lease-minutes", type=int, default=120)

    p = t.add_parser("start", help="claimed -> in_progress")
    p.add_argument("task_id")

    p = t.add_parser("release", help="give a task back to the pool")
    p.add_argument("task_id")
    p.add_argument("--reason")

    p = t.add_parser("code-complete", help="record a CI gate verdict (requires a run reference)")
    p.add_argument("task_id")
    p.add_argument("--ci-run", required=True)

    p = t.add_parser("accept", help="owner-only: accept verified work")
    p.add_argument("task_id")
    p.add_argument("--owner", required=True)

    p = t.add_parser("reiterate", help="owner-only: send back as a new superseding task")
    p.add_argument("task_id")
    p.add_argument("--owner", required=True)
    p.add_argument("--note", required=True)

    # --- ideas ---
    i = sub.add_parser("idea", help="the idea lanes").add_subparsers(dest="sub", required=True)
    p = i.add_parser("add", help="capture an idea")
    p.add_argument("title")
    p.add_argument("description")
    p.add_argument("--lane", default="project_ideas")
    p.add_argument("--project", dest="target_project")
    p.add_argument("--target-type", default="project")
    p.add_argument("--tag", action="append", dest="tags", default=[])
    p = i.add_parser("list", help="list ideas")
    p.add_argument("--lane")
    p.add_argument("--status")
    p.add_argument("--limit", type=int, default=50)
    p = i.add_parser("search", help="search ideas")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=50)
    p = i.add_parser("show", help="one idea in full")
    p.add_argument("idea_id")
    p = i.add_parser("update", help="edit an idea's mutable fields")
    p.add_argument("idea_id")
    p.add_argument("--title")
    p.add_argument("--description")
    p.add_argument("--lane")
    p.add_argument("--status")
    p.add_argument("--project", dest="target_project")
    p.add_argument("--target-type")
    p.add_argument("--tag", action="append", dest="tags",
                   help="replaces the tag list; repeat for several")
    p = i.add_parser("promote", help="mark an idea as having left the icebox")
    p.add_argument("idea_id")
    p.add_argument("--notes")
    p = i.add_parser("relate", help="record a relationship between two ideas")
    p.add_argument("source_idea_id")
    p.add_argument("target_idea_id")
    p.add_argument("relationship_type",
                   choices=["duplicate_of", "related_to", "promoted_from", "spin_off_from",
                            "supersedes"])
    p.add_argument("--notes")
    p = i.add_parser("relations", help="list recorded relationships")
    p.add_argument("--idea")
    p.add_argument("--type", dest="relationship_type")
    p.add_argument("--limit", type=int, default=50)
    p = i.add_parser("sync-portfolio", help="non-destructively upsert Portfolio features")
    p.add_argument("--project", required=True)
    p.add_argument("--features", required=True,
                   help="path to a JSON file of features, or - for stdin")

    # --- ranking ---
    r = sub.add_parser("rank", help="head-to-head ranking").add_subparsers(dest="sub", required=True)
    p = r.add_parser("pair", help="get a comparison pair")
    p.add_argument("--lane")
    p = r.add_parser("record", help="record a preference")
    p.add_argument("idea_a")
    p.add_argument("idea_b")
    p.add_argument("winner", choices=["a", "b", "tie", "draw"])
    p.add_argument("--rationale")
    p = r.add_parser("list", help="the priority board")
    p.add_argument("--lane")
    p.add_argument("--limit", type=int, default=50)
    p = r.add_parser("history", help="recent comparison records")
    p.add_argument("--idea")
    p.add_argument("--limit", type=int, default=50)
    p = r.add_parser("runs", help="published ranking sessions")
    p.add_argument("--limit", type=int, default=50)
    p = r.add_parser("run", help="one published ranking session")
    p.add_argument("run_id")
    p = r.add_parser("rank-history", help="historical rating snapshots")
    p.add_argument("--idea")
    p.add_argument("--limit", type=int, default=200)
    p = r.add_parser("publish", help="persist a ranking session from a JSON payload")
    p.add_argument("name")
    p.add_argument("--payload", required=True,
                   help="path to a JSON file with decisions[] and rankings[], or - for stdin")
    p.add_argument("--notes")

    # --- locations ---
    loc = sub.add_parser("location", help="named filesystem roots")
    locsub = loc.add_subparsers(dest="sub", required=True)
    locsub.add_parser("list", help="show this machine's locations")
    p = locsub.add_parser("set", help="record a location")
    p.add_argument("name")
    p.add_argument("path")
    p = locsub.add_parser("remove", help="forget a location")
    p.add_argument("name")
    p = locsub.add_parser("resolve", help="resolve a portable reference to a real path")
    p.add_argument("reference")

    # --- backup ---
    b = sub.add_parser("backup", help="dump the database (see also scripts/restore.py)")
    b.add_argument("--commit", action="store_true")
    b.add_argument("--push", action="store_true")

    return parser


def _given(args: argparse.Namespace, *names: str) -> dict[str, Any]:
    """Only the flags actually supplied.

    argparse leaves an unsupplied flag as None, and the store treats None as 'leave alone' --
    but passing every field explicitly would make a typo in one flag look like a deliberate
    blanking of the others. Filtering here keeps an edit to exactly what was typed.
    """
    return {n: getattr(args, n) for n in names if getattr(args, n, None) is not None}


def _load_json(path: str) -> Any:
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def run(args: argparse.Namespace) -> int:
    store = IceboxStore(Path(args.db).expanduser()) if args.db else IceboxStore()
    tasks = TaskStore(store)
    j = args.json

    if args.command == "task":
        if args.sub == "add":
            task = tasks.add_task(
                title=args.title, description=args.description, project=args.project,
                repo=args.repo, location=args.location,
                recommended_capabilities=args.capabilities, depends_on=args.depends_on,
                links=args.links, source=args.source, task_key=args.task_key, tags=args.tags)
            _out(task, j, render_task)
        elif args.sub == "list":
            blocked = True if args.blocked else (False if args.unblocked else None)
            _out(tasks.list_tasks(status=args.status, project=args.project, repo=args.repo,
                                  claimed_by=args.claimed_by, blocked=blocked,
                                  include_terminal=args.all, limit=args.limit), j, render_tasks)
        elif args.sub == "show":
            _out(tasks.get_task(args.task_id), j, render_task)
        elif args.sub == "update":
            fields = _given(args, "title", "description", "target_project", "tags")
            if not fields:
                print("error: nothing to update — pass at least one field", file=sys.stderr)
                return 1
            tasks.get_task(args.task_id)      # refuses if it is not a task
            store.update_idea(idea_id=args.task_id, **fields)
            _out(tasks.get_task(args.task_id), j, render_task)
        elif args.sub == "claim":
            _out(tasks.claim_task(args.task_id, args.claimed_by, args.lease_minutes), j, render_task)
        elif args.sub == "start":
            _out(tasks.start_task(args.task_id), j, render_task)
        elif args.sub == "release":
            _out(tasks.release_task(args.task_id, args.reason), j, render_task)
        elif args.sub == "code-complete":
            _out(tasks.mark_code_complete(args.task_id, args.ci_run), j, render_task)
        elif args.sub == "accept":
            _out(tasks.accept_task(args.task_id, args.owner), j, render_task)
        elif args.sub == "reiterate":
            result = tasks.reiterate_task(args.task_id, args.owner, args.note)
            _out(result, j, lambda r: (print("superseded:"), render_task(r["original"]),
                                       print("\nsuccessor:"), render_task(r["successor"])))

    elif args.command == "idea":
        if args.sub == "add":
            _out(store.add_idea(title=args.title, description=args.description,
                                target_type=args.target_type, target_project=args.target_project,
                                lane=args.lane, tags=args.tags), j,
                 lambda i: print(f"{i['id']}  {i['title']}"))
        elif args.sub == "list":
            _out(store.list_ideas(lane=args.lane, status=args.status, limit=args.limit),
                 j, render_ideas)
        elif args.sub == "search":
            _out(store.search_ideas(query=args.query, limit=args.limit), j, render_ideas)
        elif args.sub == "show":
            _out(store.get_idea(args.idea_id), j, render_idea)
        elif args.sub == "update":
            fields = _given(args, "title", "description", "lane", "status", "target_project",
                            "target_type", "tags")
            if not fields:
                print("error: nothing to update — pass at least one field", file=sys.stderr)
                return 1
            _out(store.update_idea(idea_id=args.idea_id, **fields), j, render_idea)
        elif args.sub == "promote":
            _out(store.promote_idea(idea_id=args.idea_id, promotion_notes=args.notes), j,
                 lambda r: print(f"promoted: {r['idea']['title']}"))
        elif args.sub == "relate":
            _out(store.add_idea_relationship(
                source_idea_id=args.source_idea_id, target_idea_id=args.target_idea_id,
                relationship_type=args.relationship_type, notes=args.notes), j,
                 lambda r: print(f"{args.source_idea_id[:8]} {args.relationship_type} "
                                 f"{args.target_idea_id[:8]}"))
        elif args.sub == "relations":
            _out(store.list_idea_relationships(idea_id=args.idea,
                                               relationship_type=args.relationship_type,
                                               limit=args.limit), j, render_relations)
        elif args.sub == "sync-portfolio":
            _out(store.sync_portfolio_features(project=args.project,
                                               features=_load_json(args.features)), j,
                 lambda r: print(json.dumps(r, indent=2, default=str)))

    elif args.command == "rank":
        if args.sub == "pair":
            _out(store.get_comparison_pair(lane=args.lane), j,
                 lambda p: print(json.dumps(p, indent=2, default=str)))
        elif args.sub == "record":
            _out(store.record_comparison(idea_a_id=args.idea_a, idea_b_id=args.idea_b,
                                         winner=args.winner, rationale=args.rationale), j,
                 lambda r: print("comparison recorded"))
        elif args.sub == "list":
            _out(store.list_priorities(lane=args.lane, limit=args.limit), j, render_priorities)
        elif args.sub == "history":
            _out(store.get_comparison_history(idea_id=args.idea, limit=args.limit), j,
                 render_comparisons)
        elif args.sub == "runs":
            _out(store.list_ranking_runs(limit=args.limit), j, render_runs)
        elif args.sub == "run":
            _out(store.get_ranking_run(args.run_id), j,
                 lambda r: print(json.dumps(r, indent=2, default=str)))
        elif args.sub == "rank-history":
            _out(store.get_rank_history(idea_id=args.idea, limit=args.limit), j,
                 lambda rows: print(json.dumps(rows, indent=2, default=str)))
        elif args.sub == "publish":
            payload = _load_json(args.payload)
            _out(store.publish_ranking_run(
                name=args.name, filters=payload.get("filters"),
                decisions=payload.get("decisions", []),
                rankings=payload.get("rankings", []), notes=args.notes), j,
                 lambda r: print(f"published ranking run {r.get('id', '')}"))

    elif args.command == "location":
        if args.sub == "list":
            _out(locations.list_locations(), j, render_locations)
        elif args.sub == "set":
            _out(locations.set_location(args.name, args.path), j,
                 lambda r: print(f"{r['name']} -> {r['path']}"
                                 f"{'' if r['exists'] else '  (missing on this machine)'}"))
        elif args.sub == "remove":
            _out(locations.remove_location(args.name), j, lambda r: print(f"removed {r['name']}"))
        elif args.sub == "resolve":
            _out(locations.resolve_location(args.reference), j,
                 lambda r: print(r["path"] + ("" if r["exists"] else "   (does not exist)")))

    elif args.command == "backup":
        import subprocess
        script = Path(__file__).resolve().parents[2] / "scripts" / "backup.py"
        cmd = [sys.executable, str(script)]
        if args.commit:
            cmd.append("--commit")
        if args.push:
            cmd.append("--push")
        return subprocess.run(cmd).returncode

    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except (TaskError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
