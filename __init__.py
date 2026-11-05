"""delegation-scout — learning delegation backend.

Routes every ``delegate_task`` task by deterministic task-shape heuristics, nudged by
recorded outcomes in this plugin's durable SQLite DB. Registered via
``ctx.register_delegation_provider()``; the backend name is ``scout``
(``delegation.backend: scout``, settings under ``delegation.backends.scout``).
"""

from .scout.provider import ScoutProvider


def register(ctx):
    ctx.register_delegation_provider(ScoutProvider())
