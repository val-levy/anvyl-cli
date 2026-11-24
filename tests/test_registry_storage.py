"""Registry + storage tests."""

import json
import os
import time
from pathlib import Path

import pytest

from anvyl.registry import PluginRegistry, SkillRegistry
from anvyl.state import initial_real_state
from anvyl.storage import (
    bundled_data_dir,
    cleanup_stale_work,
    ensure_data_dir,
    reset_data,
    resolve_data_dir,
    save_diff,
    save_session,
    work_dir_for,
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


def _real_state(**extra):
    st = dict(
        initial_real_state("s-real", "fix bug", "/tmp/f", "personal", "learn", 1, False, "/tmp/w")
    )
    st.update(extra)
    return st


def test_initial_real_state_defaults():
    st = initial_real_state("s1", "t", "/f", "professional", "ship", 2, True, "/w")
    assert st["real"] is True
    assert st["gate_passed"] is False
    assert st["gate_blocked"] is False
    assert st["changes"] == {"files": 0, "added": 0, "removed": 0}
    assert st["profile"] == "professional" and st["work_dir"] == "/w"


def test_real_session_json_has_schema_version_and_no_code_fields(tmp_path):
    st = _real_state(solution_code="SECRET", verification={"x": 1}, answers=["my words"])
    record = json.loads(save_session(st, tmp_path).read_text())
    assert record["schema_version"] == 2
    assert "solution_code" not in record and "verification" not in record
    assert record["answers"] == ["my words"]
    assert record["changes"] == {"files": 0, "added": 0, "removed": 0}
    assert "SECRET" not in json.dumps(record)


def test_tutorial_session_still_saves_solution_code(tmp_path):
    st = {"session_id": "s-t", "solution_code": "def f(): ...", "verification": {"passed": True}}
    record = json.loads(save_session(st, tmp_path).read_text())
    assert record["schema_version"] == 2
    assert record["solution_code"] == "def f(): ..."
    assert "ticket" not in record


def test_work_dir_for_and_traversal(tmp_path):
    assert work_dir_for(tmp_path, "s-1") == tmp_path / "work" / "s-1"
    for bad in ("", "..", ".", "../x", "a/b", "a\\b", "/abs"):
        with pytest.raises(ValueError):
            work_dir_for(tmp_path, bad)
        with pytest.raises(ValueError):
            save_diff(tmp_path / "sessions", bad, "x")


def test_save_diff_writes_file(tmp_path):
    p = save_diff(tmp_path / "sessions", "s-1", "diff text")
    assert p == tmp_path / "sessions" / "s-1.diff" and p.read_text() == "diff text"


def test_cleanup_stale_work_removes_only_old_dirs(tmp_path):
    work = tmp_path / "work"
    old, new = work / "old", work / "new"
    old.mkdir(parents=True)
    new.mkdir()
    (work / "file").write_text("x")
    outside = tmp_path / "outside"
    outside.mkdir()
    (work / "link").symlink_to(outside)
    ancient = time.time() - 30 * 86400
    for p in (old, work / "link"):
        os.utime(p, (ancient, ancient), follow_symlinks=False)
    os.utime(work / "file", (ancient, ancient))
    assert cleanup_stale_work(tmp_path) == 1
    assert not old.exists() and new.exists()
    assert (work / "file").exists() and (work / "link").is_symlink() and outside.exists()


def test_cleanup_stale_work_missing_dir(tmp_path):
    assert cleanup_stale_work(tmp_path) == 0


def test_reset_data_clears_everything(tmp_path):
    (tmp_path / "sessions").mkdir()
    (tmp_path / "sessions" / "a.json").write_text("{}")
    (tmp_path / "config.json").write_text("{}")
    reset_data(tmp_path)
    assert tmp_path.is_dir() and list(tmp_path.iterdir()) == []


def test_reset_data_never_follows_symlinks(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    (target / "keep.txt").write_text("keep")
    data = tmp_path / "data"
    data.mkdir()
    (data / "link").symlink_to(target)
    reset_data(data)
    assert list(data.iterdir()) == []
    assert (target / "keep.txt").read_text() == "keep"


def test_reset_data_refuses_dangerous_dirs(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "f").write_text("x")
    link = tmp_path / "link"
    link.symlink_to(real)
    for bad in (Path("/"), Path.home(), Path(""), tmp_path / "missing", link, real / "f"):
        with pytest.raises(ValueError):
            reset_data(bad)
    assert (real / "f").exists()
