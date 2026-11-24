"""Storage: where anvyl keeps its data.

No hardcoded paths. The data dir resolves as:

1. an explicit ``--data-dir`` / constructor argument,
2. the ``ANVYL_HOME`` environment variable,
3. ``~/.anvyl``.

Sessions land in ``<data>/sessions/`` as JSON, the LangGraph
checkpointer lives at ``<data>/checkpoints.sqlite``, and user
skills/plugins live in ``<data>/skills/`` and ``<data>/plugins/``.
Bundled example skills/plugins ship inside the package (``anvyl/data/``)
and are copied into a fresh data dir on first run, so a new install
works with no manual setup.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from importlib import resources
from pathlib import Path

from .judge import CODE_LINE_RE

SCHEMA_VERSION = 2
ENV_VAR = "ANVYL_HOME"
DEFAULT_DIRNAME = ".anvyl"


def resolve_data_dir(explicit: str | Path | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get(ENV_VAR)
    if env:
        return Path(env).expanduser()
    return Path.home() / DEFAULT_DIRNAME


def bundled_data_dir() -> Path:
    """The read-only examples shipped inside the installed package."""
    return Path(str(resources.files("anvyl") / "data"))


def ensure_data_dir(data_dir: str | Path) -> Path:
    """Create the data dir and seed it with bundled examples if empty."""
    data_dir = Path(data_dir)
    (data_dir / "sessions").mkdir(parents=True, exist_ok=True)
    bundled = bundled_data_dir()
    for sub in ("skills", "plugins"):
        target = data_dir / sub
        source = bundled / sub
        if not target.exists() and source.exists():
            shutil.copytree(source, target)
    return data_dir


def sessions_dir(data_dir: str | Path) -> Path:
    return Path(data_dir) / "sessions"


def checkpoints_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / "checkpoints.sqlite"


def save_session(state: dict, sessions_dir_path: str | Path) -> Path:
    """Save one finished (or blocked) run as JSON. Returns the path."""
    sessions_dir_path = Path(sessions_dir_path)
    session_id = _check_session_id(state.get("session_id", f"s-{int(time.time())}"))
    sessions_dir_path.mkdir(parents=True, exist_ok=True)
    path = sessions_dir_path / f"{session_id}.json"
    record: dict = {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "task_id": state.get("task_id"),
        "task_title": state.get("task_title"),
        "goal": state.get("goal"),
        "mode": state.get("mode"),
        "level": state.get("level"),
        "high_stakes": state.get("high_stakes"),
        "human_attempt": state.get("human_attempt"),
        "attempts": state.get("attempts", []),
        "help_rung": state.get("help_rung"),
        "level_history": state.get("level_history", []),
        "events": state.get("events", []),
        "human_lines": state.get("human_lines"),
        "ai_lines": state.get("ai_lines"),
        "ai_suggested_lines": state.get("ai_suggested_lines"),
        "tokens": state.get("tokens"),
        "ownership_score": state.get("ownership_score"),
        "explain_score": state.get("explain_score"),
        "gate_passed": state.get("gate_passed"),
        "gate_blocked": state.get("gate_blocked"),
        "live_model": state.get("live_model"),
        "started_at": state.get("started_at"),
        "finished_at": state.get("finished_at"),
        "time_with_ai_s": state.get("time_with_ai_s"),
        "est_without_ai_s": state.get("est_without_ai_s"),
        "errors": state.get("errors", []),
    }
    if state.get("real"):
        for key in ("profile", "folder"):
            record[key] = state.get(key)
        for key in ("ticket", "goal", "human_attempt", "task_title"):
            record[key] = _scrub_text(state.get(key))
        for key in ("attempts", "questions", "answers", "feedback", "errors"):
            record[key] = _scrub_list(state.get(key))
        record["real"] = True
        record["files_read"] = state.get("files_read") or []
        record["shown_snippets_count"] = len(state.get("shown_snippets") or [])
        events = [_scrub_event(e) for e in state.get("events") or []]
        record["events"] = [e for e in events if e is not None][:50]
        changes = state.get("changes") or {}
        record["changes"] = {k: changes.get(k, 0) for k in ("files", "added", "removed")}
    else:
        record["solution_code"] = state.get("solution_code")
        record["verification"] = state.get("verification")
    path.write_text(json.dumps(record, indent=2, default=str))
    return path


_FENCE_RE = re.compile(r"(```|~~~).*?(\1|\Z)", re.DOTALL)
_INLINE_RE = re.compile(r"`[^\n]*")  # first backtick to end of line; linear
_INDENTED_RE = re.compile(r"^[ \t]+\S")


def _scrub_text(value: object) -> str:
    """Best-effort removal of code from user free text (defense in depth), capped at 500."""
    if not isinstance(value, str):
        return ""
    text = _INLINE_RE.sub("", _FENCE_RE.sub("", value))
    lines = [
        ln for ln in text.splitlines() if not (CODE_LINE_RE.match(ln) or _INDENTED_RE.match(ln))
    ]
    return "\n".join(lines)[:500]


def _scrub_list(value: object) -> list[str]:
    return [_scrub_text(v) for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _scalar(v: object) -> bool:
    return isinstance(v, int | float | bool) or (isinstance(v, str) and len(v) <= 40)


def _scrub_event(event: object) -> object:
    """Keep only short scalars so a diff or file body can't ride along in an event."""
    if isinstance(event, dict):
        return {k: v for k, v in event.items() if isinstance(k, str) and _scalar(k) and _scalar(v)}
    return event if _scalar(event) else None


def _check_session_id(session_id: str) -> str:
    if (
        not session_id
        or session_id in (".", "..")
        or "/" in session_id
        or "\\" in session_id
        or "\0" in session_id
        or Path(session_id).name != session_id
    ):
        raise ValueError(f"invalid session id: {session_id!r}")
    return session_id


def work_dir_for(data_dir: Path, session_id: str) -> Path:
    return Path(data_dir) / "work" / _check_session_id(session_id)


def save_diff(sessions_dir: Path, session_id: str, text: str) -> Path:
    path = Path(sessions_dir) / f"{_check_session_id(session_id)}.diff"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def cleanup_stale_work(data_dir: Path, max_age_days: int = 7) -> int:
    """Remove direct-child work dirs untouched for max_age_days. Returns the count."""
    work = Path(data_dir) / "work"
    if work.is_symlink():
        return 0
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    try:
        children = list(work.iterdir())
    except OSError:
        return 0
    for child in children:
        try:
            if child.is_symlink() or not child.is_dir():
                continue
            if child.stat().st_mtime < cutoff:
                shutil.rmtree(child)
                removed += 1
        except OSError:
            continue
    return removed


def reset_data(data_dir: Path) -> None:
    """Delete the contents of data_dir (not the dir itself); refuses unsafe targets."""
    raw = str(data_dir)
    if raw in ("", "."):
        raise ValueError("refusing to reset: empty path")
    path = Path(data_dir)
    if not path.is_absolute():
        raise ValueError(f"refusing to reset: not an absolute path: {path}")
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"refusing to reset: not a real directory: {path}")
    real = path.resolve()
    home = Path.home().resolve()
    if real == real.parent or real == home or real in home.parents:
        raise ValueError(f"refusing to reset: {real}")
    for child in path.iterdir():
        if child.is_symlink() or not child.is_dir():
            child.unlink()
        else:
            shutil.rmtree(child)
