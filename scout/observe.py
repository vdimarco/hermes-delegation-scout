"""Outcome capture: record finished ``delegate_task`` results into scout's SQLite DB.

Registered as the public ``post_tool_call`` observer hook (see
``docs/outcome-seam.md``): core calls it after every tool with
``tool_name, args, result, ...`` and ignores its return. Every failure is swallowed —
outcome capture must never break a delegation run.

Only entries routed by the scout backend (``route.backend == "scout"``) with a
terminal status are recorded; the route row is re-located by the deterministic
``sha1(goal)[:16]`` task hash ``ScoutProvider.route_task`` wrote.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from .stats import PLUGIN_DB_NAME, Stats

#: Statuses that mean a child actually finished (dispatch/refusal payloads don't).
_TERMINAL_ERROR = "error"

_SKIPPED_PREFIXES = ("dispatched", "queued", "started", "running", "pending")


def _task_hashes(args: Any) -> dict[int, str]:
    hashes: dict[int, str] = {}
    tools_tasks = args.get("tasks") if isinstance(args, dict) else None
    if not isinstance(tools_tasks, list):
        return hashes
    for i, task in enumerate(tools_tasks):
        if isinstance(task, dict):
            goal = str(task.get("goal") or "")
            hashes[i] = hashlib.sha1(goal.encode("utf-8")).hexdigest()[:16]
    return hashes


def observe_delegate_task(tool_name: Optional[str] = None, args: Optional[dict] = None,
                          result: Any = None, **kwargs: Any) -> None:
    """post_tool_call handler: swallow everything, record what we can."""
    try:
        if tool_name != "delegate_task":
            return
        data = json.loads(result) if isinstance(result, str) else result
        if not isinstance(data, dict):
            return
        results = data.get("results")
        if not isinstance(results, list):
            return
        hashes = _task_hashes(args)

        from plugins.plugin_storage import plugin_db

        stats = Stats(plugin_db(PLUGIN_DB_NAME))
        stats.ensure_schema()
        for entry in results:
            if not isinstance(entry, dict):
                continue
            route = entry.get("route")
            if not isinstance(route, dict) or route.get("backend") != "scout":
                continue
            status = str(entry.get("status") or "")
            if not status or status.startswith(_SKIPPED_PREFIXES):
                continue
            error = entry.get("error") if entry.get("status") == _TERMINAL_ERROR else None
            index = entry.get("task_index")
            stats.record_outcome_for_route(
                task_hash=hashes.get(index) if isinstance(index, int) else None,
                label=route.get("label") or None,
                status=status,
                error=str(error) if error is not None else None,
            )
    except Exception:  # noqa: BLE001 — observation must never break the agent loop
        return
