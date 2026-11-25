"""Dynamic tutor turns: the model picks a move, code guards the gate, never a lockout."""

from conftest import run_real
from support import FakeClient
from test_real_graph import ANS, ATTEMPT, COACH, GATE_OK, GOOD, QS, edit

from anvyl import graph as graph_mod
from anvyl.llm import ChatResult, ModelError

READY = ChatResult('{"move": "ready"}')
TEACH = ChatResult('{"move": "teach"}')
NO = ChatResult('{"genuine": false, "reason": "filler"}')


def kinds(run):
    return [p["kind"] for p in run.payloads]


def base(**over):
    return {
        "tutor": ATTEMPT,
        "coach_next": "g",
        "work": edit(),
        "explain": ANS,
        "error": "retry",
        "nochange": "continue",
        **over,
    }


def test_clear_plan_skips_straight_to_gate_and_coach(tmp_path):
    client = FakeClient([COACH, READY, GATE_OK, COACH, QS, GOOD])
    run = run_real(tmp_path, client, base())
    assert kinds(run)[:2] == ["tutor", "coach_next"]
    assert run.state["gate_passed"] is True and run.state["approach"] == ATTEMPT


def test_idk_never_locks_and_teaches_then_moves_on(tmp_path, monkeypatch):
    monkeypatch.setattr(graph_mod, "TUTOR_MAX_TURNS", 2)
    client = FakeClient([COACH, TEACH, COACH, COACH, QS, GOOD])
    run = run_real(tmp_path, client, base(tutor="idk"))
    assert kinds(run)[:4] == ["tutor", "tutor", "coach_next", "work"]
    assert run.state["gate_blocked"] is False and run.state["gate_passed"] is False


def test_ready_before_any_real_answer_is_demoted_to_teach(tmp_path):
    client = FakeClient([COACH, READY, COACH, READY, GATE_OK, COACH, QS, GOOD])
    run = run_real(tmp_path, client, base(tutor=["idk", ATTEMPT]))
    assert kinds(run)[:3] == ["tutor", "tutor", "coach_next"]
    assert run.state["gate_passed"] is True


def test_failed_gate_check_goes_back_to_teaching(tmp_path):
    client = FakeClient([COACH, READY, NO, COACH, READY, GATE_OK, COACH, QS, GOOD])
    run = run_real(tmp_path, client, base())
    assert kinds(run)[:3] == ["tutor", "tutor", "coach_next"]
    assert run.state["gate_passed"] is True


def test_unknown_move_counts_as_ask(tmp_path):
    bad = ChatResult('{"move": "write_code"}')
    client = FakeClient([COACH, bad, COACH, READY, GATE_OK, COACH, QS, GOOD])
    run = run_real(tmp_path, client, base())
    assert kinds(run)[:3] == ["tutor", "tutor", "coach_next"]


def test_model_error_in_decide_retries(tmp_path):
    client = FakeClient([COACH, ModelError("x"), READY, GATE_OK, COACH, QS, GOOD])
    run = run_real(tmp_path, client, base())
    assert kinds(run)[:3] == ["tutor", "error", "coach_next"]
    assert run.state["gate_passed"] is True
