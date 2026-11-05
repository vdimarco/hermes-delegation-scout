"""scout_stats tool: schema is arg-free, output is the stats summary as JSON."""

import json

import hermes_yaml as yaml
import pytest

from scout.stats import Stats, PLUGIN_DB_NAME
from scout.stats_tool import build_tool


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home / "os-home"))
    monkeypatch.setenv("HERMES_HOME", str(home))
    (home / "config.yaml").write_text(yaml.safe_dump({"delegation": {}}))
    return home


def test_tool_shape():
    tool = build_tool()
    assert tool["name"] == "scout_stats"
    assert tool["schema"] == {"type": "object", "properties": {}, "required": []}
    assert tool["toolset"] == PLUGIN_DB_NAME


def test_handler_returns_summary_json():
    from plugins.plugin_storage import plugin_db

    stats = Stats(plugin_db(PLUGIN_DB_NAME))
    stats.ensure_schema()
    rid = stats.record_route("h" * 16, "quick", "openrouter", "google/gemini-3-flash-preview")
    stats.record_outcome(rid, "completed")

    out = json.loads(build_tool()["handler"]())
    assert out["routes_total"] == 1
    assert out["per_route"]["quick"]["success_rate"] == 1.0
    assert out["last_decisions"][0]["label"] == "quick"


def test_handler_on_empty_db():
    out = json.loads(build_tool()["handler"]())
    assert out == {"routes_total": 0, "per_route": {}, "last_decisions": []}


def test_scout_stats_accepts_positional_args_dict(monkeypatch, tmp_path):
    """The Hermes tool bridge forwards the arguments dict POSITIONALLY.

    Regression test: scout_stats(**kwargs) failed live with 'takes 0
    positional arguments but 1 was given'.
    """
    from scout import stats_tool
    from plugins import plugin_storage

    import sqlite3

    monkeypatch.setattr(
        plugin_storage, "plugin_db", lambda name: sqlite3.connect(tmp_path / f"{name}.db")
    )
    # Calls the handler exactly as the bridge does: positional dict, kwargs empty.
    out = stats_tool.scout_stats({})
    import json as _json

    parsed = _json.loads(out)
    assert isinstance(parsed, dict)
