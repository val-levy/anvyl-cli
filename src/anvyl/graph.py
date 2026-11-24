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

import hashlib
import time
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from . import changes as changes_mod
from . import grader, guard, policy, tasks
from .coach import Coach
from .llm import ModelClient, ModelError
from .profile import Profile
from .real_coach import RealCoach
from .state import HarnessState
from .storage import save_diff, save_session

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


# -- real-project sessions ---------------------------------------------------
GATE_TRIES = 3
FAULT = (
    "The model could not be used just now (unavailable or unusable reply). "
    "Nothing was scored. Type retry to try again, or quit to end without scoring."
)
NO_COACH_L0 = "(the coach is off at level 0)"


def hash_lines(text: str) -> list[str]:
    """sha256 of each whitespace-normalized non-blank, non-fence line.

    Checkpoints are written to disk, so shown snippets are stored only as these digests.
    """
    return [
        hashlib.sha256(n.encode()).hexdigest()
        for ln in text.splitlines()
        if not ln.lstrip().startswith("```") and (n := " ".join(ln.split()))
    ]


def build_real_graph(
    coach: RealCoach,
    client: ModelClient,
    root: Path,
    profile: Profile,
    sessions_dir: Path,
    work_dir: Path,
    checkpointer,
    keep_diffs: bool = False,
) -> Any:
    """Graph for real tickets. Every node returns a Command, so there are no static edges.

    Interrupts come first in a node and model work after them, so a resume never
    repeats a model call. A ModelError is a denial: the node records a fixed safe
    fault and re-enters, asking retry/quit; nothing is passed, scored or raised.
    """
    graph = StateGraph(HarnessState)
    outbox: dict[str, str] = {}  # coach text for the wait node; kept out of checkpointed state

    def red(text: str) -> str:
        return guard.redact(text)[0]

    def quit_cmd(state: HarnessState) -> Command:
        changes_mod.clear_snapshot(work_dir)
        return Command(
            goto=END,
            update={
                "fault": "",
                "quit": True,
                "events": ["session ended by user after a model error; nothing scored"],
            },
        )

    def faulted(state: HarnessState) -> bool:
        """True if a pending model error was answered with anything but 'retry'."""
        if not state.get("fault"):
            return False
        choice = interrupt({"kind": "error", "message": FAULT, "prompt": "[retry/quit]:"})
        return str(choice or "").strip().lower() != "retry"

    def fault_update(node: str) -> dict:
        return {"fault": FAULT, "errors": [f"{node}: model error"], "current_node": node}

    def fail(node: str) -> Command:
        return Command(goto=node, update=fault_update(node))

    def diff_text() -> str:
        c = changes_mod.compute_changes(root, profile, work_dir)
        if coach.can_read_files:
            return c.text
        # Ticket-and-plan-only: nothing from the diff (added lines can carry old text).
        return ""

    # -- nodes -----------------------------------------------------------
    def ticket_node(state: HarnessState) -> Command:
        ticket = (state.get("ticket") or "").strip()
        if not ticket:
            ticket = str(
                interrupt({"kind": "ticket", "prompt": "Describe the ticket or task:"}) or ""
            ).strip()
        return Command(
            goto="triage", update={"ticket": ticket, "goal": ticket, "current_node": "ticket"}
        )

    def triage_node(state: HarnessState) -> Command:
        stakes = bool(state.get("high_stakes")) or policy.high_stakes(state.get("ticket"), [])
        return Command(
            goto="implement" if state.get("mode") == "ship" else "attempt_gate",
            update={"high_stakes": stakes, "current_node": "triage"},
        )

    def attempt_gate_node(state: HarnessState) -> Command:
        if faulted(state):
            return quit_cmd(state)
        tries = int(state.get("gate_tries", 0))
        update: dict = {"fault": "", "current_node": "attempt_gate"}
        if state.get("fault"):
            attempt = state.get("human_attempt") or ""  # retry: same attempt, no new try
        else:
            prompt = state.get("gate_reason") or (
                "[locked] attempt gate - AI cannot write code yet.\n"
                "Write your attempt first: a plan in your own words. It can be wrong."
            )
            attempt = str(interrupt({"kind": "attempt", "prompt": prompt}) or "").strip()
            tries += 1
            update.update(
                human_attempt=attempt, attempts=[attempt] if attempt else [], gate_tries=tries
            )
        ticket = state.get("ticket") or ""
        ok, reason = policy.attempt_floor(attempt, ticket)
        if ok:
            try:
                ok, reason = grader.check_attempt(client, red(ticket), red(attempt))
            except ModelError:
                return Command(
                    goto="attempt_gate", update={**update, **fault_update("attempt_gate")}
                )
        if ok:
            return Command(
                goto="coach" if state.get("mode") != "ship" else "implement",
                update={
                    **update,
                    "gate_passed": True,
                    "gate_blocked": False,
                    "gate_reason": "",
                    "events": ["attempt gate passed"],
                },
            )
        if tries >= GATE_TRIES:
            return Command(
                goto=END,
                update={
                    **update,
                    "gate_passed": False,
                    "gate_blocked": True,
                    "events": [f"attempt gate BLOCKED after {tries} tries"],
                },
            )
        return Command(goto="attempt_gate", update={**update, "gate_reason": reason})

    def coach_node(state: HarnessState) -> Command:
        if faulted(state):
            return quit_cmd(state)
        level = policy.clamp_real_level(int(state.get("level", 1)))
        try:
            result = coach.reply({**state, "level": level})
        except ModelError:
            return fail("coach")
        outbox[str(state.get("session_id"))] = result["text"] or NO_COACH_L0
        seen = list(state.get("files_read") or [])
        return Command(
            goto="coach_wait",
            update={
                "fault": "",
                "tokens": int(state.get("tokens", 0)) + result["tokens"],
                "shown_snippets": [h for sn in result["snippets"] for h in hash_lines(sn)],
                "files_read": [f for f in result["files_read"] if f not in seen],
                "events": (
                    [f"policy stripped {result['stripped']} code item(s) from coach reply"]
                    if result["stripped"]
                    else []
                ),
                "current_node": "coach",
            },
        )

    def coach_wait_node(state: HarnessState) -> Command:
        text = outbox.get(str(state.get("session_id")), "")
        if not text:  # resumed in a new process: the reply is gone, ask again
            return Command(goto="coach")
        choice = interrupt(
            {
                "kind": "coach_next",
                "text": text,
                "prompt": "[h]int for a deeper hint, [g]o to implement:",
            }
        )
        outbox.pop(str(state.get("session_id")), None)  # after the interrupt: replay needs it
        if str(choice or "").strip().lower() in ("h", "hint", "/hint"):
            return Command(
                goto="coach",
                update={
                    "help_rung": min(int(state.get("help_rung", 0)) + 1, policy.MAX_RUNG),
                    "events": ["asked the coach for a deeper hint"],
                },
            )
        return Command(goto="implement", update={"current_node": "coach"})

    def implement_node(state: HarnessState) -> Command:
        if not (work_dir / "base").is_dir():
            changes_mod.take_snapshot(root, profile, work_dir)
        choice = (
            str(
                interrupt(
                    {
                        "kind": "work",
                        "prompt": "[implement] you edit the files. Type /done when finished, "
                        "or /hint for the coach.",
                    }
                )
                or ""
            )
            .strip()
            .lower()
        )
        if choice == "/hint":
            return Command(
                goto="coach",
                update={
                    "help_rung": min(int(state.get("help_rung", 0)) + 1, policy.MAX_RUNG),
                    "current_node": "implement",
                },
            )
        return Command(
            goto="review" if choice == "/done" else "implement",
            update={"current_node": "implement"},
        )

    def review_node(state: HarnessState) -> Command:
        c = changes_mod.compute_changes(root, profile, work_dir)
        update: dict = {"current_node": "review"}
        if not c.files:
            choice = (
                str(
                    interrupt(
                        {
                            "kind": "nochange",
                            "prompt": "No changes found. Type continue to keep working or abandon.",
                        }
                    )
                    or ""
                )
                .strip()
                .lower()
            )
            if choice == "abandon":
                return Command(
                    goto="scorecard",
                    update={
                        **update,
                        "abandoned": True,
                        "events": ["session abandoned: no changes"],
                    },
                )
            return Command(goto="implement" if choice == "continue" else "review", update=update)
        added = [h for ln in c.added_lines for h in hash_lines(ln)]
        ai = changes_mod.count_ai_lines(added, list(state.get("shown_snippets") or []))
        merged = {
            **state,
            "high_stakes": state.get("high_stakes") or policy.high_stakes("", c.files),
        }
        return Command(
            goto="explain_questions" if policy.explainback_required(merged) else "scorecard",
            update={
                **update,
                "high_stakes": bool(merged["high_stakes"]),
                "changes": {"files": len(c.files), "added": c.added, "removed": c.removed},
                "ai_lines": ai,
                "human_lines": max(c.added - ai, 0),
            },
        )

    def explain_questions_node(state: HarnessState) -> Command:
        if faulted(state):
            return quit_cmd(state)
        try:
            qs = grader.generate_questions(client, red(state.get("ticket") or ""), red(diff_text()))
        except ModelError:
            return fail("explain_questions")
        return Command(
            goto="explain_answers",
            update={"fault": "", "questions": qs, "current_node": "explain_questions"},
        )

    def explain_answers_node(state: HarnessState) -> Command:
        qs = state.get("questions") or []
        answers = [
            str(
                interrupt(
                    {
                        "kind": "explain",
                        "question": q,
                        "index": i,
                        "prompt": f"[explain-back {i + 1}/{len(qs)}] {q}",
                    }
                )
                or ""
            ).strip()
            for i, q in enumerate(qs)
        ]
        return Command(
            goto="explain_grade", update={"answers": answers, "current_node": "explain_answers"}
        )

    def explain_grade_node(state: HarnessState) -> Command:
        if faulted(state):
            return quit_cmd(state)
        qa = list(zip(state.get("questions") or [], state.get("answers") or []))
        try:
            grade = grader.grade_answers(client, red(diff_text()), qa)
        except ModelError:
            return fail("explain_grade")
        return Command(
            goto="scorecard",
            update={
                "fault": "",
                "feedback": grade.feedback,
                "explain_score": grade.score,
                "ownership_score": grade.score,
                "current_node": "explain_grade",
                "events": [f"explain-back graded: {sum(grade.correct)}/{len(qa)} correct"],
            },
        )

    def scorecard_node(state: HarnessState) -> Command:
        now = time.time()
        scored = {**state} if state.get("questions") else {**state, "ownership_score": None}
        level = policy.clamp_real_level(policy.auto_drop_level(scored))
        events: list[str] = []
        if level != int(state.get("level", 1)):
            events.append(
                f"level auto-dropped L{state.get('level')} -> L{level} "
                f"(ownership {float(state.get('ownership_score', 0)):.2f})"
            )
        out = {
            "finished_at": now,
            "time_with_ai_s": now - float(state.get("started_at", now)),
            "level": level,
            "level_history": [level],
            "current_node": "scorecard",
            "events": events,
        }
        if keep_diffs:
            save_diff(sessions_dir, str(state.get("session_id")), diff_text())
        changes_mod.clear_snapshot(work_dir)
        save_session(
            {**state, **out, "events": list(state.get("events", [])) + events}, sessions_dir
        )
        return Command(goto=END, update=out)

    for name, fn in [
        ("ticket", ticket_node),
        ("triage", triage_node),
        ("attempt_gate", attempt_gate_node),
        ("coach", coach_node),
        ("coach_wait", coach_wait_node),
        ("implement", implement_node),
        ("review", review_node),
        ("explain_questions", explain_questions_node),
        ("explain_answers", explain_answers_node),
        ("explain_grade", explain_grade_node),
        ("scorecard", scorecard_node),
    ]:
        graph.add_node(name, fn)
    graph.add_edge(START, "ticket")
    return graph.compile(checkpointer=checkpointer)
