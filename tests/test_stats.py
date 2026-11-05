"""Durable outcome stats on a temp sqlite connection (plugin_db passes its own)."""

import sqlite3

import pytest

from scout.stats import Stats


@pytest.fixture
def stats():
    conn = sqlite3.connect(":memory:")
    s = Stats(conn)
    s.ensure_schema()
    return s


def _route_with_outcomes(stats, label, statuses):
    rid = stats.record_route(f"hash-{label}", label, "p", "m", ts=1.0)
    for i, st in enumerate(statuses):
        stats.record_outcome(rid, st, ts=float(i))
    return rid


def test_schema_is_idempotent():
    conn = sqlite3.connect(":memory:")
    Stats(conn).ensure_schema()
    Stats(conn).ensure_schema()
    # second ensure did not drop data
    conn.execute("INSERT INTO routes(task_hash, label, provider, model, ts) VALUES ('h','quick','p','m',1.0)")
    conn.execute("INSERT INTO outcomes(route_id, status, error, ts) VALUES (1,'completed',NULL,1.0)")
    Stats(conn).ensure_schema()
    assert conn.execute("SELECT COUNT(*) FROM routes").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0] == 1


def test_record_route_returns_id_and_links_outcome(stats):
    rid = stats.record_route("abc123", "deep", "nous", "moonshotai/kimi-k3")
    assert isinstance(rid, int) and rid > 0
    stats.record_outcome(rid, "completed")
    row = stats.conn.execute(
        "SELECT r.label, o.status FROM outcomes o JOIN routes r ON r.id=o.route_id"
    ).fetchone()
    assert row == ("deep", "completed")


def test_record_outcome_for_route_matches_latest(stats):
    stats.record_route("h", "quick", "p", "m1")
    later = stats.record_route("h", "quick", "p", "m2")
    assert stats.record_outcome_for_route(task_hash="h", label="quick", status="completed")
    got = stats.conn.execute("SELECT route_id, status FROM outcomes").fetchone()
    assert got == (later, "completed")


def test_record_outcome_for_route_missing_route(stats):
    assert stats.record_outcome_for_route(task_hash="nope", label="quick", status="completed") is False


def test_nudge_below_min_samples_never_fires(stats):
    # 4 samples (< 5): no nudging no matter the rate gap.
    _route_with_outcomes(stats, "quick", ["completed"] * 4)
    _route_with_outcomes(stats, "deep", ["error"] * 4)
    assert stats.nudge({"quick": None, "deep": None}) is None


def test_nudge_at_exactly_five_samples(stats):
    # boundary: exactly min_samples qualifies.
    _route_with_outcomes(stats, "quick", ["completed"] * 5)
    _route_with_outcomes(stats, "deep", ["error"] * 5)
    assert stats.nudge({"quick": None, "deep": None}) == "quick"


def test_nudge_requires_margin(stats):
    # quick 4/5 (0.8), deep 3/5 (0.6): gap 0.2 >= 0.15 → nudge; shrink the gap → None.
    _route_with_outcomes(stats, "quick", ["completed"] * 4 + ["error"])
    _route_with_outcomes(stats, "deep", ["completed"] * 3 + ["error"] * 2)
    assert stats.nudge({"quick": None, "deep": None}) == "quick"
    s2 = Stats(sqlite3.connect(":memory:"))
    s2.ensure_schema()
    _route_with_outcomes(s2, "quick", ["completed"] * 4 + ["error"])
    _route_with_outcomes(s2, "deep", ["completed"] * 3 + ["error"] * 2)
    assert s2.nudge({"quick": None, "deep": None}, margin=0.25) is None


def test_nudge_needs_two_qualified_candidates(stats):
    _route_with_outcomes(stats, "quick", ["completed"] * 6)
    _route_with_outcomes(stats, "deep", ["error"] * 2)  # deep has too few samples to compare
    assert stats.nudge({"quick": None, "deep": None}) is None


def test_summary_shape(stats):
    _route_with_outcomes(stats, "quick", ["completed"] * 2 + ["error"])
    _route_with_outcomes(stats, "deep", ["completed"])
    summary = stats.summary()
    assert summary["routes_total"] == 2
    assert summary["per_route"]["quick"]["samples"] == 3
    assert summary["per_route"]["quick"]["successes"] == 2
    assert abs(summary["per_route"]["quick"]["success_rate"] - 2 / 3) < 1e-6
    assert summary["per_route"]["deep"]["success_rate"] == 1.0
    assert len(summary["last_decisions"]) == 2
    assert set(summary["last_decisions"][0]) == {"task_hash", "label", "provider", "model", "ts", "status"}
    # newest first
    assert summary["last_decisions"][0]["label"] == "deep"
