# Outcome-capture seam discovery (Task 5, Step 1)

**Question:** does a public plugin seam receive finished `delegate_task` results
(including `route.label` and per-task `status`) without monkey-patching core?

**Answer: YES — the public `post_tool_call` observer hook.** A second seam
(`tool_execution` middleware) also works; the hook was chosen because its return value
is ignored by core (observer-only) so it is physically incapable of changing behavior.

## Evidence

1. **Docs (Plugin guide, "Middleware: change what happens" / hook reference):**
   - `post_tool_call` fires "after any tool returns" and receives
     `tool_name: str, args: dict, result: str, task_id: str, duration_ms: int`;
     return value ignored (hooks reference table).
   - `VALID_MIDDLEWARE` in `hermes_cli/middleware.py` also includes `tool_execution`,
     which wraps execution with a single-use `next_call(payload)` that returns the tool
     result — an alternative seam we did not need.
2. **Installed source:**
   - `model_tools._emit_post_tool_call_hook` emits the hook for registry-dispatched
     tools inside `handle_function_call` (gated on `has_hook`).
   - `delegate_task` is in `AGENT_RUNTIME_POST_HOOK_TOOL_NAMES` and
     `agent/inline_tool_executors.emit_terminal_post_tool_call` fires the same hook on
     the agent-runtime path — both paths covered.
3. **Result shape (Delegation Provider Plugins guide, "Result route"):**
   each result entry of a task routed by a non-default backend carries
   `route: {"backend", "label", "provider", "model", ...}` plus `status`/`error`.
   Entries are correlated back to tasks via `task_index`; scout re-derives its
   deterministic `task_hash = sha1(goal)[:16]` (the same value `route_task` recorded).

## Caveats (documented for users)

- Background dispatches return a dispatch payload, not finished results; outcomes are
  recorded for entries that arrive with a terminal `status` in the tool result.
- The hook is registered as `post_tool_call` via `ctx.register_hook` — no core patching,
  per catalog rule 9.
