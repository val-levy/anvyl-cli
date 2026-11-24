"""Coach tests: offline fallback, and the live path via FakeClient. No network."""

from support import FakeClient

from anvyl import tasks as tasks_mod
from anvyl.coach import Coach
from anvyl.llm import ChatResult, ModelError


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
    monkeypatch.setattr("anvyl.auth.get_api_key", lambda data_dir=None: None)
    coach = Coach(live=True)
    result = coach.reply(tasks_mod.get_task("toy-backoff"), _state())
    assert result["live"] is False
    assert coach.live_available is False
    assert result["text"], "offline fallback must still answer"
    assert "```" not in result["text"]


def test_offline_coach_never_returns_code():
    coach = Coach(live=False)
    task = tasks_mod.get_task("toy-backoff")
    for rung in range(4):
        result = coach.reply(task, _state(help_rung=rung))
        assert result["judge"]["leaked"] is False
        assert "def retry" not in result["text"]


def test_live_via_client():
    fake = FakeClient([ChatResult("What changes between one failed call and the next?", [], 5)])
    text = Coach(live=True, client=fake).live_call("system", "user")
    assert text == "What changes between one failed call and the next?"


def test_model_error_falls_back_offline():
    coach = Coach(live=True, client=FakeClient([ModelError("down")]))
    result = coach.reply(tasks_mod.get_task("toy-backoff"), _state())
    assert result["live"] is False and coach.live_available is False
    assert result["text"]


def test_coach_strips_leaked_code_from_live_reply():
    leak = "Here you go:\n```python\ndef retry(fn):\n    return fn()\n```"
    coach = Coach(live=True, client=FakeClient([ChatResult(leak, [], 9)]))
    result = coach.reply(tasks_mod.get_task("toy-backoff"), _state())
    assert result["live"] is True, "live call ran"
    assert result["judge"]["leaked"] is False, "leaked code must not reach the human"
    assert "def retry" not in result["text"]
    assert result["stripped"] >= 1


def test_coach_silent_at_l0():
    coach = Coach(live=False)
    result = coach.reply(tasks_mod.get_task("toy-backoff"), _state(level=0))
    assert result["text"] == ""
