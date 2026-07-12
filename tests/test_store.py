from __future__ import annotations

import json
import os
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from uuid import uuid4

from global_icebox.store import IceboxStore
from global_icebox.ui import INDEX_HTML, IceboxUiHandler

TEST_TEMP_ROOT = Path(__file__).resolve().parents[1] / ".test-tmp"


class IceboxStoreTests(unittest.TestCase):
    def test_add_and_list_ideas(self) -> None:
        with temp_store() as store:
            idea = store.add_idea(
                title="Offline-first notes app",
                description="A small notes app with local sync later.",
                target_type="project",
                tags=["local", "notes", "local"],
            )

            ideas = store.list_ideas(target_type="project", tag="local")

        self.assertEqual(len(ideas), 1)
        self.assertEqual(ideas[0]["id"], idea["id"])
        self.assertEqual(ideas[0]["tags"], ["local", "notes"])
        self.assertEqual(ideas[0]["lane"], "project_ideas")

    def test_lane_defaults_and_filters_keep_legacy_status(self) -> None:
        with temp_store() as store:
            project = store.add_idea(
                title="Standalone model lab",
                description="Future standalone project idea.",
                target_type="project",
            )
            feature = store.add_idea(
                title="Existing app workflow",
                description="Parked feature idea.",
                target_type="feature",
                target_project="mcp-hub",
            )
            backlog = store.add_idea(
                title="Portfolio todo candidate",
                description="Backlog feature idea.",
                target_type="feature",
                target_project="mcp-hub",
                lane="backlog",
            )

            project_ideas = store.list_ideas(lane="project_ideas")
            local_icebox = store.list_ideas(lane="local_icebox")
            backlog_priorities = store.list_priorities(lane="backlog")

        self.assertEqual([idea["id"] for idea in project_ideas], [project["id"]])
        self.assertEqual([idea["id"] for idea in local_icebox], [feature["id"]])
        self.assertEqual([idea["id"] for idea in backlog_priorities], [backlog["id"]])
        self.assertEqual(backlog_priorities[0]["lane"], "backlog")

    def test_search_ideas_matches_description_and_project(self) -> None:
        with temp_store() as store:
            store.add_idea(
                title="Editor helper",
                description="Move repeated review steps into a reusable panel.",
                origin_project="mcp-hub",
                target_type="feature",
                target_project="SpaghettiSpia",
                tags=["review"],
            )

            description_matches = store.search_ideas("reusable panel")
            project_matches = store.search_ideas("spaghettispia")

        self.assertEqual(len(description_matches), 1)
        self.assertEqual(len(project_matches), 1)

    def test_sync_portfolio_features_upserts_without_deleting_missing_features(self) -> None:
        with temp_store() as store:
            local = store.add_idea(
                title="Hand-entered idea",
                description="Should remain after portfolio sync.",
                target_type="feature",
                target_project="Portfolio App",
                lane="local_icebox",
            )

            first_sync = store.sync_portfolio_features(
                project_key="PRJ001",
                project_name="Portfolio App",
                repo_name="portfolio-app",
                features=[
                    {
                        "feature_key": "FEAT00001",
                        "name": "Show launch checklist",
                        "status": "todo",
                        "description": "Show the next launch task.",
                    },
                    {
                        "feature_key": "FEAT00002",
                        "name": "Publish live demo",
                        "status": "done",
                    },
                ],
            )
            second_sync = store.sync_portfolio_features(
                project_key="PRJ001",
                project_name="Portfolio App",
                repo_name="portfolio-app",
                features=[
                    {
                        "feature_key": "FEAT99999",
                        "name": "Show launch checklist",
                        "status": "done",
                        "description": "Show the next launch task.",
                    },
                ],
            )
            all_ideas = store.list_ideas(target_project="Portfolio App", limit=10)
            backlog = store.list_ideas(lane="backlog")
            done = store.list_ideas(lane="done")

        self.assertEqual(first_sync["created"], 2)
        self.assertEqual(first_sync["updated"], 0)
        self.assertEqual(second_sync["created"], 0)
        self.assertEqual(second_sync["updated"], 1)
        self.assertEqual(
            sorted(idea["title"] for idea in all_ideas),
            ["Hand-entered idea", "Publish live demo", "Show launch checklist"],
        )
        self.assertEqual([idea["title"] for idea in backlog], [])
        self.assertEqual(
            sorted(idea["title"] for idea in done),
            ["Publish live demo", "Show launch checklist"],
        )
        synced = next(
            idea for idea in done if idea["title"] == "Show launch checklist"
        )
        self.assertEqual(synced["external_source"], "portfolio")
        self.assertEqual(synced["external_project_key"], "PRJ001")
        self.assertEqual(synced["external_item_key"], "show-launch-checklist")
        self.assertEqual(
            synced["external_item_metadata"]["portfolio_feature_key"],
            "FEAT99999",
        )
        self.assertIn(local["id"], {idea["id"] for idea in all_ideas})

    def test_list_projects_returns_sorted_non_empty_icebox_targets(self) -> None:
        with temp_store() as store:
            store.add_idea(
                title="Hub feature",
                description="First hub-scoped feature.",
                target_type="feature",
                target_project="mcp-hub",
            )
            store.add_idea(
                title="Second hub feature",
                description="Second hub-scoped feature.",
                target_type="feature",
                target_project="mcp-hub",
            )
            store.add_idea(
                title="Icebox feature",
                description="Icebox-scoped feature.",
                target_type="feature",
                target_project="global-icebox",
            )
            store.add_idea(
                title="Blank target",
                description="Should not appear in project scopes.",
                target_type="feature",
                target_project=" ",
            )
            store.add_idea(
                title="Promoted target",
                description="Should not appear in active icebox scopes.",
                target_type="feature",
                target_project="archived-project",
                status="promoted",
            )

            projects = store.list_projects()

        self.assertEqual(
            projects,
            [
                {"target_project": "global-icebox", "idea_count": 1},
                {"target_project": "mcp-hub", "idea_count": 2},
            ],
        )

    def test_update_idea_changes_status_and_fields(self) -> None:
        with temp_store() as store:
            idea = store.add_idea(
                title="CLI audit helper",
                description="Audit common project setup issues.",
            )

            updated = store.update_idea(
                idea_id=idea["id"],
                status="reviewing",
                target_type="feature",
                target_project="mcp-hub",
                tags=["audit", "hub"],
            )

        self.assertEqual(updated["status"], "reviewing")
        self.assertEqual(updated["target_type"], "feature")
        self.assertEqual(updated["target_project"], "mcp-hub")
        self.assertEqual(updated["tags"], ["audit", "hub"])

    def test_promote_idea_marks_promoted_and_returns_payload(self) -> None:
        with temp_store() as store:
            idea = store.add_idea(
                title="Seed a project",
                description="Turn this into a standalone project later.",
                origin_project="codex",
                target_type="spin_off",
                target_project="seed-project",
            )

            payload = store.promote_idea(
                idea_id=idea["id"],
                promotion_notes="Ready for feature note drafting.",
            )

        self.assertEqual(payload["idea"]["status"], "promoted")
        self.assertEqual(payload["promotion"]["target_type"], "spin_off")
        self.assertEqual(
            payload["promotion"]["promotion_notes"],
            "Ready for feature note drafting.",
        )
        self.assertIsNotNone(payload["promotion"]["promoted_at"])

    def test_add_and_list_idea_relationships(self) -> None:
        with temp_store() as store:
            source = store.add_idea(
                title="Standalone dashboard",
                description="Promoted from a project-scoped dashboard feature.",
            )
            target = store.add_idea(
                title="Dashboard widget",
                description="Original project-scoped dashboard feature.",
            )

            relationship = store.add_idea_relationship(
                source_idea_id=source["id"],
                target_idea_id=target["id"],
                relationship_type="promoted_from",
                notes="Intentional promotion; do not dedupe away.",
            )
            source_relationships = store.list_idea_relationships(idea_id=source["id"])
            promoted = store.list_idea_relationships(
                relationship_type="promoted_from",
            )

        self.assertEqual(relationship["source_idea_id"], source["id"])
        self.assertEqual(relationship["target_idea_id"], target["id"])
        self.assertEqual(relationship["relationship_type"], "promoted_from")
        self.assertEqual(len(source_relationships), 1)
        self.assertEqual(promoted[0]["id"], relationship["id"])

    def test_invalid_relationship_type_is_rejected(self) -> None:
        with temp_store() as store:
            source = store.add_idea(title="Source", description="Source idea.")
            target = store.add_idea(title="Target", description="Target idea.")

            with self.assertRaisesRegex(ValueError, "relationship_type"):
                store.add_idea_relationship(
                    source_idea_id=source["id"],
                    target_idea_id=target["id"],
                    relationship_type="auto_merge",
                )

    def test_relationships_persist_in_sqlite_database(self) -> None:
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        path = TEST_TEMP_ROOT / f"{uuid4()}.db"
        try:
            first_store = IceboxStore(path)
            source = first_store.add_idea(title="Source", description="Source idea.")
            target = first_store.add_idea(title="Target", description="Target idea.")
            first_store.add_idea_relationship(
                source["id"],
                target["id"],
                "spin_off_from",
                notes="Purposeful lineage.",
            )

            second_store = IceboxStore(path)
            relationships = second_store.list_idea_relationships(idea_id=target["id"])
        finally:
            safe_unlink(path)

        self.assertEqual(len(relationships), 1)
        self.assertEqual(relationships[0]["relationship_type"], "spin_off_from")
        self.assertEqual(relationships[0]["notes"], "Purposeful lineage.")

    def test_lineage_relationship_does_not_merge_or_delete_ideas(self) -> None:
        with temp_store() as store:
            project_feature = store.add_idea(
                title="Project feature",
                description="Feature inside an existing project.",
                target_type="feature",
                target_project="mcp-hub",
            )
            standalone = store.add_idea(
                title="Standalone project",
                description="Intentional spin-off project.",
                target_type="project",
                target_project="standalone-project",
            )

            relationship = store.add_idea_relationship(
                source_idea_id=standalone["id"],
                target_idea_id=project_feature["id"],
                relationship_type="spin_off_from",
            )
            remaining_ids = {
                idea["id"]
                for idea in store.list_ideas(status="icebox", limit=20)
            }

        self.assertEqual(relationship["relationship_type"], "spin_off_from")
        self.assertIn(project_feature["id"], remaining_ids)
        self.assertIn(standalone["id"], remaining_ids)

    def test_persists_records_in_sqlite_database(self) -> None:
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        path = TEST_TEMP_ROOT / f"{uuid4()}.db"
        try:
            first_store = IceboxStore(path)
            idea = first_store.add_idea(
                title="Persistent idea",
                description="Keep this after reconnect.",
            )

            second_store = IceboxStore(path)
            persisted = second_store.get_idea(idea["id"])
        finally:
            safe_unlink(path)

        self.assertEqual(persisted["title"], "Persistent idea")

    def test_record_comparison_updates_elo_for_win(self) -> None:
        with temp_store() as store:
            winner = store.add_idea(
                title="Fast project switcher",
                description="Jump between active project contexts.",
            )
            loser = store.add_idea(
                title="Color theme picker",
                description="Pick a nicer local dashboard theme.",
            )

            result = store.record_comparison(
                idea_a_id=winner["id"],
                idea_b_id=loser["id"],
                winner="a",
                rationale="Context switching has higher leverage.",
            )

        self.assertEqual(result["winner"], "a")
        self.assertEqual(result["idea_a"]["rating"], 1016.0)
        self.assertEqual(result["idea_b"]["rating"], 984.0)
        self.assertEqual(result["idea_a"]["comparison_count"], 1)
        self.assertEqual(result["idea_a"]["wins"], 1)
        self.assertEqual(result["idea_b"]["losses"], 1)

    def test_record_comparison_accepts_tie_and_draw(self) -> None:
        with temp_store() as store:
            first = store.add_idea(
                title="Import checklist",
                description="Import reusable setup checklists.",
            )
            second = store.add_idea(
                title="Export checklist",
                description="Export reusable setup checklists.",
            )

            tie = store.record_comparison(
                idea_a_id=first["id"],
                idea_b_id=second["id"],
                winner="tie",
            )
            draw = store.record_comparison(
                idea_a_id=first["id"],
                idea_b_id=second["id"],
                winner="draw",
            )

        self.assertEqual(tie["idea_a"]["rating"], 1000.0)
        self.assertEqual(tie["idea_b"]["rating"], 1000.0)
        self.assertEqual(draw["winner"], "tie")
        self.assertEqual(draw["idea_a"]["ties"], 2)
        self.assertEqual(draw["idea_b"]["ties"], 2)

    def test_list_priorities_orders_by_rating(self) -> None:
        with temp_store() as store:
            best = store.add_idea(
                title="Best idea",
                description="Most useful option.",
            )
            middle = store.add_idea(
                title="Middle idea",
                description="Useful option.",
            )
            lowest = store.add_idea(
                title="Lowest idea",
                description="Less useful option.",
            )

            store.record_comparison(best["id"], middle["id"], "a")
            store.record_comparison(best["id"], lowest["id"], "a")
            store.record_comparison(middle["id"], lowest["id"], "a")
            priorities = store.list_priorities()

        self.assertEqual(
            [idea["id"] for idea in priorities],
            [best["id"], middle["id"], lowest["id"]],
        )
        self.assertEqual(
            set(priorities[0]),
            {
                "id",
                "title",
                "target_type",
                "target_project",
                "lane",
                "status",
                "external_source",
                "external_project_key",
                "external_item_key",
                "rating",
                "comparison_count",
                "wins",
                "losses",
                "ties",
                "updated_at",
                "tags",
            },
        )

    def test_comparison_history_persists(self) -> None:
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        path = TEST_TEMP_ROOT / f"{uuid4()}.db"
        try:
            first_store = IceboxStore(path)
            first = first_store.add_idea(
                title="Local RSS reader",
                description="Keep up with project feeds.",
            )
            second = first_store.add_idea(
                title="Local bookmark search",
                description="Search saved references.",
            )
            first_store.record_comparison(
                first["id"],
                second["id"],
                "b",
                rationale="Search is more immediately useful.",
            )

            second_store = IceboxStore(path)
            history = second_store.get_comparison_history(idea_id=second["id"])
        finally:
            safe_unlink(path)

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["idea_a_id"], first["id"])
        self.assertEqual(history[0]["idea_b_id"], second["id"])
        self.assertEqual(history[0]["winner"], "b")
        self.assertEqual(history[0]["rationale"], "Search is more immediately useful.")

    def test_get_comparison_pair_prefers_uncompared_low_count_candidates(self) -> None:
        with temp_store() as store:
            first = store.add_idea(
                title="First",
                description="First candidate.",
                target_type="feature",
                target_project="mcp-hub",
                tags=["priority"],
            )
            second = store.add_idea(
                title="Second",
                description="Second candidate.",
                target_type="feature",
                target_project="mcp-hub",
                tags=["priority"],
            )
            third = store.add_idea(
                title="Third",
                description="Third candidate.",
                target_type="feature",
                target_project="mcp-hub",
                tags=["priority"],
            )
            store.record_comparison(first["id"], second["id"], "a")

            pair = store.get_comparison_pair(
                target_type="feature",
                target_project="mcp-hub",
                tag="priority",
            )

        pair_ids = {pair["idea_a"]["id"], pair["idea_b"]["id"]}
        self.assertFalse(pair["already_compared"])
        self.assertIn(third["id"], pair_ids)
        self.assertNotEqual(pair_ids, {first["id"], second["id"]})

    def test_publish_ranking_run_stores_decisions_snapshot_and_updates_ratings(self) -> None:
        with temp_store() as store:
            first = store.add_idea(
                title="Billing audit",
                description="Review billing flow regressions.",
            )
            second = store.add_idea(
                title="Dashboard polish",
                description="Improve dashboard visual hierarchy.",
            )

            run = store.publish_ranking_run(
                name="Planning pass",
                filters={"status": "icebox"},
                decisions=[
                    {
                        "round_number": 1,
                        "idea_a_id": first["id"],
                        "idea_b_id": second["id"],
                        "winner": "a",
                        "reason_code": "higher_user_value",
                        "reason_note": "Billing has direct user impact.",
                        "rating_a_before": 1000,
                        "rating_b_before": 1000,
                        "rating_a_after": 1016,
                        "rating_b_after": 984,
                    }
                ],
                rankings=[
                    {
                        "idea_id": first["id"],
                        "rank": 1,
                        "rating": 1016,
                        "comparison_count": 1,
                        "wins": 1,
                        "losses": 0,
                        "ties": 0,
                    },
                    {
                        "idea_id": second["id"],
                        "rank": 2,
                        "rating": 984,
                        "comparison_count": 1,
                        "wins": 0,
                        "losses": 1,
                        "ties": 0,
                    },
                ],
                notes="First published web session.",
                algorithm="local_web_session_elo",
            )
            priority = store.get_priority(first["id"])
            loaded = store.get_ranking_run(run["run"]["id"])

        self.assertEqual(run["run"]["name"], "Planning pass")
        self.assertEqual(run["run"]["filters"], {"status": "icebox"})
        self.assertEqual(loaded["decisions"][0]["reason_code"], "higher_user_value")
        self.assertEqual(
            loaded["decisions"][0]["reason_note"],
            "Billing has direct user impact.",
        )
        self.assertEqual(loaded["snapshot"][0]["idea_id"], first["id"])
        self.assertEqual(priority["rating"], 1016.0)
        self.assertEqual(priority["comparison_count"], 1)

    def test_save_ranking_draft_upserts_and_reads_before_after_snapshots(self) -> None:
        with temp_store() as store:
            first = store.add_idea(title="First draft idea", description="First option.")
            second = store.add_idea(title="Second draft idea", description="Second option.")

            draft = store.save_ranking_draft(
                draft_id="browser-session-1",
                client_session_id="browser-session-1",
                name="Draft planning pass",
                filters={"target_project": "draft-project"},
                decisions=[],
                before_rankings=[
                    {"idea_id": first["id"], "rank": 1, "rating": 1000},
                    {"idea_id": second["id"], "rank": 2, "rating": 1000},
                ],
                after_rankings=[
                    {"idea_id": first["id"], "rank": 1, "rating": 1000},
                    {"idea_id": second["id"], "rank": 2, "rating": 1000},
                ],
                notes="Saved at session load.",
                algorithm="local_web_session_elo",
            )
            updated = store.save_ranking_draft(
                draft_id=draft["draft"]["id"],
                client_session_id="browser-session-1",
                name="Draft planning pass",
                filters={"target_project": "draft-project"},
                decisions=[
                    {
                        "round_number": 1,
                        "idea_a_id": first["id"],
                        "idea_b_id": second["id"],
                        "winner": "b",
                        "reason_code": "more_urgent",
                        "rating_a_before": 1000,
                        "rating_b_before": 1000,
                        "rating_a_after": 984,
                        "rating_b_after": 1016,
                    }
                ],
                before_rankings=[
                    {"idea_id": first["id"], "rank": 1, "rating": 1000},
                    {"idea_id": second["id"], "rank": 2, "rating": 1000},
                ],
                after_rankings=[
                    {"idea_id": second["id"], "rank": 1, "rating": 1016},
                    {"idea_id": first["id"], "rank": 2, "rating": 984},
                ],
                notes="Saved after one decision.",
                algorithm="local_web_session_elo",
            )
            loaded = store.get_ranking_draft("browser-session-1")

        self.assertEqual(draft["draft"]["status"], "staged")
        self.assertEqual(updated["draft"]["id"], "browser-session-1")
        self.assertEqual(loaded["draft"]["filters"], {"target_project": "draft-project"})
        self.assertEqual(loaded["decisions"][0]["winner"], "b")
        self.assertEqual(
            [item["idea_id"] for item in loaded["before_rankings"]],
            [first["id"], second["id"]],
        )
        self.assertEqual(
            [item["idea_id"] for item in loaded["after_rankings"]],
            [second["id"], first["id"]],
        )

    def test_publish_ranking_draft_is_idempotent_and_updates_current_ratings(self) -> None:
        with temp_store() as store:
            first = store.add_idea(title="Draft publish first", description="First option.")
            second = store.add_idea(title="Draft publish second", description="Second option.")
            store.save_ranking_draft(
                draft_id="publish-draft",
                client_session_id="publish-draft",
                name="Reviewed planning pass",
                filters={"target_project": "draft-project"},
                decisions=[
                    {
                        "round_number": 1,
                        "idea_a_id": first["id"],
                        "idea_b_id": second["id"],
                        "winner": "a",
                        "reason_code": "higher_user_value",
                        "rating_a_before": 1000,
                        "rating_b_before": 1000,
                        "rating_a_after": 1016,
                        "rating_b_after": 984,
                    }
                ],
                before_rankings=[
                    {"idea_id": first["id"], "rank": 1, "rating": 1000},
                    {"idea_id": second["id"], "rank": 2, "rating": 1000},
                ],
                after_rankings=[
                    {
                        "idea_id": first["id"],
                        "rank": 1,
                        "rating": 1016,
                        "comparison_count": 1,
                        "wins": 1,
                        "losses": 0,
                    },
                    {
                        "idea_id": second["id"],
                        "rank": 2,
                        "rating": 984,
                        "comparison_count": 1,
                        "wins": 0,
                        "losses": 1,
                    },
                ],
            )

            first_publish = store.publish_ranking_draft("publish-draft")
            second_publish = store.publish_ranking_draft("publish-draft")
            draft = store.get_ranking_draft("publish-draft")
            runs = store.list_ranking_runs()
            priority = store.get_priority(first["id"])

        self.assertEqual(
            first_publish["published"]["run"]["id"],
            second_publish["published"]["run"]["id"],
        )
        self.assertEqual(len(runs), 1)
        self.assertEqual(draft["draft"]["status"], "published")
        self.assertEqual(
            draft["draft"]["published_run_id"],
            first_publish["published"]["run"]["id"],
        )
        self.assertEqual(priority["rating"], 1016.0)
        self.assertEqual(priority["wins"], 1)

    def test_rank_history_keeps_multiple_published_snapshots(self) -> None:
        with temp_store() as store:
            first = store.add_idea(title="First", description="First option.")
            second = store.add_idea(title="Second", description="Second option.")
            store.publish_ranking_run(
                name="Run one",
                filters={},
                decisions=[],
                rankings=[
                    {"idea_id": first["id"], "rank": 1, "rating": 1030},
                    {"idea_id": second["id"], "rank": 2, "rating": 970},
                ],
            )
            store.publish_ranking_run(
                name="Run two",
                filters={},
                decisions=[],
                rankings=[
                    {"idea_id": second["id"], "rank": 1, "rating": 1040},
                    {"idea_id": first["id"], "rank": 2, "rating": 960},
                ],
            )

            first_history = store.get_rank_history(idea_id=first["id"])
            all_history = store.get_rank_history()
            runs = store.list_ranking_runs()

        self.assertEqual([item["rank"] for item in first_history], [2, 1])
        self.assertEqual(len(all_history), 4)
        self.assertEqual(runs[0]["snapshot_count"], 2)
        self.assertEqual(runs[0]["decision_count"], 0)

    def test_local_ui_api_lists_candidates_and_publishes_reviewed_draft(self) -> None:
        with temp_store() as store:
            first = store.add_idea(
                title="API first",
                description="First API candidate.",
                target_type="feature",
                target_project="api-project",
            )
            second = store.add_idea(
                title="API second",
                description="Second API candidate.",
                target_type="feature",
                target_project="api-project",
            )

            with temp_http_server() as base_url:
                with urlopen(f"{base_url}/api/projects") as response:
                    projects = json.loads(response.read())
                with urlopen(f"{base_url}/api/ideas?target_type=feature") as response:
                    ideas = json.loads(response.read())

                payload = {
                    "name": "API smoke",
                    "filters": {"target_type": "feature"},
                    "decisions": [
                        {
                            "round_number": 1,
                            "idea_a_id": first["id"],
                            "idea_b_id": second["id"],
                            "winner": "a",
                            "reason_code": "better_strategic_fit",
                            "reason_note": "First fits the current direction.",
                            "rating_a_before": 1000,
                            "rating_b_before": 1000,
                            "rating_a_after": 1016,
                            "rating_b_after": 984,
                        }
                    ],
                    "rankings": [
                        {
                            "idea_id": first["id"],
                            "rank": 1,
                            "rating": 1016,
                            "comparison_count": 1,
                            "wins": 1,
                            "losses": 0,
                        },
                        {
                            "idea_id": second["id"],
                            "rank": 2,
                            "rating": 984,
                            "comparison_count": 1,
                            "wins": 0,
                            "losses": 1,
                        },
                    ],
                    "before_rankings": [
                        {"idea_id": first["id"], "rank": 1, "rating": 1000},
                        {"idea_id": second["id"], "rank": 2, "rating": 1000},
                    ],
                }
                request = Request(
                    f"{base_url}/api/drafts",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request) as response:
                    draft = json.loads(response.read())
                publish_request = Request(
                    f"{base_url}/api/drafts/{draft['draft']['id']}/publish",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(publish_request) as response:
                    published = json.loads(response.read())
                with urlopen(publish_request) as response:
                    republished = json.loads(response.read())

        self.assertEqual(
            projects,
            [{"target_project": "api-project", "idea_count": 2}],
        )
        self.assertEqual(len(ideas), 2)
        self.assertEqual(draft["draft"]["status"], "staged")
        self.assertEqual(published["published"]["run"]["name"], "API smoke")
        self.assertEqual(
            published["published"]["decisions"][0]["reason_code"],
            "better_strategic_fit",
        )
        self.assertEqual(
            published["published"]["run"]["id"],
            republished["published"]["run"]["id"],
        )

    def test_local_ui_contains_context_guard_copy(self) -> None:
        self.assertIn("Concinnity H2H", INDEX_HTML)
        self.assertIn("Board type", INDEX_HTML)
        self.assertIn("Global Projects", INDEX_HTML)
        self.assertIn("Project Backlog", INDEX_HTML)
        self.assertIn("Local Icebox", INDEX_HTML)
        self.assertIn("Allow mixed-context board", INDEX_HTML)
        self.assertIn("requires a target project", INDEX_HTML)
        self.assertIn('<select id="targetProject"', INDEX_HTML)
        self.assertIn("/api/projects", INDEX_HTML)
        self.assertIn("No ${board.label.toLowerCase()} projects", INDEX_HTML)
        self.assertIn("target_project", INDEX_HTML)
        self.assertIn("lane", INDEX_HTML)
        self.assertIn('id="navigationTree"', INDEX_HTML)
        self.assertIn("Project Ideas", INDEX_HTML)
        self.assertIn("Backlog by project", INDEX_HTML)
        self.assertIn("Local Icebox by project", INDEX_HTML)
        self.assertIn("Done by project", INDEX_HTML)
        self.assertIn("selectedWinnerSlot", INDEX_HTML)
        self.assertIn("let slotAIndex", INDEX_HTML)
        self.assertIn("let slotBIndex", INDEX_HTML)
        self.assertIn('class="idea-card slot-a"', INDEX_HTML)
        self.assertIn('class="idea-card slot-b"', INDEX_HTML)
        self.assertIn("--slot-a-line", INDEX_HTML)
        self.assertIn("--slot-b-line", INDEX_HTML)
        self.assertIn(".idea-card.slot-a", INDEX_HTML)
        self.assertIn(".idea-card.slot-b", INDEX_HTML)
        self.assertIn("championSlot = winnerSlot", INDEX_HTML)
        self.assertIn("setSlotIndex(loserSlot", INDEX_HTML)
        self.assertIn("Choose a winning card", INDEX_HTML)
        self.assertIn("confirmDecision", INDEX_HTML)
        self.assertIn('tabindex="0"', INDEX_HTML)
        self.assertIn("Review and publish", INDEX_HTML)
        self.assertIn("Old leaderboard", INDEX_HTML)
        self.assertIn("New leaderboard", INDEX_HTML)
        self.assertIn('id="reviewArrows"', INDEX_HTML)
        self.assertIn("<svg", INDEX_HTML)
        self.assertIn("marker-end", INDEX_HTML)
        self.assertIn("Publish reviewed ranking", INDEX_HTML)
        self.assertIn("/api/drafts", INDEX_HTML)
        self.assertIn("publishReviewedDraft", INDEX_HTML)
        self.assertNotIn('<span class="role">${role}</span>', INDEX_HTML)
        self.assertNotIn(".role {", INDEX_HTML)
        self.assertNotIn('id="aWins"', INDEX_HTML)
        self.assertNotIn('id="bWins"', INDEX_HTML)
        self.assertNotIn('id="tie"', INDEX_HTML)
        self.assertNotIn('id="skip"', INDEX_HTML)
        self.assertNotIn("Publish final ranking", INDEX_HTML)
        self.assertNotIn("A wins", INDEX_HTML)
        self.assertNotIn("B wins", INDEX_HTML)
        self.assertNotIn("Tie / equal", INDEX_HTML)
        self.assertNotIn(">Skip<", INDEX_HTML)
        self.assertNotIn("championIndex = previousChallenger", INDEX_HTML)


class temp_store:
    def __enter__(self) -> IceboxStore:
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.old_path = os.environ.get("GLOBAL_ICEBOX_DB_PATH")
        self.path = TEST_TEMP_ROOT / f"{uuid4()}.db"
        os.environ["GLOBAL_ICEBOX_DB_PATH"] = str(self.path)
        return IceboxStore()

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.old_path is None:
            os.environ.pop("GLOBAL_ICEBOX_DB_PATH", None)
        else:
            os.environ["GLOBAL_ICEBOX_DB_PATH"] = self.old_path
        safe_unlink(self.path)


def safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        pass


class temp_http_server:
    def __enter__(self) -> str:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), IceboxUiHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __exit__(self, exc_type, exc, tb) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


if __name__ == "__main__":
    unittest.main()
