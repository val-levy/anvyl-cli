"""Persistent real-project session: one prompt, many tickets.

Trust boundary: slash commands are parsed only from what the human types at a
prompt (`Session.ask`). Model text, ticket text and file contents are only ever
printed, never parsed. Level, profile, consent and keepdiffs change only through
those commands and the consent prompt, and every setting is enforced in code.
All output goes through `Session.say`: control/ANSI stripped, Rich markup, emoji
codes and highlighting off.

Checkpoint privacy: LangGraph persists interrupt payloads (coach text, snippets)
in checkpoints.sqlite. The connection uses secure_delete, each ticket's thread is
deleted when it ends however it ends (finished, abandoned, quit, EOF, Ctrl-C, error),
and threads a killed process left behind are purged at startup once their marker
file under <data>/threads/ is 7 days old.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from . import guard, tui, welcome
from . import harness as hs
from . import models as modelcat
from .auth import get_api_key
from .changes import clear_snapshot
from .driver import drive
from .grader import _clean
from .graph import LOOP_STEPS, build_real_graph
from .history import load_sessions, render_history
from .llm import ModelClient, ModelError, OpenRouterClient
from .memory import Memory
from .policy import REAL_MAX_LEVEL, clamp_real_level
from .profile import FolderConfig, Profile, effective_profile
from .real_coach import RealCoach
from .registry import PluginRegistry, SkillRegistry
from .state import initial_real_state
from .storage import (
    checkpoints_path,
    cleanup_stale_work,
    ensure_data_dir,
    sessions_dir,
    work_dir_for,
)
from .theme import (
    ACCENT,
    COACH,
    MUTED,
    RED,
    animate,
    banner,
    bar_text,
    busy,
    intro,
    typewrite,
)

LOGIN_HINT = 'not logged in: run "anvyl login"'
TICKET_ONLY = (
    "[!] ticket-and-plan-only coaching: the model sees only your ticket text and what you type"
)
RAIL_MIN_WIDTH = 110
STALE_DAYS = 7
HELP = "\n".join(f"{c:<11}{d}" for c, d in tui.COMMANDS.items())
HOWTO = (
    "How this works (not a chat: you drive, the AI coaches):",
    "  1. Type one task for this folder, e.g. 'add retry to fetch'.",
    "  2. Talk it through with the tutor: what you want and how you would go about it.",
    "     'I don't know' is fine: it teaches you, it never locks you out.",
    "  3. You write the code in your editor, then type /done.",
    "  4. Answer three short questions about your change. That is your score.",
    "Type /help for commands, /mode ship to skip the plan and questions.",
)
HINTS = {
    "ticket": "Step 0: describe one task, e.g. add retry to fetch",
    "tutor": "Talking it through: answer in your own words. 'I don't know' is fine",
    "coach_next": "Answer the coach, or /hint for another question. Type g when ready to code",
    "work": "Edit your files in your editor, then type /done",
    "review": "Reviewing your change: reply to continue",
    "explain": "Last part: answer in your own words",
}
PERSONAL_NOTICE = (
    "notice (personal profile): the model may read non-secret files in this folder. "
    "With /keepdiffs on, diffs of your changes are kept in your anvyl data dir. "
    "Shown once."
)


class _Quit(Exception):
    pass


def _input(prompt: str) -> str | None:
    try:
        return input(prompt)
    except EOFError:
        return None


@contextmanager
def open_checkpointer(data_dir: Path) -> Iterator[SqliteSaver]:
    """Checkpointer whose connection overwrites deleted rows instead of leaving them on disk."""
    conn = sqlite3.connect(str(checkpoints_path(data_dir)), check_same_thread=False)
    try:
        conn.execute("PRAGMA secure_delete=ON")
        yield SqliteSaver(conn)
    finally:
        conn.close()


def _forget_thread(saver: SqliteSaver, data_dir: Path, thread_id: str) -> None:
    """Delete a thread's checkpoints and marker, and fold the WAL so no old copy lingers."""
    try:
        saver.delete_thread(thread_id)
    except Exception:
        # keep the marker so the stale purge can retry later
        return
    (data_dir / "threads" / thread_id).unlink(missing_ok=True)
    with contextlib.suppress(Exception):
        saver.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def _purge_stale_threads(saver: SqliteSaver, data_dir: Path) -> None:
    # ponytail: marker mtime = ticket start; a ticket open for 7+ days would be purged.
    cutoff = time.time() - STALE_DAYS * 86400
    marks = data_dir / "threads"
    try:
        children = list(marks.iterdir())
    except OSError:
        return
    for mark in children:
        try:
            if mark.is_file() and not mark.is_symlink() and mark.stat().st_mtime < cutoff:
                _forget_thread(saver, data_dir, mark.name)
        except OSError:
            continue


class _NoClient:
    def chat(self, *args: Any, **kwargs: Any) -> Any:
        raise ModelError("preview makes no model calls")


def _access(cfg: FolderConfig, root: Path) -> tuple[Profile, bool]:
    """Stored profile and whether the model may read files (no stored consent means no)."""
    profile = effective_profile(cfg, root)
    return profile, profile is Profile.PERSONAL or cfg.consented(root)


class Session:
    def __init__(
        self,
        root: Path,
        data_dir: Path,
        console: Console,
        client: ModelClient | None,
        read_line: Callable[[str], str | None],
    ):
        self.root = root.resolve()
        self.data_dir = data_dir
        self.console = console
        self.client = client
        self.read_line = read_line
        self.cfg = FolderConfig(data_dir)
        self.mode = "learn"
        self.level = 1
        self.rail = True
        self.profile = Profile.PROFESSIONAL
        self.can_read = False
        self.view: Mapping[str, Any] = {}
        self.score_lines: list[str] = []
        self.saver: SqliteSaver | None = None
        self.t0 = time.monotonic()
        self.last_answer = ""
        self.harness: hs.Harness | None = None
        self.hint = ""  # dim text inside the empty input box: the next step
        self.memory = Memory(data_dir, self.root)
        self.plugins = PluginRegistry(data_dir / "plugins")
        self.skills = SkillRegistry(data_dir / "skills")

    # -- io --------------------------------------------------------------------
    def say(self, text: object, style: str | None = None, wrap: bool = False) -> None:
        """`style` colours Anvyl's own lines only; markup stays off so text is never parsed.
        `wrap` breaks prose at word boundaries instead of leaving it to the terminal."""
        self.console.print(
            _clean(str(text), 4000),
            style=style,
            markup=False,
            highlight=False,
            emoji=False,
            soft_wrap=not wrap,
        )

    def ask(self, prompt: str, graph_prompt: bool = False) -> str:
        """One line from the human. EOF or /quit ends the session; other /commands run here."""
        while True:
            line = self.read_line(prompt)
            if line is None:
                raise _Quit
            line = line.strip()
            if not line.startswith("/"):
                return line
            if graph_prompt and line.lower() in ("/done", "/hint"):
                return line.lower()
            self.command(line)

    # -- folder setup ----------------------------------------------------------
    def setup_folder(self) -> None:
        profile = self.cfg.profile(self.root)
        if profile is None:
            self.say(
                f"First time in {self.root}. Is this a work project (professional, the default) "
                "or a personal one?",
                COACH,
                wrap=True,
            )
            while profile is None:
                choice = self.ask("[professional/personal] ").lower()
                profile = (
                    Profile.PERSONAL
                    if choice == "personal"
                    else Profile.PROFESSIONAL
                    if choice in ("", "professional")
                    else None
                )
        self.use_profile(profile)

    def use_profile(self, profile: Profile) -> None:
        self.cfg.set_profile(self.root, profile)
        self.profile = profile
        if profile is Profile.PERSONAL:
            self.can_read = True
            if not self.cfg.personal_notice_seen():
                self.say(PERSONAL_NOTICE, MUTED, wrap=True)
                self.cfg.mark_personal_notice_seen()
            return
        if not self.cfg.consent_asked(self.root):
            self.say(
                f"Let the model read files in {self.root}? Secrets are redacted and denied "
                "files are never sent. Default is no.",
                COACH,
                wrap=True,
            )
            self.cfg.set_consent(self.root, self.ask("[y/N] ").lower() in ("y", "yes"))
        self.can_read = self.cfg.consented(self.root)
        if not self.can_read:
            self.say(TICKET_ONLY, MUTED, wrap=True)

    # -- slash commands (human-typed only) -------------------------------------
    def command(self, line: str) -> None:
        cmd, *args = line.split()
        cmd, arg = cmd.lower(), (args[0].lower() if args else "")
        if cmd in ("/quit", "/exit", "/q"):
            raise _Quit
        if cmd == "/help":
            self.say(HELP)
        elif cmd == "/status":
            self.status()
        elif cmd == "/usage":
            files, tokens = self.stats()
            mins = (time.monotonic() - self.t0) / 60
            self.say(
                f"session {mins:.0f} min | tokens {tokens} | files sent {files} | "
                f"L{self.level} | mode {self.mode}",
                MUTED,
            )
        elif cmd == "/clear":
            ui = getattr(self.console, "ui", None)
            if ui:
                ui.clear()
            else:
                self.console.clear()
        elif cmd == "/history":
            render_history(load_sessions(sessions_dir(self.data_dir)), self.console)
        elif cmd == "/copy":
            ui = getattr(self.console, "ui", None)
            if arg == "all" and ui:
                self.copy(ui.plain(), "transcript")
            else:
                self.copy(self.last_answer, "last coach answer")
        elif cmd == "/model":
            self.pick_model(" ".join(args))
        elif cmd == "/plugin":
            self.registry_cmd("plugin", self.plugins, args)
        elif cmd == "/skill":
            self.registry_cmd("skill", self.skills, args)
        elif cmd == "/welcome":
            welcome.show(self)
        elif cmd == "/memory":
            self.memory_cmd(args)
        elif cmd == "/score":
            self.say("\n".join(self.score_lines) or "no scorecard yet")
        elif cmd == "/graph":
            self.say(" -> ".join(LOOP_STEPS) + f"   (now: {self.view.get('current_node', '-')})")
        elif cmd == "/rail":
            self.rail = not self.rail
            self.say(f"rail {'on' if self.rail else 'off'}")
        elif cmd == "/mode":
            self.pick_mode(arg)
        elif cmd == "/harness":
            self.harness_cmd(args)
        elif cmd == "/level":
            if not (arg.isascii() and arg.isdigit()):
                self.say(f"usage: /level 0-{REAL_MAX_LEVEL}")
            elif int(arg) > REAL_MAX_LEVEL:
                self.say(
                    f"level {int(arg)} is not available on real projects (max L{REAL_MAX_LEVEL})"
                )
            else:
                self.level = clamp_real_level(int(arg))
                self.say(f"level -> L{self.level} (applies from the next ticket)")
        elif cmd == "/profile":
            if arg in ("professional", "personal"):
                self.use_profile(Profile(arg))
                self.say(f"profile -> {arg}")
            else:
                self.say("usage: /profile professional|personal")
        elif cmd == "/keepdiffs":
            if self.profile is not Profile.PERSONAL:
                self.say("keepdiffs is only available with the personal profile")
            elif arg in ("on", "off"):
                self.cfg.set_keep_diffs(self.root, arg == "on")
                self.say(f"keepdiffs -> {arg}")
            else:
                self.say("usage: /keepdiffs on|off")
        elif cmd in ("/done", "/hint"):
            self.say(f"{cmd} is only valid at a work prompt")
        else:
            self.say(f"unknown command {cmd} (try /help)")

    def copy(self, text: str, what: str) -> None:
        """Put text on the system clipboard via a fixed local tool (no shell, text on stdin)."""
        tools = (["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"], ["clip.exe"])
        argv = next((t for t in tools if shutil.which(t[0])), None)
        if not text.strip():
            self.say(f"nothing to copy yet ({what})", MUTED)
        elif argv is None:
            self.say("no clipboard tool found (pbcopy, wl-copy, xclip)", RED)
        else:
            try:
                subprocess.run(argv, input=text.encode(), check=True, timeout=5)
                self.say(f"copied {what} ({len(text)} chars)", MUTED)
            except (OSError, subprocess.SubprocessError):
                self.say("clipboard copy failed", RED)

    def pick_mode(self, arg: str) -> None:
        """/mode [ship|learn|<harness id>]; with no argument, an interactive menu."""
        found = hs.installed(self.data_dir)
        ui = getattr(self.console, "ui", None)
        if not arg and ui:
            cur = self.harness.id if self.harness else self.mode
            names = ["learn", "ship", *found]
            pitch = {"learn": "attempt gate first, then the coach", "ship": "AI may draft code"}
            rows = [
                (f"{'●' if n == cur else ' '} {n}", pitch.get(n) or found[n].pitch) for n in names
            ]
            i = ui.choose("mode", rows)
            arg = names[i] if i is not None else ""
            if not arg:
                return
        if arg in hs.BUILTIN_MODES:
            self.mode, self.harness = arg, None
            self.say(f"mode -> {arg} (applies from the next ticket)")
        elif arg in found:
            h = found[arg]
            warn = f"{h.id} has no attempt gate (AI may draft). Use it? [y/N] "
            if h.base == "ship" and self.ask(warn).lower() not in ("y", "yes"):
                return
            self.mode, self.harness = h.base, h
            self.say(f"mode -> {h.id} ({h.base} base, level cap L{h.max_level}); next ticket")
        else:
            self.say("usage: /mode ship|learn|<harness id>   (/harness lists yours)")

    def harness_cmd(self, args: list[str]) -> None:
        """/harness [install <folder>|remove <id>]; with nothing, the same menu as /mode."""
        sub, ident = (args[0].lower() if args else ""), (args[1] if len(args) > 1 else "")
        if sub == "install" and ident:
            try:
                h = hs.install(Path(ident).expanduser(), self.data_dir)
            except hs.HarnessError as e:
                for p in e.problems[:6]:
                    self.say(f"rejected: {_clean(p, 160)}", RED)
                return
            self.say(f"installed {h.id} v{h.version} ({h.base} base, cap L{h.max_level})")
        elif sub == "remove" and ident in hs.installed(self.data_dir):
            shutil.rmtree(self.data_dir / "harnesses" / ident, ignore_errors=True)
            if self.harness and self.harness.id == ident:
                self.mode, self.harness = "learn", None
            self.say(f"removed {ident}")
        elif sub in ("", "list"):
            found = hs.installed(self.data_dir)
            if not found:
                self.say("no harnesses installed. Author one: `anvyl harness init <id>`", MUTED)
            elif getattr(self.console, "ui", None):
                self.pick_mode("")
            else:
                for h in found.values():
                    self.say(f"{h.id} v{h.version}  {h.pitch}")
        else:
            self.say("usage: /harness  |  /harness install <folder>  |  /harness remove <id>")

    def set_model(self, chosen: modelcat.Model) -> None:
        if self.client is not None:
            self.client.model = chosen.id  # type: ignore[attr-defined]
        self.cfg.set_model(chosen.id)
        p = f"${modelcat.money(chosen.price_in).strip()} in / "
        p += f"${modelcat.money(chosen.price_out).strip()} out per 1M tokens"
        self.say(f"model -> {chosen.id}  ({p})")

    def pick_model(self, query: str) -> None:
        """/model [filter]: list OpenRouter models with $/M-token prices, pick by number or id.
        Only tool-capable models are listed (the coach needs tools). Applies to the next call."""
        cur = str(getattr(self.client, "model", "") or "")
        with busy(self.console):
            cat = [m for m in modelcat.fetch() if m.tools]
        if not cat:
            self.say("could not load the model list (offline?). Current: " + (cur or "?"), RED)
            return
        ui = getattr(self.console, "ui", None)
        if ui:
            rows = [
                (
                    f"{'●' if m.id == cur else ' '} {m.id}",
                    f"${modelcat.money(m.price_in).strip()} in  "
                    f"${modelcat.money(m.price_out).strip()} out /1M  "
                    f"ctx {modelcat.ctx(m.context).strip()}",
                )
                for m in cat
            ]
            i = ui.choose("model", rows, "  (prices per 1M tokens)")
            if i is not None:
                self.set_model(cat[i])
            return
        shown = modelcat.search(cat, query)
        while True:
            self.say(f"{len(shown)} of {len(cat)} models   (* = current)", MUTED)
            if shown:
                self.say(modelcat.HEADER, MUTED)
            for i, m in enumerate(shown[:15], 1):
                self.say(modelcat.row(i, m, cur))
            if len(shown) > 15:
                self.say(f"... {len(shown) - 15} more, type words to narrow", MUTED)
            reply = self.ask("number, id, words to filter, Enter to cancel: ").strip()
            if not reply:
                return
            chosen: modelcat.Model | None = None
            if reply.isascii() and reply.isdigit() and 1 <= int(reply) <= min(15, len(shown)):
                chosen = shown[int(reply) - 1]
            else:
                chosen = next((m for m in cat if m.id == reply), None)
            if chosen:
                self.set_model(chosen)
                return
            shown = modelcat.search(cat, reply)

    def registry_cmd(self, kind: str, reg: PluginRegistry | SkillRegistry, args: list[str]) -> None:
        """/plugin and /skill list|load|unload <id>. Ids must be known ones; plugin loads go
        through policy.plugin_allowed. Loading records intent only: nothing is sent to the model."""
        sub, ident = (args[0].lower() if args else "list"), (args[1] if len(args) > 1 else "")
        known = {x["id"]: x for x in reg.list()}
        ui = getattr(self.console, "ui", None)
        if ui and not args and known:  # interactive menu: Enter toggles, Esc closes
            while True:
                known = {x["id"]: x for x in reg.list()}
                ids = list(known)
                rows = [
                    (
                        f"[{'x' if known[i]['loaded'] else ' '}] {i}",
                        _clean(str(known[i].get("description", "")), 70),
                    )
                    for i in ids
                ]
                n = ui.choose(kind, rows, "  ([x] = loaded)")
                if n is None:
                    return
                self.registry_cmd(
                    kind, reg, ["unload" if known[ids[n]]["loaded"] else "load", ids[n]]
                )
        if sub == "list":
            for i, x in known.items():
                desc = _clean(str(x.get("description", "")), 80)
                self.say(f"[{'x' if x['loaded'] else ' '}] {i} {desc}".rstrip())
            if not known:
                self.say(f"no {kind}s in {reg.dir}", MUTED)
        elif sub in ("load", "unload") and ident in known:
            if isinstance(reg, PluginRegistry) and sub == "load":
                state = {**self.view, "mode": self.mode, "level": self.level}
                self.say(reg.load(ident, state)[1])
            else:
                self.say(getattr(reg, sub)(ident)[1])
        elif sub in ("load", "unload"):
            self.say(f"no {kind} {_clean(ident, 40)!r} (try /{kind} list)")
        else:
            self.say(f"usage: /{kind} list|load|unload <id>")

    # -- rendering -------------------------------------------------------------
    def stats(self) -> tuple[int, int]:
        return len(self.view.get("files_read") or []), int(self.view.get("tokens", 0))

    def status(self) -> None:
        files, tokens = self.stats()
        v = self.view
        level = v.get("level", self.level)
        gate = "passed" if v.get("gate_passed") else "locked"
        if self.rail and self.console.width >= RAIL_MIN_WIDTH:
            self.say(
                f"| step       {v.get('current_node', '-')}\n"
                f"| level      L{level}  mode {v.get('mode', self.mode)}\n"
                f"| profile    {self.profile.value}\n"
                f"| gate       {gate}\n"
                f"| files sent {files}\n"
                f"| tokens     {tokens}",
                MUTED,
            )
        else:
            self.say(
                f"step {v.get('current_node', '-')} | L{level} | mode {v.get('mode', self.mode)} | "
                f"{self.profile.value} | gate {gate} | files sent {files} | tokens {tokens}",
                MUTED,
            )

    def scorecard(self, st: Mapping[str, Any]) -> list[str]:
        h, a = int(st.get("human_lines", 0)), int(st.get("ai_lines", 0))
        you = h / (h + a) * 100 if h + a else 100.0
        ch = st.get("changes") or {}
        files, tokens = self.stats()
        lines = ["scorecard"]
        if st.get("abandoned"):
            lines.append("  abandoned: no changes found")
        lines += [
            f"  authorship  you {you:.0f}% ({h} lines) / AI {100 - you:.0f}% ({a} lines)",
            f"  changes     {ch.get('files', 0)} files, "
            f"+{ch.get('added', 0)} -{ch.get('removed', 0)}",
        ]
        if st.get("questions"):
            lines.append(f"  explain     {float(st.get('explain_score', 0)):.0%}")
            lines.append(f"  ownership   {float(st.get('ownership_score', 0)):.0%}")
        if st.get("idea_labels"):
            lines.append(f"  learned     {', '.join(st['idea_labels'])}")
        lines += [
            f"  level       L{st.get('level', self.level)}",
            f"  profile     {self.profile.value}",
            f"  files sent  {files}",
            f"  tokens      {tokens}",
        ]
        return lines

    def memory_cmd(self, args: list[str]) -> None:
        if args[:1] == ["forget"] and len(args) > 1:
            label = " ".join(args[1:])
            self.say(f"forgot: {label}" if self.memory.forget(label) else f"not found: {label}")
            return
        ideas = self.memory.ideas()
        if not ideas:
            self.say("nothing remembered yet: ideas you show you can do are kept here", MUTED)
        for i in ideas:
            self.say(f"{i['label']} (x{i['reps']}, {', '.join(i['aspects'])})")
        if ideas:
            self.say("/memory forget <idea> removes one", MUTED)

    # -- one ticket --------------------------------------------------------------
    def answer(self, payload: dict) -> str:
        kind = payload.get("kind")
        self.hint = HINTS.get(str(kind), "")
        if kind in ("coach_next", "tutor"):
            label = "● " if self.console.is_terminal else "coach: "
            self.console.print(label, style=COACH, end="", markup=False, highlight=False)
            self.last_answer = _clean(str(payload.get("text", "")), 4000)
            typewrite(self.console, self.last_answer)
        elif kind == "error":
            self.say(payload.get("message", ""), RED)
        self.say(payload.get("prompt", ""), COACH)
        return self.ask("> ", graph_prompt=True)

    def run_ticket(self, ticket: str) -> None:
        assert self.saver is not None and self.client is not None
        sid = f"r-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        work = work_dir_for(self.data_dir, sid)
        marks = self.data_dir / "threads"
        marks.mkdir(parents=True, exist_ok=True)
        (marks / sid).touch()
        key = self.memory.start_ticket(ticket) if self.can_read else ""
        outcome, labels = "unfinished", []
        try:
            h = self.harness
            coach = RealCoach(
                self.client,
                self.root,
                self.profile,
                self.can_read,
                h.guidance if h else "",
                self.memory.recap(ticket) if self.can_read else "",
            )
            graph = build_real_graph(
                coach,
                self.client,
                self.root,
                self.profile,
                sessions_dir(self.data_dir),
                work,
                self.saver,
                self.cfg.keep_diffs(self.root),
                self.memory if self.can_read else None,
            )
            state0 = initial_real_state(
                sid, ticket, str(self.root), self.profile.value, self.mode,
                min(self.level, h.max_level) if h else self.level, False, str(work),
            )  # fmt: skip
            self.view = state0
            if not self.console.is_terminal:  # the TUI status bar already shows this
                self.status()
            config = {"configurable": {"thread_id": sid}}
            drive(
                graph, state0, config, self.answer, self.on_state, busy=lambda: busy(self.console)
            )
            final = graph.get_state(config).values
            labels = list(final.get("idea_labels") or [])
            if final.get("current_node") == "scorecard":
                outcome = "abandoned" if final.get("abandoned") else "done"
            self.finish(final)
        except (_Quit, KeyboardInterrupt):
            raise
        except Exception as exc:  # type name only: messages can echo ticket or file text
            self.say(f"error: the ticket failed ({type(exc).__name__}); nothing was scored", RED)
        finally:
            if key:
                self.memory.finish_ticket(key, outcome, labels)
            self.view = {}
            clear_snapshot(work)
            _forget_thread(self.saver, self.data_dir, sid)

    def on_state(self, values: Mapping[str, Any]) -> None:
        self.view = dict(values)

    def show_score(self, st: Mapping[str, Any]) -> None:
        if not self.console.is_terminal:
            self.say("\n".join(self.score_lines))
            return
        own = float(st.get("ownership_score", 0)) * 100 if st.get("questions") else None

        def panel(fill: float) -> Panel:
            body = Text()  # Text never parses markup; the lines are numbers and enums anyway
            for i, line in enumerate(self.score_lines[1:]):  # "scorecard" is the panel title
                body.append("\n" if i else "")
                if own is not None and line.startswith("  ownership"):
                    body.append("  ownership   ")
                    body.append_text(bar_text(own * fill))
                else:
                    body.append(line)
            return Panel(body, title="scorecard", border_style=ACCENT, expand=False)

        animate(self.console, panel)

    def finish(self, st: Mapping[str, Any]) -> None:
        self.view = st
        if st.get("quit"):
            self.say("session ended: nothing scored")
        elif st.get("gate_blocked") and not st.get("gate_passed"):
            self.say(
                "[locked] attempt gate blocked: no usable human attempt. Nothing was scored.", RED
            )
        else:
            self.score_lines = self.scorecard(st)
            self.show_score(st)
            if st.get("current_node") == "scorecard":
                self.level = clamp_real_level(int(st.get("level", self.level)))


def run_session(
    root: Path,
    data_dir: Path,
    console: Console,
    client: ModelClient | None,
    read_line: Callable[[str], str | None] | None = None,
) -> int:
    data_dir = ensure_data_dir(data_dir)
    cleanup_stale_work(data_dir)
    s = Session(root, data_dir, console, client, read_line or _input)
    interactive = read_line is None and console.is_terminal and sys.stdin.isatty()
    fullscreen = interactive and not os.environ.get("ANVYL_INLINE")
    if interactive and not fullscreen:
        s.read_line = tui.reader(s)
    if client is None:
        key = get_api_key(data_dir)
        if not key:
            s.say(LOGIN_HINT, RED)
            return 1
        s.client = OpenRouterClient(key, s.cfg.model())

    def loop() -> int:
        try:
            with open_checkpointer(data_dir) as saver:
                s.saver = saver
                _purge_stale_threads(saver, data_dir)
                if fullscreen:
                    pass  # the empty transcript shows the animated welcome screen
                elif console.is_terminal:
                    intro(console)
                    tui.dock(console, banner(s.root))
                else:
                    s.say(f"anvyl  |  {s.root.name}  |  /help for commands", ACCENT)
                s.setup_folder()
                if not welcome.seen(data_dir):
                    welcome.show(s)
                    welcome.mark_seen(data_dir)
                for ln in HOWTO:
                    s.say(ln, MUTED)
                if last := s.memory.last_line():
                    s.say(last, MUTED)
                while True:
                    s.hint = HINTS["ticket"]
                    if ticket := s.ask("ticket> "):
                        s.say(
                            "Got it. Ship mode: write the code, then /done."
                            if s.mode == "ship"
                            else "Got it. Next: we talk it through.",
                            MUTED,
                        )
                        s.run_ticket(ticket)
                        s.hint = ""
        except _Quit:
            return 0
        except KeyboardInterrupt:
            s.say("interrupted")
            return 130

    if fullscreen:
        from .fullscreen import FullScreen

        intro(console)
        return FullScreen(s).run(loop)
    return loop()


def preview(
    root: Path,
    data_dir: Path,
    console: Console,
    ticket: str,
    client: ModelClient | None = None,
) -> None:
    """Print the exact messages a first model call would carry. Never touches the network."""
    root = root.resolve()
    profile, can_read = _access(FolderConfig(data_dir), root)
    coach = RealCoach(client or _NoClient(), root, profile, can_read)
    s = Session(root, data_dir, console, None, _input)
    for m in coach.build_messages({"ticket": ticket, "level": 1}):
        s.say(f"--- {m['role']} ---\n{m['content']}")
    n = len(guard.list_files(root, profile)) if can_read else 0
    s.say(f"--- file tools: {'on' if can_read else 'off'} ({n} readable files) ---")
