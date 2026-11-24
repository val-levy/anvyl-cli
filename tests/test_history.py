import io
import json

from rich.console import Console

from anvyl import cli
from anvyl.history import load_sessions, render_history, summary_lines


def _write(d, name, rec):
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.json").write_text(rec if isinstance(rec, str) else json.dumps(rec))


def _rec(i, level, own, **kw):
    r = {
        "session_id": f"s{i}",
        "task_title": f"t{i}",
        "mode": "learn",
        "level": level,
        "ownership_score": own,
        "started_at": 1_700_000_000 + i,
        "human_lines": 3,
        "ai_lines": 1,
        "time_with_ai_s": 60,
        "est_without_ai_s": 120,
    }
    r.update(kw)
    return r


def _out(rows):
    buf = io.StringIO()
    render_history(rows, Console(file=buf, width=200, force_terminal=False))
    return buf.getvalue()


def test_load_skips_corrupt_and_handles_old_schema(tmp_path):
    _write(tmp_path, "bad", "{not json")
    _write(tmp_path, "list", "[1, 2]")
    _write(tmp_path, "old", {"session_id": "old", "level": 1})
    _write(tmp_path, "new", {"schema_version": 2, "profile": "web", "level": 2})
    rows = {r["session_id"] if "session_id" in r else "new": r for r in load_sessions(tmp_path)}
    assert len(rows) == 2
    assert rows["old"]["schema_version"] == 1 and rows["old"]["profile"] == "tutorial"
    assert rows["new"]["profile"] == "web"


def test_summary_mean_ownership_by_level():
    rows = [_rec(1, 1, 1.0), _rec(2, 1, 0.5), _rec(3, 2, 0.4), _rec(4, 2, None)]
    text = "\n".join(summary_lines(rows))
    assert "L1 75%" in text and "L2 40%" in text  # None excluded, not a zero


def test_no_sessions_prints_friendly_message(tmp_path, monkeypatch, capsys):
    assert "No sessions" in _out([])
    monkeypatch.setenv("ANVYL_HOME", str(tmp_path / "home"))
    assert cli.main(["history"]) == 0
    assert "No sessions" in capsys.readouterr().out
    assert not (tmp_path / "home").exists()


def test_correlation_line_needs_three_each():
    def line(n1, n2):
        rows = [_rec(i, 1, 0.9) for i in range(n1)] + [_rec(10 + i, 2, 0.3) for i in range(n2)]
        return "\n".join(summary_lines(rows))

    assert "lower" in line(3, 3)
    assert "lower" not in line(3, 2)
    assert "lower" not in line(2, 3)


def test_untrusted_strings_print_literally():
    rows = [_rec(1, 1, 0.5, task_title="[bold red]x[/] \x1b[31mred\x1b[0m", mode="[b]m[/]")]
    out = _out(rows)
    assert "[bold red]x[/]" in out and "\x1b" not in out and "[b]m[/]" in out


def test_malformed_records_never_raise():
    rows = [
        _rec(1, 1, "abc"),
        _rec(2, "x", 10**400, human_lines="a", ai_lines=[1]),
        _rec(3, 2, float("nan"), time_with_ai_s={}, est_without_ai_s=0),
        _rec(4, 1, True, started_at="yesterday", task_title=["a"], profile=7),
        {"level": 99999999999999999999},
        {},
    ]
    assert _out(rows)
    assert summary_lines(rows) is not None


def test_cli_history(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setenv("ANVYL_HOME", str(tmp_path))
    _write(tmp_path / "sessions", "a", _rec(1, 1, 0.5, task_title="My ticket"))
    assert cli.main(["history"]) == 0
    out = capsys.readouterr().out
    assert "My ticket" in out and "L1 50%" in out


def test_correlation_counts_only_scored_sessions():
    rows = [_rec(i, 1, 0.9) for i in range(3)]
    rows += [_rec(10, 2, 0.3), _rec(11, 2, None), _rec(12, 2, None)]
    assert "lower" not in "\n".join(summary_lines(rows))
    rows[4]["ownership_score"] = rows[5]["ownership_score"] = 0.3
    assert "lower" in "\n".join(summary_lines(rows))


def test_load_skips_symlinks_dirs_and_oversize(tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"session_id": "evil"}))
    d = tmp_path / "sessions"
    d.mkdir()
    (d / "link.json").symlink_to(outside)
    (d / "dir.json").mkdir()
    (d / "big.json").write_text(json.dumps({"session_id": "big", "pad": "x" * 1_100_000}))
    _write(d, "ok", {"session_id": "ok"})
    assert [r["session_id"] for r in load_sessions(d)] == ["ok"]


def test_minutes_dash_for_nonpositive():
    from anvyl.history import _mins

    assert _mins(0) == "-" and _mins(-5) == "-" and _mins(120) == "2m"
