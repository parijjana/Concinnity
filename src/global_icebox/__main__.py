from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from .store import IceboxStore
from global_icebox import locations as _locations
from global_icebox.tasks import TaskStore as _TaskStore


def _tasks() -> _TaskStore:
    return _TaskStore(store())

mcp = FastMCP("Concinnity")


def store() -> IceboxStore:
    return IceboxStore()


@mcp.tool()
def add_idea(
    title: str,
    description: str,
    origin_project: str | None = None,
    target_type: str = "unknown",
    target_project: str | None = None,
    tags: list[str] | None = None,
    status: str = "icebox",
    lane: str | None = None,
) -> dict[str, Any]:
    """Add a project, feature, or spin-off idea to Concinnity."""
    return store().add_idea(
        title=title,
        description=description,
        origin_project=origin_project,
        target_type=target_type,
        target_project=target_project,
        tags=tags,
        status=status,
        lane=lane,
    )


@mcp.tool()
def list_ideas(
    status: str | None = None,
    target_type: str | None = None,
    origin_project: str | None = None,
    target_project: str | None = None,
    lane: str | None = None,
    tag: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List ideas with optional lane, status, project, target type, and tag filters."""
    return store().list_ideas(
        status=status,
        target_type=target_type,
        origin_project=origin_project,
        target_project=target_project,
        lane=lane,
        tag=tag,
        limit=limit,
    )


@mcp.tool()
def search_ideas(
    query: str,
    lane: str | None = None,
    status: str | None = None,
    target_type: str | None = None,
    target_project: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Search ideas by text, projects, tags, promotion notes, or external identity."""
    return store().search_ideas(
        query=query,
        lane=lane,
        status=status,
        target_type=target_type,
        target_project=target_project,
        limit=limit,
    )


@mcp.tool()
def update_idea(
    idea_id: str,
    title: str | None = None,
    description: str | None = None,
    origin_project: str | None = None,
    target_type: str | None = None,
    target_project: str | None = None,
    lane: str | None = None,
    status: str | None = None,
    tags: list[str] | None = None,
    promotion_notes: str | None = None,
) -> dict[str, Any]:
    """Update mutable idea fields."""
    return store().update_idea(
        idea_id=idea_id,
        title=title,
        description=description,
        origin_project=origin_project,
        target_type=target_type,
        target_project=target_project,
        lane=lane,
        status=status,
        tags=tags,
        promotion_notes=promotion_notes,
    )


@mcp.tool()
def promote_idea(
    idea_id: str,
    promotion_notes: str | None = None,
) -> dict[str, Any]:
    """Mark an idea as promoted and return a structured promotion payload."""
    return store().promote_idea(
        idea_id=idea_id,
        promotion_notes=promotion_notes,
    )


@mcp.tool()
def add_idea_relationship(
    source_idea_id: str,
    target_idea_id: str,
    relationship_type: str,
    notes: str | None = None,
) -> dict[str, Any]:
    """Record lineage, duplication, or relatedness between two ideas."""
    return store().add_idea_relationship(
        source_idea_id=source_idea_id,
        target_idea_id=target_idea_id,
        relationship_type=relationship_type,
        notes=notes,
    )


@mcp.tool()
def list_idea_relationships(
    idea_id: str | None = None,
    relationship_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List idea relationships, optionally filtered by idea or relationship type."""
    return store().list_idea_relationships(
        idea_id=idea_id,
        relationship_type=relationship_type,
        limit=limit,
    )


@mcp.tool()
def get_comparison_pair(
    status: str | None = None,
    target_type: str | None = None,
    target_project: str | None = None,
    lane: str | None = None,
    tag: str | None = None,
) -> dict[str, Any]:
    """Return two candidate ideas for head-to-head priority comparison."""
    return store().get_comparison_pair(
        status=status,
        target_type=target_type,
        target_project=target_project,
        lane=lane,
        tag=tag,
    )


@mcp.tool()
def record_comparison(
    idea_a_id: str,
    idea_b_id: str,
    winner: str,
    rationale: str | None = None,
) -> dict[str, Any]:
    """Record a pairwise preference and update reproducible Elo ratings."""
    return store().record_comparison(
        idea_a_id=idea_a_id,
        idea_b_id=idea_b_id,
        winner=winner,
        rationale=rationale,
    )


@mcp.tool()
def list_priorities(
    status: str | None = None,
    target_type: str | None = None,
    target_project: str | None = None,
    lane: str | None = None,
    tag: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List ideas ranked by head-to-head Elo priority rating."""
    return store().list_priorities(
        status=status,
        target_type=target_type,
        target_project=target_project,
        lane=lane,
        tag=tag,
        limit=limit,
    )


@mcp.tool()
def sync_portfolio_features(
    project_key: str,
    project_name: str,
    repo_name: str | None = None,
    features: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Non-destructively upsert Portfolio todo/done features into Concinnity lanes."""
    return store().sync_portfolio_features(
        project_key=project_key,
        project_name=project_name,
        repo_name=repo_name,
        features=features,
    )


@mcp.tool()
def get_comparison_history(
    idea_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return recent head-to-head comparison records."""
    return store().get_comparison_history(
        idea_id=idea_id,
        limit=limit,
    )


@mcp.tool()
def publish_ranking_run(
    name: str,
    filters: dict[str, Any] | str | None,
    decisions: list[dict[str, Any]],
    rankings: list[dict[str, Any]],
    notes: str | None = None,
    algorithm: str = "session_elo",
) -> dict[str, Any]:
    """Publish a session-based H2H run, decisions, and final ranking snapshot."""
    return store().publish_ranking_run(
        name=name,
        filters=filters,
        decisions=decisions,
        rankings=rankings,
        notes=notes,
        algorithm=algorithm,
    )


@mcp.tool()
def list_ranking_runs(limit: int = 50) -> list[dict[str, Any]]:
    """List published session ranking runs."""
    return store().list_ranking_runs(limit=limit)


@mcp.tool()
def get_ranking_run(run_id: str) -> dict[str, Any]:
    """Return a ranking run with decision rationale and snapshot rows."""
    return store().get_ranking_run(run_id=run_id)


@mcp.tool()
def get_rank_history(
    idea_id: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Return historical ranking snapshot rows for one idea or all ideas."""
    return store().get_rank_history(idea_id=idea_id, limit=limit)


@mcp.resource("icebox://recent")
def recent_ideas() -> str:
    """Return recent ideas as formatted JSON."""
    ideas = store().list_ideas(limit=20)
    return json.dumps(ideas, indent=2)


@mcp.tool()
def list_locations() -> dict[str, Any]:
    """List this machine's named filesystem roots, with the config path and whether each exists."""
    return _locations.list_locations()


@mcp.tool()
def set_location(name: str, path: str) -> dict[str, Any]:
    """Record where a named root lives on THIS machine, so ideas can cite files portably."""
    return _locations.set_location(name=name, path=path)


@mcp.tool()
def remove_location(name: str) -> dict[str, Any]:
    """Forget a named root. Removes the mapping only; nothing on disk is touched."""
    return _locations.remove_location(name=name)


@mcp.tool()
def resolve_location(reference: str) -> dict[str, Any]:
    """Resolve a portable reference like 'future_work/mcp-servers.md' to a real local path."""
    return _locations.resolve_location(reference=reference)


@mcp.tool()
def add_task(
    title: str,
    description: str,
    kind: str = "code",
    acceptance: list[str] | None = None,
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
    """Register a task. kind: code (CI-verifiable) | decision | docs. acceptance: gate:green, test:<id>, check:<G-id>, none."""
    return _tasks().add_task(
        title=title, description=description, kind=kind, acceptance=acceptance,
        project=project, repo=repo,
        location=location, recommended_capabilities=recommended_capabilities,
        depends_on=depends_on, links=links, source=source, task_key=task_key, tags=tags,
    )


@mcp.tool()
def list_tasks(
    status: str | None = None,
    project: str | None = None,
    repo: str | None = None,
    claimed_by: str | None = None,
    blocked: bool | None = None,
    kind: str | None = None,
    include_terminal: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List tasks with derived `blocked` and lease state. Terminal tasks are hidden by default."""
    return _tasks().list_tasks(
        status=status, project=project, repo=repo, claimed_by=claimed_by,
        blocked=blocked, kind=kind, include_terminal=include_terminal, limit=limit,
    )


@mcp.tool()
def get_task(task_id: str) -> dict[str, Any]:
    """One task, with its blockers and lease state resolved."""
    return _tasks().get_task(task_id)


@mcp.tool()
def claim_task(task_id: str, claimed_by: str, lease_minutes: int = 120) -> dict[str, Any]:
    """Claim an open or released task for a lease. Refuses a blocked task or a live claim."""
    return _tasks().claim_task(task_id=task_id, claimed_by=claimed_by, lease_minutes=lease_minutes)


@mcp.tool()
def start_task(task_id: str) -> dict[str, Any]:
    """Move a claimed task to in_progress."""
    return _tasks().start_task(task_id)


@mcp.tool()
def release_task(task_id: str, reason: str | None = None) -> dict[str, Any]:
    """Give a claimed or in-progress task back to the pool."""
    return _tasks().release_task(task_id=task_id, reason=reason)


@mcp.tool()
def mark_code_complete(task_id: str, ci_run: str) -> dict[str, Any]:
    """Record a CI gate's verdict. Requires a CI run reference; this is the ONLY writer of code_complete."""
    return _tasks().mark_code_complete(task_id=task_id, ci_run=ci_run)


@mcp.tool()
def accept_task(task_id: str, owner: str) -> dict[str, Any]:
    """Owner-only: accept verified work. Code complete is not accepted."""
    return _tasks().accept_task(task_id=task_id, owner=owner)


@mcp.tool()
def reiterate_task(task_id: str, owner: str, note: str) -> dict[str, Any]:
    """Owner-only: send verified work back as a NEW task that supersedes this one."""
    return _tasks().reiterate_task(task_id=task_id, owner=owner, note=note)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
