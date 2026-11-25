"""Full-screen UI: scrolling transcript on top, spinner, ruled input and status line pinned.

The session runs in a worker thread and prints through a Rich console whose output lands in
the transcript pane (wheel/PgUp scroll it, it re-wraps on resize). The human's typing goes
through `read`, which blocks the worker until Enter. Colour comes only from Anvyl's own
strings via Rich styles; typed text is echoed through `Text`, never parsed, and the input
history lives in memory only: nothing typed is written to disk here.
"""

from __future__ import annotations

import queue
import shutil
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.data_structures import Point
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import ANSI, FormattedText, to_formatted_text
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import (
    ConditionalContainer,
    Dimension,
    Float,
    FloatContainer,
    HSplit,
    Layout,
    VSplit,
    Window,
)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl, UIContent, UIControl
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.layout.processors import Processor, Transformation, TransformationInput
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
from prompt_toolkit.utils import get_cwidth
from rich.console import Console, ConsoleDimensions
from rich.text import Text

from .grader import _clean
from .theme import ACCENT, COACH, GLYPHS, MUTED, RED, SPIN_WORDS, USER_BG, _grid, _lerp
from .tui import STYLE, SlashCompleter, status_fragments

Frag = tuple[str, str]
MAX_RAW = 400_000  # transcript cap in characters of ANSI text; oldest lines drop first


class _Sink:
    """File-like target for Rich: everything printed becomes transcript text."""

    def __init__(self, ui: FullScreen):
        self.ui = ui

    def write(self, s: str) -> int:
        self.ui.feed(s)
        return len(s)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return True


class UIConsole(Console):
    """A terminal-like Console sized to the transcript pane (follows resizes)."""

    def __init__(self, ui: FullScreen):
        super().__init__(
            file=_Sink(ui),  # type: ignore[arg-type]
            force_terminal=True,
            color_system="truecolor",
            legacy_windows=False,
        )
        self.ui = ui

    @property
    def size(self) -> ConsoleDimensions:
        return ConsoleDimensions(self.ui.width, self.ui.height)

    @size.setter
    def size(self, new: tuple[int, int]) -> None:  # the pane decides; ignore Rich's own sets
        pass


def _wrap(chars: list[Frag], width: int) -> list[list[Frag]]:
    """Word-wrap one logical line (a list of (style, char)) into rows of <= width cells."""
    rows: list[list[Frag]] = []
    cur: list[Frag] = []
    used = 0
    last_space = -1
    for st, ch in chars:
        cw = get_cwidth(ch)
        if used + cw > width and cur:
            if ch != " " and last_space > 0:
                rows.append(cur[:last_space])
                cur = cur[last_space + 1 :]
            else:
                rows.append(cur)
                cur = []
            used = sum(get_cwidth(c) for _, c in cur)
            last_space = max((i for i, (_, c) in enumerate(cur) if c == " "), default=-1)
            if ch == " ":
                continue
        if ch == " ":
            last_space = len(cur)
        cur.append((st, ch))
        used += cw
    rows.append(cur)
    return rows


def _merge(row: list[Frag]) -> list[Any]:
    out: list[Frag] = []
    for st, ch in row:
        if out and out[-1][0] == st:
            out[-1] = (st, out[-1][1] + ch)
        else:
            out.append((st, ch))
    return out


def _unmerge(row: list[Frag]) -> list[Frag]:
    return [(st, c) for st, text in row for c in text]


def _split_lines(raw: str) -> list[list[Frag]]:
    lines: list[list[Frag]] = [[]]
    for frag in to_formatted_text(ANSI(raw)):
        style, text = frag[0], frag[1]
        for i, piece in enumerate(text.split("\n")):
            if i:
                lines.append([])
            lines[-1].extend((style, c) for c in piece)
    return lines


class _Hint(Processor):
    """Dim placeholder text shown inside the input while it is empty."""

    def __init__(self, text: Callable[[], str]) -> None:
        self.text = text

    def apply_transformation(self, ti: TransformationInput) -> Transformation:
        if ti.lineno == 0 and not ti.document.text and self.text():
            return Transformation([*ti.fragments, ("class:queued", self.text())])
        return Transformation(ti.fragments)


class _Transcript(UIControl):
    """Wrapped, scrollable view of everything the session printed."""

    def __init__(self, ui: FullScreen):
        self.ui = ui
        self.window: Window | None = None
        self.pin: int | None = None  # None = follow the bottom, else the row kept in view
        self._key: tuple[int, int] | None = None
        self._rows: list[list[Frag]] = [[]]

    def is_focusable(self) -> bool:
        return False

    def rows(self, width: int) -> list[list[Frag]]:
        key = (self.ui.version, width)
        if key != self._key:
            rows: list[list[Frag]] = []
            for line in self.ui.lines:
                rows.extend(_wrap(line, width))
            self._rows, self._key = rows or [[]], key
        return self._rows

    def create_content(self, width: int, height: int) -> UIContent:
        self.ui.width, self.ui.height = max(width, 20), max(height, 1)
        rows = list(self.rows(width))
        if len(rows) > 1 and not rows[-1]:
            rows.pop()  # the empty row after the last newline: keep text against the input
        if len(rows) < height:  # short transcript: sit on the input, fill upward
            pad = height - len(rows)
            rows = self.ui.welcome(width, pad) + rows
            self.pin = None
        y = len(rows) - 1 if self.pin is None else min(self.pin, len(rows) - 1)
        return UIContent(
            get_line=lambda i: _merge(rows[i]),
            line_count=len(rows),
            cursor_position=Point(0, y),
            show_cursor=False,
        )

    def scroll(self, delta: int) -> None:
        info = self.window.render_info if self.window else None
        if info is None:
            return
        total = info.ui_content.line_count
        if delta < 0:
            self.pin = max(0, info.first_visible_line() + delta)
        else:
            target = info.last_visible_line() + delta
            self.pin = None if target >= total - 1 else target

    def mouse_handler(self, mouse_event: MouseEvent) -> Any:
        if mouse_event.event_type == MouseEventType.SCROLL_UP:
            self.scroll(-3)
        elif mouse_event.event_type == MouseEventType.SCROLL_DOWN:
            self.scroll(3)
        else:
            return NotImplemented
        return None


class FullScreen:
    def __init__(self, session: Any, input: Any = None, output: Any = None):
        self.s = session
        self.lock = threading.Lock()
        self.raw = ""
        self.lines: list[list[Frag]] = [[]]
        self.version = 0
        self.width, self.height = shutil.get_terminal_size()
        self.console = UIConsole(self)
        self.label = "❯ "
        self.reading = False
        self.interrupted = False
        self.busy_since: float | None = None
        self.q: queue.Queue[str | None] = queue.Queue()
        self.pending: list[str] = []
        self.menu: dict[str, Any] | None = None  # the open picker, if any
        self.menu_q: queue.Queue[int | None] = queue.Queue()
        self.words = list(SPIN_WORDS)
        self.transcript = _Transcript(self)
        self.input = Buffer(
            history=InMemoryHistory(),
            completer=SlashCompleter(),
            complete_while_typing=True,
            multiline=True,
        )
        self.app = self._build(input, output)
        session.console = self.console
        session.read_line = self.read

    # -- output side (worker thread) ------------------------------------------------
    def feed(self, s: str) -> None:
        with self.lock:
            self.raw += s
            if len(self.raw) > MAX_RAW:
                cut = self.raw.find("\n", len(self.raw) - MAX_RAW // 2)
                self.raw = self.raw[cut + 1 :] if cut >= 0 else self.raw[-MAX_RAW // 2 :]
            self.lines = _split_lines(self.raw)
            self.version += 1
        self._redraw()

    def plain(self) -> str:
        with self.lock:
            return Text.from_ansi(self.raw).plain

    def clear(self) -> None:
        with self.lock:
            self.raw, self.lines = "", []
            self.version += 1
        self.transcript.pin = None
        self._redraw()

    def _redraw(self) -> None:
        try:
            self.app.invalidate()
        except Exception:  # no running loop yet or already closed
            pass

    @contextmanager
    def busy(self) -> Iterator[None]:
        self.busy_since = time.monotonic()
        try:
            yield
        finally:
            self.busy_since = None
            self._redraw()

    # -- welcome screen: fills the empty space above a short transcript ----------------
    def welcome(self, width: int, pad: int) -> list[list[Frag]]:
        """`pad` rows to draw above the transcript: the animated logo block, at the top."""
        block: list[list[Frag]] = []
        grid = _grid(2, 1)
        if width >= len(grid[0]) + 4:
            t = time.monotonic()
            span = len(grid[0])
            glint = int(t * 24) % (span + 60) - 30  # a glint passes every few seconds
            for row in grid:
                line: list[Frag] = []
                for x, ch in enumerate(row):
                    if ch == " ":
                        line.append(("", " "))
                        continue
                    hue = _lerp([ACCENT, COACH, RED], x / span)
                    line.append((f"bold fg:{hue}" if abs(x - glint) < 5 else f"fg:{hue}", ch))
                block.append(line)
        else:
            block.append([(f"bold fg:{ACCENT}", "✻ anvyl")])
        cwd = str(self.s.root)
        tips = "/help for commands  ·  /done when finished  ·  /hint for the coach"
        block += [
            [],
            [(f"fg:{MUTED}", "you drive, the AI navigates")],
            [],
            [(f"fg:{MUTED}", "cwd  "), ("", cwd[-max(width - 10, 10) :])],
            [(f"fg:{MUTED}", tips[: max(width - 2, 10)])],
        ]
        if len(block) + 2 > pad:
            return [[] for _ in range(pad)]
        top = 1  # start at the top of the screen; messages grow upward from the input
        out: list[list[Frag]] = [[] for _ in range(top)]
        for line in block:
            w = sum(get_cwidth(c) for _, c in line)
            out.append(([("", " " * ((width - w) // 2))] if line else []) + line)
        # characters are single cells here, so a row of (style, text) pairs merges cleanly
        return [_unmerge(r) for r in out] + [[] for _ in range(pad - top - len(block))]

    # -- input side ---------------------------------------------------------------
    def read(self, prompt: str) -> str | None:
        chat = prompt in ("ticket> ", "> ")
        self.label = "❯ " if chat else prompt
        if chat and self.pending:  # typed while the agent worked: send it now
            text = self.pending.pop(0)
            self._echo(text)
            return text
        self.reading = True
        self._redraw()
        item = self.q.get()
        self.reading = False
        return item

    def _echo(self, text: str) -> None:
        """Your message in the transcript: a full-width band, darker than the page."""
        self.console.print()
        for i, ln in enumerate(_clean(text, 4000).splitlines() or [""]):
            row = Text.assemble(("❯ " if i == 0 else "  ", f"bold {COACH}"), ln)
            row.pad_right(max(0, self.width - row.cell_len))
            self.console.print(row, style=f"on {USER_BG}", soft_wrap=True, highlight=False)
        self.transcript.pin = None

    def _submit(self) -> None:
        text = self.input.text
        if not text.strip():
            return
        self.input.append_to_history()
        self.input.reset()
        if not self.reading:
            self.pending.append(text)  # queued: shown dimmed, sent at the next chat prompt
            self._redraw()
            return
        self.reading = False
        self._echo(text)
        self.q.put(text)

    # -- layout ---------------------------------------------------------------------
    def _spinner(self) -> FormattedText:
        if self.busy_since is None:
            return FormattedText([])
        el = time.monotonic() - self.busy_since
        return FormattedText(
            [
                ("class:spin.glyph", " " + GLYPHS[int(el * 8) % len(GLYPHS)] + " "),
                ("class:spin.word", self.words[int(el // 4) % len(self.words)] + "… "),
                ("class:spin.time", f"({int(el)}s)"),
            ]
        )

    # -- picker (worker thread asks, UI thread answers) -------------------------------
    def choose(self, title: str, items: list[tuple[str, str]], hint: str = "") -> int | None:
        """Show a filterable list; return the chosen index, or None on Esc."""
        with self.lock:
            self.menu = {"title": title, "items": items, "q": "", "sel": 0, "hint": hint}
        self._redraw()
        got = self.menu_q.get()
        with self.lock:
            self.menu = None
        self._redraw()
        return got

    def _visible(self) -> list[int]:
        m = self.menu or {}
        words = str(m.get("q", "")).lower().split()
        return [
            i
            for i, (a, b) in enumerate(m.get("items", []))
            if all(w in f"{a} {b}".lower() for w in words)
        ]

    def _menu_text(self) -> FormattedText:
        m = self.menu
        if not m:
            return FormattedText([])
        vis = self._visible()
        sel = min(m["sel"], max(len(vis) - 1, 0))
        top = max(0, min(sel - 5, len(vis) - 12))
        out: list[Frag] = [
            ("class:menu.title", f" {m['title']}  "),
            ("class:menu.dim", f"{len(vis)}\n"),
        ]
        out.append(("class:menu.dim", f" › {m['q']}▏\n"))
        for k in range(top, min(top + 12, len(vis))):
            a, b = m["items"][vis[k]]
            on = k == sel
            out.append(("class:menu.sel" if on else "", f" {'▸' if on else ' '} {a}"))
            out.append(("class:menu.sel" if on else "class:menu.dim", f"  {b}\n"))
        if not vis:
            out.append(("class:menu.dim", " no matches\n"))
        out.append(("class:menu.dim", f" ↑↓ move · Enter select · Esc cancel{m['hint']}"))
        return FormattedText(out)

    def _queued(self) -> FormattedText:
        rows = [(" ❯ " + " ".join(t.split())[:200] + "\n") for t in self.pending[-3:]]
        return FormattedText([("class:queued", "".join(rows).rstrip("\n"))])

    def _build(self, input: Any, output: Any) -> Application[None]:
        tr = self.transcript
        tr.window = Window(tr, wrap_lines=False, always_hide_cursor=True)
        input_win = Window(
            BufferControl(
                self.input, input_processors=[_Hint(lambda: getattr(self.s, "hint", ""))]
            ),
            height=Dimension(min=1, max=8),
            wrap_lines=True,
            dont_extend_height=True,
        )
        tag = Window(
            FormattedTextControl(lambda: FormattedText([("class:prompt", self.label)])),
            width=lambda: len(self.label),
            dont_extend_width=True,
        )
        status = Window(
            FormattedTextControl(lambda: status_fragments(self.s)), height=1, style="class:bar"
        )
        rule = lambda: Window(height=1, char="─", style="class:rule")  # noqa: E731
        body = HSplit(
            [
                tr.window,
                Window(FormattedTextControl(self._spinner), height=1),
                Window(
                    FormattedTextControl(self._queued),
                    height=lambda: min(len(self.pending), 3),
                    style="class:queued",
                ),
                rule(),
                VSplit([tag, input_win]),
                rule(),
                status,
            ]
        )
        # the input is pinned to the bottom, so the slash menu opens upward, above the rule
        menu = Float(left=2, bottom=4, content=CompletionsMenu(max_height=8, scroll_offset=1))
        picker = Float(
            left=1,
            right=1,
            bottom=3,
            content=ConditionalContainer(
                Window(
                    FormattedTextControl(self._menu_text),
                    height=lambda: 17,
                    style="class:menu",
                    dont_extend_height=True,
                ),
                filter=Condition(lambda: self.menu is not None),
            ),
        )
        kb = KeyBindings()
        open_ = Condition(lambda: self.menu is not None)

        def move(d: int) -> None:
            with self.lock:
                if self.menu:
                    n = len(self._visible())
                    self.menu["sel"] = max(0, min(self.menu["sel"] + d, n - 1))

        @kb.add("up", filter=open_, eager=True)
        def _(event: Any) -> None:
            move(-1)

        @kb.add("down", filter=open_, eager=True)
        def _(event: Any) -> None:
            move(1)

        @kb.add("enter", filter=open_, eager=True)
        def _(event: Any) -> None:
            vis = self._visible()
            if vis:
                self.menu_q.put(vis[min(self.menu["sel"], len(vis) - 1)])  # type: ignore[index]

        @kb.add("escape", filter=open_, eager=True)
        @kb.add("c-d", filter=open_, eager=True)
        def _(event: Any) -> None:
            self.menu_q.put(None)

        @kb.add("backspace", filter=open_, eager=True)
        def _(event: Any) -> None:
            if self.menu:
                self.menu["q"], self.menu["sel"] = self.menu["q"][:-1], 0

        @kb.add(Keys.Any, filter=open_, eager=True)
        def _(event: Any) -> None:
            if self.menu and event.data.isprintable():
                self.menu["q"], self.menu["sel"] = self.menu["q"] + event.data, 0

        @kb.add("enter", filter=~open_)
        def _(event: Any) -> None:
            self._submit()

        @kb.add("escape", "enter")
        def _(event: Any) -> None:
            self.input.insert_text("\n")

        @kb.add("pageup")
        def _(event: Any) -> None:
            tr.scroll(-max(self.height - 2, 1))

        @kb.add("pagedown")
        def _(event: Any) -> None:
            tr.scroll(max(self.height - 2, 1))

        @kb.add("c-d")
        def _(event: Any) -> None:
            if not self.input.text and self.reading:
                self.q.put(None)

        @kb.add("c-c")
        def _(event: Any) -> None:
            self.interrupted = True
            self.q.put(None)
            event.app.exit()

        return Application(
            layout=Layout(FloatContainer(body, floats=[menu, picker]), focused_element=input_win),
            key_bindings=kb,
            style=STYLE,
            full_screen=True,
            mouse_support=True,
            refresh_interval=0.1,
            erase_when_done=True,
            input=input,
            output=output,
        )

    # -- run ------------------------------------------------------------------------
    def run(self, body: Callable[[], int]) -> int:
        result: list[int] = [1]

        def work() -> None:
            try:
                result[0] = body()
            finally:
                try:
                    loop = self.app.loop
                    if loop is not None:
                        loop.call_soon_threadsafe(self._exit)
                except Exception:
                    pass

        thread = threading.Thread(target=work, daemon=True)
        self.app.run(pre_run=thread.start)
        self.q.put(None)  # release a worker still waiting for input
        thread.join(timeout=2)
        return 130 if self.interrupted else result[0]

    def _exit(self) -> None:
        if self.app.is_running and not self.app.future.done():  # type: ignore[union-attr]
            self.app.exit()
