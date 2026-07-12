from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

TARGET_TYPES = {"project", "feature", "spin_off", "unknown"}
STATUSES = {"icebox", "reviewing", "promoted", "rejected", "archived"}
LANES = {"project_ideas", "backlog", "local_icebox", "done"}
PORTFOLIO_STATUSES = {"todo", "done"}
COMPARISON_WINNERS = {"a", "b", "tie", "draw"}
DRAFT_STATUSES = {"staged", "published"}
RELATIONSHIP_TYPES = {
    "duplicate_of",
    "related_to",
    "promoted_from",
    "spin_off_from",
    "supersedes",
}
DEFAULT_ELO_RATING = 1000.0
ELO_K_FACTOR = 32.0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_db_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "icebox.db"


def db_path() -> Path:
    override = os.environ.get("GLOBAL_ICEBOX_DB_PATH")
    if override:
        return Path(override)
    return default_db_path()


def normalize_tags(tags: list[str] | None) -> list[str]:
    if not tags:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        value = tag.strip()
        key = value.casefold()
        if value and key not in seen:
            normalized.append(value)
            seen.add(key)
    return normalized


def validate_target_type(target_type: str) -> str:
    if target_type not in TARGET_TYPES:
        allowed = ", ".join(sorted(TARGET_TYPES))
        raise ValueError(f"target_type must be one of: {allowed}")
    return target_type


def validate_status(status: str) -> str:
    if status not in STATUSES:
        allowed = ", ".join(sorted(STATUSES))
        raise ValueError(f"status must be one of: {allowed}")
    return status


def validate_lane(lane: str) -> str:
    value = lane.casefold().strip()
    if value not in LANES:
        allowed = ", ".join(sorted(LANES))
        raise ValueError(f"lane must be one of: {allowed}")
    return value


def default_lane_for_target_type(target_type: str) -> str:
    return "project_ideas" if target_type == "project" else "local_icebox"


def validate_relationship_type(relationship_type: str) -> str:
    value = relationship_type.casefold().strip()
    if value not in RELATIONSHIP_TYPES:
        allowed = ", ".join(sorted(RELATIONSHIP_TYPES))
        raise ValueError(f"relationship_type must be one of: {allowed}")
    return value


class IceboxStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or db_path()

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = OFF")
        return connection

    def initialize(self) -> None:
        with closing(self.connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ideas (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        description TEXT NOT NULL,
                        origin_project TEXT,
                        target_type TEXT NOT NULL,
                        target_project TEXT,
                        lane TEXT,
                        status TEXT NOT NULL,
                        tags TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        promotion_notes TEXT,
                        promoted_at TEXT,
                        external_source TEXT,
                        external_project_key TEXT,
                        external_item_key TEXT,
                        external_item_metadata TEXT
                    )
                    """
                )
                ensure_column(connection, "ideas", "lane", "TEXT")
                ensure_column(connection, "ideas", "external_source", "TEXT")
                ensure_column(connection, "ideas", "external_project_key", "TEXT")
                ensure_column(connection, "ideas", "external_item_key", "TEXT")
                ensure_column(connection, "ideas", "external_item_metadata", "TEXT")
                connection.execute(
                    """
                    UPDATE ideas
                    SET lane = CASE
                        WHEN target_type = 'project' THEN 'project_ideas'
                        ELSE 'local_icebox'
                    END
                    WHERE lane IS NULL OR TRIM(lane) = ''
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_ideas_status ON ideas(status)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_ideas_lane ON ideas(lane)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_ideas_target_type ON ideas(target_type)"
                )
                connection.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_ideas_external_identity
                    ON ideas(external_source, external_project_key, external_item_key)
                    WHERE external_source IS NOT NULL
                      AND external_project_key IS NOT NULL
                      AND external_item_key IS NOT NULL
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS idea_ratings (
                        idea_id TEXT PRIMARY KEY,
                        rating REAL NOT NULL DEFAULT 1000,
                        comparison_count INTEGER NOT NULL DEFAULT 0,
                        wins INTEGER NOT NULL DEFAULT 0,
                        losses INTEGER NOT NULL DEFAULT 0,
                        ties INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY (idea_id) REFERENCES ideas(id) ON DELETE CASCADE
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS idea_comparisons (
                        id TEXT PRIMARY KEY,
                        idea_a_id TEXT NOT NULL,
                        idea_b_id TEXT NOT NULL,
                        winner TEXT NOT NULL,
                        rationale TEXT,
                        rating_a_before REAL NOT NULL,
                        rating_b_before REAL NOT NULL,
                        rating_a_after REAL NOT NULL,
                        rating_b_after REAL NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (idea_a_id) REFERENCES ideas(id) ON DELETE CASCADE,
                        FOREIGN KEY (idea_b_id) REFERENCES ideas(id) ON DELETE CASCADE
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_idea_comparisons_created_at
                    ON idea_comparisons(created_at)
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_idea_comparisons_idea_a
                    ON idea_comparisons(idea_a_id)
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_idea_comparisons_idea_b
                    ON idea_comparisons(idea_b_id)
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS idea_relationships (
                        id TEXT PRIMARY KEY,
                        source_idea_id TEXT NOT NULL,
                        target_idea_id TEXT NOT NULL,
                        relationship_type TEXT NOT NULL,
                        notes TEXT,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (source_idea_id) REFERENCES ideas(id) ON DELETE CASCADE,
                        FOREIGN KEY (target_idea_id) REFERENCES ideas(id) ON DELETE CASCADE
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_idea_relationships_source
                    ON idea_relationships(source_idea_id)
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_idea_relationships_target
                    ON idea_relationships(target_idea_id)
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ranking_runs (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        filters_json TEXT NOT NULL,
                        algorithm TEXT NOT NULL,
                        status TEXT NOT NULL,
                        notes TEXT,
                        created_at TEXT NOT NULL,
                        published_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ranking_decisions (
                        id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        round_number INTEGER NOT NULL,
                        idea_a_id TEXT NOT NULL,
                        idea_b_id TEXT NOT NULL,
                        winner TEXT NOT NULL,
                        reason_code TEXT NOT NULL,
                        reason_note TEXT,
                        rating_a_before REAL NOT NULL,
                        rating_b_before REAL NOT NULL,
                        rating_a_after REAL NOT NULL,
                        rating_b_after REAL NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (run_id) REFERENCES ranking_runs(id) ON DELETE CASCADE,
                        FOREIGN KEY (idea_a_id) REFERENCES ideas(id) ON DELETE CASCADE,
                        FOREIGN KEY (idea_b_id) REFERENCES ideas(id) ON DELETE CASCADE
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_ranking_decisions_run
                    ON ranking_decisions(run_id, round_number)
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ranking_snapshot_items (
                        id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        idea_id TEXT NOT NULL,
                        rank INTEGER NOT NULL,
                        rating REAL NOT NULL,
                        comparison_count INTEGER NOT NULL,
                        wins INTEGER NOT NULL,
                        losses INTEGER NOT NULL,
                        ties INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (run_id) REFERENCES ranking_runs(id) ON DELETE CASCADE,
                        FOREIGN KEY (idea_id) REFERENCES ideas(id) ON DELETE CASCADE
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_ranking_snapshot_idea
                    ON ranking_snapshot_items(idea_id, created_at)
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ranking_drafts (
                        id TEXT PRIMARY KEY,
                        client_session_id TEXT,
                        name TEXT NOT NULL,
                        filters_json TEXT NOT NULL,
                        algorithm TEXT NOT NULL,
                        notes TEXT,
                        decisions_json TEXT NOT NULL,
                        before_rankings_json TEXT NOT NULL,
                        after_rankings_json TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        published_run_id TEXT,
                        FOREIGN KEY (published_run_id) REFERENCES ranking_runs(id)
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_ranking_drafts_client_session
                    ON ranking_drafts(client_session_id)
                    WHERE client_session_id IS NOT NULL
                    """
                )
                now = utc_now()
                connection.execute(
                    """
                    INSERT OR IGNORE INTO idea_ratings (
                        idea_id, rating, comparison_count, wins, losses, ties, updated_at
                    )
                    SELECT id, ?, 0, 0, 0, 0, ? FROM ideas
                    """,
                    (DEFAULT_ELO_RATING, now),
                )

    def add_idea(
        self,
        title: str,
        description: str,
        origin_project: str | None = None,
        target_type: str = "unknown",
        target_project: str | None = None,
        tags: list[str] | None = None,
        status: str = "icebox",
        lane: str | None = None,
        external_source: str | None = None,
        external_project_key: str | None = None,
        external_item_key: str | None = None,
        external_item_metadata: dict[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        title = title.strip()
        description = description.strip()
        if not title:
            raise ValueError("title is required")
        if not description:
            raise ValueError("description is required")
        target_type = validate_target_type(target_type)
        status = validate_status(status)
        lane = validate_lane(lane) if lane is not None else default_lane_for_target_type(target_type)
        now = utc_now()
        record = {
            "id": str(uuid4()),
            "title": title,
            "description": description,
            "origin_project": origin_project,
            "target_type": target_type,
            "target_project": target_project,
            "lane": lane,
            "status": status,
            "tags": normalize_tags(tags),
            "created_at": now,
            "updated_at": now,
            "promotion_notes": None,
            "promoted_at": None,
            "external_source": optional_text(external_source),
            "external_project_key": optional_text(external_project_key),
            "external_item_key": optional_text(external_item_key),
            "external_item_metadata": normalize_optional_json_payload(
                external_item_metadata,
            ),
        }
        self.initialize()
        with closing(self.connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO ideas (
                        id, title, description, origin_project, target_type,
                        target_project, lane, status, tags, created_at, updated_at,
                        promotion_notes, promoted_at, external_source,
                        external_project_key, external_item_key,
                        external_item_metadata
                    )
                    VALUES (
                        :id, :title, :description, :origin_project, :target_type,
                        :target_project, :lane, :status, :tags, :created_at,
                        :updated_at, :promotion_notes, :promoted_at,
                        :external_source, :external_project_key,
                        :external_item_key, :external_item_metadata
                    )
                    """,
                    {**record, "tags": json.dumps(record["tags"])},
                )
                connection.execute(
                    """
                    INSERT INTO idea_ratings (
                        idea_id, rating, comparison_count, wins, losses, ties, updated_at
                    )
                    VALUES (?, ?, 0, 0, 0, 0, ?)
                    """,
                    (record["id"], DEFAULT_ELO_RATING, now),
                )
        return record

    def get_idea(self, idea_id: str) -> dict[str, Any]:
        self.initialize()
        with closing(self.connect()) as connection:
            row = connection.execute(
                "SELECT * FROM ideas WHERE id = ?",
                (idea_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"idea not found: {idea_id}")
        return row_to_idea(row)

    def list_ideas(
        self,
        status: str | None = None,
        target_type: str | None = None,
        origin_project: str | None = None,
        target_project: str | None = None,
        lane: str | None = None,
        tag: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if status is not None:
            validate_status(status)
        if target_type is not None:
            validate_target_type(target_type)
        if lane is not None:
            lane = validate_lane(lane)
        limit = clamp_limit(limit)
        filters: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("status", status),
            ("target_type", target_type),
            ("origin_project", origin_project),
            ("target_project", target_project),
            ("lane", lane),
        ):
            if value is not None:
                filters.append(f"{column} = ?")
                params.append(value)
        if tag:
            filters.append("LOWER(tags) LIKE ?")
            params.append(f"%{tag.casefold()}%")
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        params.append(limit)
        self.initialize()
        with closing(self.connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM ideas
                {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        ideas = [row_to_idea(row) for row in rows]
        if tag:
            tag_key = tag.casefold()
            ideas = [
                idea
                for idea in ideas
                if any(existing.casefold() == tag_key for existing in idea["tags"])
            ]
        return ideas

    def search_ideas(
        self,
        query: str,
        lane: str | None = None,
        status: str | None = None,
        target_type: str | None = None,
        target_project: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            return self.list_ideas(
                lane=lane,
                status=status,
                target_type=target_type,
                target_project=target_project,
                limit=limit,
            )
        if lane is not None:
            lane = validate_lane(lane)
        if status is not None:
            validate_status(status)
        if target_type is not None:
            validate_target_type(target_type)
        limit = clamp_limit(limit)
        like = f"%{query.casefold()}%"
        filters = [
            """(
                LOWER(title) LIKE ?
                OR LOWER(description) LIKE ?
                OR LOWER(COALESCE(origin_project, '')) LIKE ?
                OR LOWER(COALESCE(target_project, '')) LIKE ?
                OR LOWER(tags) LIKE ?
                OR LOWER(COALESCE(promotion_notes, '')) LIKE ?
                OR LOWER(COALESCE(external_project_key, '')) LIKE ?
                OR LOWER(COALESCE(external_item_key, '')) LIKE ?
            )"""
        ]
        params: list[Any] = [like, like, like, like, like, like, like, like]
        for column, value in (
            ("lane", lane),
            ("status", status),
            ("target_type", target_type),
            ("target_project", target_project),
        ):
            if value is not None:
                filters.append(f"{column} = ?")
                params.append(value)
        params.append(limit)
        self.initialize()
        with closing(self.connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM ideas
                WHERE {' AND '.join(filters)}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [row_to_idea(row) for row in rows]

    def list_projects(
        self,
        status: str | None = "icebox",
        lane: str | None = None,
    ) -> list[dict[str, Any]]:
        if status is not None:
            validate_status(status)
        if lane is not None:
            lane = validate_lane(lane)
        filters = [
            "target_project IS NOT NULL",
            "TRIM(target_project) != ''",
        ]
        params: list[Any] = []
        if status is not None:
            filters.append("status = ?")
            params.append(status)
        if lane is not None:
            filters.append("lane = ?")
            params.append(lane)
        self.initialize()
        with closing(self.connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT
                    TRIM(target_project) AS target_project,
                    COUNT(*) AS idea_count
                FROM ideas
                WHERE {' AND '.join(filters)}
                GROUP BY TRIM(target_project)
                ORDER BY LOWER(TRIM(target_project)) ASC, TRIM(target_project) ASC
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def update_idea(
        self,
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
        external_source: str | None = None,
        external_project_key: str | None = None,
        external_item_key: str | None = None,
        external_item_metadata: dict[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        self.get_idea(idea_id)
        updates: dict[str, Any] = {"updated_at": utc_now()}
        if title is not None:
            title = title.strip()
            if not title:
                raise ValueError("title cannot be empty")
            updates["title"] = title
        if description is not None:
            description = description.strip()
            if not description:
                raise ValueError("description cannot be empty")
            updates["description"] = description
        if origin_project is not None:
            updates["origin_project"] = origin_project
        if target_type is not None:
            updates["target_type"] = validate_target_type(target_type)
        if target_project is not None:
            updates["target_project"] = target_project
        if lane is not None:
            updates["lane"] = validate_lane(lane)
        if status is not None:
            updates["status"] = validate_status(status)
        if tags is not None:
            updates["tags"] = json.dumps(normalize_tags(tags))
        if promotion_notes is not None:
            updates["promotion_notes"] = promotion_notes
        if external_source is not None:
            updates["external_source"] = optional_text(external_source)
        if external_project_key is not None:
            updates["external_project_key"] = optional_text(external_project_key)
        if external_item_key is not None:
            updates["external_item_key"] = optional_text(external_item_key)
        if external_item_metadata is not None:
            updates["external_item_metadata"] = normalize_optional_json_payload(
                external_item_metadata,
            )
        assignments = ", ".join(f"{field} = :{field}" for field in updates)
        params = {**updates, "id": idea_id}
        self.initialize()
        with closing(self.connect()) as connection:
            with connection:
                connection.execute(
                    f"UPDATE ideas SET {assignments} WHERE id = :id",
                    params,
                )
        return self.get_idea(idea_id)

    def promote_idea(
        self,
        idea_id: str,
        promotion_notes: str | None = None,
    ) -> dict[str, Any]:
        promoted_at = utc_now()
        notes = promotion_notes or ""
        self.get_idea(idea_id)
        with closing(self.connect()) as connection:
            with connection:
                connection.execute(
                    """
                    UPDATE ideas
                    SET status = ?, promotion_notes = ?, promoted_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    ("promoted", notes, promoted_at, promoted_at, idea_id),
                )
        idea = self.get_idea(idea_id)
        return {
            "idea": idea,
            "promotion": {
                "id": idea["id"],
                "title": idea["title"],
                "description": idea["description"],
                "origin_project": idea["origin_project"],
                "target_type": idea["target_type"],
                "target_project": idea["target_project"],
                "promotion_notes": idea["promotion_notes"],
                "promoted_at": idea["promoted_at"],
            },
        }

    def sync_portfolio_features(
        self,
        project_key: str,
        project_name: str,
        repo_name: str | None = None,
        features: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        project_key = project_key.strip()
        project_name = project_name.strip()
        if not project_key:
            raise ValueError("project_key is required")
        if not project_name:
            raise ValueError("project_name is required")
        if features is None:
            features = []
        if not isinstance(features, list):
            raise ValueError("features must be a list")

        now = utc_now()
        created = 0
        updated = 0
        unchanged = 0
        upserted: list[dict[str, Any]] = []
        self.initialize()
        with closing(self.connect()) as connection:
            with connection:
                for feature in features:
                    if not isinstance(feature, dict):
                        raise ValueError("each feature must be an object")
                    title = require_text(feature, "name")
                    portfolio_status = str(feature.get("status") or "").casefold().strip()
                    if portfolio_status not in PORTFOLIO_STATUSES:
                        allowed = ", ".join(sorted(PORTFOLIO_STATUSES))
                        raise ValueError(f"feature status must be one of: {allowed}")
                    lane = "done" if portfolio_status == "done" else "backlog"
                    lifecycle_status = "promoted" if lane == "done" else "icebox"
                    external_item_key = portfolio_feature_identity_key(title)
                    external_metadata = normalize_optional_json_payload(
                        {
                            "portfolio_feature_key": optional_text(
                                feature.get("feature_key"),
                            ),
                            "portfolio_status": portfolio_status,
                            "repo_name": optional_text(repo_name),
                        },
                    )
                    description = optional_text(feature.get("description")) or (
                        f"Portfolio {portfolio_status} feature synced from {project_name}."
                    )
                    existing = connection.execute(
                        """
                        SELECT * FROM ideas
                        WHERE external_source = ?
                          AND external_project_key = ?
                          AND external_item_key = ?
                        """,
                        ("portfolio", project_key, external_item_key),
                    ).fetchone()
                    if existing is None:
                        idea_id = str(uuid4())
                        connection.execute(
                            """
                            INSERT INTO ideas (
                                id, title, description, origin_project, target_type,
                                target_project, lane, status, tags, created_at,
                                updated_at, promotion_notes, promoted_at,
                                external_source, external_project_key,
                                external_item_key, external_item_metadata
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                idea_id,
                                title,
                                description,
                                optional_text(repo_name) or project_name,
                                "feature",
                                project_name,
                                lane,
                                lifecycle_status,
                                json.dumps(normalize_tags(["portfolio", portfolio_status])),
                                now,
                                now,
                                None,
                                now if lifecycle_status == "promoted" else None,
                                "portfolio",
                                project_key,
                                external_item_key,
                                external_metadata,
                            ),
                        )
                        connection.execute(
                            """
                            INSERT INTO idea_ratings (
                                idea_id, rating, comparison_count, wins, losses,
                                ties, updated_at
                            )
                            VALUES (?, ?, 0, 0, 0, 0, ?)
                            """,
                            (idea_id, DEFAULT_ELO_RATING, now),
                        )
                        created += 1
                        row = connection.execute(
                            "SELECT * FROM ideas WHERE id = ?",
                            (idea_id,),
                        ).fetchone()
                    else:
                        existing_idea = row_to_idea(existing)
                        changes = {
                            "title": title,
                            "description": description,
                            "origin_project": optional_text(repo_name) or project_name,
                            "target_type": "feature",
                            "target_project": project_name,
                            "lane": lane,
                            "status": lifecycle_status,
                            "tags": json.dumps(normalize_tags(["portfolio", portfolio_status])),
                            "promoted_at": now
                            if lifecycle_status == "promoted"
                            else existing_idea["promoted_at"],
                            "external_item_metadata": external_metadata,
                        }
                        changed = existing_idea["tags"] != [
                            "portfolio",
                            portfolio_status,
                        ]
                        for field, value in changes.items():
                            if field == "tags":
                                continue
                            existing_value = existing_idea.get(field)
                            if field == "external_item_metadata":
                                value = parse_optional_json_payload(value)
                            if existing_value != value:
                                changed = True
                                break
                        if changed:
                            changes["updated_at"] = now
                            assignments = ", ".join(
                                f"{field} = :{field}" for field in changes
                            )
                            connection.execute(
                                f"UPDATE ideas SET {assignments} WHERE id = :id",
                                {**changes, "id": existing_idea["id"]},
                            )
                            updated += 1
                        else:
                            unchanged += 1
                        row = connection.execute(
                            "SELECT * FROM ideas WHERE id = ?",
                            (existing_idea["id"],),
                        ).fetchone()
                    upserted.append(row_to_idea(row))

        return {
            "project_key": project_key,
            "project_name": project_name,
            "repo_name": repo_name,
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "upserted_count": len(upserted),
            "upserted": upserted,
        }

    def add_idea_relationship(
        self,
        source_idea_id: str,
        target_idea_id: str,
        relationship_type: str,
        notes: str | None = None,
    ) -> dict[str, Any]:
        if source_idea_id == target_idea_id:
            raise ValueError("source_idea_id and target_idea_id must be different")
        relationship_type = validate_relationship_type(relationship_type)
        now = utc_now()
        relationship_id = str(uuid4())
        self.initialize()
        with closing(self.connect()) as connection:
            with connection:
                ensure_idea_exists(connection, source_idea_id)
                ensure_idea_exists(connection, target_idea_id)
                connection.execute(
                    """
                    INSERT INTO idea_relationships (
                        id, source_idea_id, target_idea_id, relationship_type,
                        notes, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        relationship_id,
                        source_idea_id,
                        target_idea_id,
                        relationship_type,
                        optional_text(notes),
                        now,
                    ),
                )
        return self.get_idea_relationship(relationship_id)

    def get_idea_relationship(self, relationship_id: str) -> dict[str, Any]:
        self.initialize()
        with closing(self.connect()) as connection:
            row = connection.execute(
                """
                SELECT * FROM idea_relationships
                WHERE id = ?
                """,
                (relationship_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"idea relationship not found: {relationship_id}")
        return dict(row)

    def list_idea_relationships(
        self,
        idea_id: str | None = None,
        relationship_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if relationship_type is not None:
            relationship_type = validate_relationship_type(relationship_type)
        limit = clamp_limit(limit)
        filters: list[str] = []
        params: list[Any] = []
        if idea_id is not None:
            filters.append("(source_idea_id = ? OR target_idea_id = ?)")
            params.extend([idea_id, idea_id])
        if relationship_type is not None:
            filters.append("relationship_type = ?")
            params.append(relationship_type)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        params.append(limit)
        self.initialize()
        with closing(self.connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM idea_relationships
                {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def get_comparison_pair(
        self,
        status: str | None = None,
        target_type: str | None = None,
        target_project: str | None = None,
        lane: str | None = None,
        tag: str | None = None,
    ) -> dict[str, Any]:
        ideas = self.list_priorities(
            status=status,
            target_type=target_type,
            target_project=target_project,
            lane=lane,
            tag=tag,
            limit=200,
            order_by="fewest_comparisons",
        )
        if len(ideas) < 2:
            raise ValueError("at least two matching ideas are required")

        compared_pairs = self._compared_pair_keys()
        fallback: tuple[dict[str, Any], dict[str, Any]] | None = None
        for index, idea_a in enumerate(ideas):
            for idea_b in ideas[index + 1 :]:
                fallback = fallback or (idea_a, idea_b)
                pair_key = canonical_pair_key(idea_a["id"], idea_b["id"])
                if pair_key not in compared_pairs:
                    return {
                        "idea_a": idea_a,
                        "idea_b": idea_b,
                        "already_compared": False,
                    }
        assert fallback is not None
        return {
            "idea_a": fallback[0],
            "idea_b": fallback[1],
            "already_compared": True,
        }

    def record_comparison(
        self,
        idea_a_id: str,
        idea_b_id: str,
        winner: str,
        rationale: str | None = None,
    ) -> dict[str, Any]:
        if idea_a_id == idea_b_id:
            raise ValueError("idea_a_id and idea_b_id must be different")
        winner = normalize_winner(winner)
        self.initialize()
        with closing(self.connect()) as connection:
            with connection:
                idea_a = connection.execute(
                    "SELECT * FROM ideas WHERE id = ?",
                    (idea_a_id,),
                ).fetchone()
                idea_b = connection.execute(
                    "SELECT * FROM ideas WHERE id = ?",
                    (idea_b_id,),
                ).fetchone()
                if idea_a is None:
                    raise ValueError(f"idea not found: {idea_a_id}")
                if idea_b is None:
                    raise ValueError(f"idea not found: {idea_b_id}")

                rating_a = self._rating_row(connection, idea_a_id)
                rating_b = self._rating_row(connection, idea_b_id)
                rating_a_before = float(rating_a["rating"])
                rating_b_before = float(rating_b["rating"])
                score_a, score_b = comparison_scores(winner)
                rating_a_after = elo_after(rating_a_before, rating_b_before, score_a)
                rating_b_after = elo_after(rating_b_before, rating_a_before, score_b)
                now = utc_now()

                connection.execute(
                    """
                    INSERT INTO idea_comparisons (
                        id, idea_a_id, idea_b_id, winner, rationale,
                        rating_a_before, rating_b_before, rating_a_after,
                        rating_b_after, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        idea_a_id,
                        idea_b_id,
                        winner,
                        rationale,
                        rating_a_before,
                        rating_b_before,
                        rating_a_after,
                        rating_b_after,
                        now,
                    ),
                )
                counts_a = outcome_counts_for_a(winner)
                counts_b = outcome_counts_for_b(winner)
                self._update_rating(
                    connection,
                    idea_a_id,
                    rating_a_after,
                    now,
                    counts_a,
                )
                self._update_rating(
                    connection,
                    idea_b_id,
                    rating_b_after,
                    now,
                    counts_b,
                )

        return {
            "idea_a": self.get_priority(idea_a_id),
            "idea_b": self.get_priority(idea_b_id),
            "winner": winner,
            "rationale": rationale,
        }

    def list_priorities(
        self,
        status: str | None = None,
        target_type: str | None = None,
        target_project: str | None = None,
        lane: str | None = None,
        tag: str | None = None,
        limit: int = 50,
        order_by: str = "rating",
    ) -> list[dict[str, Any]]:
        if status is not None:
            validate_status(status)
        if target_type is not None:
            validate_target_type(target_type)
        if lane is not None:
            lane = validate_lane(lane)
        limit = clamp_limit(limit)
        filters: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("ideas.status", status),
            ("ideas.target_type", target_type),
            ("ideas.target_project", target_project),
            ("ideas.lane", lane),
        ):
            if value is not None:
                filters.append(f"{column} = ?")
                params.append(value)
        if tag:
            filters.append("LOWER(ideas.tags) LIKE ?")
            params.append(f"%{tag.casefold()}%")
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        ordering = (
            "idea_ratings.comparison_count ASC, ideas.created_at DESC"
            if order_by == "fewest_comparisons"
            else "idea_ratings.rating DESC, idea_ratings.comparison_count DESC, ideas.created_at DESC"
        )
        params.append(limit)
        self.initialize()
        with closing(self.connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT
                    ideas.id,
                    ideas.title,
                    ideas.target_type,
                    ideas.target_project,
                    ideas.lane,
                    ideas.status,
                    ideas.external_source,
                    ideas.external_project_key,
                    ideas.external_item_key,
                    idea_ratings.rating,
                    idea_ratings.comparison_count,
                    idea_ratings.wins,
                    idea_ratings.losses,
                    idea_ratings.ties,
                    idea_ratings.updated_at,
                    ideas.tags
                FROM ideas
                JOIN idea_ratings ON idea_ratings.idea_id = ideas.id
                {where}
                ORDER BY {ordering}
                LIMIT ?
                """,
                params,
            ).fetchall()
        priorities = [row_to_priority(row) for row in rows]
        if tag:
            tag_key = tag.casefold()
            priorities = [
                idea
                for idea in priorities
                if any(existing.casefold() == tag_key for existing in idea["tags"])
            ]
        return priorities

    def get_priority(self, idea_id: str) -> dict[str, Any]:
        self.initialize()
        with closing(self.connect()) as connection:
            row = connection.execute(
                """
                SELECT
                    ideas.id,
                    ideas.title,
                    ideas.target_type,
                    ideas.target_project,
                    ideas.lane,
                    ideas.status,
                    ideas.external_source,
                    ideas.external_project_key,
                    ideas.external_item_key,
                    idea_ratings.rating,
                    idea_ratings.comparison_count,
                    idea_ratings.wins,
                    idea_ratings.losses,
                    idea_ratings.ties,
                    idea_ratings.updated_at,
                    ideas.tags
                FROM ideas
                JOIN idea_ratings ON idea_ratings.idea_id = ideas.id
                WHERE ideas.id = ?
                """,
                (idea_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"idea not found: {idea_id}")
        return row_to_priority(row)

    def get_comparison_history(
        self,
        idea_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        limit = clamp_limit(limit)
        filters = ""
        params: list[Any] = []
        if idea_id is not None:
            filters = "WHERE idea_a_id = ? OR idea_b_id = ?"
            params.extend([idea_id, idea_id])
        params.append(limit)
        self.initialize()
        with closing(self.connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM idea_comparisons
                {filters}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def save_ranking_draft(
        self,
        name: str,
        filters: dict[str, Any] | str | None,
        decisions: list[dict[str, Any]],
        before_rankings: list[dict[str, Any]],
        after_rankings: list[dict[str, Any]],
        notes: str | None = None,
        algorithm: str = "session_elo",
        draft_id: str | None = None,
        client_session_id: str | None = None,
    ) -> dict[str, Any]:
        draft_id = (draft_id or client_session_id or str(uuid4())).strip()
        client_session_id = optional_text(client_session_id) or draft_id
        name = name.strip()
        if not draft_id:
            raise ValueError("draft_id is required")
        if not name:
            raise ValueError("name is required")
        if not before_rankings:
            raise ValueError("before_rankings are required")
        if not after_rankings:
            raise ValueError("after_rankings are required")
        filters_json = normalize_json_payload(filters or {})
        decisions_json = json.dumps(decisions)
        before_rankings_json = json.dumps(before_rankings)
        after_rankings_json = json.dumps(after_rankings)
        algorithm = algorithm.strip() or "session_elo"
        now = utc_now()
        self.initialize()
        with closing(self.connect()) as connection:
            with connection:
                existing = connection.execute(
                    """
                    SELECT id, status FROM ranking_drafts
                    WHERE id = ? OR client_session_id = ?
                    """,
                    (draft_id, client_session_id),
                ).fetchone()
                if existing is not None and existing["status"] == "published":
                    raise ValueError("published drafts cannot be updated")

                self._validate_ranking_payload(
                    connection,
                    before_rankings,
                    "before_rankings",
                )
                self._validate_ranking_payload(
                    connection,
                    after_rankings,
                    "after_rankings",
                )
                self._validate_decision_payload(connection, decisions)

                if existing is None:
                    created_at = now
                    connection.execute(
                        """
                        INSERT INTO ranking_drafts (
                            id, client_session_id, name, filters_json, algorithm,
                            notes, decisions_json, before_rankings_json,
                            after_rankings_json, status, created_at, updated_at,
                            published_run_id
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                        """,
                        (
                            draft_id,
                            client_session_id,
                            name,
                            filters_json,
                            algorithm,
                            notes,
                            decisions_json,
                            before_rankings_json,
                            after_rankings_json,
                            "staged",
                            created_at,
                            now,
                        ),
                    )
                else:
                    draft_id = existing["id"]
                    connection.execute(
                        """
                        UPDATE ranking_drafts
                        SET client_session_id = ?,
                            name = ?,
                            filters_json = ?,
                            algorithm = ?,
                            notes = ?,
                            decisions_json = ?,
                            before_rankings_json = ?,
                            after_rankings_json = ?,
                            status = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            client_session_id,
                            name,
                            filters_json,
                            algorithm,
                            notes,
                            decisions_json,
                            before_rankings_json,
                            after_rankings_json,
                            "staged",
                            now,
                            draft_id,
                        ),
                    )
        return self.get_ranking_draft(draft_id)

    def get_ranking_draft(self, draft_id: str) -> dict[str, Any]:
        self.initialize()
        with closing(self.connect()) as connection:
            row = connection.execute(
                """
                SELECT * FROM ranking_drafts
                WHERE id = ? OR client_session_id = ?
                """,
                (draft_id, draft_id),
            ).fetchone()
        if row is None:
            raise ValueError(f"ranking draft not found: {draft_id}")
        return split_ranking_draft(row_to_ranking_draft(row))

    def publish_ranking_draft(self, draft_id: str) -> dict[str, Any]:
        self.initialize()
        with closing(self.connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    """
                    SELECT * FROM ranking_drafts
                    WHERE id = ? OR client_session_id = ?
                    """,
                    (draft_id, draft_id),
                ).fetchone()
                if row is None:
                    raise ValueError(f"ranking draft not found: {draft_id}")
                draft = row_to_ranking_draft(row)
                published_run_id = draft["published_run_id"]
                if published_run_id is None:
                    published_run_id = str(uuid4())
                    now = utc_now()
                    self._insert_published_ranking_run(
                        connection=connection,
                        run_id=published_run_id,
                        name=draft["name"],
                        filters_json=normalize_json_payload(draft["filters"]),
                        decisions=draft["decisions"],
                        rankings=draft["after_rankings"],
                        notes=draft["notes"],
                        algorithm=draft["algorithm"],
                        now=now,
                    )
                    connection.execute(
                        """
                        UPDATE ranking_drafts
                        SET status = ?, updated_at = ?, published_run_id = ?
                        WHERE id = ?
                        """,
                        ("published", now, published_run_id, draft["id"]),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return {
            "draft": self.get_ranking_draft(draft_id)["draft"],
            "published": self.get_ranking_run(published_run_id),
        }

    def publish_ranking_run(
        self,
        name: str,
        filters: dict[str, Any] | str | None,
        decisions: list[dict[str, Any]],
        rankings: list[dict[str, Any]],
        notes: str | None = None,
        algorithm: str = "session_elo",
    ) -> dict[str, Any]:
        name = name.strip()
        if not name:
            raise ValueError("name is required")
        if not rankings:
            raise ValueError("rankings are required")
        filters_json = normalize_json_payload(filters or {})
        now = utc_now()
        run_id = str(uuid4())
        self.initialize()
        with closing(self.connect()) as connection:
            with connection:
                self._insert_published_ranking_run(
                    connection=connection,
                    run_id=run_id,
                    name=name,
                    filters_json=filters_json,
                    decisions=decisions,
                    rankings=rankings,
                    notes=notes,
                    algorithm=algorithm,
                    now=now,
                )

        return self.get_ranking_run(run_id)

    def list_ranking_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = clamp_limit(limit)
        self.initialize()
        with closing(self.connect()) as connection:
            rows = connection.execute(
                """
                SELECT
                    ranking_runs.*,
                    COUNT(DISTINCT ranking_snapshot_items.id) AS snapshot_count,
                    COUNT(DISTINCT ranking_decisions.id) AS decision_count
                FROM ranking_runs
                LEFT JOIN ranking_snapshot_items
                    ON ranking_snapshot_items.run_id = ranking_runs.id
                LEFT JOIN ranking_decisions
                    ON ranking_decisions.run_id = ranking_runs.id
                GROUP BY ranking_runs.id
                ORDER BY ranking_runs.published_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [row_to_ranking_run(row) for row in rows]

    def get_ranking_run(self, run_id: str) -> dict[str, Any]:
        self.initialize()
        with closing(self.connect()) as connection:
            run = connection.execute(
                "SELECT * FROM ranking_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if run is None:
                raise ValueError(f"ranking run not found: {run_id}")
            decisions = connection.execute(
                """
                SELECT * FROM ranking_decisions
                WHERE run_id = ?
                ORDER BY round_number ASC
                """,
                (run_id,),
            ).fetchall()
            snapshot = connection.execute(
                """
                SELECT
                    ranking_snapshot_items.*,
                    ideas.title,
                    ideas.target_type,
                    ideas.target_project,
                    ideas.lane,
                    ideas.status
                FROM ranking_snapshot_items
                JOIN ideas ON ideas.id = ranking_snapshot_items.idea_id
                WHERE ranking_snapshot_items.run_id = ?
                ORDER BY ranking_snapshot_items.rank ASC
                """,
                (run_id,),
            ).fetchall()
        return {
            "run": row_to_ranking_run(run),
            "decisions": [dict(row) for row in decisions],
            "snapshot": [row_to_snapshot_item(row) for row in snapshot],
        }

    def get_rank_history(
        self,
        idea_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        limit = clamp_limit(limit)
        filters = ""
        params: list[Any] = []
        if idea_id is not None:
            filters = "WHERE ranking_snapshot_items.idea_id = ?"
            params.append(idea_id)
        params.append(limit)
        self.initialize()
        with closing(self.connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT
                    ranking_snapshot_items.*,
                    ranking_runs.name AS run_name,
                    ranking_runs.algorithm,
                    ranking_runs.published_at,
                    ideas.title
                FROM ranking_snapshot_items
                JOIN ranking_runs ON ranking_runs.id = ranking_snapshot_items.run_id
                JOIN ideas ON ideas.id = ranking_snapshot_items.idea_id
                {filters}
                ORDER BY ranking_runs.published_at DESC,
                         ranking_snapshot_items.rank ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [row_to_rank_history(row) for row in rows]

    def _validate_ranking_payload(
        self,
        connection: sqlite3.Connection,
        rankings: list[dict[str, Any]],
        field_name: str,
    ) -> None:
        if not isinstance(rankings, list):
            raise ValueError(f"{field_name} must be a list")
        for ranking in rankings:
            idea_id = require_text(ranking, "idea_id")
            ensure_idea_exists(connection, idea_id)

    def _validate_decision_payload(
        self,
        connection: sqlite3.Connection,
        decisions: list[dict[str, Any]],
    ) -> None:
        if not isinstance(decisions, list):
            raise ValueError("decisions must be a list")
        for decision in decisions:
            idea_a_id = require_text(decision, "idea_a_id")
            idea_b_id = require_text(decision, "idea_b_id")
            if idea_a_id == idea_b_id:
                raise ValueError("decision idea ids must be different")
            ensure_idea_exists(connection, idea_a_id)
            ensure_idea_exists(connection, idea_b_id)
            normalize_winner(str(decision.get("winner", "")))

    def _insert_published_ranking_run(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        name: str,
        filters_json: str,
        decisions: list[dict[str, Any]],
        rankings: list[dict[str, Any]],
        notes: str | None,
        algorithm: str,
        now: str,
    ) -> None:
        self._validate_ranking_payload(connection, rankings, "rankings")
        self._validate_decision_payload(connection, decisions)

        connection.execute(
            """
            INSERT INTO ranking_runs (
                id, name, filters_json, algorithm, status, notes,
                created_at, published_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                name,
                filters_json,
                algorithm.strip() or "session_elo",
                "published",
                notes,
                now,
                now,
            ),
        )

        for index, decision in enumerate(decisions, start=1):
            winner = normalize_winner(str(decision.get("winner", "")))
            connection.execute(
                """
                INSERT INTO ranking_decisions (
                    id, run_id, round_number, idea_a_id, idea_b_id,
                    winner, reason_code, reason_note, rating_a_before,
                    rating_b_before, rating_a_after, rating_b_after,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    run_id,
                    int(decision.get("round_number") or index),
                    require_text(decision, "idea_a_id"),
                    require_text(decision, "idea_b_id"),
                    winner,
                    str(decision.get("reason_code") or "unspecified"),
                    optional_text(decision.get("reason_note")),
                    float(decision.get("rating_a_before", DEFAULT_ELO_RATING)),
                    float(decision.get("rating_b_before", DEFAULT_ELO_RATING)),
                    float(decision.get("rating_a_after", DEFAULT_ELO_RATING)),
                    float(decision.get("rating_b_after", DEFAULT_ELO_RATING)),
                    str(decision.get("created_at") or now),
                ),
            )

        for index, ranking in enumerate(rankings, start=1):
            idea_id = require_text(ranking, "idea_id")
            rating = float(ranking.get("rating", DEFAULT_ELO_RATING))
            comparison_count = int(ranking.get("comparison_count", 0))
            wins = int(ranking.get("wins", 0))
            losses = int(ranking.get("losses", 0))
            ties = int(ranking.get("ties", 0))
            rank = int(ranking.get("rank") or index)
            connection.execute(
                """
                INSERT INTO ranking_snapshot_items (
                    id, run_id, idea_id, rank, rating, comparison_count,
                    wins, losses, ties, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    run_id,
                    idea_id,
                    rank,
                    rating,
                    comparison_count,
                    wins,
                    losses,
                    ties,
                    now,
                ),
            )
            self._rating_row(connection, idea_id)
            connection.execute(
                """
                UPDATE idea_ratings
                SET rating = ?,
                    comparison_count = ?,
                    wins = ?,
                    losses = ?,
                    ties = ?,
                    updated_at = ?
                WHERE idea_id = ?
                """,
                (
                    rating,
                    comparison_count,
                    wins,
                    losses,
                    ties,
                    now,
                    idea_id,
                ),
            )

    def _compared_pair_keys(self) -> set[tuple[str, str]]:
        self.initialize()
        with closing(self.connect()) as connection:
            rows = connection.execute(
                "SELECT idea_a_id, idea_b_id FROM idea_comparisons",
            ).fetchall()
        return {canonical_pair_key(row["idea_a_id"], row["idea_b_id"]) for row in rows}

    def _rating_row(
        self,
        connection: sqlite3.Connection,
        idea_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM idea_ratings WHERE idea_id = ?",
            (idea_id,),
        ).fetchone()
        if row is not None:
            return row
        now = utc_now()
        connection.execute(
            """
            INSERT INTO idea_ratings (
                idea_id, rating, comparison_count, wins, losses, ties, updated_at
            )
            VALUES (?, ?, 0, 0, 0, 0, ?)
            """,
            (idea_id, DEFAULT_ELO_RATING, now),
        )
        return connection.execute(
            "SELECT * FROM idea_ratings WHERE idea_id = ?",
            (idea_id,),
        ).fetchone()

    def _update_rating(
        self,
        connection: sqlite3.Connection,
        idea_id: str,
        rating: float,
        updated_at: str,
        counts: dict[str, int],
    ) -> None:
        connection.execute(
            """
            UPDATE idea_ratings
            SET rating = ?,
                comparison_count = comparison_count + 1,
                wins = wins + ?,
                losses = losses + ?,
                ties = ties + ?,
                updated_at = ?
            WHERE idea_id = ?
            """,
            (
                rating,
                counts["wins"],
                counts["losses"],
                counts["ties"],
                updated_at,
                idea_id,
            ),
        )


def clamp_limit(limit: int) -> int:
    if limit < 1:
        return 1
    if limit > 200:
        return 200
    return limit


def row_to_idea(row: sqlite3.Row) -> dict[str, Any]:
    idea = dict(row)
    idea["tags"] = json.loads(idea["tags"])
    if "external_item_metadata" in idea:
        idea["external_item_metadata"] = parse_optional_json_payload(
            idea["external_item_metadata"],
        )
    return idea


def row_to_priority(row: sqlite3.Row) -> dict[str, Any]:
    priority = dict(row)
    priority["rating"] = round(float(priority["rating"]), 2)
    priority["tags"] = json.loads(priority.pop("tags"))
    return priority


def row_to_ranking_run(row: sqlite3.Row) -> dict[str, Any]:
    run = dict(row)
    run["filters"] = json.loads(run.pop("filters_json"))
    if "snapshot_count" in run:
        run["snapshot_count"] = int(run["snapshot_count"])
    if "decision_count" in run:
        run["decision_count"] = int(run["decision_count"])
    return run


def row_to_ranking_draft(row: sqlite3.Row) -> dict[str, Any]:
    draft = dict(row)
    draft["filters"] = json.loads(draft.pop("filters_json"))
    draft["decisions"] = json.loads(draft.pop("decisions_json"))
    draft["before_rankings"] = json.loads(draft.pop("before_rankings_json"))
    draft["after_rankings"] = json.loads(draft.pop("after_rankings_json"))
    return draft


def split_ranking_draft(draft: dict[str, Any]) -> dict[str, Any]:
    decisions = draft.pop("decisions")
    before_rankings = draft.pop("before_rankings")
    after_rankings = draft.pop("after_rankings")
    return {
        "draft": draft,
        "decisions": decisions,
        "before_rankings": before_rankings,
        "after_rankings": after_rankings,
    }


def row_to_snapshot_item(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["rating"] = round(float(item["rating"]), 2)
    return item


def row_to_rank_history(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["rating"] = round(float(item["rating"]), 2)
    return item


def normalize_winner(winner: str) -> str:
    value = winner.casefold().strip()
    if value not in COMPARISON_WINNERS:
        allowed = ", ".join(sorted(COMPARISON_WINNERS))
        raise ValueError(f"winner must be one of: {allowed}")
    if value == "draw":
        return "tie"
    return value


def comparison_scores(winner: str) -> tuple[float, float]:
    if winner == "a":
        return 1.0, 0.0
    if winner == "b":
        return 0.0, 1.0
    return 0.5, 0.5


def elo_after(rating: float, opponent_rating: float, score: float) -> float:
    expected = 1.0 / (1.0 + 10.0 ** ((opponent_rating - rating) / 400.0))
    return rating + ELO_K_FACTOR * (score - expected)


def outcome_counts_for_a(winner: str) -> dict[str, int]:
    if winner == "a":
        return {"wins": 1, "losses": 0, "ties": 0}
    if winner == "b":
        return {"wins": 0, "losses": 1, "ties": 0}
    return {"wins": 0, "losses": 0, "ties": 1}


def outcome_counts_for_b(winner: str) -> dict[str, int]:
    if winner == "b":
        return {"wins": 1, "losses": 0, "ties": 0}
    if winner == "a":
        return {"wins": 0, "losses": 1, "ties": 0}
    return {"wins": 0, "losses": 0, "ties": 1}


def canonical_pair_key(idea_a_id: str, idea_b_id: str) -> tuple[str, str]:
    return tuple(sorted((idea_a_id, idea_b_id)))


def normalize_json_payload(value: dict[str, Any] | str) -> str:
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return "{}"
        json.loads(value)
        return value
    return json.dumps(value, sort_keys=True)


def normalize_optional_json_payload(value: dict[str, Any] | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        json.loads(value)
        return value
    return json.dumps(value, sort_keys=True)


def parse_optional_json_payload(value: Any) -> dict[str, Any] | list[Any] | str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def portfolio_feature_identity_key(title: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
    return key or "untitled-feature"


def require_text(record: dict[str, Any], field: str) -> str:
    value = str(record.get(field) or "").strip()
    if not value:
        raise ValueError(f"{field} is required")
    return value


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def ensure_idea_exists(connection: sqlite3.Connection, idea_id: str) -> None:
    row = connection.execute(
        "SELECT id FROM ideas WHERE id = ?",
        (idea_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"idea not found: {idea_id}")


def ensure_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_type: str,
) -> None:
    columns = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        connection.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}",
        )
