"""Durable routing/outcome stats for scout, on ``plugins.plugin_storage.plugin_db``.

The connection comes from the caller so the same class runs on the real WAL plugin DB
and on an in-memory test DB. Every method is dependency-free (stdlib sqlite3 only).

Tables:
    routes(id INTEGER PK, task_hash TEXT, label TEXT, provider TEXT, model TEXT, ts REAL)
    outcomes(route_id INTEGER, status TEXT, error TEXT, ts REAL)
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Optional

#: The plugin's manifest name — the plugin_db/plugin_data_dir key.
PLUGIN_DB_NAME = "delegation-scout"

SUCCESS_STATUS = "completed"


class Stats:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def ensure_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS routes(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_hash TEXT,
                label TEXT,
                provider TEXT,
                model TEXT,
                ts REAL);
            CREATE INDEX IF NOT EXISTS idx_routes_label ON routes(label);
            CREATE TABLE IF NOT EXISTS outcomes(
                route_id INTEGER,
                status TEXT,
                error TEXT,
                ts REAL);
            """
        )
        self.conn.commit()

    def record_route(self, task_hash: str, label: str, provider: Optional[str],
                     model: Optional[str], ts: Optional[float] = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO routes(task_hash, label, provider, model, ts) VALUES (?,?,?,?,?)",
            (task_hash, label, provider, model, time.time() if ts is None else ts),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def record_outcome(self, route_id: int, status: str, error: Optional[str] = None,
                       ts: Optional[float] = None) -> None:
        self.conn.execute(
            "INSERT INTO outcomes(route_id, status, error, ts) VALUES (?,?,?,?)",
            (route_id, status, error, time.time() if ts is None else ts),
        )
        self.conn.commit()

    def record_outcome_for_route(self, task_hash: Optional[str] = None,
                                 label: Optional[str] = None, status: str = SUCCESS_STATUS,
                                 error: Optional[str] = None,
                                 ts: Optional[float] = None) -> bool:
        """Attach an outcome to the newest recorded route matching task_hash + label.

        The observation seam only sees the tool args/result, so it re-derives the
        deterministic task_hash instead of threading a route_id through core. Returns
        False (records nothing) when no matching route exists.
        """
        row = None
        if task_hash and label:
            row = self.conn.execute(
                "SELECT id FROM routes WHERE task_hash=? AND label=? ORDER BY id DESC LIMIT 1",
                (task_hash, label),
            ).fetchone()
        if row is None and label:
            row = self.conn.execute(
                "SELECT id FROM routes WHERE label=? ORDER BY id DESC LIMIT 1", (label,)
            ).fetchone()
        if row is None:
            return False
        self.record_outcome(int(row[0]), status, error, ts)
        return True

    def _rates(self) -> dict[str, dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT r.label, COUNT(*) AS n, "
            "SUM(CASE WHEN o.status=? THEN 1 ELSE 0 END) AS ok "
            "FROM outcomes o JOIN routes r ON r.id = o.route_id GROUP BY r.label",
            (SUCCESS_STATUS,),
        ).fetchall()
        return {
            label: {"samples": int(n), "successes": int(ok or 0), "rate": (ok or 0) / n}
            for label, n, ok in rows
        }

    def nudge(self, candidate_classes, min_samples: int = 5,
              margin: float = 0.15) -> Optional[str]:
        """The candidate class with enough samples that outperforms every other qualified
        candidate by >= margin success rate, else None (never nudges on thin evidence).
        """
        candidates = set(candidate_classes or {})
        rates = self._rates()
        qualified = {
            c: r for c, r in rates.items() if c in candidates and r["samples"] >= min_samples
        }
        if len(qualified) < 2:
            return None
        best = max(qualified, key=lambda c: qualified[c]["rate"])
        for cls, r in qualified.items():
            if cls != best and qualified[best]["rate"] - r["rate"] < margin:
                return None
        return best

    def summary(self, last: int = 10) -> dict[str, Any]:
        counts = {
            label: int(n)
            for label, n in self.conn.execute(
                "SELECT label, COUNT(*) FROM routes GROUP BY label"
            ).fetchall()
        }
        rates = self._rates()
        per_route: dict[str, dict[str, Any]] = {}
        for label, n in counts.items():
            r = rates.get(label, {"samples": 0, "successes": 0, "rate": 0.0})
            per_route[label] = {
                "routes": n,
                "samples": r["samples"],
                "successes": r["successes"],
                "success_rate": r["rate"],
            }
        recent = [
            {"task_hash": h, "label": label, "provider": provider, "model": model,
             "ts": ts, "status": status}
            for h, label, provider, model, ts, status in self.conn.execute(
                "SELECT r.task_hash, r.label, r.provider, r.model, r.ts, o.status "
                "FROM routes r LEFT JOIN outcomes o ON o.route_id = r.id "
                "ORDER BY r.id DESC LIMIT ?", (last,),
            ).fetchall()
        ]
        return {
            "routes_total": sum(counts.values()),
            "per_route": per_route,
            "last_decisions": recent,
        }
