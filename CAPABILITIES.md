# Concinnity Capabilities

## Purpose

Stores durable local ideas and preference signals before they become active project work, including standalone project ideas, feature candidates for existing projects, project-scoped parked ideas, and completed Portfolio feature context.

Concinnity is not a project management tool. It does not model plans, sprints, dependencies, or assignees; it scopes ideas into lanes and records priority preferences.

## When To Use

- Capture a rough project idea without creating a full project.
- Save a feature idea for an existing project.
- Record an idea from one project that likely belongs to another project.
- Review, search, update, or promote saved ideas later.

## When Not To Use

- Do not store secrets, credentials, tokens, or sensitive personal data.
- Do not use it as the source of truth for active project requirements.
- Do not store large binary files or long generated logs.
- Do not expect promotion to write into project folders yet.

## Main Capabilities

- Add ideas with title, description, origin project, target type, target project, lane, status, and tags.
- List ideas by lane, status, target type, origin project, target project, or tag.
- Search idea text, projects, tags, promotion notes, and external identity.
- Update idea metadata and status.
- Non-destructively sync Portfolio features into Concinnity: `todo` features enter `backlog`, and `done` features enter `done`.
- Promote an idea by marking it promoted and returning a promotion payload.
- Record idea relationships for duplicate review, related ideas, promotions, spin-offs, and supersession.
- List relationship/lineage records by idea or relationship type.
- Compare two ideas head-to-head and update local Elo priority ratings.
- Request a comparison pair, preferring under-compared ideas and avoiding repeated pairs when possible.
- List priority rankings with rating, comparison count, wins, losses, ties, and rating update timestamp.
- Review durable comparison history with timestamps, outcomes, rationale, and before/after ratings.
- Launch a standalone local H2H web app for longer fixed-slot winner-stays ranking sessions.
- Populate the H2H target-project selector from distinct existing Concinnity target projects in the selected lane.
- Review a compact navigation tree that separates Project Ideas, Backlog by project, Local Icebox by project, and Done by project when loaded.
- Save H2H web sessions as staged ranking drafts with filters, notes, decisions, baseline rankings, and current rankings.
- Review old-versus-new leaderboard movement with SVG arrow connectors before final publishing.
- Publish reviewed staged drafts with final snapshots so rank and preference changes can be tracked over time.
- Store per-round rationale with reason codes and optional notes for later planning and LLM context.
- Read recent ideas through `icebox://recent`.

## Data Scope

Data is stored locally in this server folder at `data/icebox.db` by default. The `GLOBAL_ICEBOX_DB_PATH` environment variable can point the server at another SQLite database.

## Safety Notes

Promotion is intentionally simple in this version: it updates the icebox record and returns structured data for the caller. It does not write into arbitrary project repositories or feature folders.

Promotion and spin-off lineage should be explicit. Use `add_idea_relationship` with `promoted_from` or `spin_off_from` when a new idea intentionally descends from another idea. Possible overlap can be marked with `duplicate_of`, but the server does not auto-merge or auto-delete anything.

Elo priority is a planning heuristic, not an objective measure of value. Rankings are reproducible from the recorded comparison history and should be treated as an auditable signal for review.

The local web UI is served by a local backend because browser JavaScript cannot speak stdio MCP directly. The backend uses the same server-local Concinnity operations exposed as MCP tools and writes to the same SQLite store. Its pairing flow is fixed-slot winner-stays: A stays on the left and B stays on the right. If B wins, B remains on the right as champion and the next challenger appears in A; if A wins, A remains on the left and the next challenger appears in B. The user clicks the winning card, then clicks a reason button to confirm the decision. `Other` requires a note.

H2H sessions are staged before publish. The UI saves the draft when ideas load, after each decision, and before opening review. `Review and publish` shows old and new leaderboard columns with arrows for rank movement; final publish is only available from that review screen. Publishing by draft id is idempotent, so a repeated final publish request returns the existing published ranking run instead of creating a duplicate.

The H2H web UI requires a ranking context by default. Users choose a board type: `Global Projects` loads `project_ideas`/`project` ideas without a target project, while `Project Backlog` and `Local Icebox` require a `Target project` from a lane-filtered dropdown. Cross-project or mixed-context boards require the explicit `Allow mixed-context board` opt-in plus a board/run name so published runs can be audited later.

## Typical Workflow

1. Add a rough idea with enough context to understand its origin and likely destination.
2. List or search ideas during planning or review.
3. Compare candidate ideas head-to-head when priority is unclear.
4. For longer ranking passes, run `.\scripts\launch-ui.ps1`, choose a board type and target project where required, work through the fixed-slot winner-stays champion queue by clicking a winning card and confirming with a reason, and publish the session.
5. List priorities or ranking runs to review the current Elo-ranked order and published snapshots.
6. Update status, tags, target project, or notes as the idea becomes clearer.
7. Promote the idea when it is ready for project planning or implementation.
