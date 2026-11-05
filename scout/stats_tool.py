"""The ``scout_stats`` tool: pretty-printed routing stats from scout's SQLite DB."""

from __future__ import annotations

import json
from typing import Any

from .stats import PLUGIN_DB_NAME, Stats

TOOL_NAME = "scout_stats"

SCHEMA: dict[str, Any] = {"type": "object", "properties": {}, "required": []}

DESCRIPTION = (
    "Show scout's delegation-learning stats: per-route decision counts and success "
    "rates (from outcomes observed on delegate_task) plus the most recent decisions."
)


def scout_stats(**kwargs: Any) -> str:
    """Schema: no arguments. Returns the stats summary as pretty-printed JSON."""
    from plugins.plugin_storage import plugin_db

    stats = Stats(plugin_db(PLUGIN_DB_NAME))
    stats.ensure_schema()
    return json.dumps(stats.summary(), indent=2, sort_keys=True)


def build_tool() -> dict[str, Any]:
    return {
        "name": TOOL_NAME,
        "toolset": PLUGIN_DB_NAME,
        "schema": SCHEMA,
        "handler": scout_stats,
        "description": DESCRIPTION,
        "emoji": "🧭",
    }
