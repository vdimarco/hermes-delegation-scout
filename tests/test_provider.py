"""ScoutProvider routing contract: mode honored → heuristics → history nudge → routes,
with per-task refusals and a fail-closed is_available (no network anywhere)."""

import hashlib
import json
import sqlite3

import hermes_yaml as yaml
import pytest

from agent.delegation_provider import DelegationRouteError

from scout.provider import ScoutProvider

ROUTES = {
    "quick": {"provider": "openrouter", "model": "google/gemini-3-flash-preview"},
    "deep": {"provider": "nous", "model": "moonshotai/kimi-k3"},
}

DEEP_GOAL = ("Please review the billing module architecture and document the migration "
             "design decisions for the whole team so everyone understands the plan "
             "across every service and pipeline")


def _config(routes=ROUTES):
    return {"backend": "scout", "backends": {"scout": {"routes": dict(routes)}}}


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    """plugin_db()/load_config() must never touch the real profile during tests."""
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home / "os-home"))
    monkeypatch.setenv("HERMES_HOME", str(home))
    (home / "config.yaml").write_text(yaml.safe_dump({"delegation": _config()}))
    return home


def test_task_parameters_and_description_are_byte_stable():
    provider = ScoutProvider()
    assert provider.name == "scout"
    assert json.dumps(provider.task_parameters(_config())) == json.dumps(provider.task_parameters(_config()))
    params = provider.task_parameters(_config())
    assert params["mode"]["enum"] == ["auto", "quick", "deep"]
    assert provider.description(_config()) == provider.description(_config())
    assert provider.description(_config())


def test_mode_is_honored_first():
    provider = ScoutProvider()
    route = provider.route_task({"goal": DEEP_GOAL, "mode": "quick"}, _config())
    assert route["model"] == "google/gemini-3-flash-preview" and route["label"] == "quick"
    route = provider.route_task({"goal": "quick lookup", "mode": "deep"}, _config())
    assert route["model"] == "moonshotai/kimi-k3" and route["label"] == "deep"


def test_unknown_mode_is_refused_defensively():
    # core's enum check refuses first, but route_task must never co-route a bad value.
    provider = ScoutProvider()
    with pytest.raises(DelegationRouteError, match="Unknown mode 'quantum'"):
        provider.route_task({"goal": "x", "mode": "quantum"}, _config())


def test_auto_uses_heuristics():
    provider = ScoutProvider()
    route = provider.route_task({"goal": DEEP_GOAL}, _config())
    assert route["label"] == "deep" and route["model"] == "moonshotai/kimi-k3"
    route = provider.route_task({"goal": "quick lookup of the docs"}, _config())
    assert route["label"] == "quick" and route["model"] == "google/gemini-3-flash-preview"


def test_missing_route_class_inherits_default_config():
    provider = ScoutProvider()
    cfg = _config(routes={"deep": ROUTES["deep"]})  # no "quick" key
    route = provider.route_task({"goal": "quick lookup of the docs"}, cfg)
    assert route["label"] == "default" and "model" not in route
    # explicit mode into a missing class also inherits instead of crashing
    route = provider.route_task({"goal": "x", "mode": "quick"}, cfg)
    assert route["label"] == "default"


def test_history_nudges_to_better_performer(home):
    from plugins.plugin_storage import plugin_db
    from scout.stats import Stats, PLUGIN_DB_NAME

    stats = Stats(plugin_db(PLUGIN_DB_NAME))
    stats.ensure_schema()
    for status, label in [("completed", "quick")] * 5 + [("error", "deep")] * 5:
        rid = stats.record_route("h", label, "p", "m")
        stats.record_outcome(rid, status)

    provider = ScoutProvider()
    route = provider.route_task({"goal": DEEP_GOAL}, _config())  # heuristics say deep
    assert route["label"] == "quick"  # history nudged away from deep's 0% success rate


def test_no_nudge_below_five_samples(home):
    from plugins.plugin_storage import plugin_db
    from scout.stats import Stats, PLUGIN_DB_NAME

    stats = Stats(plugin_db(PLUGIN_DB_NAME))
    stats.ensure_schema()
    for status, label in [("completed", "quick")] * 4 + [("error", "deep")] * 4:
        rid = stats.record_route("h", label, "p", "m")
        stats.record_outcome(rid, status)

    provider = ScoutProvider()
    assert provider.route_task({"goal": DEEP_GOAL}, _config())["label"] == "deep"


def test_route_is_recorded_with_deterministic_hash(home):
    from plugins.plugin_storage import plugin_db
    from scout.stats import PLUGIN_DB_NAME

    provider = ScoutProvider()
    provider.route_task({"goal": DEEP_GOAL}, _config())
    row = plugin_db(PLUGIN_DB_NAME).execute(
        "SELECT task_hash, label, provider, model FROM routes"
    ).fetchone()
    assert row == (hashlib.sha1(DEEP_GOAL.encode("utf-8")).hexdigest()[:16],
                   "deep", "nous", "moonshotai/kimi-k3")


def test_stats_failure_is_swallowed(monkeypatch):
    provider = ScoutProvider()
    monkeypatch.setattr(ScoutProvider, "_stats", lambda self: (_ for _ in ()).throw(RuntimeError("db gone")))
    route = provider.route_task({"goal": DEEP_GOAL}, _config())
    assert route["label"] == "deep" and route["model"] == "moonshotai/kimi-k3"


def test_is_available_requires_routes_config(home):
    provider = ScoutProvider()
    assert provider.is_available() is True
    (home / "config.yaml").write_text(yaml.safe_dump({"delegation": {"backend": "scout"}}))
    assert provider.is_available() is False
