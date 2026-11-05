# delegation-scout

A Hermes delegation backend plugin (`delegation.backend: scout`) that routes every
`delegate_task` child run to the right model/profile — using deterministic task-shape
heuristics plus **recorded past outcomes** in its own durable SQLite DB. Over sessions,
routing accuracy improves because the plugin observes which route actually succeeded
for which kind of task.

## Install

```bash
hermes plugins install ./hermes-delegation-scout   # or: link/copy into ~/.hermes/plugins/
hermes plugins enable delegation-scout
```

Requirements: Hermes `>=0.22.0`. No Python dependencies beyond stdlib; no network calls
on any path (routes resolve credentials through core).

## Configure

```yaml
# ~/.hermes/config.yaml
delegation:
  backend: scout
  backends:
    scout:
      routes:
        quick: {provider: openrouter, model: google/gemini-3-flash-preview}
        deep:  {provider: nous, model: moonshotai/kimi-k3}
```

- `mode: "quick" | "deep" | "auto"` appears on every `delegate_task` task. Explicit
  `mode` is honoured first; an unknown value is refused (the tool error tells the model
  the allowed values).
- `auto` (or omitted) scores the task: deep-work keywords (`review`, `analyze`,
  `refactor`, `debug`, ...), quick-work keywords (`lookup`, `summarize`, ...),
  attached images, and text length. A class with ≥5 recorded samples whose success rate
  beats the other candidate by ≥15 points nudges the final pick.
- A class missing from `routes` inherits the `delegation` section (label `default`).
- If `routes` is empty the backend reports unavailable: delegation fails closed with
  the fix message instead of silently running a wrong route.

## How it learns

- `route_task` writes each decision to the plugin DB (`delegation.backends.scout` stays
  config-only): `routes(task_hash, label, provider, model, ts)` with a deterministic
  `sha1(goal)[:16]` hash.
- A public `post_tool_call` observer hook records finished `delegate_task` results
  (`route.backend == "scout"`, terminal statuses only) into `outcomes(route_id, status,
  error, ts)`. See `docs/outcome-seam.md` for the seam evidence; no core patching.
- `scout_stats` (the plugin's one tool) returns per-route counts, success rates, and
  the last-N decisions as pretty-printed JSON.

Determinism: `task_parameters`/`description` are byte-stable per config (prompt
caching). History lookups happen only inside `route_task`.

## Non-goals (v1)

LLM-based classification inside `route_task` (nondeterministic / prompt-cache hostile),
cross-user learning, UI.

## Development

```bash
python -m pytest -q        # unit + e2e (temp HERMES_HOME; never the real profile)
hermes plugins doctor ./hermes-delegation-scout
hermes plugins validate ./hermes-delegation-scout --install-deps
```
