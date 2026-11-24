"""Real-session graph: gate, coach, review, explain-back, fail-closed model errors."""

import hashlib
import json
import sqlite3

from conftest import run_real
from support import FakeClient

from anvyl.graph import hash_lines
from anvyl.llm import ChatResult, ModelError

ATTEMPT = "I would wrap the fetch call in a loop that retries with a growing delay"
GATE_OK = ChatResult('{"genuine": true, "reason": "ok"}')
COACH = ChatResult("What happens when the first call fails?", [], 7)
QS = ChatResult(json.dumps({"questions": ["What does it do?", "Why?", "What could break?"]}))
ANS = "it retries the call three times"


def grades(*flags):
    results = [{"correct": f, "feedback": "fine"} for f in flags]
    return ChatResult(json.dumps({"results": results}))


GOOD, BAD = grades(True, True, True), grades(False, False, False)


def edit(text="y = 2\nz = 3\n"):
    def _do(payload, root):
        with (root / "app.py").open("a") as f:
            f.write(text)
        return "/done"

    return _do


def answers(**over):
    base = {
        "attempt": ATTEMPT,
        "coach_next": "g",
        "work": edit(),
        "explain": ANS,
        "error": "retry",
        "nochange": "continue",
    }
    return {**base, **over}


def kinds(run):
    return [p["kind"] for p in run.payloads]


def test_learn_flow_end_to_end(tmp_path):
    client = FakeClient([GATE_OK, COACH, QS, GOOD])
    run = run_real(tmp_path, client, answers())
    s = run.state
    assert kinds(run) == ["attempt", "coach_next", "work"] + ["explain"] * 3
    assert s["gate_passed"] is True and s["ownership_score"] == 1.0
    assert s["changes"] == {"files": 1, "added": 2, "removed": 0}
    assert s["human_lines"] == 2 and s["ai_lines"] == 0
    assert s["current_node"] == "scorecard" and s["tokens"] == 7
    saved = json.loads((run.sessions / "real-test.json").read_text())
    assert saved["ownership_score"] == 1.0 and saved["real"] is True
    assert not (run.work_dir / "base").exists()


def test_junk_attempt_blocks_after_three_tries(tmp_path):
    client = FakeClient([])
    run = run_real(tmp_path, client, answers(attempt=["a", "b", "c"]))
    assert kinds(run) == ["attempt"] * 3
    assert run.state["gate_passed"] is False and run.state["gate_blocked"] is True
    assert not client.calls


def test_gate_model_error_surfaces_error_kind_and_retry_works(tmp_path):
    client = FakeClient([ModelError("boom sk-leak"), GATE_OK, COACH, QS, GOOD])
    run = run_real(tmp_path, client, answers())
    assert kinds(run)[:3] == ["attempt", "error", "coach_next"]
    err = run.payloads[1]
    assert "sk-leak" not in json.dumps(err) and "boom" not in json.dumps(err)
    assert run.state["gate_passed"] is True and run.state["ownership_score"] == 1.0


def test_gate_model_error_then_quit_never_passes(tmp_path):
    client = FakeClient([ModelError("x")])
    run = run_real(tmp_path, client, answers(error="quit"))
    assert kinds(run) == ["attempt", "error"]
    assert run.state["gate_passed"] is False and run.state.get("quit") is True
    assert not (run.sessions / "real-test.json").exists()


def test_coach_model_error_is_denial_not_pass(tmp_path):
    client = FakeClient([GATE_OK, ModelError("x")])
    run = run_real(tmp_path, client, answers(error="quit"))
    assert kinds(run) == ["attempt", "error"]
    assert run.state["current_node"] != "scorecard" and run.state["ownership_score"] == 0.0


def test_zero_change_done_asks_continue_or_abandon(tmp_path):
    client = FakeClient([GATE_OK, COACH, QS, GOOD])
    run = run_real(tmp_path, client, answers(work=["/done", edit()]))
    assert kinds(run)[2:6] == ["work", "nochange", "work", "explain"]
    assert run.state["changes"]["added"] == 2


def test_abandon_skips_explain_back(tmp_path):
    client = FakeClient([GATE_OK, COACH])
    run = run_real(tmp_path, client, answers(work="/done", nochange="abandon"), level=2)
    assert "explain" not in kinds(run)
    assert run.state["current_node"] == "scorecard" and run.state["level"] == 2
    assert (run.sessions / "real-test.json").exists()


def test_malformed_grading_json_surfaces_error_and_never_scores(tmp_path):
    client = FakeClient([GATE_OK, COACH, QS, ChatResult("not json"), GOOD])
    run = run_real(tmp_path, client, answers())
    assert "error" in kinds(run)
    assert kinds(run).count("explain") == 3, "answers are kept, not re-asked, on retry"
    assert run.state["ownership_score"] == 1.0
    quit_run = run_real(
        tmp_path / "q",
        FakeClient([GATE_OK, COACH, QS, ChatResult("not json")]),
        answers(error="quit"),
        level=2,
    )
    assert quit_run.state["ownership_score"] == 0.0 and quit_run.state["level"] == 2
    assert quit_run.state["current_node"] != "scorecard"


def test_low_ownership_drops_level_to_1(tmp_path):
    client = FakeClient([GATE_OK, COACH, QS, BAD])
    run = run_real(tmp_path, client, answers(), level=2)
    assert run.state["ownership_score"] == 0.0 and run.state["level"] == 1


def test_high_stakes_ship_still_runs_explain_back(tmp_path):
    client = FakeClient([QS, GOOD])
    run = run_real(tmp_path, client, answers(), mode="ship", level=2, high_stakes=True)
    assert kinds(run) == ["work"] + ["explain"] * 3
    assert run.state["ownership_score"] == 1.0


def test_ship_routine_skips_explain_back(tmp_path):
    client = FakeClient([])
    run = run_real(tmp_path, client, answers(), mode="ship", level=2)
    assert kinds(run) == ["work"] and not client.calls
    assert run.state["current_node"] == "scorecard" and run.state["level"] == 2


def test_state_and_checkpoint_never_contain_file_contents(tmp_path):
    secret = "SENTINEL_FILE_BODY_91"
    client = FakeClient([GATE_OK, COACH, QS, GOOD])
    run = run_real(tmp_path, client, answers(work=edit(f"{secret} = 1\n")))
    assert secret not in json.dumps(run.state, default=str)
    assert secret not in (run.sessions / "real-test.json").read_text()
    assert secret.encode() not in run.db


def test_without_file_consent_the_grader_sees_only_added_lines(tmp_path):
    client = FakeClient([GATE_OK, COACH, QS, GOOD])
    run_real(tmp_path, client, answers(work=edit("y = 2\n")))
    sent = json.dumps(client.calls[2:])  # explain-back questions and grading
    assert "y = 2" in sent
    assert "x = 1" not in sent and "app.py" not in sent, "untouched content/file names stay local"


def test_keep_diffs_writes_diff_only_when_enabled(tmp_path):
    for keep in (True, False):
        client = FakeClient([GATE_OK, COACH, QS, GOOD])
        run = run_real(tmp_path / str(keep), client, answers(), keep_diffs=keep)
        assert (run.sessions / "real-test.diff").exists() is keep


SNIPPET = "Try this:\n```python\ndef f(x):\n    return x+1\n```"


def test_ai_lines_counted_from_shown_snippets(tmp_path):
    client = FakeClient([GATE_OK, ChatResult(SNIPPET), QS, GOOD])
    typed = edit("def f(x):\n        return x+1\nk = 3\n")
    run = run_real(tmp_path, client, answers(work=typed), level=2)
    s = run.state
    assert s["ai_lines"] == 2 and s["human_lines"] == 1
    assert "def f" in run.payloads[1]["text"], "L2 user still sees the snippet"
    assert s["shown_snippets"] and all(len(h) == 64 for h in s["shown_snippets"])
    assert "return x" not in json.dumps(s, default=str)


def test_snippet_text_not_in_state_or_checkpoints_except_interrupt_payload(tmp_path):
    marker = "SNIPPET_SENTINEL_77"
    reply = f"Try:\n```python\n{marker} = 1\n```"
    client = FakeClient([GATE_OK, ChatResult(reply), QS, GOOD])
    run = run_real(tmp_path, client, answers(), level=2)
    assert marker not in json.dumps(run.state, default=str)
    assert marker not in (run.sessions / "real-test.json").read_text()
    con = sqlite3.connect(tmp_path / "checkpoints.sqlite")
    # Graph level only: the graph alone still writes the shown text into `writes`. The session
    # (tests/test_session.py) deletes the thread, uses secure_delete and so leaves no copy on disk.
    # Checkpointed state never has it. LangGraph also stores the interrupt payload shown to
    # the user (the coach text at L2) in `writes`; that is the only place it may appear.
    assert not [
        r for (r,) in con.execute("select checkpoint from checkpoints") if marker.encode() in r
    ]
    hits = con.execute("select channel, value from writes").fetchall()
    assert {ch for ch, v in hits if marker.encode() in v} <= {"__interrupt__"}


def test_ansi_in_model_reply_never_reaches_payload(tmp_path):
    client = FakeClient([GATE_OK, ChatResult("\x1b[31mred\x1b[0m \x1b]0;t\x07question?"), QS, GOOD])
    run = run_real(tmp_path, client, answers())
    assert "\x1b" not in json.dumps(run.payloads) and "\x07" not in json.dumps(run.payloads)


def test_hash_lines_normalizes_whitespace_skips_blank_and_fences():
    h = hashlib.sha256(b"return x + 1").hexdigest()
    assert hash_lines("```py\n\n    return   x + 1\n```") == [h]
    assert hash_lines("   ") == []
