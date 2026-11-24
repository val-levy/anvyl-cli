"""The invoke / interrupt / resume loop, shared by the tutorial and real sessions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from langgraph.errors import GraphInterrupt
from langgraph.types import Command

from .graph import pending_interrupt


def drive(
    graph: Any,
    initial: Mapping | None,
    config: dict,
    answer: Callable[[dict], Any],
    on_state: Callable[[Mapping], None] | None = None,
) -> dict:
    """Run `graph` until it finishes, answering every interrupt with `answer(payload)`.

    A thread that already has a pending interrupt (a resumed session) is answered first.
    `on_state` sees the checkpointed state just before each answer is requested.
    """

    def snapshot() -> None:
        if on_state is None:
            return
        try:
            on_state(graph.get_state(config).values)
        except Exception:
            pass

    pending = None
    payload = pending_interrupt(graph, config)
    if payload is not None:
        pending = Command(resume=answer(payload))
    result: dict = {}
    while True:
        try:
            result = graph.invoke(pending if pending is not None else initial, config)
        except GraphInterrupt as exc:
            # Older LangGraph raises on interrupt; 1.x returns instead.
            interrupts = getattr(exc, "interrupts", [])
            payload = interrupts[0].value if interrupts else None
            if payload is None:
                payload = pending_interrupt(graph, config)
            if payload is None:
                raise
            snapshot()
            pending = Command(resume=answer(payload))
            continue
        pending = None
        payload = pending_interrupt(graph, config)
        if payload is None:
            return result
        snapshot()
        pending = Command(resume=answer(payload))
