"""Rich CLI for anvyl.

Opencode style, per Val's direction: warm dark background (the terminal's
own), JetBrains Mono, one blue accent, thin borders, no gradients, no
emoji. ASCII markers only: [ok], [!], [>], [locked].

Top bar shows the task name and the timer only. It deliberately does NOT
show a "LEARN - L1 - COACH" badge -- Val rejected that as AI-looking.
Mode, level, and the 1-6 loop live in the side rail only. The rail
auto-hides on narrow terminals (under 110 columns); a one-line ministrip
carries step / level / gate / ownership / work-split while it is hidden.

The CLI drives the LangGraph graph: human input arrives through
``interrupt()`` and is answered with ``Command(resume=...)``. In demo
mode (no tty, or --demo) answers are scripted from the task; in a
terminal the human types them.
"""

from __future__ import annotations

import argparse
import getpass
import shutil
import sys
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from rich.console import Console
from rich.panel import Panel

from . import auth, tasks
from .coach import Coach
from .driver import drive
from .graph import LOOP_STEPS, build_graph
from .history import load_sessions, render_history
from .registry import PluginRegistry, SkillRegistry
from .session import preview, run_session
from .state import HarnessState, initial_state
from .storage import (
    checkpoints_path,
    ensure_data_dir,
    reset_data,
    resolve_data_dir,
    save_session,
    sessions_dir,
)
from .theme import ACCENT, COACH, MUTED, RED, animate, bar, busy, typewrite

MIN_RAIL_WIDTH = 110


def fmt_secs(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


class ScriptedProvider:
    """Demo answers, straight from the task. Deterministic, no model."""

    def __init__(self, task: dict):
        self.task = task
        self._quiz_i = 0

    def answer(self, payload: dict, ctx: "Runner") -> str:
        kind = payload.get("kind")
        if kind == "goal":
            return self.task["goal_prompt"]
        if kind == "attempt":
            return self.task["scripted_attempt"]
        if kind == "coach_next":
            return "g"
        if kind == "code":
            return self.task["scripted_code"]
        if kind == "explain":
            idx = int(payload.get("index", self._quiz_i))
            self._quiz_i = idx + 1
            return self.task["scripted_answers"][idx]
        if kind == "review":
            return "ok"
        return ""


class InteractiveProvider:
    """Reads from the terminal. Multi-line input ends with /done.

    Uses raw ``input()`` on purpose: Rich's Prompt strips leading
    whitespace, which destroys indented code.
    """

    def __init__(self, console: Console):
        self.console = console

    def _read_line(self, prompt: str, ctx: "Runner") -> str | None:
        while True:
            self.console.print(prompt, end=" ")
            try:
                raw = input()
            except EOFError:
                return None
            line = raw.rstrip("\n")
            if line.startswith("/") and line not in ("/done", "/hint"):
                if ctx.handle_command(line):
                    continue
            return line

    def _read_block(self, prompt: str, ctx: "Runner") -> str:
        lines: list[str] = []
        while True:
            line = self._read_line(prompt if not lines else "...", ctx)
            if line is None or line == "/done":
                break
            if line == "/hint" and not lines:
                return "/hint"
            lines.append(line)
        return "\n".join(lines)

    def answer(self, payload: dict, ctx: "Runner") -> str:
        kind = payload.get("kind")
        prompt = payload.get("prompt", "")
        if kind == "coach_next":
            ctx.console.print(f"[{COACH}]coach:[/{COACH}] ", end="")
            typewrite(ctx.console, payload.get("text", ""))
            return self._read_line(prompt, ctx) or ""
        if kind == "review":
            ctx.console.print(Panel(payload.get("text", ""), title="AI draft", border_style=MUTED))
            return self._read_block(prompt, ctx)
        if kind in ("goal", "attempt", "code", "explain"):
            ctx.console.print(f"[{COACH}]{prompt}[/{COACH}]")
            return self._read_block(">", ctx)
        return self._read_line(prompt or ">", ctx) or ""


class Runner:
    def __init__(
        self,
        task: dict,
        mode: str,
        level: int,
        high_stakes: bool,
        demo: bool,
        live: bool,
        session_id: str,
        data_dir=None,
        rail_visible: bool = True,
    ):
        self.task = task
        self.mode = mode
        self.level = level
        self.high_stakes = high_stakes
        self.demo = demo
        self.session_id = session_id
        self.data_dir = ensure_data_dir(resolve_data_dir(data_dir))
        self.rail_visible = rail_visible
        self.console = Console()
        self.coach = Coach(live=live)
        self.plugins = PluginRegistry(self.data_dir / "plugins")
        self.skills = SkillRegistry(self.data_dir / "skills")
        self.graph: Any = None
        self.config = {"configurable": {"thread_id": session_id}}
        self.started = time.time()
        self.provider = ScriptedProvider(task) if demo else InteractiveProvider(self.console)
        self._state_view: dict = {}

    # -- rendering ------------------------------------------------------
    def width(self) -> int:
        return shutil.get_terminal_size().columns

    def rail_on(self) -> bool:
        return self.rail_visible and self.width() >= MIN_RAIL_WIDTH

    def top_bar(self, state: Mapping[str, Any]) -> None:
        elapsed = fmt_secs(time.time() - float(state.get("started_at", self.started)))
        self.console.rule(
            f"[bold]{state.get('task_title', '')}[/bold]  [{MUTED}]{elapsed}[/{MUTED}]"
        )

    def render_rail(self, state: Mapping[str, Any]) -> None:
        current = state.get("current_node", "goal")
        lines = []
        for i, step in enumerate(LOOP_STEPS, 1):
            mark = (
                ">" if step == current or (current == "attempt_gate" and step == "attempt") else " "
            )
            lines.append(f"{mark} {i}. {step}")
        total = int(state.get("human_lines", 0)) + int(state.get("ai_lines", 0))
        human_pct = (int(state.get("human_lines", 0)) / total * 100) if total else 100.0
        with_ai = fmt_secs(
            float(state.get("time_with_ai_s", 0))
            or time.time() - float(state.get("started_at", self.started))
        )
        without = fmt_secs(float(state.get("est_without_ai_s", 0)))
        gate = (
            "passed"
            if state.get("gate_passed")
            else "locked"
            if state.get("mode") == "learn"
            else "n/a (ship)"
        )
        body = (
            "\n".join(lines)
            + f"\n\nownership {bar(float(state.get('ownership_score', 0)) * 100)}"
            + f"\nyou vs AI  {bar(human_pct)} you"
            + f"\nhelp rung  {int(state.get('help_rung', 0))} / 3"
            + f"\nlevel      L{int(state.get('level', 1))}  mode {state.get('mode', '')}"
            + f"\ntokens     {int(state.get('tokens', 0))}"
            + f"\ntime       {with_ai} with AI / ~{without} est. without"
            + f"\ngate       {gate}"
        )
        self.console.print(Panel(body, title="rail", border_style=MUTED))

    def render_ministrip(self, state: Mapping[str, Any]) -> None:
        total = int(state.get("human_lines", 0)) + int(state.get("ai_lines", 0))
        human_pct = (int(state.get("human_lines", 0)) / total * 100) if total else 100.0
        self.console.print(
            f"[{MUTED}]step {state.get('current_node', '?')} | L{int(state.get('level', 1))} | "
            f"gate {'passed' if state.get('gate_passed') else 'locked'} | "
            f"ownership {float(state.get('ownership_score', 0)):.0%} | "
            f"you {human_pct:.0f}%[/{MUTED}]"
        )

    def render_scorecard(self, state: Mapping[str, Any]) -> None:
        animate(self.console, lambda fill: self._scorecard_panel(state, fill))

    def _scorecard_panel(self, state: Mapping[str, Any], fill: float) -> Panel:
        total = int(state.get("human_lines", 0)) + int(state.get("ai_lines", 0))
        human_pct = (int(state.get("human_lines", 0)) / total * 100) if total else 100.0
        with_ai = float(state.get("time_with_ai_s", 0))
        without = float(state.get("est_without_ai_s", 0))
        verify = "passed" if (state.get("verification") or {}).get("passed") else "FAILED"
        body = (
            f"time        {fmt_secs(with_ai)} with AI / ~{fmt_secs(without)} est. without\n"
            f"authorship  you {human_pct:.0f}% ({state.get('human_lines', 0)} lines) / "
            f"AI {100 - human_pct:.0f}% ({state.get('ai_lines', 0)} lines)\n"
            f"ownership   {bar(float(state.get('ownership_score', 0)) * 100 * fill)}\n"
            f"explain     {float(state.get('explain_score', 0)):.0%}\n"
            f"levels      {' -> '.join('L' + str(lvl) for lvl in state.get('level_history', []))}\n"
            f"verify      {verify}\n"
            f"live model  {'yes' if state.get('live_model') else 'no (offline/demo coach)'}"
        )
        for check in (state.get("verification") or {}).get("checks", []):
            mark = "[ok]" if check["passed"] else "[FAIL]"
            body += f"\n  {mark} {check['name']}: {check['detail']}"
        return Panel(body, title="scorecard", border_style=ACCENT)

    # -- slash commands ---------------------------------------------------
    def handle_command(self, line: str) -> bool:
        parts = line.split()
        cmd = parts[0].lower()
        args = parts[1:]
        c = self.console
        state = self._state_view

        if cmd == "/help":
            c.print(
                "/mode ship|learn  /level 0-4  /status  /score  /graph\n"
                "/rail  /plugin list|load|unload|install <id>  "
                "/skill list|load|unload <id>  /quit"
            )
            return True
        if cmd == "/status":
            self.top_bar(state or {"task_title": self.task["title"], "started_at": self.started})
            if self.rail_on():
                self.render_rail(state or {})
            else:
                self.render_ministrip(state or {})
            return True
        if cmd == "/score":
            self.render_scorecard(state or {})
            return True
        if cmd == "/graph":
            c.print(" -> ".join(LOOP_STEPS) + f"   (now: {state.get('current_node', '?')})")
            return True
        if cmd == "/rail":
            self.rail_visible = not self.rail_visible
            c.print(f"rail {'on' if self.rail_visible else 'off'}")
            return True
        if cmd == "/mode" and args and args[0] in ("ship", "learn"):
            self.mode = args[0]
            self._apply_state({"mode": args[0]})
            c.print(f"mode -> {args[0]}")
            return True
        if cmd == "/level" and args and args[0].isdigit() and 0 <= int(args[0]) <= 4:
            self.level = int(args[0])
            self._apply_state({"level": self.level, "level_history": [self.level]})
            c.print(f"level -> L{self.level}")
            return True
        if cmd == "/plugin":
            sub = args[0] if args else "list"
            if sub == "list":
                for p in self.plugins.list():
                    mark = "[x]" if p["loaded"] else "[ ]"
                    desc = p.get("description", "")
                    c.print(f"  {mark} {p['id']} v{p.get('version', '?')} - {desc}")
            elif sub in ("load", "unload") and len(args) > 1:
                ok, msg = getattr(self.plugins, sub)(
                    args[1], state or {"mode": self.mode, "level": self.level, "human_attempt": ""}
                )
                c.print(f"  {msg}")
            elif sub == "install" and len(args) > 1:
                c.print("  " + self.plugins.install(args[1]).replace("\n", "\n  "))
            else:
                c.print("  usage: /plugin list|load|unload|install <id>")
            return True
        if cmd == "/skill":
            sub = args[0] if args else "list"
            if sub == "list":
                for s in self.skills.list():
                    c.print(f"  {'[x]' if s['loaded'] else '[ ]'} {s['id']}")
            elif sub in ("load", "unload") and len(args) > 1:
                ok, msg = getattr(self.skills, sub)(args[1])
                c.print(f"  {msg}")
            else:
                c.print("  usage: /skill list|load|unload <id>")
            return True
        if cmd == "/quit":
            raise SystemExit(0)
        c.print(f"unknown command {cmd} (try /help)")
        return True

    def _apply_state(self, values: dict) -> None:
        """Apply a mid-run state change (from /mode, /level) if a graph
        is already running; otherwise it is picked up at start."""
        if self.graph is not None:
            try:
                self.graph.update_state(self.config, values)
            except Exception:
                pass
        self._state_view.update(values)

    # -- main driver ------------------------------------------------------
    def run(self, initial: HarnessState, resume: bool = False) -> dict:
        db_path = checkpoints_path(self.data_dir)
        with SqliteSaver.from_conn_string(str(db_path)) as checkpointer:
            self.graph = build_graph(
                self.task, self.coach, sessions_dir(self.data_dir), checkpointer
            )
            coach_label = (
                "live (Claude via OpenRouter)" if self.coach.live_requested else "offline/demo"
            )
            self.console.print(
                f"anvyl  |  task: {self.task['title']}  |  "
                f"coach: {coach_label}" + ("  |  demo mode" if self.demo else "")
            )
            self.top_bar(initial)
            if self.rail_on():
                self.render_rail(initial)
            else:
                self.render_ministrip(initial)

            def on_state(values: Mapping[str, Any]) -> None:
                self._state_view = dict(values)

            result = drive(
                self.graph,
                initial,
                self.config,
                lambda payload: self.provider.answer(payload, self),
                on_state,
                busy=lambda: busy(self.console),
            )
            self._state_view = result
            save_session(result, sessions_dir(self.data_dir))
            if result.get("gate_blocked") and not result.get("gate_passed"):
                self.console.print(
                    f"[{RED}][locked] attempt gate blocked: no usable human "
                    f"attempt. Session saved; resume with --session.[/{RED}]"
                )
            else:
                self.render_scorecard(result)
            return result


SUBCOMMANDS = ("session", "tutorial", "login", "logout", "preview", "reset", "history")
# The old top-level tutorial flags stay accepted (hidden) and mean `anvyl tutorial ...`.
LEGACY_FLAGS = {
    "--task",
    "--mode",
    "--level",
    "--goal",
    "--demo",
    "--interactive",
    "--live",
    "--high-stakes",
    "--session",
    "--list-tasks",
    "--no-rail",
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="anvyl", description="Human-most-of-the-loop coding coach")
    sub = p.add_subparsers(dest="cmd")

    def add(name: str, help: str) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help, description=help)
        sp.add_argument(
            "--data-dir",
            default=None,
            help="data dir for sessions/checkpoints/config (default: $ANVYL_HOME or ~/.anvyl)",
        )
        return sp

    add("session", "coach you on a real ticket in the current folder (default)")
    add("login", "store your OpenRouter API key")
    add("logout", "remove the stored API key")
    add("reset", "delete all anvyl data")
    add("history", "list past sessions with ownership and time summaries")
    add("preview", "show what would be sent to the model for a ticket (no network)").add_argument(
        "ticket", nargs="+"
    )
    t = add("tutorial", "run the built-in tutorial tasks")
    t.add_argument(
        "--task",
        default=tasks.DEFAULT_TASK,
        choices=sorted(tasks.TASKS),
        help="task to run (default: toy-backoff)",
    )
    t.add_argument("--mode", default="learn", choices=["ship", "learn"])
    t.add_argument("--level", type=int, default=1, choices=range(0, 5))
    t.add_argument(
        "--goal", default=None, help="goal in your own words (else prompted / task default)"
    )
    t.add_argument(
        "--demo",
        action="store_true",
        help="scripted demo run (also the default when stdin is not a tty)",
    )
    t.add_argument(
        "--interactive", action="store_true", help="force interactive prompts even without a tty"
    )
    t.add_argument(
        "--live",
        action="store_true",
        help="use the live Claude coach via OpenRouter (default: offline/demo coach)",
    )
    t.add_argument(
        "--high-stakes",
        action="store_true",
        help="high-stakes change: explain-back required even in Ship mode",
    )
    t.add_argument(
        "--session", default=None, help="session id to resume (re-answers the pending interrupt)"
    )
    t.add_argument("--list-tasks", action="store_true", help="list tasks and exit")
    t.add_argument(
        "--no-rail", action="store_true", help="start with the observability rail hidden"
    )
    return p


def _route(argv: list[str]) -> list[str]:
    """No subcommand means `session`; legacy tutorial flags mean `tutorial`."""
    if argv and (argv[0] in SUBCOMMANDS or argv[0] in ("-h", "--help")):
        return argv
    if argv and not argv[0].startswith("-"):
        return argv  # let argparse report the bad subcommand
    legacy = any(a.split("=", 1)[0] in LEGACY_FLAGS for a in argv)
    return ["tutorial" if legacy else "session", *argv]


def run_tutorial(args: argparse.Namespace, console: Console) -> int:
    if args.list_tasks:
        for task_id, task in sorted(tasks.TASKS.items()):
            mark = " (default)" if task_id == tasks.DEFAULT_TASK else ""
            console.print(f"  {task_id}{mark} - {task['title']}")
        return 0

    task = tasks.get_task(args.task)
    demo = args.demo or (not sys.stdin.isatty() and not args.interactive)
    session_id = args.session or f"s-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    runner = Runner(
        task,
        args.mode,
        args.level,
        args.high_stakes,
        demo,
        live=args.live,
        session_id=session_id,
        data_dir=args.data_dir,
        rail_visible=not args.no_rail,
    )
    goal = args.goal or task["goal_prompt"]
    initial = initial_state(
        session_id=session_id,
        task_id=task["id"],
        task_title=task["title"],
        goal=goal,
        mode=args.mode,
        level=args.level,
        high_stakes=args.high_stakes,
        demo=demo,
        est_without_ai_s=task["est_without_ai_s"],
    )
    runner.run(initial, resume=bool(args.session))
    return 0


def run_login(data_dir: Path) -> int:
    try:
        key = getpass.getpass("OpenRouter API key (input hidden): ").strip()
    except (EOFError, KeyboardInterrupt):
        key = ""
    if not key:
        print("error: no key entered", file=sys.stderr)
        return 1
    where = auth.store_api_key(key, data_dir)
    print(
        "key stored in the OS keychain"
        if where == "keychain"
        else f"key stored in {data_dir / 'key'} (owner-only file)"
    )
    return 0


def run_reset(data_dir: Path) -> int:
    try:
        answer = input("type yes to delete all anvyl data: ")
    except EOFError:
        answer = ""
    if answer != "yes":
        print("aborted: nothing deleted", file=sys.stderr)
        return 1
    try:
        reset_data(data_dir)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"deleted the contents of {data_dir} (a key in the OS keychain stays: anvyl logout)")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(_route(list(sys.argv[1:] if argv is None else argv)))
    console = Console()
    if args.cmd == "tutorial":
        return run_tutorial(args, console)
    data_dir = resolve_data_dir(args.data_dir).absolute()
    if args.cmd == "login":
        return run_login(data_dir)
    if args.cmd == "logout":
        auth.delete_api_key(data_dir)
        print("key removed (OS keychain and key file)")
        return 0
    if args.cmd == "reset":
        return run_reset(data_dir)
    if args.cmd == "history":
        render_history(load_sessions(sessions_dir(data_dir)), console)
        return 0
    if args.cmd == "preview":
        preview(Path.cwd(), data_dir, console, " ".join(args.ticket))
        return 0
    return run_session(Path.cwd(), data_dir, console, None)


if __name__ == "__main__":
    raise SystemExit(main())
