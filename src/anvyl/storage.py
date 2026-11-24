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
import shutil
import time
from importlib import resources
from pathlib import Path

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
    sessions_dir_path.mkdir(parents=True, exist_ok=True)
    session_id = state.get("session_id", f"s-{int(time.time())}")
    path = sessions_dir_path / f"{session_id}.json"
    record = {
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
        "solution_code": state.get("solution_code"),
        "verification": state.get("verification"),
        "live_model": state.get("live_model"),
        "started_at": state.get("started_at"),
        "finished_at": state.get("finished_at"),
        "time_with_ai_s": state.get("time_with_ai_s"),
        "est_without_ai_s": state.get("est_without_ai_s"),
        "errors": state.get("errors", []),
    }
    path.write_text(json.dumps(record, indent=2, default=str))
    return path
