"""Outcome capture through the public post_tool_call observer hook."""

import hashlib
import json
import sqlite3

import hermes_yaml as yaml
import pytest

from scout import observe
from scout.provider import ScoutProvider
from scout.stats import PLUGIN_DB_NAME


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home / "os-home"))
    monkeypatch.setenv("HERMES_HOME", str(home))
    (home / "config.yaml").write_text(yaml.safe_dump({"delegation": {}}))
    return home


GOAL = ("Please review the billing module architecture and document the migration "
        "design decisions for the whole team so everyone understands the plan "
        "across every service and pipeline")
TASK_HASH = hashlib.sha1(GOAL.encode("utf-8")).hexdigest()[:16]


def _seed_route(status="completed"):
    provider = ScoutProvider()
    cfg = {"backends": {"scout": {"routes": {"deep": {"provider": "nous", "model": "m"}}}}}
    route = provider.route_task({"goal": GOAL}, cfg)
    assert route["label"] == "deep"
    return route


def _fire(payload, args=None):
    observe.observe_delegate_task(
        tool_name="delegate_task",
        args=args or {"tasks": [{"goal": GOAL}]},
        result=json.dumps(payload) if not isinstance(payload, str) else payload,
    )


def _outcomes():
    from plugins.plugin_storage import plugin_db
    return plugin_db(PLUGIN_DB_NAME).execute(
        "SELECT status FROM outcomes ORDER BY rowid"
    ).fetchall()


def test_finished_scout_result_is_recorded():
    _seed_route()
    _fire({"results": [{"task_index": 0, "status": "completed",
                        "route": {"backend": "scout", "label": "deep", "model": "m"}}]})
    assert _outcomes() == [("completed",)]


def test_error_results_and_other_backends():
    _seed_route()
    _fire({"results": [
        {"task_index": 0, "status": "completed",
         "route": {"backend": "scout", "label": "deep"}},
    ]})
    # a second task routed by another backend must not be recorded
    _fire({"results": [
        {"task_index": 0, "status": "completed", "route": {"backend": "default"}},
        {"task_index": 0, "status": "error", "error": "boom",
         "route": {"backend": "scout", "label": "deep"}},
    ]})
    assert _outcomes() == [("completed",), ("error",)]


def test_dispatch_payload_and_junk_are_ignored_and_never_raise():
    _fire({"dispatched": [{"task_index": 0, "route": {"backend": "scout"}}]})
    _fire({"results": [{"task_index": 0, "status": "running",
                        "route": {"backend": "scout", "label": "deep"}}]})
    _fire("not json at all")
    observe.observe_delegate_task(tool_name="terminal", args={}, result="{}")
    observe.observe_delegate_task(tool_name="delegate_task", args=None, result=None)
    assert _outcomes() == []


def test_registered_through_the_real_hook_seam(tmp_path, monkeypatch):
    """PluginManager discovery → register_hook → lifecycle.invoke_hook (the seam)."""
    from hermes_cli import plugins as plugins_mod
    from hermes_cli.plugins import PluginManager

    home = tmp_path / ".hermes"
    plugin_dir = home / "plugins" / "delegation-scout"
    plugin_dir.mkdir(parents=True)
    from pathlib import Path
    repo = Path(__file__).resolve().parents[1]
    (plugin_dir / "plugin.yaml").write_text((repo / "plugin.yaml").read_text(), encoding="utf-8")
    (plugin_dir / "__init__.py").write_text((repo / "__init__.py").read_text(), encoding="utf-8")
    (plugin_dir / "scout").mkdir()
    for py in (repo / "scout").glob("*.py"):
        (plugin_dir / "scout" / py.name).write_text(py.read_text(), encoding="utf-8")
    (home / "config.yaml").write_text(yaml.safe_dump(
        {"plugins": {"enabled": ["delegation-scout"]}, "delegation": {}}), encoding="utf-8")
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "delegation").symlink_to(
        Path(plugins_mod.__file__).resolve().parents[1] / "plugins" / "delegation",
        target_is_directory=True)
    monkeypatch.setenv("HOME", str(tmp_path / "os-home"))
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(plugins_mod, "get_bundled_plugins_dir", lambda: bundled)
    manager = PluginManager()
    manager.discover_and_load()
    try:
        from hermes_cli.lifecycle import has_hook, invoke_hook

        assert has_hook("post_tool_call")
        _seed_route()
        invoke_hook("post_tool_call", tool_name="delegate_task",
                    args={"tasks": [{"goal": GOAL}]},
                    result=json.dumps({"results": [{"task_index": 0, "status": "completed",
                                                    "route": {"backend": "scout", "label": "deep"}}]}))
        assert _outcomes() == [("completed",)]
    finally:
        manager.unload()
