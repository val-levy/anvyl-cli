"""Persistent real-project session and the CLI subcommands around it."""

import getpass
import io
import json
import os
import sqlite3
import time
from types import SimpleNamespace

import keyring
import pytest
from conftest import run_real
from rich.console import Console
from support import FakeClient

from anvyl import auth, cli
from anvyl.llm import ChatResult
from anvyl.profile import FolderConfig, Profile
from anvyl.session import open_checkpointer, run_session

GOAL = "Make fetch retry so a flaky network does not break it"
STEP = "Wrap the call in a loop"
ATTEMPT = "I would wrap the fetch call in a loop that retries with a growing delay"
GATE_OK = ChatResult('{"genuine": true, "reason": "ok"}')
COACH = ChatResult("What happens when the first call fails?", [], 7)
QS = ChatResult(json.dumps({"questions": ["What does it do?", "Why?", "What could break?"]}))
GOOD = ChatResult(json.dumps({"results": [{"correct": True, "feedback": "fine"}] * 3}))
ANSWERS = ["it retries the call three times"] * 3


def ticket_script(client_extra=()):
    return [GATE_OK, COACH, QS, GOOD, *client_extra]


def reader(items, prompts=None):
    """Scripted read_line: str | callable | exception instance; exhausted means EOF (None)."""
    it = iter(items)

    def read(prompt):
        if prompts is not None:
            prompts.append(prompt)
        item = next(it, None)
        if isinstance(item, BaseException):
            raise item
        return item() if callable(item) else item

    return read


def prep(tmp_path, profile=Profile.PROFESSIONAL, consent=True, name="proj", files=True):
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    if files:
        (root / "app.py").write_text("x = 1\n")
    data = tmp_path / "data"
    cfg = FolderConfig(data)
    if profile is not None:
        cfg.set_profile(root, profile)
    if consent is not None:
        cfg.set_consent(root, consent)
    return root, data


def go(root, data, items, client=None, key="client-given", **console_kw):
    buf = io.StringIO()
    console = Console(file=buf, width=100, **console_kw)
    prompts: list[str] = []
    client = client if client is not None else FakeClient([])
    rc = run_session(root, data, console, client, reader(items, prompts))
    return SimpleNamespace(rc=rc, out=buf.getvalue(), prompts=prompts, client=client)


def edit(root):
    def _do():
        with (root / "app.py").open("a") as f:
            f.write("y = 2\nz = 3\n")
        return "/done"

    return _do


def one_ticket(root, ticket="Add retry to fetch"):
    return [ticket, GOAL, ATTEMPT, STEP, "g", edit(root), *ANSWERS]


def thread_rows(data):
    con = sqlite3.connect(data / "checkpoints.sqlite")
    try:
        return con.execute("select count(*) from checkpoints").fetchone()[0]
    finally:
        con.close()


@pytest.fixture(autouse=True)
def no_real_keychain(monkeypatch):
    monkeypatch.setattr(keyring, "get_password", lambda s, u: None)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)


# -- startup ---------------------------------------------------------------------
def test_no_key_prints_login_hint_and_returns_1(tmp_path):
    root, data = prep(tmp_path)
    buf = io.StringIO()
    rc = run_session(root, data, Console(file=buf, width=100), None, reader([]))
    assert rc == 1 and 'not logged in: run "anvyl login"' in buf.getvalue()


def test_tutorial_works_without_key(tmp_path):
    assert cli.main(["tutorial", "--demo", "--data-dir", str(tmp_path / "d")]) == 0


def test_legacy_task_flag_still_runs_tutorial(tmp_path, capsys):
    assert cli.main(["--task", "toy-backoff", "--demo", "--data-dir", str(tmp_path / "d")]) == 0
    assert cli.main(["--list-tasks"]) == 0
    assert "toy-backoff" in capsys.readouterr().out


def test_bare_anvyl_runs_session(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        cli, "run_session", lambda root, data, console, client: seen.update(r=root) or 0
    )
    monkeypatch.chdir(tmp_path)
    assert cli.main(["--data-dir", str(tmp_path / "d")]) == 0
    assert seen["r"] == tmp_path.resolve()


def test_first_use_defaults_to_professional_and_remembers(tmp_path):
    root, data = prep(tmp_path, profile=None, consent=None)
    first = go(root, data, ["", "", "/quit"])
    cfg = FolderConfig(data)
    assert first.rc == 0 and len(first.prompts) == 3
    assert cfg.profile(root) is Profile.PROFESSIONAL
    assert cfg.consented(root) is False and cfg.consent_asked(root) is True
    second = go(root, data, ["/quit"])
    assert len(second.prompts) == 1, "profile and consent are asked once per folder"


def test_eof_at_first_prompts_is_a_clean_quit_and_stores_nothing(tmp_path):
    root, data = prep(tmp_path, profile=None, consent=None)
    r = go(root, data, [])
    assert r.rc == 0 and "Traceback" not in r.out
    assert FolderConfig(data).profile(root) is None


def test_personal_choice_persists(tmp_path):
    root, data = prep(tmp_path, profile=None, consent=None)
    first = go(root, data, ["personal", "/quit"])
    assert FolderConfig(data).profile(root) is Profile.PERSONAL
    assert len(first.prompts) == 2, "personal needs no consent prompt"
    assert "personal" in first.out.lower() and "notice" in first.out.lower()
    second = go(root, data, ["/quit"])
    assert len(second.prompts) == 1 and "notice" not in second.out.lower()


def test_consent_refused_runs_ticket_only_and_sends_no_file_content(tmp_path):
    root, data = prep(tmp_path, profile=None, consent=None)
    (root / "app.py").write_text("SENTINEL_FILE_BODY_55 = 1\n")
    reply = ChatResult("Which file?", [], 3)
    client = FakeClient([GATE_OK, reply])
    r = go(root, data, ["", "n", *one_ticket(root)[: -len(ANSWERS)]], client=client)
    assert "[!] ticket-and-plan-only coaching" in r.out
    assert not FolderConfig(data).consented(root)
    assert len(client.calls) == 2, "gate and coach only: explain-back is skipped"
    assert "scorecard" in r.out and "ownership" not in r.out
    assert all(tools is None for _m, tools in client.calls)
    sent = json.dumps(client.calls)
    for leak in ("SENTINEL_FILE_BODY_55", "y = 2", "z = 3", "app.py"):
        assert leak not in sent


def test_consent_given_offers_file_tools(tmp_path):
    root, data = prep(tmp_path, consent=True)
    client = FakeClient([GATE_OK, COACH, QS, GOOD])
    go(root, data, one_ticket(root), client=client)
    assert any(tools for _m, tools in client.calls)


def test_default_answer_at_consent_prompt_is_no(tmp_path):
    root, data = prep(tmp_path, profile=Profile.PROFESSIONAL, consent=None)
    go(root, data, [None])
    assert FolderConfig(data).consented(root) is False


# -- slash commands --------------------------------------------------------------
def test_level_3_refused(tmp_path):
    root, data = prep(tmp_path)
    r = go(root, data, ["/level 3", "/level 4", "/status", "/level 2", "/status", "/quit"])
    assert r.out.count("max L2") == 2
    assert "L1" in r.out and "L2" in r.out
    assert "L3" not in r.out.replace("level 3", "") and "L4" not in r.out.replace("level 4", "")


def test_profile_switch_command(tmp_path):
    root, data = prep(tmp_path, profile=Profile.PROFESSIONAL, consent=True)
    go(root, data, ["/profile personal", "/quit"])
    assert FolderConfig(data).profile(root) is Profile.PERSONAL
    r = go(root, data, ["/profile professional", "/profile nonsense", "/quit"])
    assert FolderConfig(data).profile(root) is Profile.PROFESSIONAL
    assert "usage" in r.out and len(r.prompts) == 3, "consent already decided: not asked again"


def test_switch_to_professional_asks_consent_when_never_decided(tmp_path):
    root, data = prep(tmp_path, profile=Profile.PERSONAL, consent=None)
    go(root, data, ["/profile professional", "y", "/quit"])
    cfg = FolderConfig(data)
    assert cfg.profile(root) is Profile.PROFESSIONAL and cfg.consented(root) is True


def test_keepdiffs_only_for_personal(tmp_path):
    root, data = prep(tmp_path, profile=Profile.PROFESSIONAL)
    r = go(root, data, ["/keepdiffs on", "/quit"])
    cfg = FolderConfig(data)
    assert "personal" in r.out and cfg.keep_diffs(root) is False
    cfg.set_profile(root, Profile.PERSONAL)
    go(root, data, ["/keepdiffs on", "/quit"])
    assert cfg.keep_diffs(root) is True
    go(root, data, ["/keepdiffs off", "/quit"])
    assert cfg.keep_diffs(root) is False


def test_mode_help_score_graph_rail_and_unknown(tmp_path):
    root, data = prep(tmp_path)
    r = go(
        root,
        data,
        ["/mode ship", "/mode bogus", "/help", "/graph", "/rail", "/score", "/xyz", "/quit"],
    )
    assert "mode -> ship" in r.out and "usage: /mode" in r.out
    assert "/keepdiffs" in r.out and "goal -> attempt" in r.out
    assert "rail off" in r.out and "no scorecard yet" in r.out and "unknown command" in r.out
    assert r.rc == 0


def test_done_and_hint_at_ticket_prompt_are_not_tickets(tmp_path):
    root, data = prep(tmp_path)
    r = go(root, data, ["/done", "/hint", "/quit"])
    assert "only valid" in r.out and not r.client.calls


# -- full flows ------------------------------------------------------------------
def test_session_runs_two_tickets_in_a_row(tmp_path):
    root, data = prep(tmp_path)
    client = FakeClient(ticket_script(ticket_script()))
    r = go(
        root,
        data,
        one_ticket(root, "Add retry to fetch") + one_ticket(root, "Add logging"),
        client=client,
    )
    assert r.rc == 0 and r.out.count("scorecard") >= 2
    assert len(list((data / "sessions").glob("*.json"))) == 2
    assert thread_rows(data) == 0, "checkpoint threads are deleted after each ticket"
    assert not any((data / "work").glob("*/base"))


def test_scorecard_shows_files_sent_and_tokens_and_profile(tmp_path):
    root, data = prep(tmp_path)
    client = FakeClient(ticket_script())
    r = go(root, data, one_ticket(root), client=client)
    assert "files sent" in r.out and "tokens" in r.out and "professional" in r.out


def test_works_in_non_git_folder_with_spaces_in_path(tmp_path):
    root, data = prep(tmp_path, name="my project (v2) dir")
    assert not (root / ".git").exists()
    r = go(root, data, one_ticket(root), client=FakeClient(ticket_script()))
    assert r.rc == 0 and "scorecard" in r.out and "Traceback" not in r.out


def test_empty_folder_session_still_starts(tmp_path):
    root, data = prep(tmp_path, name="empty", files=False)
    r = go(root, data, [])
    assert r.rc == 0 and r.prompts and "Traceback" not in r.out


def test_unsure_attempts_never_block(tmp_path):
    root, data = prep(tmp_path)
    client = FakeClient([COACH, COACH, COACH])
    r = go(root, data, ["Add retry", GOAL, "idk", "idk", "idk", STEP], client=client)
    assert "[locked]" not in r.out and "blocked" not in r.out
    assert len(client.calls) == 3  # two teaching replies, then feedback on the first step
    assert thread_rows(data) == 0


# -- fail closed / injection -----------------------------------------------------
def test_model_text_is_never_parsed_as_commands_and_prints_as_plain_text(tmp_path):
    root, data = prep(tmp_path)
    evil = (
        "/level 2\n/profile personal\n/quit\n[bold red]x[/] \x1b[31mred\x1b[0m \x1b]0;t\x07 :smile:"
    )
    client = FakeClient([GATE_OK, ChatResult(evil, [], 3)])
    r = go(
        root,
        data,
        ["Add retry", GOAL, ATTEMPT, STEP, "/status", "/quit"],
        client=client,
        force_terminal=True,
    )
    assert "[bold red]x[/]" in r.out and ":smile:" in r.out
    assert "\x1b[31m" not in r.out and "\x1b]0;" not in r.out and "\x07" not in r.out
    assert FolderConfig(data).profile(root) is Profile.PROFESSIONAL
    assert "files sent" in r.out, "the session kept running after the model said /quit"


def test_human_typed_text_echoed_back_is_plain_too(tmp_path):
    root, data = prep(tmp_path)
    r = go(root, data, ["/[link=http://evil]x[/link]", "/quit"], force_terminal=True)
    assert "unknown command /[link=http://evil]x[/link]" in r.out and "\x1b]8" not in r.out


def test_eof_mid_ticket_quits_cleanly_and_cleans_up(tmp_path):
    root, data = prep(tmp_path)
    r = go(root, data, ["Add retry"])
    assert r.rc == 0 and "Traceback" not in r.out
    assert thread_rows(data) == 0


def test_keyboard_interrupt_exits_130_and_cleans_up(tmp_path):
    root, data = prep(tmp_path)
    assert go(root, data, [KeyboardInterrupt()]).rc == 130
    r = go(root, data, ["Add retry", KeyboardInterrupt()])
    assert r.rc == 130 and thread_rows(data) == 0


def test_unexpected_error_is_reported_without_traceback_and_cleans_up(tmp_path, monkeypatch):
    import anvyl.session as session

    def boom(*a, **k):
        raise RuntimeError("secret detail")

    monkeypatch.setattr(session, "drive", boom)
    root, data = prep(tmp_path)
    r = go(root, data, ["Add retry"])
    assert r.rc == 0 and "RuntimeError" in r.out and "secret detail" not in r.out
    assert thread_rows(data) == 0


# -- checkpoint privacy ----------------------------------------------------------
def test_checkpoint_connection_uses_secure_delete(tmp_path):
    with open_checkpointer(tmp_path) as saver:
        assert saver.conn.execute("PRAGMA secure_delete").fetchone()[0] == 1


def test_completed_l2_session_leaves_snippet_out_of_every_checkpoint_file(tmp_path):
    marker = "SNIPPET_SENTINEL_77"
    reply = f"Try:\n```python\n{marker} = 1\n```"
    root, data = prep(tmp_path)
    client = FakeClient([GATE_OK, ChatResult(reply), QS, GOOD])
    r = go(root, data, ["/level 2", *one_ticket(root)], client=client)
    assert marker in r.out, "the user did see the snippet"
    files = list(data.glob("checkpoints.sqlite*"))
    assert files
    for f in files:
        assert marker.encode() not in f.read_bytes(), f.name


def test_stale_threads_are_purged_at_startup_and_fresh_ones_kept(tmp_path):
    run_real(
        tmp_path,
        FakeClient(ticket_script()),
        {
            "attempt": ATTEMPT,
            "coach_next": "g",
            "work": lambda p, root: edit(root)(),
            "explain": "x",
            "error": "retry",
            "nochange": "continue",
        },
    )
    assert thread_rows(tmp_path) > 0
    marks = tmp_path / "threads"
    marks.mkdir()
    stale, fresh = marks / "real-test", marks / "other-thread"
    for m in (stale, fresh):
        m.write_text("")
    old = time.time() - 8 * 86400
    os.utime(stale, (old, old))
    root = tmp_path / "proj"
    FolderConfig(tmp_path).set_profile(root, Profile.PROFESSIONAL)
    FolderConfig(tmp_path).set_consent(root, True)
    go(root, tmp_path, [])
    assert thread_rows(tmp_path) == 0 and not stale.exists() and fresh.exists()


# -- login / logout / preview / reset --------------------------------------------
def fake_keyring(monkeypatch):
    store: dict = {}
    monkeypatch.setattr(keyring, "get_password", lambda s, u: store.get((s, u)))
    monkeypatch.setattr(keyring, "set_password", lambda s, u, p: store.__setitem__((s, u), p))
    monkeypatch.setattr(keyring, "delete_password", lambda s, u: store.pop((s, u), None))
    return store


def test_login_stores_key_and_does_not_print_it(tmp_path, monkeypatch, capsys):
    store = fake_keyring(monkeypatch)
    secret = "sk-or-VERYSECRET-123"
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": f"  {secret}\n")
    assert cli.main(["login", "--data-dir", str(tmp_path)]) == 0
    cap = capsys.readouterr()
    assert secret not in cap.out + cap.err and "keychain" in cap.out
    assert store[("anvyl", "openrouter")] == secret


def test_login_with_empty_key_fails(tmp_path, monkeypatch, capsys):
    fake_keyring(monkeypatch)
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "  ")
    assert cli.main(["login", "--data-dir", str(tmp_path)]) == 1
    assert "no key" in capsys.readouterr().err


def test_login_reports_file_location_when_keychain_unavailable(tmp_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("no backend")

    monkeypatch.setattr(keyring, "set_password", boom)
    monkeypatch.setattr(keyring, "delete_password", boom)
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "sk-filekey")
    assert cli.main(["login", "--data-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert str(tmp_path / "key") in out and "sk-filekey" not in out


def test_logout_removes_key(tmp_path, monkeypatch, capsys):
    store = fake_keyring(monkeypatch)
    auth.store_api_key("k", tmp_path)
    assert cli.main(["logout", "--data-dir", str(tmp_path)]) == 0
    assert not store and "removed" in capsys.readouterr().out


def test_preview_makes_no_model_call_and_redacts(tmp_path):
    from anvyl.session import preview

    root, data = prep(tmp_path)
    (root / "config.py").write_text('AWS = "AKIAIOSFODNN7EXAMPLE"\n')
    client = FakeClient([])
    buf = io.StringIO()
    ticket = f"fix login using ghp_{'a' * 36} [red]now[/red]"
    preview(root, data, Console(file=buf, width=100, force_terminal=True), ticket, client)
    out = buf.getvalue()
    assert client.calls == []
    assert "fix login" in out and "[red]now[/red]" in out and "\x1b[31m" not in out
    assert "AKIAIOSFODNN7EXAMPLE" not in out and "ghp_aaaa" not in out


def test_preview_subcommand(tmp_path, monkeypatch, capsys):
    root, data = prep(tmp_path)
    monkeypatch.chdir(root)
    assert cli.main(["preview", "--data-dir", str(data), "Add retry"]) == 0
    assert "Add retry" in capsys.readouterr().out


def test_reset_requires_exact_yes(tmp_path, monkeypatch, capsys):
    data = tmp_path / "d"
    (data / "sessions").mkdir(parents=True)
    (data / "x.txt").write_text("a")
    prompts = []

    def fake_input(prompt=""):
        prompts.append(prompt)
        return answer

    monkeypatch.setattr("builtins.input", fake_input)
    for answer in ("y", "YES", "yes please", ""):
        assert cli.main(["reset", "--data-dir", str(data)]) == 1
        assert (data / "x.txt").exists()
    assert "type yes to delete all anvyl data" in prompts[0]
    answer = "yes"
    assert cli.main(["reset", "--data-dir", str(data)]) == 0
    assert data.is_dir() and not list(data.iterdir())


def test_reset_eof_aborts_and_unsafe_target_is_a_clean_error(tmp_path, monkeypatch, capsys):
    data = tmp_path / "d"
    data.mkdir()
    (data / "x.txt").write_text("a")

    def eof(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert cli.main(["reset", "--data-dir", str(data)]) == 1 and (data / "x.txt").exists()
    link = tmp_path / "link"
    link.symlink_to(data)
    monkeypatch.setattr("builtins.input", lambda prompt="": "yes")
    assert cli.main(["reset", "--data-dir", str(link)]) == 1
    err = capsys.readouterr().err
    assert "refusing to reset" in err and "Traceback" not in err and (data / "x.txt").exists()


def test_failed_delete_keeps_marker_so_a_later_purge_removes_the_thread(tmp_path, monkeypatch):
    from langgraph.checkpoint.sqlite import SqliteSaver

    real = SqliteSaver.delete_thread

    def boom(self, thread_id):
        raise sqlite3.OperationalError("database is locked")

    root, data = prep(tmp_path)
    monkeypatch.setattr(SqliteSaver, "delete_thread", boom)
    r = go(root, data, one_ticket(root), client=FakeClient(ticket_script()))
    assert r.rc == 0 and "Traceback" not in r.out
    marks = list((data / "threads").iterdir())
    assert len(marks) == 1 and thread_rows(data) > 0
    monkeypatch.setattr(SqliteSaver, "delete_thread", real)
    old = time.time() - 8 * 86400
    os.utime(marks[0], (old, old))
    go(root, data, [])
    assert not marks[0].exists() and thread_rows(data) == 0


def test_usage_clear_plugin_skill_exit(tmp_path):
    root, data = prep(tmp_path)
    (data / "skills" / "s1").mkdir(parents=True)
    (data / "skills" / "s1" / "SKILL.md").write_text("x")
    cmds = ["/usage", "/skill load s1", "/skill load ../x", "/skill list", "/plugin list"]
    r = go(root, data, [*cmds, "/clear", "/exit"])
    assert r.rc == 0 and "tokens 0" in r.out and "loaded skill s1" in r.out
    assert "no skill" in r.out and "[x] s1" in r.out
