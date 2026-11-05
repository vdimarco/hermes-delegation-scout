"""delegation-scout — learning delegation backend.

Routes every ``delegate_task`` task by deterministic task-shape heuristics, nudged by
recorded outcomes in this plugin's durable SQLite DB. Registered via
``ctx.register_delegation_provider()``; the backend name is ``scout``
(``delegation.backend: scout``, settings under ``delegation.backends.scout``).
"""

try:
    from .scout.provider import ScoutProvider
except ImportError:  # plain-module import (pytest collects this dir as a package root)
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from scout.provider import ScoutProvider


def register(ctx):
    ctx.register_delegation_provider(ScoutProvider())
    from .scout import observe  # import inside register: keeps probe/loading cheap

    ctx.register_hook("post_tool_call", observe.observe_delegate_task)
