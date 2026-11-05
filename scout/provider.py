"""The scout delegation provider (``delegation.backend: scout``).

Routes each ``delegate_task`` task by task shape (``scout/features.py``), nudged by
recorded outcomes (``scout/stats.py``). Backend settings live under
``delegation.backends.scout`` — never beside core ``delegation`` keys.

Full routing logic lands in the provider task; this is the Task 1 scaffold.
"""

from __future__ import annotations

from typing import Any, Mapping

from agent.delegation_provider import DelegationProvider


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

    def route_task(self, task: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
        return dict(config)
