"""Typed state for the harness graph.

Every field the graph reads or writes lives here, so a session can be
replayed and audited from its saved JSON. Lists that grow over a run use
``operator.add`` reducers so LangGraph appends instead of overwriting.
"""

from __future__ import annotations

from operator import add
from typing import Annotated, TypedDict


class HarnessState(TypedDict, total=False):
    # Identity / task
    session_id: str
    task_id: str
    task_title: str
    goal: str

    # Mode and control level (spec: Ship vs Learn, L0-L4)
    mode: str  # "ship" | "learn"
    level: int  # 0-4
    high_stakes: bool

    # The Learn loop
    human_attempt: str
    attempts: Annotated[list, add]
    help_rung: int  # 0-3, coach hint ladder
    current_node: str
    coach_messages: Annotated[list, add]

    # Attribution / observability
    human_lines: int
    ai_lines: int
    ai_suggested_lines: int
    tokens: int
    ownership_score: float  # 0.0-1.0, from explain-back
    explain_score: float  # 0.0-1.0
    level_history: Annotated[list, add]
    events: Annotated[list, add]

    # Timing
    started_at: float
    finished_at: float
    time_with_ai_s: float
    est_without_ai_s: float

    # Gate / enforcement
    gate_blocked: bool
    gate_passed: bool
    solution_code: str
    verification: dict

    # Runtime flags
    live_model: bool  # True only if a live model call actually ran
    demo: bool
    rail_visible: bool
    errors: Annotated[list, add]


def initial_state(
    session_id: str,
    task_id: str,
    task_title: str,
    goal: str,
    mode: str = "learn",
    level: int = 1,
    high_stakes: bool = False,
    demo: bool = False,
    est_without_ai_s: float = 0.0,
) -> HarnessState:
    """Build the starting state for one task run."""
    import time

    return HarnessState(
        session_id=session_id,
        task_id=task_id,
        task_title=task_title,
        goal=goal,
        mode=mode,
        level=level,
        high_stakes=high_stakes,
        human_attempt="",
        attempts=[],
        help_rung=0,
        current_node="goal",
        coach_messages=[],
        human_lines=0,
        ai_lines=0,
        ai_suggested_lines=0,
        tokens=0,
        ownership_score=0.0,
        explain_score=0.0,
        level_history=[level],
        events=[f"session {session_id} started: {task_id} mode={mode} level=L{level}"],
        started_at=time.time(),
        finished_at=0.0,
        time_with_ai_s=0.0,
        est_without_ai_s=est_without_ai_s,
        gate_blocked=False,
        # Ship mode has no attempt gate: the gate is open by definition.
        gate_passed=(mode == "ship"),
        solution_code="",
        verification={},
        live_model=False,
        demo=demo,
        rail_visible=True,
        errors=[],
    )
