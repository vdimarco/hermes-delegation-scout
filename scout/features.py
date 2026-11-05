"""Deterministic task-shape scoring for the scout router.

Pure functions: no clock, no network, no randomness, no config — the same task dict
always scores the same (prompt-cache contract). History may nudge the final class, but
that lives in the provider's ``route_task``, never here.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

#: +2 toward deep when a hard-work keyword appears in ``goal`` + ``context``.
DEEP_SIGNAL = re.compile(
    r"\b(review|analy[sz]e|architect|design|refactor|debug|migrate|multi-step)\b",
    re.IGNORECASE,
)
#: +2 toward quick when a cheap-work keyword appears in ``goal`` + ``context``.
QUICK_SIGNAL = re.compile(
    r"\b(lookup|summari[sz]e|fetch|check|quick|simple|one-liner|trivial)\b",
    re.IGNORECASE,
)

LONG_TASK_WORDS = 120   # > this: +1 deep
SHORT_TASK_WORDS = 25   # < this: +1 quick
THRESHOLD = 2           # |deep - quick| must reach this to classify away from "default"


def score_task(task: Mapping[str, Any]) -> dict[str, Any]:
    """Score one ``delegate_task`` task: ``{"class", "score", "signals"}``.

    ``signals`` lists the fired heuristic terms (the matched keyword, ``images``,
    ``long-text:<n>`` / ``short-text:<n>``) so stats/summary reads stay explainable.
    """
    goal = task.get("goal")
    context = task.get("context")
    text = " ".join(part for part in (str(goal or ""), str(context or "")) if part).strip()
    words = len(text.split())

    deep = quick = 0
    signals: list[str] = []

    match = DEEP_SIGNAL.search(text)
    if match:
        deep += 2
        signals.append(f"deep-keyword:{match.group(0).lower()}")
    match = QUICK_SIGNAL.search(text)
    if match:
        quick += 2
        signals.append(f"quick-keyword:{match.group(0).lower()}")
    if task.get("images"):
        deep += 1
        signals.append("images")
    if words > LONG_TASK_WORDS:
        deep += 1
        signals.append(f"long-text:{words}")
    if words < SHORT_TASK_WORDS:
        quick += 1
        signals.append(f"short-text:{words}")

    score = deep - quick
    if score >= THRESHOLD:
        class_ = "deep"
    elif score <= -THRESHOLD:
        class_ = "quick"
    else:
        class_ = "default"
    return {"class": class_, "score": score, "signals": signals}
