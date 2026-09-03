# Concinnity MCP Server

Concinnity is an independent local stdio MCP server for capturing and prioritizing AI-era development ideas before they become active work. It is not a project management tool: it stores ideas, preferences, lane-scoped priority signals, and lightweight lifecycle metadata.

The package folder, Python package, default database, and `global-icebox` MCP Hub id remain unchanged for compatibility.

## CLI

Every internal tool ships a command line, not only an MCP server (standing requirement, owner
2026-09-02): an MCP server is only reachable from a client that has it registered, which over
SSH or from a script does not exist.

```
concinnity task list                            # or: uv run python -m global_icebox.cli ...
concinnity task add "Title" "Description" --repo pellucid --key SYNC-020
concinnity task claim <id> --by agent-a
concinnity task code-complete <id> --ci-run gha:12345
concinnity task accept <id> --owner animesh
concinnity rank pair --lane tasks
concinnity location list
```

`task`, `idea`, `rank`, `location` and `backup` cover the whole tool surface — **all 29 MCP
tools have a CLI path, and a test asserts it**, so the CLI cannot quietly fall behind the server
again. `--help` on any subcommand lists it. Human-readable
output by default, `--json` on any command for machines, non-zero exit and a plain message on a
refused transition. The CLI is a front door onto the same `IceboxStore` and `TaskStore` the MCP
tools call — never a second implementation.

## Tasks lane

Tasks are rows in `ideas` with `lane = "tasks"`, not a separate table. That is what lets the
existing H2H board, ranking runs and rating history rank tasks with **no changes at all**.

```
open ──► claimed ──► in_progress ──► code_complete ──► accepted
             │              │
             │              └──► reiterate ──► new task (supersedes)
             └──► released (lease expired / agent gave up)
```

Two owner rules are enforced, not merely documented:

- **`code_complete` requires a CI run reference** and is reachable only through
  `mark_code_complete`. `accept` and `reiterate` both demand `code_complete` first, so nothing
  can skip the gate.
- **`accept` and `reiterate` are owner-only** and refuse to run without an explicit owner. An
  agent cannot accept its own work.

`blocked` is **not** a status: it is derived from `depends_on` on read, so it can never disagree
with the dependencies that define it. Only `accepted` clears a dependency — code complete is not
accepted. Claiming a blocked task is refused.

A claim carries a **lease**. An expired lease makes a task reclaimable, so an agent that dies
does not strand its work; a live one refuses a second claimant. `claimed_by` is kept after
acceptance to record who did the work, but stops reading as a live claim.

`start_task` is not in the plan's tool list. The status diagram has `claimed → in_progress` and
nothing else could perform it, so the model would be unreachable without it.

**Still open (work-plane Q1):** how a CI gate actually reaches Concinnity. Today
`mark_code_complete` is invoked after a gate is observed, carrying its run id — candidate (a) in
the plan, the one that leaves an agent in the loop. The plan calls this the genuinely undecided
piece the whole model rests on.

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

## Backup

Backup, **not** sync — the database is per-machine and is never merged between machines.

```
uv run python scripts/backup.py [--commit --push]
uv run python scripts/restore.py <dump> --db <target>
```

`backup.py` writes a replayable SQL dump to `<backup-root>/<host>/icebox.sql` plus a `meta.json`
of row counts. Destination is `$CONCINNITY_BACKUP_DIR`, else the `backup` location, else
`docs/concinnity-backup` — so it uses the same locations config as everything else.

**Per-host directories** mean two machines never write the same file, so the backup cannot
quietly turn into a sync. Text rather than a copied `.db` because it diffs and compresses, and
because copying a live SQLite file (or a `-wal`/`-shm` pair out of step with it) yields a corrupt
or stale database — `iterdump` reads through a read-only connection instead. Python's `sqlite3`
rather than the CLI, which is not reliably present on Windows.

`restore.py` refuses to overwrite an existing database without `--force`: restoring the *other*
machine's dump over this one's board would destroy rankings that exist nowhere else.

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
