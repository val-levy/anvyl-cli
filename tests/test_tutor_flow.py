"""Tutor flow: goal, approach, first step, teaching, never a lockout."""

from conftest import run_real
from support import FakeClient
from test_real_graph import ANS, ATTEMPT, COACH, GATE_OK, GOOD, QS, edit  # noqa: F401

from anvyl.llm import ChatResult, ModelError


def kinds(run):
    return [p["kind"] for p in run.payloads]


def base(**over):
    return {
        "attempt": ATTEMPT,
        "coach_next": "g",
        "work": edit(),
        "explain": ANS,
        "error": "retry",
        "nochange": "continue",
        **over,
    }


def stages(client):
    return [m[0][1]["content"] for m in client.calls]


def test_learn_flow_asks_goal_approach_first_step_in_order(tmp_path):
    run = run_real(tmp_path, FakeClient([GATE_OK, COACH, QS, GOOD]), base())
    assert kinds(run)[:4] == ["tutor_goal", "attempt", "tutor_step", "coach_next"]
    assert run.state["goal_detail"] and run.state["steps"] == ["Wrap the call in a loop"]


def test_idk_never_locks_and_teaches(tmp_path):
    client = FakeClient([COACH, COACH, COACH, QS, GOOD])
    run = run_real(tmp_path, client, base(attempt="idk", teach="idk"))
    assert kinds(run)[:7] == [
        "tutor_goal",
        "attempt",
        "teach",
        "teach",
        "tutor_step",
        "coach_next",
        "work",
    ]
    s = run.state
    assert s["gate_blocked"] is False and s["gate_passed"] is False
    assert s["teach_rounds"] == 3


def test_real_attempt_after_teaching_sets_gate_passed(tmp_path):
    client = FakeClient([COACH, GATE_OK, COACH, QS, GOOD])
    run = run_real(tmp_path, client, base(attempt=["idk", ATTEMPT], teach=ATTEMPT))
    assert kinds(run)[:5] == ["tutor_goal", "attempt", "teach", "tutor_step", "coach_next"]
    assert run.state["gate_passed"] is True and run.state["approach"] == ATTEMPT


def test_filler_attempt_goes_to_teach_not_lock(tmp_path):
    no = ChatResult('{"genuine": false, "reason": "filler"}')
    client = FakeClient([no, COACH, GATE_OK, COACH, QS, GOOD])
    run = run_real(tmp_path, client, base(teach=ATTEMPT))
    assert kinds(run)[2] == "teach" and run.state["gate_blocked"] is False
    assert run.state["gate_passed"] is True


def test_model_error_in_reattempt_check_still_retries(tmp_path):
    client = FakeClient([COACH, ModelError("x"), GATE_OK, COACH, QS, GOOD])
    run = run_real(tmp_path, client, base(attempt="idk", teach=ATTEMPT))
    assert "error" in kinds(run) and run.state["gate_passed"] is True


def test_ship_mode_has_no_tutor_questions(tmp_path):
    run = run_real(tmp_path, FakeClient([QS, GOOD]), base(), mode="ship")
    assert not {"tutor_goal", "attempt", "tutor_step", "teach"} & set(kinds(run))
