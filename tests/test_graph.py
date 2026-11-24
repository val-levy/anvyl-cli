"""End-to-end graph tests: Learn loop, Ship fast path, the gate proof,
and the scorecard. Driven with scripted answers, no model calls."""

import json

from conftest import FixedProvider, run_task


def test_learn_loop_end_to_end(tmp_path):
    result = run_task("toy-backoff", mode="learn", level=1, tmp_path=tmp_path)
    assert result["gate_passed"] is True
    assert result["gate_blocked"] is False
    # Full loop ran: coach spoke, human typed, explain-back scored.
    assert result["coach_messages"], "coach never ran"
    assert result["human_lines"] > 0
    assert result["ai_lines"] == 0, "no AI code in Learn/L1"
    assert result["explain_score"] == 1.0
    assert result["ownership_score"] == 1.0
    assert result["verification"]["passed"] is True
    assert result["current_node"] == "scorecard"
    assert result["finished_at"] > result["started_at"]
    # Scorecard was saved to the session log.
    session_file = tmp_path / "sessions" / f"{result['session_id']}.json"
    assert session_file.exists()
    saved = json.loads(session_file.read_text())
    assert saved["ownership_score"] == 1.0
    assert saved["verification"]["passed"] is True


def test_learn_loop_with_live_coach_stub(tmp_path, monkeypatch):
    """Live path via a stub helper: the scorecard must record live_model."""
    stub = tmp_path / "helper.py"
    stub.write_text("#!/usr/bin/env python3\nprint('What changes between attempts?')\n")
    monkeypatch.setenv("HARNESS_OPENROUTER_HELPER", str(stub))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = run_task("toy-backoff", mode="learn", level=1, tmp_path=tmp_path, live=True)
    assert result["live_model"] is True
    assert result["gate_passed"] is True
    assert result["ownership_score"] == 1.0


def test_ship_path_has_no_gate_and_no_explainback(tmp_path):
    result = run_task("toy-backoff", mode="ship", level=3, tmp_path=tmp_path)
    assert result["gate_passed"] is True
    assert result["explain_score"] == 0.0, "ship skips explain-back unless high-stakes"
    assert result["ai_lines"] > 0, "ship mode lets the AI draft"
    assert result["human_lines"] == 0, "scripted ship run accepts the draft as-is"
    assert result["verification"]["passed"] is True
    assert result["current_node"] == "scorecard"


def test_ship_high_stakes_requires_explainback(tmp_path):
    result = run_task("toy-backoff", mode="ship", level=3, high_stakes=True, tmp_path=tmp_path)
    assert result["explain_score"] == 1.0
    assert result["ownership_score"] == 1.0


def test_gate_proof_ai_cannot_write_code_before_attempt(tmp_path):
    """The core guarantee: with no usable human attempt, the graph ends
    blocked. The coach never runs, no code exists, nothing is verified."""
    provider = FixedProvider({"attempt": ""})
    result = run_task("toy-backoff", mode="learn", level=1, tmp_path=tmp_path, provider=provider)
    assert result["gate_passed"] is False
    assert result["gate_blocked"] is True
    assert result["coach_messages"] == [], "coach ran before an attempt existed"
    assert result["solution_code"] == "", "code exists without an attempt"
    assert result["current_node"] == "attempt_gate"


def test_gate_proof_short_attempt_is_blocked(tmp_path):
    provider = FixedProvider({"attempt": "idk"})
    result = run_task("toy-backoff", mode="learn", level=1, tmp_path=tmp_path, provider=provider)
    assert result["gate_blocked"] is True
    assert result["coach_messages"] == []


def test_wifi_task_runs_as_second_example(tmp_path):
    result = run_task("wifi-csi-backoff", mode="learn", level=1, tmp_path=tmp_path)
    assert result["gate_passed"] is True
    assert result["verification"]["passed"] is True
    assert result["ownership_score"] == 1.0


def test_low_ownership_drops_level(tmp_path):
    """Wrong explain-back answers -> ownership 0 -> level auto-drops to L1."""
    from anvyl import tasks as tasks_mod

    task = tasks_mod.get_task("toy-backoff")

    class WrongAnswers:
        def answer(self, payload, ctx):
            kind = payload.get("kind")
            if kind == "attempt":
                return task["scripted_attempt"]
            if kind == "coach_next":
                return "g"
            if kind == "code":
                return task["scripted_code"]
            if kind == "explain":
                return "I have no idea."
            return ""

    result = run_task(
        "toy-backoff", mode="learn", level=3, tmp_path=tmp_path, provider=WrongAnswers()
    )
    assert result["explain_score"] == 0.0
    assert result["ownership_score"] == 0.0
    assert result["level"] == 1, "level should auto-drop to L1 on low ownership"
