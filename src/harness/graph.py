"""The LangGraph directed graph.

Nodes: goal -> attempt_gate -> coach -> implement -> explain_back ->
scorecard. Ship mode takes the fast path: goal -> ship_implement ->
scorecard (explain_back only if high_stakes).

The attempt gate is a real graph edge, not a prompt. In Learn mode there
is no edge from the gate to the coach or to any code until a human
attempt is in typed state. Human input arrives through LangGraph
``interrupt()`` + resume, with the SQLite checkpointer making the
session resumable: a blocked session can be resumed later from the
same thread id.
"""

from __future__ import annotations

import time
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from . import policy, tasks
from .coach import Coach
from .state import HarnessState
from .storage import save_session

LOOP_STEPS = ["goal", "attempt", "coach", "implement", "explain-back", "scorecard"]


def pending_interrupt(graph, config) -> dict | None:
    """Return the pending interrupt payload for this thread, if any.

    In LangGraph 1.x, ``invoke()`` returns (rather than raising) when a
    node calls ``interrupt()``. The pending interrupt lives on the
    checkpoint snapshot: ``get_state().next`` names the blocked node and
    ``tasks[0].interrupts[0].value`` is the payload the node asked for.
    The driver answers it and resumes with ``Command(resume=answer)``.
    """
    try:
        snapshot = graph.get_state(config)
    except Exception:
        return None
    if not snapshot or not snapshot.next:
        return None
    for task in snapshot.tasks or []:
        for intr in getattr(task, "interrupts", []) or []:
            return intr.value
    return None


def build_graph(task: dict, coach: Coach, sessions_dir, checkpointer) -> Any:
    graph = StateGraph(HarnessState)

    # -- nodes ---------------------------------------------------------
    def goal_node(state: HarnessState) -> dict:
        goal = (state.get("goal") or "").strip()
        if not goal:
            goal = interrupt(
                {
                    "kind": "goal",
                    "prompt": "State the goal in your own words (one or two sentences):",
                }
            )
        return {
            "goal": goal,
            "current_node": "goal",
            "events": [f"goal set: {goal[:80]}"],
        }

    def attempt_gate_node(state: HarnessState) -> dict:
        if state.get("mode") == "ship":
            return {"gate_passed": True, "current_node": "attempt_gate"}
        if policy.gate_passed(dict(state)):
            return {"gate_passed": True, "current_node": "attempt_gate"}
        # Hard gate: no edge onward until a human attempt exists. This
        # interrupt is the only way past; the model cannot answer it.
        attempt = interrupt(
            {
                "kind": "attempt",
                "prompt": (
                    "[locked] attempt gate - AI cannot write code yet.\n"
                    "Write your attempt first: a plan or pseudocode in your own "
                    "words. It can be wrong; it cannot be empty."
                ),
            }
        )
        attempt = (attempt or "").strip()
        passed = policy.gate_passed({**state, "human_attempt": attempt})
        return {
            "human_attempt": attempt,
            "attempts": [attempt] if attempt else [],
            "gate_passed": passed,
            "gate_blocked": not passed,
            "current_node": "attempt_gate",
            "events": [
                f"attempt gate {'passed' if passed else 'BLOCKED (attempt too short/empty)'}"
            ],
        }

    def coach_node(state: HarnessState) -> dict:
        messages: list[str] = []
        rung = int(state.get("help_rung", 0))
        tokens = int(state.get("tokens", 0))
        events: list[str] = []
        any_live = bool(state.get("live_model"))
        while True:
            local = dict(state)
            local["help_rung"] = rung
            result = coach.reply(task, local)
            messages.append(result["text"])
            tokens += result["tokens"]
            if result["stripped"]:
                events.append(f"policy stripped {result['stripped']} code item(s) from coach reply")
            if result["live"]:
                any_live = True
                events.append("coach reply from live model (Claude via OpenRouter)")
            choice = interrupt(
                {
                    "kind": "coach_next",
                    "text": result["text"],
                    "prompt": "[h]int for a deeper hint, [g]o to implement:",
                }
            )
            choice = (choice or "").strip().lower()
            if choice in ("h", "hint", "/hint"):
                rung = min(rung + 1, policy.MAX_RUNG)
                events.append(f"help rung -> {rung}")
                continue
            break
        return {
            "coach_messages": messages,
            "help_rung": rung,
            "tokens": tokens,
            "live_model": any_live,
            "current_node": "coach",
            "events": events,
        }

    def implement_node(state: HarnessState) -> dict | Command:
        level = int(state.get("level", 1))
        hint = (
            "Type the code, then /done on its own line. Type /hint to go back to the coach."
            if level <= 2
            else "Type the code (edit the AI draft if one was shown), then /done. "
            "Type /hint to go back to the coach."
        )
        code = interrupt({"kind": "code", "prompt": f"[implement] you type.\n{hint}"})
        code = (code or "").strip()
        if code.startswith("/hint"):
            return Command(
                goto="coach",
                update={
                    "help_rung": min(int(state.get("help_rung", 0)) + 1, policy.MAX_RUNG),
                    "current_node": "coach",
                    "events": ["went back to coach for a deeper hint"],
                },
            )
        lines = [ln for ln in code.splitlines() if ln.strip()]
        verification = task["verify"](code) if code else {"passed": False, "checks": []}
        passed = verification.get("passed")
        return {
            "solution_code": code,
            "human_lines": len(lines),
            "ai_lines": 0,
            "verification": verification,
            "current_node": "implement",
            "events": [f"implement: {len(lines)} lines typed by human, verify passed={passed}"],
        }

    def ship_implement_node(state: HarnessState) -> dict:
        # Ship mode: AI may draft. Live model if requested, else the
        # task's reference draft (clearly marked as a demo draft).
        draft = ""
        live = False
        if coach.live_requested:
            draft_text = coach.live_call(
                "You are a coding assistant. Write the implementation, concise and correct.",
                f"Task: {task.get('title', '')}\nGoal: {state.get('goal', '')}\n"
                "Write the full implementation as code.",
            )
            if draft_text:
                draft = draft_text
                live = True
        if not draft:
            draft = task["scripted_code"]
        choice = interrupt(
            {
                "kind": "review",
                "text": draft,
                "prompt": (
                    "[ship] AI draft above. Type ok to accept, or paste "
                    "your edited version, then /done:"
                ),
            }
        )
        choice = (choice or "").strip()
        if choice.lower() in ("ok", "okay", "accept", ""):
            code = draft
            human_lines = 0
            ai_lines = len([ln for ln in draft.splitlines() if ln.strip()])
            events = ["ship: AI draft accepted as-is"]
        else:
            code = choice
            human_lines = len([ln for ln in code.splitlines() if ln.strip()])
            ai_lines = 0
            events = ["ship: AI draft edited by human"]
        verification = task["verify"](code) if code else {"passed": False, "checks": []}
        return {
            "solution_code": code,
            "human_lines": human_lines,
            "ai_lines": ai_lines,
            "live_model": bool(state.get("live_model")) or live,
            "verification": verification,
            "current_node": "implement",
            "events": events + [f"ship verify passed={verification.get('passed')}"],
        }

    def explain_back_node(state: HarnessState) -> dict:
        quiz = task["quiz"]
        correct = 0
        events: list[str] = []
        for i, item in enumerate(quiz):
            answer = interrupt(
                {
                    "kind": "explain",
                    "question": item["q"],
                    "index": i,
                    "prompt": f"[explain-back {i + 1}/{len(quiz)}] {item['q']}",
                }
            )
            ok = tasks.score_answer(answer or "", item["keywords"])
            correct += 1 if ok else 0
            events.append(f"explain-back Q{i + 1}: {'correct' if ok else 'missed'}")
        score = correct / len(quiz) if quiz else 0.0
        return {
            "explain_score": score,
            "ownership_score": score,
            "current_node": "explain-back",
            "events": events,
        }

    def scorecard_node(state: HarnessState) -> dict:
        now = time.time()
        new_level = policy.auto_drop_level(dict(state))
        events = list(state.get("events", []))
        if new_level != int(state.get("level", 1)):
            ownership = float(state.get("ownership_score", 0))
            events.append(
                f"level auto-dropped L{state.get('level')} -> L{new_level} "
                f"(ownership {ownership:.2f})"
            )
        out = {
            "finished_at": now,
            "time_with_ai_s": now - float(state.get("started_at", now)),
            "level": new_level,
            "level_history": [new_level],
            "current_node": "scorecard",
            "events": events,
        }
        save_session({**state, **out}, sessions_dir)
        return out

    # -- routing -------------------------------------------------------
    def route_after_goal(state: HarnessState) -> str:
        return "ship_implement" if state.get("mode") == "ship" else "attempt_gate"

    def route_after_gate(state: HarnessState) -> str:
        return "coach" if state.get("gate_passed") else END

    def route_after_ship(state: HarnessState) -> str:
        return "explain_back" if policy.explainback_required(dict(state)) else "scorecard"

    graph.add_node("goal", goal_node)
    graph.add_node("attempt_gate", attempt_gate_node)
    graph.add_node("coach", coach_node)
    graph.add_node("implement", implement_node)
    graph.add_node("ship_implement", ship_implement_node)
    graph.add_node("explain_back", explain_back_node)
    graph.add_node("scorecard", scorecard_node)

    graph.add_edge(START, "goal")
    graph.add_conditional_edges("goal", route_after_goal)
    graph.add_conditional_edges("attempt_gate", route_after_gate)
    graph.add_edge("coach", "implement")
    graph.add_edge("implement", "explain_back")
    graph.add_conditional_edges("ship_implement", route_after_ship)
    graph.add_edge("explain_back", "scorecard")
    graph.add_edge("scorecard", END)

    return graph.compile(checkpointer=checkpointer)
