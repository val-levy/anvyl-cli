"""Registry + storage tests."""

import json

from anvyl.registry import PluginRegistry, SkillRegistry
from anvyl.storage import (
    bundled_data_dir,
    ensure_data_dir,
    resolve_data_dir,
    save_session,
)


def test_bundled_data_exists():
    data = bundled_data_dir()
    assert (data / "skills" / "toy-backoff" / "SKILL.md").exists()
    assert (data / "skills" / "wifi-csi" / "SKILL.md").exists()
    assert (data / "plugins" / "wifi-csi" / "manifest.json").exists()


def test_ensure_data_dir_seeds_examples(tmp_path):
    data_dir = ensure_data_dir(tmp_path / "anvyl-home")
    assert (data_dir / "skills" / "toy-backoff" / "SKILL.md").exists()
    assert (data_dir / "plugins" / "wifi-csi" / "manifest.json").exists()
    assert (data_dir / "sessions").is_dir()


def test_resolve_data_dir_precedence(tmp_path, monkeypatch):
    explicit = tmp_path / "explicit"
    assert resolve_data_dir(explicit) == explicit
    monkeypatch.setenv("ANVYL_HOME", str(tmp_path / "from-env"))
    assert resolve_data_dir() == tmp_path / "from-env"
    monkeypatch.delenv("ANVYL_HOME")
    assert resolve_data_dir().name == ".anvyl"


def test_plugin_registry_lists_and_gates(tmp_path):
    data_dir = ensure_data_dir(tmp_path / "home")
    registry = PluginRegistry(data_dir / "plugins")
    ids = {p["id"] for p in registry.list()}
    assert {"wifi-csi", "gh-review"} <= ids

    state = {"mode": "learn", "level": 1, "human_attempt": "Loop, try, sleep, re-raise."}
    ok, _msg = registry.load("wifi-csi", state)
    assert ok is True
    assert registry.allowed_tools(state) == ["csi-sniff", "packet-replay"]
    ok, _msg = registry.unload("wifi-csi")
    assert ok is True
    assert registry.allowed_tools(state) == []


def test_plugin_install_stub(tmp_path):
    data_dir = ensure_data_dir(tmp_path / "home")
    registry = PluginRegistry(data_dir / "plugins")
    assert "already present" in registry.install("wifi-csi")
    assert "not implemented yet" in registry.install("something-new")


def test_skill_registry_load_unload(tmp_path):
    data_dir = ensure_data_dir(tmp_path / "home")
    registry = SkillRegistry(data_dir / "skills")
    ids = {s["id"] for s in registry.list()}
    assert {"toy-backoff", "wifi-csi"} <= ids
    ok, _msg = registry.load("wifi-csi")
    assert ok is True
    assert "ESP32" in registry.loaded_text()
    ok, _msg = registry.load("nope")
    assert ok is False
    ok, _msg = registry.unload("wifi-csi")
    assert ok is True


def test_save_session_writes_json(tmp_path):
    state = {
        "session_id": "s-test",
        "task_id": "toy-backoff",
        "mode": "learn",
        "level": 1,
        "ownership_score": 1.0,
        "verification": {"passed": True, "checks": []},
    }
    path = save_session(state, tmp_path / "sessions")
    assert path.exists()
    record = json.loads(path.read_text())
    assert record["session_id"] == "s-test"
    assert record["verification"]["passed"] is True
