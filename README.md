# Concinnity MCP Server

Concinnity is an independent local stdio MCP server for capturing and prioritizing AI-era development ideas before they become active work. It is not a project management tool: it stores ideas, preferences, lane-scoped priority signals, and lightweight lifecycle metadata.

The package folder, Python package, default database, and `global-icebox` MCP Hub id remain unchanged for compatibility.

## Locations

Ideas cite files by a portable reference — `future_work/mcp-servers.md` — rather than an absolute
path, because the two machines disagree about where anything lives. Each machine keeps its own
mapping from a location name to a real directory:

```text
~/.concinnity/config.json          # override with CONCINNITY_CONFIG
```

Managed with `list_locations`, `set_location`, `remove_location` and `resolve_location`. The
config is intentionally outside the repo and outside the database: the repo is shared between
machines, and the database is per-machine and never synced, so neither is the right home for the
one thing that must differ per machine.

`resolve_location` refuses a reference that escapes its root via `..`, and accepts either
separator so a Windows-authored reference resolves here.

## Data Store

By default, data is stored at:

```text
data/icebox.db
```

Set `GLOBAL_ICEBOX_DB_PATH` to use another SQLite database path for tests or local overrides.

## Tools

- `add_idea`: Add an idea to Concinnity.
- `list_ideas`: List ideas with optional lane, lifecycle, project, target type, and tag filters.
- `search_ideas`: Search idea title, description, projects, tags, promotion notes, and external identity.
- `update_idea`: Update mutable idea fields.
- `promote_idea`: Mark an idea as promoted and return a promotion payload.
- `sync_portfolio_features`: Non-destructively upsert Portfolio `todo` and `done` features into Concinnity lanes.
- `add_idea_relationship`: Record lineage, duplicate review, or relatedness between two ideas.
- `list_idea_relationships`: List stored idea relationships by idea or relationship type.
- `get_comparison_pair`: Return two candidate ideas for head-to-head priority comparison, optionally filtered by target type, status, target project, or tag. The selector prefers ideas with fewer comparisons and avoids already-compared pairs when possible.
- `record_comparison`: Record a pairwise preference between two ideas with winner `a`, `b`, `tie`, or `draw`, plus optional rationale.
- `list_priorities`: List ideas ranked by Elo rating with comparison counts and win/loss/tie totals.
- `get_comparison_history`: Return recent durable comparison records, optionally scoped to one idea.
- `publish_ranking_run`: Persist a session-based H2H run with decisions, rationale notes, and final ranking snapshot, then update current idea ratings.
- `list_ranking_runs`: List published ranking sessions.
- `get_ranking_run`: Return one published session with decisions and snapshot rows.
- `get_rank_history`: Return historical rank/rating snapshot records for one idea or all ideas.

## Lanes

Concinnity uses `lane` as the ranking-board scope while keeping the older `status` field as lightweight lifecycle metadata:

- `project_ideas`: global future standalone project ideas.
- `backlog`: project-scoped feature candidates aligned with Portfolio `todo` features.
- `local_icebox`: project-scoped parked ideas not in an active backlog.
- `done`: completed items mirrored from Portfolio `done` features for context/history.

Existing rows migrate safely during initialization: `target_type = project` becomes `project_ideas`; other target types become `local_icebox` unless a lane was already set.

## Portfolio Sync

`sync_portfolio_features(project_key, project_name, repo_name=None, features=[...])` lets Portfolio/project code push feature lists into Concinnity without LLM interpretation. Portfolio `todo` becomes `backlog`; Portfolio `done` becomes `done`. Missing Portfolio features are not deleted from Concinnity.

Synced ideas store `external_source = portfolio`, `external_project_key = project_key`, and a stable title-derived `external_item_key` because Portfolio feature keys can be regenerated when the feature table is replaced. The incoming Portfolio `feature_key`, status, and repo name are kept in external item metadata.

## Priority Ratings

Head-to-head priority uses a simple Elo model with default rating `1000` and K-factor `32`. Ratings are a reproducible heuristic based on the stored comparison history, not objective truth. Every comparison is recorded with timestamp, outcome, optional rationale, and before/after ratings so the ranking can be audited.

Web sessions are first saved as durable staged ranking drafts with the session id, filters, notes, decisions, baseline rankings, and current rankings. Final reviewed publishing converts the staged draft into an immutable ranking run with decision rationale and final snapshot rows. Snapshot rows provide the rank/rating time series used for later analysis, even though the current UI does not visualize that history yet. Publishing a staged draft is idempotent by draft id, so repeated final publish requests return the existing published run.

Use a concrete ranking context for H2H work. The local web UI offers board types for `Global Projects`, `Project Backlog`, and `Local Icebox`. Global Projects loads `lane = project_ideas` and `target_type = project` without requiring a target project. Project Backlog and Local Icebox require a target project and scope comparisons to their lane. Mixed-context boards are allowed only when explicitly enabled and named so the resulting run remains auditable.

## Idea Relationships

Idea relationships preserve review context without auto-merging or deleting records. Supported relationship types are `duplicate_of`, `related_to`, `promoted_from`, `spin_off_from`, and `supersedes`.

Use `duplicate_of` for possible overlap that needs merge review. Use `promoted_from` or `spin_off_from` when an idea intentionally moves from a project feature into a standalone project or related follow-up. Promotion itself remains simple: `promote_idea` marks the idea promoted and returns a payload; callers should record lineage explicitly with `add_idea_relationship` when a promoted or spin-off idea has a source.

## Local H2H Web UI

Launch the standalone local web app from this server root:

```powershell
.\scripts\launch-ui.ps1
```

The script prints `http://127.0.0.1:8765` by default. Set `GLOBAL_ICEBOX_UI_PORT` to choose a different port. Set `GLOBAL_ICEBOX_UI_OPEN_BROWSER=1` if you want the script to open a browser.

The browser talks only to the local HTTP backend. That backend uses the same Concinnity store/tool surface as the stdio MCP server because browsers cannot call stdio MCP directly. The UI lets you filter candidate ideas, run as many head-to-head rounds as you want, record why each winning choice was made, preview live rankings, review leaderboard movement, and publish the final ranking snapshot back to the server.

By default, `Load / reset session` uses the selected board type to avoid apples-to-oranges comparisons. `Global Projects` loads standalone project ideas and does not require a target project. `Project Backlog` and `Local Icebox` require choosing `Target project` from the dropdown and scope candidates to that project and lane. The dropdown is loaded from `/api/projects`, filtered by the selected lane, and returns existing target projects with idea counts. To compare across contexts, check `Allow mixed-context board` and provide a board/run name. Published mixed-context runs include the context label in filters and notes.

Web sessions use fixed-slot winner-stays pairing. The left A card and right B card are stable UI slots: if B wins, B stays on the right as champion and the next challenger appears in A; if A wins, A stays on the left and the next challenger appears in B. Click the winning card first, then click a reason button to confirm and record the decision. `Other` requires a short note; all reasons can include an optional note. Once a champion has gone through the active challenger pool, that champion steps away from the active fight pool and a new champion run starts with the remaining ideas.

The left navigation panel separates loaded candidates into Project Ideas, Backlog by project, Local Icebox by project, and Done by project when done items are loaded. Nodes show candidate counts and change visual state when any idea in that node already has comparisons or was compared during the current session.

The session is staged through `/api/drafts` when ideas load, after each recorded decision, and again when entering review. `Review and publish` opens a review screen with old and new leaderboard columns plus SVG arrow connectors from each idea's old rank to its new rank. Final publishing is only available from that review screen through `/api/drafts/<draft-id>/publish`.

## Resource

- `icebox://recent`: Recent ideas as formatted JSON.

## Run

From this server root:

```powershell
.\scripts\start.ps1
```

The server uses stdio and is intended to be launched by an MCP client per connection.

## Test

From this server root:

```powershell
.\scripts\test.ps1
```

The test suite uses temporary SQLite databases and does not write to the default store.

## MCP Hub

`mcp-server.yaml` declares a command-per-client stdio lifecycle and an `mcp_initialize` health probe. All paths in the manifest are relative to this server root. The entrypoint sets `UV_CACHE_DIR` to `.uv-cache` so Hub-launched stdio probes use the server-local uv cache.
