"""First-run welcome menu, /welcome and `anvyl --welcome`."""

import re
from pathlib import Path

from test_session import go, prep

from anvyl import cli, session, tui, welcome


def all_text():
    return "\n".join(line for _, lines in welcome.PAGES for line in lines)


def test_first_run_shows_welcome_then_marks_seen(tmp_path):
    root, data = prep(tmp_path)
    r = go(root, data, ["/quit"])
    assert "What Anvyl is" in r.out and welcome.seen(data)


def test_second_run_skips_welcome(tmp_path):
    root, data = prep(tmp_path)
    go(root, data, ["/quit"])
    r = go(root, data, ["/quit"])
    assert "What Anvyl is" not in r.out


def test_welcome_command_reopens_and_does_not_reset_marker(tmp_path):
    root, data = prep(tmp_path)
    go(root, data, ["/quit"])
    stamp = (data / "welcomed").stat().st_mtime_ns
    r = go(root, data, ["/welcome", "/quit"])
    assert "What Anvyl is" in r.out
    assert (data / "welcomed").stat().st_mtime_ns == stamp


def test_welcome_flag_replays_menu_then_exits(tmp_path, capsys):
    data = tmp_path / "data"
    welcome.mark_seen(data)
    stamp = (data / "welcomed").stat().st_mtime_ns
    assert cli.main(["--welcome", "--data-dir", str(data)]) == 0
    out = capsys.readouterr().out
    assert "What Anvyl is" in out and "Privacy" in out
    assert not (data / "sessions").exists()  # no session was started
    assert (data / "welcomed").stat().st_mtime_ns == stamp


def test_welcome_cli_prints_all_pages_plain(tmp_path, capsys):
    assert cli.main(["welcome", "--data-dir", str(tmp_path / "d")]) == 0
    out = capsys.readouterr().out
    assert all(title in out for title, _ in welcome.PAGES) and "\x1b" not in out


def test_non_interactive_never_blocks(tmp_path):
    root, data = prep(tmp_path)
    r = go(root, data, [])  # EOF straight away
    assert r.rc == 0 and welcome.seen(data)


def test_welcome_file_is_private(tmp_path):
    welcome.mark_seen(tmp_path / "d")
    assert (tmp_path / "d" / "welcomed").stat().st_mode & 0o777 == 0o600


def test_every_slash_command_in_tui_appears_in_commands_page():
    commands_page = dict(welcome.PAGES)["Commands"]
    text = "\n".join(commands_page)
    assert all(c in text for c in tui.COMMANDS)
    handled = set(re.findall(r'cmd == "(/\w+)"', Path(session.__file__).read_text()))
    assert handled <= set(tui.COMMANDS), handled - set(tui.COMMANDS)
    assert "/welcome" in tui.COMMANDS
