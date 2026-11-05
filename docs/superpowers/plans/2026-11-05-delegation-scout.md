# delegation-scout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: implement task-by-task, one commit per task. Steps use checkbox syntax for tracking.

**Goal:** A `delegation.backend` plugin (`scout`) that routes `delegate_task` children by task-shape heuristics, nudged by recorded per-route outcomes in a durable SQLite DB.

**Architecture:** `scout/provider.py` (DelegationProvider) + `scout/features.py` (pure scoring) + `scout/stats.py` (plugin_db SQLite). Optional middleware outcome capture behind a discovery gate; heuristic-only is the guaranteed deliverable.

**Tech stack:** Python 3.11+, pytest; mirror Hermes repo's `tests/tools/test_delegation_backends.py` style.

**Spec:** `docs/superpowers/specs/2026-11-05-delegation-scout-design.md`

## Global Constraints

- `task_parameters` and `description` MUST be deterministic byte-wise for a given config (prompt-cache contract) — no clock, no network, no random; history lookups happen ONLY inside `route_task`.
- Keep backend settings under `delegation.backends.scout` — never beside core `delegation` keys.
- Refusals are per task: raise `DelegationRouteError` with an actionable message; never silently co-route a bad param value.
- Outcome-capture middleware: discover the TRUE public seam first (saved plugin guide sections "Middleware: change what happens" / "Hook reference" at `/home/von/.hermes/cache/web/hermes-agent.nousresearch.com-ac6255942f.md`, plus installed source under `~/.hermes/hermes-agent`). If no public middleware receives finished tool results, DO NOT patch or monkey-patch core (catalog rule 9) — ship heuristic routing and note the hook request in README.
- `capabilities:` in `plugin.yaml` matches exactly what `register(ctx)` registers.
- Zero required python deps; pytest only in dev.

## Review Focus

1. `mode: "quantum"` (outside enum) → must be refused by core's enum check AND route_task defensively; test.
2. `routes` config missing `quick`/`deep` key → inherit `dict(config)` for that class, don't crash; test.
3. Outcomes DB with 4 samples (<5 threshold) → no nudging; test boundary.
4. `images` present in task → +deep signal; test.
5. Provider unavailable (empty routes config) → `is_available()` False with fix message, never network; test.

---

### Task 1: Scaffold + manifest

**Files:** Create `plugin.yaml`, `__init__.py`, `scout/__init__.py`, `README.md` stub.

```yaml
name: delegation-scout
version: "1.0.0"
description: "Delegation backend that routes subagents by task shape and learns from recorded outcomes."
homepage: https://github.com/vdimarco/hermes-delegation-scout
requires_hermes: ">=0.22.0"
capabilities:
  delegation_backends: [scout]
  tools: [scout_stats]
```

`register(ctx)`: `ctx.register_delegation_provider(ScoutProvider())` (+ tool after Task 6).
- [ ] Steps: write → `hermes plugins doctor ~/Work/hermes-delegation-scout` → commit `feat: scaffold + manifest`.

### Task 2: Feature scoring (`scout/features.py`)

**Files:** Create `scout/features.py`, `tests/test_features.py`
**Produces:** `score_task(task: dict) -> dict` → `{"class": "quick"|"deep"|"default", "score": int, "signals": list[str]}`

Rules (pure, deterministic): +2 deep for regex `\b(review|analy[sz]e|architect|design|refactor|debug|migrate|multi-step)\b` (case-insens) on goal+context; +2 quick for `\b(lookup|summari[sz]e|fetch|check|quick|simple|one-liner|trivial)\b`; +1 deep if `images` list non-empty; +1 deep if word count > 120; +1 quick if word count < 25. `score = deep - quick`; class: ≥2 → deep, ≤-2 → quick, else default.
- [ ] Steps: failing tests (5 cases from Review Focus + tie → default) → run → implement → PASS → commit `feat: deterministic task scoring`.

### Task 3: Stats (`scout/stats.py`)

**Files:** Create `scout/stats.py`, `tests/test_stats.py`
**Produces:** `Stats` class taking an sqlite3 connection; `ensure_schema()`; `record_route(task_hash, label, provider, model, ts)` → `route_id`; `record_outcome(route_id, status, error, ts)`; `nudge(candidate_classes: dict, min_samples=5, margin=0.15) -> Optional[str]` (returns the class with ≥min_samples whose success rate exceeds every other candidate by ≥margin, else None); `summary()` → dict for the tool.
Tables: `routes(id INTEGER PK, task_hash TEXT, label TEXT, provider TEXT, model TEXT, ts REAL)`, `outcomes(route_id INTEGER, status TEXT, error TEXT, ts REAL)`.
- [ ] Steps: tests (schema idempotent; nudge boundary exactly 5 samples; summary shape) → implement → PASS → commit `feat: durable outcome stats (plugin_db sqlite)`.

### Task 4: Provider (`scout/provider.py`)

**Files:** Create `scout/provider.py`, `tests/test_provider.py`
**Consumes:** features.score_task, stats.Stats
**Produces:** `class ScoutProvider(DelegationProvider)` from `agent.delegation_provider`:

- `name` → `"scout"`
- `task_parameters(config)` → `{"mode": {"type": "string", "enum": ["auto","quick","deep"], "description": "Force a route class; auto uses task-shape heuristics."}}` — deterministic.
- `description(config)` → constant string.
- `is_available()` → `bool(self.settings(config).get("routes"))` — no network.
- `route_task(task, config)` → mode honored → features.score_task → stats.nudge consult (Stats from `plugin_db`, guarded try/except → ignore nudge on failure) → map class through `routes` config → return `{**route, "label": class_}`; degenerates to `dict(config)` with label "default"; record route into stats with a deterministic `task_hash = hashlib.sha1(goal.encode()).hexdigest()[:16]`; swallow stats errors.
- `display_name` = "Scout", `summary` = one line.

Mirror `tests/tools/test_delegation_backends.py` in `~/.hermes/hermes-agent` for how core tests providers — import path and temp-HERMES_HOME approach.
- [ ] Steps: failing tests (mode honored; auto→deep on review-keywords; missing route → default inherit + label; unknown mode refused; stats error swallowed) → run → implement → PASS → commit `feat: scout delegation provider`.

### Task 5: Outcome capture discovery + wire or fallback

- [ ] **Step 1: Discovery** — read the saved plugin guide sections on middleware/hooks and grep installed Hermes source for `register_middleware`; determine IF a public seam sees finished `delegate_task` results (including `route.label` and status). Write findings to `docs/outcome-seam.md`.
- [ ] **Step 2a (seam exists):** implement `scout/observe.py` registering it; on each delegate_task result with `route.backend == "scout"`, call `stats.record_outcome`. Test via the seam's own harness. Commit `feat: outcome capture middleware (learning loop)`.
- [ ] **Step 2b (no seam):** document the gap in README ("outcome learning activates when Hermes exposes a tool-result middleware — see <issue link if filed>"); `record_outcome` stays unit-tested but unwired. Commit `docs: document outcome-seam gap (no core patching per catalog rule 9)`.

### Task 6: `scout_stats` tool

**Files:** `scout/stats_tool.py`, tests. Schema: no args. Returns `stats.summary()` pretty-printed JSON.
- [ ] Steps: failing test → implement → PASS → commit `feat: scout_stats tool`.

### Task 7: e2e config test + validation

- [ ] **Step 1:** temp-HERMES_HOME test enabling `delegation.backend: scout` with a routes config; assert `delegate_task` tool definition carries `mode` param and a routed task returns `route.backend == "scout"` + label.
- [ ] **Step 2:** `hermes plugins validate ~/Work/hermes-delegation-scout --install-deps` zero failures.
- [ ] **Step 3:** README (install, config example, how it learns, non-goals); commit `docs+feat: e2e test, validation, README`; push.

### Task 8: Handoff report

Final message: commits list, validate tail output, Steps 2a/2b branch taken with evidence, capability list registered.
