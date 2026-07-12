from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from .store import IceboxStore

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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
