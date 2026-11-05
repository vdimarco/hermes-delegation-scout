"""End-to-end: the real discovery path against a temp HERMES_HOME whose config.yaml
enables the plugin and selects ``delegation.backend: scout`` — mirrors the Hermes
repo's ``tests/tools/test_delegation_backends.py`` style (real PluginManager, real
delegate_task; only child construction/run are stubbed)."""

import json
import types

import hermes_yaml as yaml
import pytest

from pathlib import Path

from hermes_cli import plugins as plugins_mod
from hermes_cli.plugins import PluginManager

REPO_ROOT = Path(__file__).resolve().parents[1]
HERMES_PLUGINS = Path(plugins_mod.__file__).resolve().parents[1] / "plugins"

ROUTES = {
    "quick": {"provider": "openrouter", "model": "quick-model", "base_url": "http://127.0.0.1:9/v1"},
    "deep": {"provider": "nous", "model": "deep-model", "base_url": "http://127.0.0.1:9/v1"},
}

DEEP_GOAL = ("Please review the billing module architecture and document the migration "
             "design decisions for the whole team so everyone understands the plan "
             "across every service and pipeline")


def _home(tmp_path, monkeypatch, delegation: dict, copy_plugin=True):
    home = tmp_path / ".hermes"
    if copy_plugin:
        plugin_dir = home / "plugins" / "delegation-scout"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.yaml").write_text(
            (REPO_ROOT / "plugin.yaml").read_text(encoding="utf-8"), encoding="utf-8")
        (plugin_dir / "__init__.py").write_text(
            (REPO_ROOT / "__init__.py").read_text(encoding="utf-8"), encoding="utf-8")
        (plugin_dir / "scout").mkdir()
        for py in (REPO_ROOT / "scout").glob("*.py"):
            (plugin_dir / "scout" / py.name).write_text(py.read_text(encoding="utf-8"), encoding="utf-8")
    (home / "config.yaml").write_text(yaml.safe_dump(
        {"plugins": {"enabled": ["delegation-scout"]}, "delegation": delegation}), encoding="utf-8")
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "delegation").symlink_to(HERMES_PLUGINS / "delegation", target_is_directory=True)
    monkeypatch.setenv("HOME", str(home / "os-home"))
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(plugins_mod, "get_bundled_plugins_dir", lambda: bundled)
    manager = PluginManager()
    manager.discover_and_load()
    return home, manager


def _definition():
    from tools.registry import registry
    return registry.get_definitions({"delegate_task"})[0]["function"]


@pytest.fixture
def recorded(monkeypatch):
    from tools import delegate_tool as dt

    built = []

    def build(**kwargs):
        built.append(kwargs)
        return types.SimpleNamespace(tool_progress_callback=None, model=kwargs.get("model"))

    monkeypatch.setattr(dt, "_build_child_preserving_parent_tools", build)
    monkeypatch.setattr(dt, "_run_single_child", lambda task_index, goal, child=None, parent_agent=None, **kw: {
        "task_index": task_index, "status": "completed", "summary": "ok", "api_calls": 1, "duration_seconds": 0})
    return built


def _parent(session_id="root"):
    return types.SimpleNamespace(session_id=session_id, model="parent-model", provider="openrouter",
                                 tool_progress_callback=None, _delegate_spinner=None, request_overrides={},
                                 _safe_print=lambda line: None)


def _delegation(routes=ROUTES):
    return {"backend": "scout", "backends": {"scout": {"routes": dict(routes)}}}


def test_schema_carries_mode_and_is_byte_stable(tmp_path, monkeypatch, recorded):
    _, manager = _home(tmp_path, monkeypatch, _delegation())
    try:
        from tools.delegate_tool_config import _load_config
        from agent.delegation_registry import get_active_provider

        assert get_active_provider(_load_config()).name == "scout"
        definition = _definition()
        mode = definition["parameters"]["properties"]["tasks"]["items"]["properties"]["mode"]
        assert mode["enum"] == ["auto", "quick", "deep"]
        assert definition["description"].endswith("omit it to let heuristics decide.")
        assert json.dumps(_definition()) == json.dumps(definition)  # byte-stable
    finally:
        manager.unload()


def test_each_task_routes_by_shape_or_mode_and_refusals_are_per_task(tmp_path, monkeypatch, recorded):
    _, manager = _home(tmp_path, monkeypatch, _delegation())
    try:
        from tools.delegate_tool import delegate_task
        from tools.delegate_tool_config import _load_config
        from tools.delegate_tool_routes import resolve_task_routes

        task_list = [
            {"goal": "quick lookup of the docs"},                       # heuristic quick
            {"goal": DEEP_GOAL},                                        # heuristic deep
            {"goal": "a neutral status note for the team about this"},  # no strong signal
            {"goal": "quick lookup of the docs", "mode": "deep"},       # mode wins
            {"goal": "this task has a typo mode", "mode": "quantum"},   # refused by core enum check
        ]
        routes, err = resolve_task_routes(task_list, _load_config(), _parent())
        assert err is None  # call-level error only when EVERY task is refused
        assert [r.label for r in routes] == ["quick", "deep", "default", "deep", None]

        out = json.loads(delegate_task(tasks=task_list, parent_agent=_parent()))
        quick, deep, plain, forced, refused = out["results"]
        assert [r["status"] for r in out["results"]] == ["completed"] * 4 + ["error"]
        assert refused["route"] == {"backend": "scout", "refused": True}
        assert "must be one of auto, quick, deep" in refused["error"]
        assert [b["model"] for b in recorded] == ["quick-model", "deep-model", None, "deep-model"]
    finally:
        manager.unload()


def test_missing_route_class_inherits_the_default_route(tmp_path, monkeypatch, recorded):
    _, manager = _home(tmp_path, monkeypatch, _delegation({"deep": ROUTES["deep"]}))
    try:
        from tools.delegate_tool import delegate_task

        out = json.loads(delegate_task(tasks=[{"goal": "quick lookup of the docs"}],
                                       parent_agent=_parent()))
        assert out["results"][0]["status"] == "completed"
        assert recorded[0]["model"] is None and recorded[0]["override_provider"] is None
    finally:
        manager.unload()


def test_empty_routes_fail_closed_with_the_fix_named(tmp_path, monkeypatch, recorded):
    _, manager = _home(tmp_path, monkeypatch, {"backend": "scout"})
    try:
        from agent.delegation_registry import backend_status

        provider, reason = backend_status("scout")
        assert provider is not None  # registered but not runnable
        assert "unavailable" in reason and "delegation.backend default" in reason
        from tools.delegate_tool import delegate_task

        out = json.loads(delegate_task(tasks=[{"goal": "anything"}], parent_agent=_parent()))
        assert "error" in out and recorded == []
    finally:
        manager.unload()
