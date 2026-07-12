from __future__ import annotations

import argparse
import json
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .store import IceboxStore

REASON_OPTIONS = [
    "higher_user_value",
    "more_urgent",
    "lower_effort",
    "unblocks_other_work",
    "better_strategic_fit",
    "more_exciting",
    "other",
]


def candidate_ideas(params: dict[str, list[str]]) -> list[dict[str, Any]]:
    filters = {
        "status": first(params, "status"),
        "target_type": first(params, "target_type"),
        "origin_project": first(params, "origin_project"),
        "target_project": first(params, "target_project"),
        "lane": first(params, "lane"),
        "tag": first(params, "tag"),
        "limit": int(first(params, "limit") or 100),
    }
    store = IceboxStore()
    ideas = store.list_ideas(**filters)
    priorities = {
        item["id"]: item
        for item in store.list_priorities(
            status=filters["status"],
            target_type=filters["target_type"],
            target_project=filters["target_project"],
            lane=filters["lane"],
            tag=filters["tag"],
            limit=200,
        )
    }
    result: list[dict[str, Any]] = []
    for idea in ideas:
        priority = priorities.get(idea["id"], {})
        result.append(
            {
                **idea,
                "rating": priority.get("rating", 1000.0),
                "comparison_count": priority.get("comparison_count", 0),
                "wins": priority.get("wins", 0),
                "losses": priority.get("losses", 0),
                "ties": priority.get("ties", 0),
            }
        )
    return result


def publish_run(payload: dict[str, Any]) -> dict[str, Any]:
    return IceboxStore().publish_ranking_run(
        name=str(payload.get("name") or "H2H ranking run"),
        filters=payload.get("filters") or {},
        decisions=list(payload.get("decisions") or []),
        rankings=list(payload.get("rankings") or []),
        notes=payload.get("notes"),
        algorithm=str(payload.get("algorithm") or "session_elo"),
    )


def save_draft(payload: dict[str, Any]) -> dict[str, Any]:
    rankings = list(payload.get("rankings") or payload.get("after_rankings") or [])
    return IceboxStore().save_ranking_draft(
        draft_id=payload.get("draft_id") or payload.get("id"),
        client_session_id=payload.get("client_session_id") or payload.get("draft_id"),
        name=str(payload.get("name") or "H2H ranking run"),
        filters=payload.get("filters") or {},
        decisions=list(payload.get("decisions") or []),
        before_rankings=list(
            payload.get("before_rankings")
            or payload.get("baseline_rankings")
            or rankings
        ),
        after_rankings=rankings,
        notes=payload.get("notes"),
        algorithm=str(payload.get("algorithm") or "session_elo"),
    )


def project_options(params: dict[str, list[str]] | None = None) -> list[dict[str, Any]]:
    params = params or {}
    status = first(params, "status")
    if "status" not in params:
        status = None
    return IceboxStore().list_projects(
        status=status,
        lane=first(params, "lane"),
    )


def first(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    if not values:
        return None
    value = values[0].strip()
    return value or None


class IceboxUiHandler(BaseHTTPRequestHandler):
    server_version = "ConcinnityUi/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.write_text(INDEX_HTML, "text/html; charset=utf-8")
            return
        if parsed.path == "/api/ideas":
            self.write_json(candidate_ideas(parse_qs(parsed.query)))
            return
        if parsed.path == "/api/projects":
            self.write_json(project_options(parse_qs(parsed.query)))
            return
        if parsed.path == "/api/runs":
            limit = int(first(parse_qs(parsed.query), "limit") or 20)
            self.write_json(IceboxStore().list_ranking_runs(limit=limit))
            return
        parts = parsed.path.strip("/").split("/")
        if len(parts) == 3 and parts[:2] == ["api", "drafts"]:
            self.write_json(IceboxStore().get_ranking_draft(parts[2]))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            parts = parsed.path.strip("/").split("/")
            if parsed.path == "/api/publish":
                self.write_json(publish_run(payload))
                return
            if parsed.path == "/api/drafts":
                self.write_json(save_draft(payload))
                return
            if len(parts) == 4 and parts[:2] == ["api", "drafts"] and parts[3] == "publish":
                self.write_json(IceboxStore().publish_ranking_draft(parts[2]))
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:  # pragma: no cover - exact HTTP path covered in tests.
            self.write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def write_json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def write_text(self, value: str, content_type: str) -> None:
        body = value.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> None:
    server = ThreadingHTTPServer((host, port), IceboxUiHandler)
    url = f"http://{host}:{server.server_address[1]}"
    print(f"Concinnity H2H UI: {url}", flush=True)
    if open_browser:
        webbrowser.open(url)
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch Concinnity H2H UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args()
    run(host=args.host, port=args.port, open_browser=args.open_browser)


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Concinnity H2H</title>
<style>
:root {
  color-scheme: light;
  --bg: #f7f8f5;
  --panel: #ffffff;
  --ink: #18201c;
  --muted: #637067;
  --line: #cfd8d1;
  --accent: #0f7c80;
  --accent-dark: #095c5f;
  --warn: #9a5b00;
  --selected: #b8452f;
  --ranked: #245c9f;
  --session: #6f5b00;
  --slot-a-line: #a9cceb;
  --slot-a-glow: rgba(36, 92, 159, 0.13);
  --slot-b-line: #ecb5ad;
  --slot-b-glow: rgba(184, 69, 47, 0.12);
  --shadow: 0 1px 2px rgba(20, 30, 25, 0.08);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
header, main { max-width: 1180px; margin: 0 auto; padding: 16px; }
header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
h1 { font-size: 24px; margin: 0; letter-spacing: 0; }
h2 { font-size: 17px; margin: 0 0 10px; }
button, input, select, textarea {
  font: inherit;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
  color: var(--ink);
}
button { cursor: pointer; padding: 9px 11px; font-weight: 650; }
button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
button.primary:hover { background: var(--accent-dark); }
button.ghost { background: transparent; }
button:disabled { cursor: not-allowed; opacity: 0.55; }
input, select, textarea { width: 100%; padding: 8px 9px; }
textarea { min-height: 72px; resize: vertical; }
.filters {
  display: grid;
  grid-template-columns: repeat(8, minmax(120px, 1fr));
  gap: 10px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px;
  box-shadow: var(--shadow);
}
label { display: grid; gap: 4px; color: var(--muted); font-size: 12px; font-weight: 650; }
.checkbox-label { display: flex; align-items: center; gap: 8px; color: var(--ink); }
.checkbox-label input { width: auto; }
.workspace { display: grid; grid-template-columns: 230px minmax(0, 2fr) minmax(300px, 1fr); gap: 14px; margin-top: 14px; align-items: start; }
.panel, .idea-card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  box-shadow: var(--shadow);
}
.panel { padding: 14px; }
.cards { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.idea-card { padding: 14px; min-height: 260px; display: grid; align-content: start; gap: 10px; transition: border-color 120ms ease, box-shadow 120ms ease, transform 120ms ease; }
.idea-card.slot-a { border-color: var(--slot-a-line); box-shadow: var(--shadow), 0 0 0 2px var(--slot-a-glow); }
.idea-card.slot-b { border-color: var(--slot-b-line); box-shadow: var(--shadow), 0 0 0 2px var(--slot-b-glow); }
.idea-card.clickable { cursor: pointer; }
.idea-card.clickable:hover, .idea-card.clickable:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(15, 124, 128, 0.16); outline: none; }
.idea-card.selected { border-color: var(--selected); box-shadow: 0 0 0 3px rgba(184, 69, 47, 0.18); }
.idea-card h3 { margin: 0; font-size: 19px; line-height: 1.2; }
.meta { color: var(--muted); display: flex; flex-wrap: wrap; gap: 6px; font-size: 12px; }
.tag { border: 1px solid var(--line); border-radius: 999px; padding: 2px 7px; background: #f9fbfa; }
.reason-panel { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--line); }
.reason-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.reason-btn { text-align: left; background: #f9fbfa; }
.reason-btn:not(:disabled):hover, .reason-btn:not(:disabled):focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(15, 124, 128, 0.14); outline: none; }
.status { color: var(--muted); min-height: 20px; }
.navigation { position: sticky; top: 12px; }
.tree { display: grid; gap: 12px; }
.tree-section { display: grid; gap: 6px; }
.tree-heading { color: var(--muted); font-size: 12px; font-weight: 750; text-transform: uppercase; letter-spacing: 0; }
.tree-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 5px; }
.tree-node { border-left: 3px solid var(--line); padding: 5px 6px 5px 8px; background: #fbfcfb; }
.tree-node.ranked { border-left-color: var(--ranked); background: #eef5fc; }
.tree-node.session-touched { border-left-color: var(--session); background: #fff8d9; }
.tree-label { display: flex; justify-content: space-between; gap: 8px; font-weight: 650; }
.tree-count { color: var(--muted); font-variant-numeric: tabular-nums; }
.ranking { display: grid; gap: 8px; margin-top: 8px; max-height: 520px; overflow: auto; }
.rank-row { display: grid; grid-template-columns: 34px 1fr auto; gap: 8px; align-items: center; border-bottom: 1px solid var(--line); padding: 7px 0; }
.rank-title { font-weight: 650; }
.score { color: var(--muted); font-variant-numeric: tabular-nums; }
.publish { display: grid; gap: 9px; margin-top: 12px; }
.hidden { display: none !important; }
.review-layout { margin-top: 14px; display: grid; gap: 12px; }
.review-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.review-board { display: grid; grid-template-columns: minmax(0, 1fr) 130px minmax(0, 1fr); gap: 10px; align-items: start; }
.review-column { display: grid; gap: 6px; }
.review-list { display: grid; gap: 6px; }
.review-row { min-height: 48px; border: 1px solid var(--line); border-radius: 6px; background: #fbfcfb; padding: 7px 9px; display: grid; grid-template-columns: 28px 1fr; gap: 8px; align-items: center; }
.review-rank { color: var(--muted); font-variant-numeric: tabular-nums; font-weight: 750; }
.review-title { font-weight: 650; }
.arrow-wrap { min-height: 120px; align-self: stretch; }
.arrow-wrap svg { width: 100%; height: 100%; min-height: 120px; overflow: visible; }
@media (max-width: 900px) {
  .filters, .workspace, .cards, .reason-grid, .review-board { grid-template-columns: 1fr; }
  .arrow-wrap { display: none; }
  .navigation { position: static; }
}
</style>
</head>
<body>
<header>
  <h1>Concinnity H2H</h1>
  <div class="status" id="status">Load ideas to begin.</div>
</header>
<main>
  <section class="filters" aria-label="Candidate filters">
    <label>Board type<select id="boardType"><option value="project_ideas">Global Projects</option><option value="backlog">Project Backlog</option><option value="local_icebox">Local Icebox</option></select></label>
    <label>Status<select id="statusFilter"><option value="icebox">icebox</option><option value="">any</option><option>reviewing</option><option>promoted</option><option>rejected</option><option>archived</option></select></label>
    <label>Target type<select id="targetType"><option value="">any</option><option>project</option><option>feature</option><option>spin_off</option><option>unknown</option></select></label>
    <label>Target project<select id="targetProject" disabled><option value="">Loading projects...</option></select></label>
    <label>Tag<input id="tag" placeholder="optional"></label>
    <label>Board / run name<input id="runName" placeholder="required for mixed boards" value="Concinnity H2H run"></label>
    <label class="checkbox-label"><input id="mixedContext" type="checkbox">Allow mixed-context board</label>
    <label>&nbsp;<button class="primary" id="loadBtn">Load / reset session</button></label>
  </section>
  <section class="workspace" id="sessionWorkspace">
    <aside class="panel navigation" aria-label="Idea navigation">
      <h2>Navigation</h2>
      <div class="tree" id="navigationTree"></div>
    </aside>
    <div class="panel">
      <h2>Current round</h2>
      <div class="status" id="fightState"></div>
      <div class="cards">
        <article class="idea-card slot-a" id="cardA" data-slot="a" role="button" tabindex="0" aria-pressed="false"></article>
        <article class="idea-card slot-b" id="cardB" data-slot="b" role="button" tabindex="0" aria-pressed="false"></article>
      </div>
      <div class="reason-panel">
        <h2>Confirm reason</h2>
        <div class="status" id="selectionState">Choose a winning card.</div>
        <div class="reason-grid" id="reasonGrid"></div>
        <label style="margin-top:8px">Reason note<textarea id="reasonNote" maxlength="240" placeholder="Required when Other is selected; optional otherwise."></textarea></label>
      </div>
    </div>
    <aside class="panel">
      <h2>Live ranking</h2>
      <div class="status" id="sessionStats"></div>
      <div class="ranking" id="ranking"></div>
      <div class="publish">
        <label>Publish notes<textarea id="publishNotes" maxlength="500" placeholder="Optional context for this run."></textarea></label>
        <button class="primary" id="reviewBtn">Review and publish</button>
      </div>
    </aside>
  </section>
  <section class="panel review-layout hidden" id="reviewScreen" aria-label="Ranking review">
    <div class="review-actions">
      <button class="ghost" id="backToSessionBtn" type="button">Back to session</button>
      <button class="primary" id="finalPublishBtn" type="button">Publish reviewed ranking</button>
      <div class="status" id="reviewStatus">Review movement before publishing.</div>
    </div>
    <div class="review-board">
      <div class="review-column">
        <h2>Old leaderboard</h2>
        <div class="review-list" id="oldLeaderboard"></div>
      </div>
      <div class="arrow-wrap" aria-hidden="true">
        <svg id="reviewArrows" viewBox="0 0 300 120" preserveAspectRatio="none">
          <defs>
            <marker id="arrowHead" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
              <path d="M0,0 L8,4 L0,8 Z" fill="#0f7c80"></path>
            </marker>
          </defs>
        </svg>
      </div>
      <div class="review-column">
        <h2>New leaderboard</h2>
        <div class="review-list" id="newLeaderboard"></div>
      </div>
    </div>
  </section>
</main>
<script>
const reasons = [
  ["higher_user_value", "Higher user value"],
  ["more_urgent", "More urgent"],
  ["lower_effort", "Lower effort"],
  ["unblocks_other_work", "Unblocks other work"],
  ["better_strategic_fit", "Better strategic fit"],
  ["more_exciting", "More exciting"],
  ["other", "Other"]
];
let ideas = [];
let slotAIndex = null;
let slotBIndex = null;
let championSlot = null;
let selectedWinnerSlot = null;
let activeIndices = [];
let retiredIndices = [];
let championRunSeen = new Set();
let completedChampions = [];
let runSerial = 0;
let round = 0;
let decisions = [];
let projectOptions = [];
let sessionTouchedIds = new Set();
let baselineRankings = [];
let draftId = null;
const kFactor = 32;

function $(id) { return document.getElementById(id); }
function setStatus(text) { $("status").textContent = text; }
function expected(a, b) { return 1 / (1 + Math.pow(10, (b - a) / 400)); }
function nextRating(rating, opponent, score) { return rating + kFactor * (score - expected(rating, opponent)); }

function rankingContext() {
  const board = boardConfig();
  const targetProject = $("targetProject").value.trim();
  const mixed = $("mixedContext").checked;
  const runName = $("runName").value.trim();
  if (!mixed && board.requiresProject && !targetProject) {
    return {ok: false, message: `${board.label} requires a target project from the dropdown or an explicit mixed-context board.`};
  }
  if (mixed && !runName) {
    return {ok: false, message: "Mixed-context boards require a board/run name so the ranking context is auditable."};
  }
  return {
    ok: true,
    board,
    mixed,
    targetProject,
    label: mixed ? runName : (targetProject || board.label),
    message: mixed ? `Mixed-context board: ${runName}` : board.requiresProject ? `Ranking target project: ${targetProject}` : `Ranking board: ${board.label}`
  };
}

function boardConfig() {
  const boardType = $("boardType").value;
  if (boardType === "project_ideas") {
    return {lane: "project_ideas", targetType: "project", label: "Global Projects", requiresProject: false};
  }
  if (boardType === "backlog") {
    return {lane: "backlog", targetType: "feature", label: "Project Backlog", requiresProject: true};
  }
  return {lane: "local_icebox", targetType: "", label: "Local Icebox", requiresProject: true};
}

function newDraftId() {
  if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
  return `draft-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function currentFilters(context = rankingContext()) {
  const board = context.board || boardConfig();
  return {
    status: $("statusFilter").value || null,
    target_type: board.targetType || $("targetType").value || null,
    target_project: context.mixed ? null : $("targetProject").value || null,
    lane: board.lane,
    tag: $("tag").value || null,
    mixed_context: $("mixedContext").checked,
    context_label: context.label || null
  };
}

function currentRankings() {
  const ranked = [...ideas].sort((a, b) => b.rating - a.rating || b.comparison_count - a.comparison_count || a.title.localeCompare(b.title) || a.id.localeCompare(b.id));
  return rankingsFrom(ranked);
}

function rankingsFrom(values) {
  return values.map((idea, index) => ({
    idea_id: idea.id,
    rank: index + 1,
    rating: Number(idea.rating || 1000),
    comparison_count: Number(idea.comparison_count || 0),
    wins: Number(idea.wins || 0),
    losses: Number(idea.losses || 0),
    ties: Number(idea.ties || 0)
  }));
}

function draftPayload() {
  const context = rankingContext();
  return {
    draft_id: draftId,
    client_session_id: draftId,
    name: $("runName").value.trim() || "Concinnity H2H run",
    filters: currentFilters(context),
    algorithm: "local_web_session_elo",
    notes: [`Context: ${context.message}`, $("publishNotes").value.trim()].filter(Boolean).join("\n") || null,
    decisions,
    before_rankings: baselineRankings,
    rankings: currentRankings()
  };
}

async function saveDraft(statusText = "Session draft saved.") {
  if (!draftId || ideas.length === 0) return null;
  const response = await fetch("/api/drafts", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(draftPayload())});
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || "Draft save failed.");
  if (statusText) setStatus(statusText);
  return data;
}

function renderReasons() {
  $("reasonGrid").innerHTML = reasons.map(([code, label]) => `
    <button class="reason-btn" type="button" data-reason="${code}" disabled>${label}</button>
  `).join("");
  document.querySelectorAll(".reason-btn").forEach(button => {
    button.addEventListener("click", () => confirmDecision(button.dataset.reason));
  });
}

async function loadProjectOptions() {
  const board = boardConfig();
  const select = $("targetProject");
  $("targetType").value = board.targetType;
  $("targetType").disabled = true;
  select.disabled = !board.requiresProject;
  if (!board.requiresProject) {
    select.innerHTML = `<option value="">Not required for ${board.label}</option>`;
    return;
  }
  select.disabled = true;
  select.innerHTML = `<option value="">Loading projects...</option>`;
  const params = new URLSearchParams();
  params.set("lane", board.lane);
  const status = $("statusFilter").value.trim();
  if (status) params.set("status", status);
  const response = await fetch(`/api/projects?${params}`);
  projectOptions = await response.json();
  if (projectOptions.length === 0) {
    select.innerHTML = `<option value="">No ${board.label.toLowerCase()} projects</option>`;
    select.disabled = true;
    return;
  }
  select.innerHTML = [
    `<option value="">Choose target project</option>`,
    ...projectOptions.map(project => {
      const value = escapeHtml(project.target_project);
      const count = Number(project.idea_count || 0);
      return `<option value="${value}">${value} (${count})</option>`;
    })
  ].join("");
  select.disabled = false;
}

function syncBoardControls() {
  const board = boardConfig();
  $("targetType").value = board.targetType;
  $("targetType").disabled = true;
  $("targetProject").disabled = !board.requiresProject;
}

async function loadIdeas() {
  const context = rankingContext();
  if (!context.ok) {
    ideas = [];
    activeIndices = [];
    retiredIndices = [];
    completedChampions = [];
    slotAIndex = null;
    slotBIndex = null;
    championSlot = null;
    selectedWinnerSlot = null;
    sessionTouchedIds = new Set();
    baselineRankings = [];
    draftId = null;
    setStatus(context.message);
    render();
    return;
  }
  const params = new URLSearchParams();
  const board = context.board;
  params.set("lane", board.lane);
  if (board.targetType) params.set("target_type", board.targetType);
  const status = $("statusFilter").value.trim();
  if (status) params.set("status", status);
  if (!context.mixed && context.targetProject) params.set("target_project", context.targetProject);
  const tag = $("tag").value.trim();
  if (tag) params.set("tag", tag);
  const response = await fetch(`/api/ideas?${params}`);
  ideas = await response.json();
  ideas = ideas.map(item => ({...item, rating: Number(item.rating || 1000), comparison_count: Number(item.comparison_count || 0), wins: Number(item.wins || 0), losses: Number(item.losses || 0), ties: Number(item.ties || 0)}));
  draftId = newDraftId();
  baselineRankings = currentRankings();
  decisions = [];
  round = 0;
  activeIndices = ideas.map((_, index) => index);
  retiredIndices = [];
  completedChampions = [];
  sessionTouchedIds = new Set();
  showSession();
  startChampionRun(`Session loaded. ${context.message}.`);
  render();
  try {
    await saveDraft("Session draft saved at load.");
  } catch (error) {
    setStatus(error.message);
  }
}

function ideaSort(aIndex, bIndex) {
  const a = ideas[aIndex];
  const b = ideas[bIndex];
  return a.comparison_count - b.comparison_count || b.rating - a.rating || a.title.localeCompare(b.title) || a.id.localeCompare(b.id);
}

function startChampionRun(message) {
  championRunSeen = new Set();
  slotAIndex = null;
  slotBIndex = null;
  championSlot = null;
  selectedWinnerSlot = null;
  if (activeIndices.length < 2) {
    if (activeIndices.length === 1) {
      slotAIndex = activeIndices[0];
      championSlot = "a";
      setStatus("One active candidate remains; publish when ready.");
    } else {
      setStatus("Load at least two ideas.");
    }
    return;
  }
  activeIndices.sort(ideaSort);
  slotAIndex = activeIndices[0];
  championSlot = "a";
  runSerial += 1;
  chooseChallenger();
  setStatus(`${message || "New champion run started."} Champion: ${ideas[championIndex()].title}`);
}

function chooseChallenger(excludeIndex = null) {
  const champion = championIndex();
  const slot = challengerSlot();
  if (champion === null || slot === null) return;
  const candidates = activeIndices
    .filter(index => index !== champion && index !== excludeIndex && !championRunSeen.has(index))
    .sort(ideaSort);
  if (candidates.length > 0) {
    setSlotIndex(slot, candidates[0]);
    return;
  }
  setSlotIndex(slot, null);
  retireChampion();
}

function retireChampion() {
  const champion = championIndex();
  if (champion === null) return;
  const retired = champion;
  activeIndices = activeIndices.filter(index => index !== retired);
  retiredIndices.push(retired);
  completedChampions.push({index: retired, run: runSerial, title: ideas[retired].title});
  setStatus(`${ideas[retired].title} completed a champion run and stepped away.`);
  startChampionRun("New champion run started.");
}

function championIndex() {
  return championSlot === "a" ? slotAIndex : championSlot === "b" ? slotBIndex : null;
}

function challengerSlot() {
  return championSlot === "a" ? "b" : championSlot === "b" ? "a" : null;
}

function challengerIndex() {
  const slot = challengerSlot();
  return slot === "a" ? slotAIndex : slot === "b" ? slotBIndex : null;
}

function slotIndex(slot) {
  return slot === "a" ? slotAIndex : slotBIndex;
}

function setSlotIndex(slot, index) {
  if (slot === "a") slotAIndex = index;
  else slotBIndex = index;
}

function hasMatchup() {
  return championIndex() !== null && challengerIndex() !== null;
}

function selectWinner(slot) {
  if (!hasMatchup() || slotIndex(slot) === null) return;
  selectedWinnerSlot = slot;
  const label = slot.toUpperCase();
  $("selectionState").textContent = `${label} selected. Choose a reason to record.`;
  render();
}

function handleCardKey(event, slot) {
  if (event.key !== "Enter" && event.key !== " ") return;
  event.preventDefault();
  selectWinner(slot);
}

function renderCard(element, idea, label, slot) {
  const selectable = Boolean(idea) && hasMatchup();
  element.classList.toggle("clickable", selectable);
  element.classList.toggle("selected", selectedWinnerSlot === slot);
  element.setAttribute("aria-pressed", selectedWinnerSlot === slot ? "true" : "false");
  element.setAttribute("aria-disabled", selectable ? "false" : "true");
  element.setAttribute("aria-label", idea ? `${label}: ${idea.title}` : `${label} empty slot`);
  element.innerHTML = !idea ? `<h3>${label}</h3><p>Load at least two ideas.</p>` : `
    <div class="meta"><span class="tag">${label}</span><span>${idea.lane}</span><span>${idea.status}</span><span>${idea.target_type}</span><span>${idea.target_project || "no target project"}</span></div>
    <h3>${escapeHtml(idea.title)}</h3>
    <p>${escapeHtml(idea.description)}</p>
    <div class="meta">${(idea.tags || []).map(tag => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div>
    <div class="score">Rating ${idea.rating.toFixed(1)} | ${idea.comparison_count} comparisons</div>
  `;
}

function render() {
  renderCard($("cardA"), ideas[slotAIndex], "A", "a");
  renderCard($("cardB"), ideas[slotBIndex], "B", "b");
  const ranked = [...ideas].sort((a, b) => b.rating - a.rating || b.comparison_count - a.comparison_count);
  $("ranking").innerHTML = ranked.map((idea, index) => `
    <div class="rank-row"><div>${index + 1}</div><div><div class="rank-title">${escapeHtml(idea.title)}</div><div class="score">${idea.wins}-${idea.losses}</div></div><div class="score">${idea.rating.toFixed(1)}</div></div>
  `).join("");
  $("sessionStats").textContent = `${round} rounds recorded. ${retiredIndices.length} completed champions. ${activeIndices.length} active fighters.`;
  $("fightState").textContent = !hasMatchup()
    ? "No active matchup available."
    : `Run ${runSerial}: champion has seen ${championRunSeen.size} of ${Math.max(activeIndices.length - 1, 0)} challengers.`;
  if (!selectedWinnerSlot) {
    $("selectionState").textContent = hasMatchup() ? "Choose a winning card." : "Load a matchup to choose a winner.";
  }
  document.querySelectorAll(".reason-btn").forEach(button => {
    button.disabled = !hasMatchup() || !selectedWinnerSlot;
  });
  $("reviewBtn").disabled = ideas.length < 2;
  renderNavigationTree();
}

function confirmDecision(reason) {
  if (!selectedWinnerSlot) {
    setStatus("Choose a winning card before selecting a reason.");
    return;
  }
  const note = $("reasonNote").value.trim();
  if (reason === "other" && !note) {
    setStatus("Other requires a short reason note.");
    return;
  }
  record(selectedWinnerSlot, reason, note);
}

function record(winnerSlot, reason, note) {
  if (!hasMatchup()) return;
  const aIndex = slotAIndex;
  const bIndex = slotBIndex;
  const a = ideas[aIndex];
  const b = ideas[bIndex];
  const beforeA = a.rating;
  const beforeB = b.rating;
  const scoreA = winnerSlot === "a" ? 1 : 0;
  const scoreB = winnerSlot === "b" ? 1 : 0;
  a.rating = nextRating(beforeA, beforeB, scoreA);
  b.rating = nextRating(beforeB, beforeA, scoreB);
  a.comparison_count += 1;
  b.comparison_count += 1;
  if (winnerSlot === "a") { a.wins += 1; b.losses += 1; }
  else { b.wins += 1; a.losses += 1; }
  round += 1;
  sessionTouchedIds.add(a.id);
  sessionTouchedIds.add(b.id);
  decisions.push({
    round_number: round,
    idea_a_id: a.id,
    idea_b_id: b.id,
    winner: winnerSlot,
    reason_code: reason,
    reason_note: note || null,
    rating_a_before: beforeA,
    rating_b_before: beforeB,
    rating_a_after: a.rating,
    rating_b_after: b.rating,
    created_at: new Date().toISOString()
  });
  const previousChampion = championIndex();
  const previousChallenger = challengerIndex();
  const winnerIdea = ideas[slotIndex(winnerSlot)];
  const loserSlot = winnerSlot === "a" ? "b" : "a";
  const loserIndex = slotIndex(loserSlot);
  if (winnerSlot === championSlot) {
    championRunSeen.add(previousChallenger);
    setStatus(`${winnerIdea.title} stays champion.`);
  } else {
    championSlot = winnerSlot;
    championRunSeen = new Set([previousChampion]);
    runSerial += 1;
    setStatus(`${winnerIdea.title} is the new champion.`);
  }
  setSlotIndex(loserSlot, loserIndex);
  selectedWinnerSlot = null;
  $("reasonNote").value = "";
  chooseChallenger();
  render();
  saveDraft("Session draft saved after decision.").catch(error => setStatus(error.message));
}

function renderNavigationTree() {
  const tree = $("navigationTree");
  if (!tree) return;
  if (ideas.length === 0) {
    tree.innerHTML = `<div class="status">No candidates loaded.</div>`;
    return;
  }
  const projectIdeas = ideas.filter(idea => idea.lane === "project_ideas");
  const backlog = ideas.filter(idea => idea.lane === "backlog");
  const localIcebox = ideas.filter(idea => idea.lane === "local_icebox");
  const done = ideas.filter(idea => idea.lane === "done");
  tree.innerHTML = `
    <div class="tree-section">
      <div class="tree-heading">Project Ideas</div>
      <ul class="tree-list">${treeNode("Global future projects", projectIdeas.length, projectIdeas)}</ul>
    </div>
    <div class="tree-section">
      <div class="tree-heading">Backlog by project</div>
      <ul class="tree-list">${projectTreeNodes(backlog, "No backlog candidates")}</ul>
    </div>
    <div class="tree-section">
      <div class="tree-heading">Local Icebox by project</div>
      <ul class="tree-list">${projectTreeNodes(localIcebox, "No local icebox candidates")}</ul>
    </div>
    ${done.length ? `<div class="tree-section"><div class="tree-heading">Done by project</div><ul class="tree-list">${projectTreeNodes(done, "No done candidates")}</ul></div>` : ""}
  `;
}

function projectTreeNodes(groupIdeas, emptyLabel) {
  const groups = groupBy(groupIdeas, idea => idea.target_project || "No target project");
  const nodes = Object.keys(groups).sort().map(project => {
    const group = groups[project];
    return treeNode(project, group.length, group);
  }).join("");
  return nodes || treeNode(emptyLabel, 0, []);
}

function treeNode(label, count, groupIdeas) {
  const className = treeClass(groupIdeas);
  return `<li class="tree-node ${className}"><div class="tree-label"><span>${escapeHtml(label)}</span><span class="tree-count">${count}</span></div></li>`;
}

function treeClass(groupIdeas) {
  if (groupIdeas.some(idea => sessionTouchedIds.has(idea.id))) return "session-touched";
  if (groupIdeas.some(idea => Number(idea.comparison_count || 0) > 0)) return "ranked";
  return "";
}

function groupBy(values, keyFn) {
  return values.reduce((groups, value) => {
    const key = keyFn(value);
    groups[key] = groups[key] || [];
    groups[key].push(value);
    return groups;
  }, {});
}

async function reviewAndPublish() {
  const context = rankingContext();
  if (!context.ok) {
    setStatus(context.message);
    return;
  }
  try {
    await saveDraft("Session draft saved for review.");
    renderReview();
    showReview();
  } catch (error) {
    setStatus(error.message);
  }
}

function showReview() {
  $("sessionWorkspace").classList.add("hidden");
  $("reviewScreen").classList.remove("hidden");
  $("reviewStatus").textContent = "Review movement before publishing.";
  $("finalPublishBtn").disabled = false;
}

function showSession() {
  $("reviewScreen").classList.add("hidden");
  $("sessionWorkspace").classList.remove("hidden");
}

function ideaTitle(ideaId) {
  const idea = ideas.find(item => item.id === ideaId);
  return idea ? idea.title : ideaId;
}

function renderReview() {
  const before = baselineRankings;
  const after = currentRankings();
  $("oldLeaderboard").innerHTML = before.map(item => reviewRow(item)).join("");
  $("newLeaderboard").innerHTML = after.map(item => reviewRow(item)).join("");
  renderReviewArrows(before, after);
}

function reviewRow(item) {
  return `
    <div class="review-row" data-idea-id="${escapeHtml(item.idea_id)}">
      <div class="review-rank">${item.rank}</div>
      <div><div class="review-title">${escapeHtml(ideaTitle(item.idea_id))}</div><div class="score">${Number(item.rating || 1000).toFixed(1)}</div></div>
    </div>
  `;
}

function renderReviewArrows(before, after) {
  const svg = $("reviewArrows");
  const rowStep = 54;
  const height = Math.max(before.length, after.length, 1) * rowStep;
  const oldPositions = new Map(before.map((item, index) => [item.idea_id, index]));
  const newPositions = new Map(after.map((item, index) => [item.idea_id, index]));
  const ids = [...new Set([...before.map(item => item.idea_id), ...after.map(item => item.idea_id)])];
  svg.setAttribute("viewBox", `0 0 300 ${height}`);
  svg.style.minHeight = `${height}px`;
  const defs = `
    <defs>
      <marker id="arrowHead" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
        <path d="M0,0 L8,4 L0,8 Z" fill="#0f7c80"></path>
      </marker>
    </defs>
  `;
  const paths = ids.map(id => {
    const oldIndex = oldPositions.has(id) ? oldPositions.get(id) : before.length;
    const newIndex = newPositions.has(id) ? newPositions.get(id) : after.length;
    const y1 = oldIndex * rowStep + rowStep / 2;
    const y2 = newIndex * rowStep + rowStep / 2;
    const stroke = oldIndex === newIndex ? "#637067" : "#0f7c80";
    return `<path d="M20 ${y1} C110 ${y1}, 190 ${y2}, 280 ${y2}" fill="none" stroke="${stroke}" stroke-width="2" marker-end="url(#arrowHead)"></path>`;
  }).join("");
  svg.innerHTML = defs + paths;
}

async function publishReviewedDraft() {
  if (!draftId) {
    setStatus("No staged draft is available to publish.");
    return;
  }
  try {
    await saveDraft("");
  } catch (error) {
    setStatus(error.message);
    return;
  }
  const response = await fetch(`/api/drafts/${encodeURIComponent(draftId)}/publish`, {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"});
  const data = await response.json();
  if (!response.ok || data.error) {
    setStatus(data.error || "Publish failed.");
    return;
  }
  const published = data.published;
  setStatus(`Published ${published.snapshot.length} ranked ideas in run ${published.run.id}.`);
  $("reviewStatus").textContent = `Published reviewed ranking in run ${published.run.id}.`;
  $("finalPublishBtn").disabled = true;
}

function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[char]));
}

renderReasons();
$("loadBtn").addEventListener("click", loadIdeas);
$("boardType").addEventListener("change", () => {
  syncBoardControls();
  loadProjectOptions().catch(error => setStatus(error.message));
});
$("statusFilter").addEventListener("change", () => {
  loadProjectOptions().catch(error => setStatus(error.message));
});
$("cardA").addEventListener("click", () => selectWinner("a"));
$("cardB").addEventListener("click", () => selectWinner("b"));
$("cardA").addEventListener("keydown", event => handleCardKey(event, "a"));
$("cardB").addEventListener("keydown", event => handleCardKey(event, "b"));
$("reviewBtn").addEventListener("click", reviewAndPublish);
$("backToSessionBtn").addEventListener("click", showSession);
$("finalPublishBtn").addEventListener("click", publishReviewedDraft);
syncBoardControls();
render();
loadProjectOptions()
  .then(loadIdeas)
  .catch(error => setStatus(error.message));
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
