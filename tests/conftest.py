"""Shared helpers for the anvyl tests."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

# Make the src layout importable whether or not the package is installed.
sys.path.insert(0, str(Path(__file__).parent.parent))

from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: E402
from langgraph.errors import GraphInterrupt  # noqa: E402
from langgraph.types import Command  # noqa: E402

from anvyl import tasks as tasks_mod  # noqa: E402
from anvyl.cli import ScriptedProvider  # noqa: E402
from anvyl.coach import Coach  # noqa: E402
from anvyl.graph import build_graph, build_real_graph, pending_interrupt  # noqa: E402
from anvyl.profile import Profile  # noqa: E402
from anvyl.real_coach import RealCoach  # noqa: E402
from anvyl.state import initial_real_state, initial_state  # noqa: E402


def run_task(
    task_id,
    mode="learn",
    level=1,
    high_stakes=False,
    tmp_path=None,
    live=False,
    provider=None,
    client=None,
):
    """Drive one full graph run with scripted answers. Returns the final state."""
    task = tasks_mod.get_task(task_id)
    coach = Coach(live=live, client=client)
    session_id = f"test-{task_id}-{mode}-L{level}"
    state0 = initial_state(
        session_id=session_id,
        task_id=task["id"],
        task_title=task["title"],
        goal=task["goal_prompt"],
        mode=mode,
        level=level,
        high_stakes=high_stakes,
        demo=True,
        est_without_ai_s=task["est_without_ai_s"],
    )
    provider = provider if provider is not None else ScriptedProvider(task)
    sessions_dir = tmp_path / "sessions"
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as cp:
        graph = build_graph(task, coach, sessions_dir, cp)
        config = {"configurable": {"thread_id": session_id}}
        pending = None
        result = None
        while True:
            try:
                result = graph.invoke(pending if pending is not None else state0, config)
            except GraphInterrupt as exc:
                pending = Command(resume=provider.answer(exc.interrupts[0].value, None))
                continue
            pending = None
            payload = pending_interrupt(graph, config)
            if payload is None:
                break
            pending = Command(resume=provider.answer(payload, None))
    return result


class FixedProvider:
    """Answer every interrupt from a fixed mapping, for gate tests."""

    def __init__(self, answers: dict):
        self.answers = answers

    def answer(self, payload, ctx):
        return self.answers.get(payload.get("kind"), "")


def run_real(
    tmp_path,
    client,
    answers,
    mode="learn",
    level=1,
    ticket="Add retry to fetch",
    high_stakes=False,
    keep_diffs=False,
    can_read_files=True,
):
    """Drive build_real_graph with scripted answers.

    `answers` maps interrupt kind -> str | callable(payload, root) | list of those
    (consumed in order, the last one repeats). Returns a namespace with the final
    `state`, every interrupt `payloads` seen, `root`, `sessions` and raw checkpoint `db` bytes.
    """
    root = tmp_path / "proj"
    root.mkdir(parents=True, exist_ok=True)
    (root / "app.py").write_text("x = 1\n")
    work_dir, sessions = tmp_path / "work", tmp_path / "sessions"
    session_id = "real-test"
    state0 = initial_real_state(
        session_id, ticket, str(root), "professional", mode, level, high_stakes, str(work_dir)
    )
    coach = RealCoach(client, root, Profile.PROFESSIONAL, can_read_files=can_read_files)
    defaults = {
        "tutor": "I would wrap the fetch call in a loop that retries with a growing delay",
    }
    queues = {
        k: list(v) if isinstance(v, list) else [v] for k, v in {**defaults, **answers}.items()
    }
    payloads: list[dict] = []

    def answer(payload):
        q = queues[payload["kind"]]
        value = q.pop(0) if len(q) > 1 else q[0]
        return value(payload, root) if callable(value) else value

    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as cp:
        graph = build_real_graph(
            coach, client, root, Profile.PROFESSIONAL, sessions, work_dir, cp, keep_diffs
        )
        config = {"configurable": {"thread_id": session_id}}
        graph.invoke(state0, config)
        while (payload := pending_interrupt(graph, config)) is not None:
            payloads.append(payload)
            graph.invoke(Command(resume=answer(payload)), config)
        state = graph.get_state(config).values
    db = b"".join(p.read_bytes() for p in tmp_path.glob("checkpoints.sqlite*"))
    return SimpleNamespace(
        state=state, payloads=payloads, root=root, sessions=sessions, db=db, work_dir=work_dir
    )
