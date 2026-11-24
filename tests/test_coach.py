"""Coach tests: offline fallback, and the live path via a stub helper.

No real API key or network is used here. The live path is exercised
through HARNESS_OPENROUTER_HELPER pointing at a stub script.
"""

import stat

from anvyl import tasks as tasks_mod
from anvyl.coach import Coach


def _state(**over):
    base = {
        "mode": "learn",
        "level": 1,
        "human_attempt": "x" * 60,
        "help_rung": 0,
        "goal": "retry helper",
    }
    base.update(over)
    return base


def test_live_without_credentials_falls_back_offline(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("HARNESS_OPENROUTER_HELPER", raising=False)
    coach = Coach(live=True)
    result = coach.reply(tasks_mod.get_task("toy-backoff"), _state())
    assert result["live"] is False
    assert result["text"], "offline fallback must still answer"
    assert "```" not in result["text"]


def test_offline_coach_never_returns_code():
    coach = Coach(live=False)
    task = tasks_mod.get_task("toy-backoff")
    for rung in range(4):
        result = coach.reply(task, _state(help_rung=rung))
        assert result["judge"]["leaked"] is False
        assert "def retry" not in result["text"]


def test_live_via_helper_stub(monkeypatch, tmp_path):
    stub = tmp_path / "fake-helper.py"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "print('What changes between one failed call and the next?')\n"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("HARNESS_OPENROUTER_HELPER", str(stub))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    coach = Coach(live=True)
    text = coach.live_call("system", "user")
    assert text == "What changes between one failed call and the next?"


def test_coach_strips_leaked_code_from_live_reply(monkeypatch, tmp_path):
    stub = tmp_path / "leaky-helper.py"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "print('Here you go:\\n```python\\ndef retry(fn):\\n    return fn()\\n```')\n"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("HARNESS_OPENROUTER_HELPER", str(stub))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    coach = Coach(live=True)
    result = coach.reply(tasks_mod.get_task("toy-backoff"), _state())
    assert result["live"] is True, "live call ran"
    assert result["judge"]["leaked"] is False, "leaked code must not reach the human"
    assert "def retry" not in result["text"]
    assert result["stripped"] >= 1


def test_coach_silent_at_l0():
    coach = Coach(live=False)
    result = coach.reply(tasks_mod.get_task("toy-backoff"), _state(level=0))
    assert result["text"] == ""
