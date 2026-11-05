# delegation-scout — learning subagent router — design spec

**Repo:** `github.com/vdimarco/hermes-delegation-scout` (standalone)
**Plugin name (manifest):** `delegation-scout`
**Hackathon:** Hermes Plugin Hackathon, due 2026-11-11 17:00 EST.

## Goal

A `delegation.backend` that routes every `delegate_task` child run to the right model/profile — using both task-shape heuristics and **recorded past outcomes** in its own durable SQLite DB. Over sessions, routing accuracy improves because the plugin observes which route actually succeeded for which kind of task.

## Surfaces used

| Surface | Use |
|---|---|
| `ctx.register_delegation_provider()` | backend name `scout` (`delegation.backend: scout`) |
| `task_parameters(config)` | adds `mode: [auto, quick, deep]` + `confidence: [low, medium, high]`(optional) to the `delegate_task` item schema |
| `description(config)` | one-line guidance the model sees on the tool |
| `plugin_db()` | durable SQLite (WAL): `routes` table + `outcomes` table |
| `ctx.register_middleware` / tool-result hook **if the public seam exists** | observe `delegate_task` results (status, route label) → `outcomes`. Fallback if unavailable: heuristic-only routing + `scout_stats` tool reading `routes` |
| `ctx.register_tool` ×1 | `scout_stats()` — routing counts, per-route success rate, last-N decisions |

## Routing contract

`route_task(task, config)`:

1. `mode` param honoured first (`quick`/`deep`); unknown value → `DelegationRouteError`.
2. `auto` or absent → feature score from task text: word count, presence of `review|analyze|architect|design|refactor|debug|multi-step` (+deep), `lookup|summarize|fetch|check|quick|simple` (+quick), `images` present (+deep). Deterministic — **never uses clock/network** (`task_parameters`/`description` must be byte-stable for prompt caching).
3. Consult `outcomes` history: if a route class has ≥5 samples and success rate differs between candidates by ≥15 points, nudge the pick to the better performer.
4. Map final class → route dict from `delegation.backends.scout.routes` config:

```yaml
delegation:
  backend: scout
  backends:
    scout:
      routes:
        quick: {provider: openrouter, model: google/gemini-3-flash-preview}
        deep:  {provider: nous, model: moonshotai/kimi-k3}
```

Missing route for a class → inherit `dict(config)` (default route). Return includes `"label": "quick"|"deep"|"default"`.

## Outcome capture

- Table `routes(task_hash TEXT, mode TEXT, label TEXT, provider TEXT, model TEXT, ts REAL)`.
- Table `outcomes(route_id INTEGER, status TEXT, error TEXT, ts REAL)`.
- Discovery step for the implementer: find in the Hermes plugin docs (saved copy at `/home/von/.hermes/cache/web/hermes-agent.nousresearch.com-ac6255942f.md`, sections "Middleware: change what happens" and "Hook reference") and installed source (`python -c "import hermes_app, os; print(os.path.dirname(hermes_app.__file__))"` or equivalent discovery) whether a middleware/hook receives finished tool results for `delegate_task`. If yes, wire it; if no, ship heuristic-only and document the seam request (docs say: ask for a hook via issue rather than patch core).

## Fail-closed rules

1. Every refusal is per-task via `DelegationRouteError` with an actionable message.
2. `is_available()` returns False (no network) when `delegation.backends.scout.routes` is empty → core refuses with the standard fix message.
3. `route_task` never falls back to a hidden default when a param value is unknown — it refuses.
4. Any exception inside outcome capture is swallowed (never breaks delegation).
5. Capabilities block matches reality; no core overrides; no env/credential reads (routes resolve credentials through core).

## Testing

- `pytest`: route decision matrix (mode × auto-features × history nudge), refusal paths, DB upserts (tmp sqlite).
- Mirror the Hermes repo's own test style (`tests/tools/test_delegation_backends.py`): temp `HERMES_HOME` with config enabling the backend; assert `delegate_task` definitions carry the params and routing lands where expected.
- `hermes plugins doctor` + `hermes plugins validate --install-deps` clean.

## Repo layout

```text
hermes-delegation-scout/
├── plugin.yaml
├── README.md
├── __init__.py
├── scout/
│   ├── provider.py      # DelegationProvider impl
│   ├── features.py      # deterministic task scoring
│   └── stats.py         # sqlite via plugin_db()
├── tests/
│   ├── test_provider.py
│   ├── test_features.py
│   └── test_stats.py
└── docs/superpowers/specs/2026-11-05-delegation-scout-design.md
```

## Non-goals (v1)

LLM-based classification inside `route_task` (nondeterministic / prompt-cache hostile), cross-user learning, UI.
