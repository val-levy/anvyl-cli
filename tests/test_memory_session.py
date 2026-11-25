"""Memory wired into sessions: recording, recap, /memory, export, reset."""

import json

from support import FakeClient
from test_session import (
    COACH,
    EXTRACT,
    GATE_OK,
    GOAL,
    GOOD,
    QS,
    go,
    one_ticket,
    prep,
)

from anvyl import cli
from anvyl.llm import ChatResult, ModelError
from anvyl.memory import Memory
from anvyl.session import HINTS

BAD = ChatResult(json.dumps({"results": [{"correct": False, "feedback": "no"}] * 3}))
LABEL = "retry with backoff"


def ticket_client(*extra):
    return FakeClient([GATE_OK, COACH, QS, GOOD, EXTRACT, *extra])


def test_ticket_start_records_unfinished_and_welcome_back_line(tmp_path):
    root, data = prep(tmp_path)
    go(root, data, ["Add retry to fetch", GOAL, "/quit"], client=FakeClient([COACH]))
    r = go(root, data, ["/quit"])
    assert "Last time you were working on: Add retry to fetch (unfinished)" in r.out


def test_ideas_recorded_only_after_explain_back_passes(tmp_path):
    root, data = prep(tmp_path)
    go(root, data, one_ticket(root), client=ticket_client())
    assert [i["label"] for i in Memory(data, root).ideas()] == [LABEL]
    root2, data2 = prep(tmp_path / "b")
    client = FakeClient([GATE_OK, COACH, QS, BAD, EXTRACT])
    go(root2, data2, one_ticket(root2), client=client)
    assert Memory(data2, root2).ideas() == []


def test_no_file_consent_records_no_ideas(tmp_path):
    root, data = prep(tmp_path, consent=False)
    go(root, data, one_ticket(root), client=ticket_client())
    assert Memory(data, root).ideas() == []


def test_extraction_model_error_does_not_fail_the_ticket(tmp_path):
    root, data = prep(tmp_path)
    client = FakeClient([GATE_OK, COACH, QS, GOOD, ModelError("x")])
    r = go(root, data, one_ticket(root), client=client)
    assert "ticket failed" not in r.out and "scorecard" in r.out
    assert Memory(data, root).ideas() == []


def test_recap_reaches_coach_not_state(tmp_path):
    root, data = prep(tmp_path)
    Memory(data, root).record(LABEL, ["happy"])
    client = ticket_client()
    go(root, data, one_ticket(root), client=client)
    coach_call = " ".join(m["content"] for m in client.calls[1][0])
    assert LABEL in coach_call and "memory" in coach_call
    saved = [p.read_text() for p in (data / "sessions").glob("*.json")]
    assert saved and all(LABEL not in t for t in saved)


def test_memory_command_lists_and_forgets(tmp_path):
    root, data = prep(tmp_path)
    Memory(data, root).record(LABEL, ["happy", "edge"])
    r = go(root, data, ["/memory", "/memory forget retry with backoff", "/memory"])
    assert f"{LABEL} (x1, edge, happy)" in r.out and f"forgot: {LABEL}" in r.out
    assert "nothing remembered yet" in r.out


def test_memory_export_cli(tmp_path, capsys, monkeypatch):
    root, data = prep(tmp_path)
    Memory(data, root).record(LABEL, ["happy"])
    monkeypatch.chdir(root)
    assert cli.main(["memory", "export", "--data-dir", str(data)]) == 0
    assert json.loads(capsys.readouterr().out)["ideas"][0]["label"] == LABEL


def test_reset_removes_memory(tmp_path):
    root, data = prep(tmp_path)
    Memory(data, root).record(LABEL, ["happy"])
    from anvyl.storage import reset_data

    reset_data(data.absolute())
    assert Memory(data, root).ideas() == []


def test_hints_cover_tutor_kinds():
    assert {"tutor_goal", "attempt", "tutor_step", "teach"} <= set(HINTS)
