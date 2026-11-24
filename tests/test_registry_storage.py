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


def test_real_session_drops_snippets_attempt_code_and_event_blobs(tmp_path):
    fence = "```python\nSECRET_CODE = 1\n```"
    st = _real_state(
        shown_snippets=["SNIPPET_TEXT"],
        human_attempt=f"my idea {fence} done",
        attempts=[f"try {fence}"],
        events=[
            "started",
            "+ DIFF_LINE " + "x" * 80,
            {"n": 1, "s": "ok", "blob": [1], "long": "y" * 50},
        ],
    )
    text = save_session(st, tmp_path).read_text()
    record = json.loads(text)
    for secret in ("SNIPPET_TEXT", "SECRET_CODE", "DIFF_LINE", "y" * 50):
        assert secret not in text
    assert record["shown_snippets_count"] == 1 and "shown_snippets" not in record
    assert "my idea" in record["human_attempt"]
    assert record["events"] == ["started", {"n": 1, "s": "ok"}]


def test_tutorial_session_keeps_attempts_and_events(tmp_path):
    fence = "```python\nx = 1\n```"
    st = {"session_id": "s-t", "human_attempt": fence, "events": ["e" * 80]}
    record = json.loads(save_session(st, tmp_path).read_text())
    assert record["human_attempt"] == fence and record["events"] == ["e" * 80]


def test_save_session_rejects_traversal_id(tmp_path):
    with pytest.raises(ValueError):
        save_session({"session_id": "../x"}, tmp_path / "sessions")


def test_reset_data_refuses_home_ancestor_and_relative_allows_inside_home(tmp_path, monkeypatch):
    home = tmp_path / "Users" / "me"
    home.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    (tmp_path / "Users" / "other.txt").write_text("x")
    with pytest.raises(ValueError):
        reset_data(tmp_path / "Users")
    assert (tmp_path / "Users" / "other.txt").exists()
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError):
        reset_data(Path("Users"))
    inside = home / ".anvyl"
    inside.mkdir()
    (inside / "f").write_text("x")
    reset_data(inside)
    assert inside.is_dir() and list(inside.iterdir()) == []


def test_cleanup_ignores_symlinked_work_dir(tmp_path):
    other = tmp_path / "other"
    (other / "old").mkdir(parents=True)
    ancient = time.time() - 30 * 86400
    os.utime(other / "old", (ancient, ancient))
    data = tmp_path / "data"
    data.mkdir()
    (data / "work").symlink_to(other)
    assert cleanup_stale_work(data) == 0
    assert (other / "old").exists()


@pytest.mark.parametrize(
    "leak",
    [
        "```python\nLEAK = 1",
        "~~~\nLEAK = 1\n~~~",
        "~~~\nLEAK = 1",
        "    LEAK = compute()\n    return LEAK",
        "use `LEAK_INLINE` here",
        "def LEAK():\n    pass",
    ],
)
def test_real_session_scrubs_all_free_text_fields(tmp_path, leak):
    st = _real_state(
        human_attempt=f"mine\n{leak}",
        attempts=[leak],
        answers=[leak],
        feedback=[leak],
        errors=[leak],
        questions=[leak],
        goal=leak,
        ticket=leak,
    )
    text = save_session(st, tmp_path).read_text()
    assert "LEAK" not in text


def test_real_session_text_capped_and_non_str_dropped(tmp_path):
    st = _real_state(
        human_attempt=["line1", "line2"],
        answers=["a" * 900, 5, ["x"]],
        events=[f"e{i}" for i in range(80)],
    )
    record = json.loads(save_session(st, tmp_path).read_text())
    assert record["human_attempt"] == ""
    assert record["answers"] == ["a" * 500]
    assert len(record["events"]) == 50


def test_save_session_tolerates_none_and_validates_before_mkdir(tmp_path):
    record = json.loads(
        save_session({"session_id": "s", "real": True, "events": None}, tmp_path).read_text()
    )
    assert record["events"] == []
    target = tmp_path / "nope"
    with pytest.raises(ValueError):
        save_session({"session_id": "../x"}, target)
    assert not target.exists()


def test_reset_data_relative_path_refused_for_being_relative(tmp_path, monkeypatch):
    (tmp_path / "plain").mkdir()
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="absolute"):
        reset_data(Path("plain"))


@pytest.mark.parametrize(
    "leak",
    [
        "use ``LEAK_DB`` here",
        "use ```LEAK_TRI``` here",
        "stray ` LEAK_STRAY",
        " LEAK_D1 = 1",
        "  LEAK_D2 = compute()",
        "   LEAK_D3 = compute()",
    ],
)
def test_real_session_scrubs_backticks_and_any_indent(tmp_path, leak):
    st = _real_state(answers=[f"ok\n{leak}"], task_title=leak)
    text = save_session(st, tmp_path).read_text()
    assert "LEAK" not in text


def test_inline_scrub_does_not_cross_lines():
    from anvyl.storage import _scrub_text

    assert "keep me" in _scrub_text("a ` stray\nkeep me\nb ` stray")
    assert _scrub_text("`" * 100_000) == ""


def test_real_session_dict_event_keys_filtered(tmp_path):
    st = _real_state(events=[{("t", 1): 1, "K" * 200 + "LEAK_KEY": 1, "ok": 2}])
    record = json.loads(save_session(st, tmp_path).read_text())
    assert record["events"] == [{"ok": 2}]
