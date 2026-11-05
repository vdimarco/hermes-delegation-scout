"""The scout delegation provider (``delegation.backend: scout``).

Routing contract (``route_task``):

1. ``mode`` honoured first (``quick``/``deep``); an unknown value is refused with
   :class:`DelegationRouteError` (defensive — core's enum check also refuses first).
2. ``auto`` or absent → deterministic task-shape score (:mod:`scout.features`).
3. Outcomes history may nudge the pick: a candidate class with ≥5 samples that
   outperforms every other candidate by ≥15 points wins (:meth:`Stats.nudge`).
4. Final class maps through ``delegation.backends.scout.routes``; a missing class
   inherits ``dict(config)`` (the default route) and is labelled ``default``.

Determinism: ``task_parameters``/``description`` are byte-stable per config (prompt
caching) — history lookups and the clock happen only inside ``route_task``.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Mapping, Optional

from agent.delegation_provider import DelegationProvider, DelegationRouteError

from .features import score_task
from .stats import PLUGIN_DB_NAME, Stats

MODES = ("auto", "quick", "deep")


class ScoutProvider(DelegationProvider):
    @property
    def name(self) -> str:
        return "scout"

    @property
    def display_name(self) -> str:
        return "Scout"

    @property
    def summary(self) -> str:
        return "Routes subagents by task shape and learns from recorded outcomes."

    def task_parameters(self, config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            "mode": {
                "type": "string",
                "enum": ["auto", "quick", "deep"],
                "description": "Force a route class; auto (default) uses task-shape heuristics.",
            }
        }

    def description(self, config: Mapping[str, Any]) -> str:
        return ("Scout routes by task shape and learns from past subagent outcomes: set "
                "`mode: \"quick\"` for cheap lookups or `mode: \"deep\"` for hard work; "
                "omit it to let heuristics decide.")

    def is_available(self) -> bool:
        """Fail closed when ``delegation.backends.scout.routes`` is unset/empty.

        Reads config.yaml only (no network), mirroring what core hands ``route_task``.
        """
        try:
            from hermes_cli.config import load_config
        except Exception:
            return False
        try:
            cfg = load_config() or {}
            delegation = cfg.get("delegation")
            return bool(self.settings(delegation if isinstance(delegation, Mapping) else {})
                        .get("routes"))
        except Exception:
            return False

    def route_task(self, task: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
        mode = task.get("mode")
        if mode in (None, "", "auto"):
            class_ = score_task(task)["class"]
            nudged = self._consult_history()
            if nudged and nudged != class_:
                class_ = nudged
        elif mode in MODES:
            class_ = mode
        else:
            raise DelegationRouteError(
                f"Unknown mode {mode!r}: use one of {', '.join(MODES)} "
                "(omit `mode` to let task-shape heuristics decide).")

        routes = self.settings(config).get("routes")
        route = routes.get(class_) if isinstance(routes, Mapping) else None
        if isinstance(route, Mapping) and route:
            chosen, label = dict(route), class_
        else:
            chosen, label = dict(config), "default"
        chosen["label"] = label
        self._record_route(task, label, chosen)
        return chosen

    # ── durable stats (best-effort: routing must never be broken by the DB) ──

    def _stats(self) -> Optional[Stats]:
        from plugins.plugin_storage import plugin_db

        stats = Stats(plugin_db(PLUGIN_DB_NAME))
        stats.ensure_schema()
        return stats

    def _consult_history(self) -> Optional[str]:
        try:
            stats = self._stats()
            if stats is None:
                return None
            return stats.nudge({"quick": None, "deep": None})
        except Exception:
            return None

    def _record_route(self, task: Mapping[str, Any], label: str, route: Mapping[str, Any]) -> None:
        try:
            stats = self._stats()
            if stats is None:
                return
            goal = str(task.get("goal") or "")
            task_hash = hashlib.sha1(goal.encode("utf-8")).hexdigest()[:16]
            stats.record_route(task_hash, label, route.get("provider"), route.get("model"),
                               ts=time.time())
        except Exception:
            return
