"""End-to-end real-session checks through run_session with a scripted terminal and model."""

import subprocess

import keyring
import pytest
from support import FakeClient
from test_session import ANSWERS, ATTEMPT, COACH, GATE_OK, GOOD, QS, edit, go, one_ticket, prep

from anvyl.llm import ChatResult, ModelError
from anvyl.profile import Profile

SENTINEL = "SENTINEL_SECRET_BODY_9137"
AWS_KEY = "AKIAIOSFODNN7EXAMPLE"


@pytest.fixture(autouse=True)
def no_real_keychain(monkeypatch):
    monkeypatch.setattr(keyring, "get_password", lambda s, u: None)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)


def all_bytes(data):
    return {p: p.read_bytes() for p in data.rglob("*") if p.is_file()}


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
    files = all_bytes(data)
    assert any(p.name.startswith("checkpoints.sqlite") for p in files)
    assert list((data / "sessions").glob("*.json"))
    for p, blob in files.items():
        assert SENTINEL.encode() not in blob, p
        assert AWS_KEY.encode() not in blob, p
    assert not any((data / "work").glob("*/*")), "work dir contents deleted"


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
