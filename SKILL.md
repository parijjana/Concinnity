# Skill: Icebox Curator

You maintain Concinnity — the register of work that has been *decided or imagined but not
started*, and the head-to-head board that puts it in order.

Concinnity is **not a project management tool**. Owner framing, 2026-08-28: "because we are not
working on projects". It records what the work is, where to find it, and the order the owner has
ranked it in. It does not manage the work, and it does not decide that something is done.

## Bootstrap: locations, before anything else

The database is per-machine and never synced. What makes an entry legible on the *other* machine
is the location config, so check it at the start of any session that will read or write file
references:

1. Call `list_locations`. If `locations` is empty, this machine has not been set up.
2. Ask the owner where the relevant roots are, or infer them and confirm — do not guess silently.
3. Record each with `set_location`, then verify with `resolve_location`.

Conventional names, so the two machines share one vocabulary:

| Name | What it points at |
|---|---|
| `projects` | the root holding all the project repos |
| `docs` | the private `project_docs` repo |
| `future_work` | `project_docs/future-work` — the cross-cutting plans |
| `progress_log` | `project_docs/progress-log` — the root timeline |

**Cite files portably.** In an idea's description write `future_work/mcp-servers.md`, never
`/Users/…` or `C:\…`. A raw path is wrong the moment it is read on the other machine. Call
`resolve_location` to turn a reference into a real path before opening it.

The config lives at `~/.concinnity/config.json` (override with `CONCINNITY_CONFIG`). It is
deliberately outside the repo: the repo is shared between machines, so a committed config would
be correct on one and wrong on the other — the same mistake as `start.ps1` pinning `UV_PYTHON`
to a Windows filename.

## Workflows

### Capturing
Use `add_idea` when something is decided-but-not-started or merely imagined. Put it in the lane
that matches its scope: `project_ideas` for cross-cutting or standalone work, `backlog` for a
project's feature candidates, `local_icebox` for parked project-scoped ideas. **One idea per
distinct decision** — granularity is what makes the board rankable. A single plan document
usually contains several; three documents make a useless board.

Prefer `search_ideas` before adding, and record `add_idea_relationship` when the new item is
lineage of, a duplicate of, or related to an existing one.

### Ranking
`get_comparison_pair` offers two candidates, preferring ideas with fewer comparisons and avoiding
pairs already seen. `record_comparison` stores the preference with a rationale. For a deliberate
session, use `publish_ranking_run` so the decisions, rationales and final snapshot are durable
rather than implied by the ratings. `list_priorities` reads the board.

**Ratings are derived, not authored.** Elo is order-dependent, so ratings are a reproducible
function of the stored comparison history. Never hand-set a rating; record a comparison instead.

### Lifecycle
`promote_idea` marks an idea as having left the icebox and returns a promotion payload. That is
the boundary of this server's authority: it registers and ranks, and it does not close work.
Per the work-plane, `done` arrives from a CI gate, not from an agent's say-so.

## Cautions

- **The database is local and unsynced by design, and is currently unbacked.** Do not assume a
  ranking recorded here exists on the other machine.
- **Never delete an idea to tidy the board.** Use `status` (`rejected`, `archived`) so the
  history survives — the estate rule is that data must still be there to be resynthesized.
- `sync_portfolio_features` upserts non-destructively. Keep it that way; the equivalent
  destructive import in Lore's harvest once took 25 entries to 1.
