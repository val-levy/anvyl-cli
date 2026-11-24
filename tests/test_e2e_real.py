"""End-to-end real-session checks through run_session with a scripted terminal and model."""

import json
import subprocess

import keyring
import pytest
from support import FakeClient
from test_session import ANSWERS, ATTEMPT, COACH, GATE_OK, GOOD, QS, edit, go, one_ticket, prep

from anvyl.llm import ChatResult, ModelError, ToolCall
from anvyl.profile import Profile

SENTINEL = "SENTINEL_SECRET_BODY_9137"
AWS_KEY = "AKIAIOSFODNN7EXAMPLE"
TYPED = "TYPED_PROSE_MARKER_4412"  # typed free text is stored (scrubbed) by design


@pytest.fixture(autouse=True)
def no_real_keychain(monkeypatch):
    monkeypatch.setattr(keyring, "get_password", lambda s, u: None)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)


def all_bytes(data):
    return {p: p.read_bytes() for p in data.rglob("*") if p.is_file()}


def leaks(data, *needles):
    """(file, needle) for each needle found in any byte under data, incl. checkpoint -wal/-shm."""
    return [
        (p.name, n) for p, blob in all_bytes(data).items() for n in needles if n.encode() in blob
    ]


def test_scan_helper_catches_a_leak(tmp_path):
    (tmp_path / "checkpoints.sqlite-wal").write_bytes(b"xx" + SENTINEL.encode() + b"yy")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.json").write_text(AWS_KEY)
    assert sorted(leaks(tmp_path, SENTINEL, AWS_KEY)) == [
        ("c.json", AWS_KEY),
        ("checkpoints.sqlite-wal", SENTINEL),
    ]


def test_e2e_professional_leaves_no_code_anywhere(tmp_path):
    root, data = prep(tmp_path)
    planted = f'{SENTINEL} = "{AWS_KEY}"'
    (root / "app.py").write_text(f"{planted}\n")

    def add_planted_copy():
        with (root / "app.py").open("a") as f:
            f.write(f"{planted}\nz = 3\n")
        return "/done"

    reply = f"Try something like:\n```python\n{planted}\n```"
    client = FakeClient([GATE_OK, ChatResult(reply), QS, GOOD])
    items = ["/level 2", "Add retry", ATTEMPT, "g", add_planted_copy, *ANSWERS]
    r = go(root, data, items, client=client)
    assert r.rc == 0 and "scorecard" in r.out
    assert SENTINEL in r.out, "the user did see the snippet"
    assert SENTINEL in json.dumps(client.calls[-1][0]), "control: the grader was sent the diff"
    assert any(p.name.startswith("checkpoints.sqlite") for p in all_bytes(data))
    assert list((data / "sessions").glob("*.json"))
    assert leaks(data, SENTINEL, AWS_KEY) == []
    assert not any((data / "work").glob("*")), "per-session work dir removed, not just emptied"


def test_e2e_read_file_tool_result_never_persists(tmp_path):
    root, data = prep(tmp_path)
    (root / "app.py").write_text(f'{SENTINEL} = 1\nkey = "{AWS_KEY}"\n')
    call = ChatResult("", [ToolCall("t1", "read_file", {"path": "app.py"})])
    client = FakeClient([GATE_OK, call, ChatResult("What happens on failure?"), QS, GOOD])
    answers = [f"it retries, see {TYPED} and {AWS_KEY}", *ANSWERS[1:]]
    r = go(root, data, [*one_ticket(root)[:-3], *answers], client=client)
    assert r.rc == 0 and "ownership" in r.out
    tool_msgs = [m["content"] for m in client.calls[2][0] if m["role"] == "tool"]
    assert len(tool_msgs) == 1
    assert SENTINEL in tool_msgs[0], "control: file content reached the coach loop"
    assert AWS_KEY not in tool_msgs[0], "the key was redacted before the model saw it"
    assert leaks(data, SENTINEL, AWS_KEY) == []
    assert {f for f, _n in leaks(data, TYPED)} == {next((data / "sessions").glob("*.json")).name}
    assert not any((data / "work").glob("*"))


def test_e2e_personal_non_git_folder_full_loop(tmp_path):
    root, data = prep(tmp_path, profile=Profile.PERSONAL)
    r = go(root, data, one_ticket(root), client=FakeClient([GATE_OK, COACH, QS, GOOD]))
    assert r.rc == 0
    assert "+2 -0" in r.out and "ownership" in r.out and "personal" in r.out
    assert not any((data / "work").glob("*/base"))


def git(root, *args):
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=root, check=True, capture_output=True,
    )  # fmt: skip


def test_e2e_git_repo_midsession_commit_does_not_change_counts(tmp_path):
    root, data = prep(tmp_path)
    git(root, "init")
    git(root, "add", ".")
    git(root, "commit", "-m", "init")
    editor = edit(root)

    def edit_then_commit():
        editor()
        git(root, "commit", "-am", "mid-session")
        return "/done"

    items = ["Add retry to fetch", ATTEMPT, "g", edit_then_commit, *ANSWERS]
    r = go(root, data, items, client=FakeClient([GATE_OK, COACH, QS, GOOD]))
    assert r.rc == 0
    assert "+2 -0" in r.out and "1 files" in r.out


def test_e2e_model_outage_mid_session_is_resumable(tmp_path):
    root, data = prep(tmp_path)
    client = FakeClient([GATE_OK, COACH, QS, ModelError("down"), GOOD])
    items = [*one_ticket(root), "retry"]
    r = go(root, data, items, client=client)
    assert r.rc == 0 and "Nothing was scored" in r.out
    assert "scorecard" in r.out and "ownership" in r.out
    assert len(list((data / "sessions").glob("*.json"))) == 1
