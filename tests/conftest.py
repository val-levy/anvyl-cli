"""Shared helpers for the harness tests."""

from __future__ import annotations

import sys
from pathlib import Path

# Make the src layout importable whether or not the package is installed.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: E402
from langgraph.errors import GraphInterrupt  # noqa: E402
from langgraph.types import Command  # noqa: E402

from anvyl import tasks as tasks_mod  # noqa: E402
from anvyl.cli import ScriptedProvider  # noqa: E402
from anvyl.coach import Coach  # noqa: E402
from anvyl.graph import build_graph, pending_interrupt  # noqa: E402
from anvyl.state import initial_state  # noqa: E402


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
