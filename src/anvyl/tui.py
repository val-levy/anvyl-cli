"""Inline terminal UI, Claude Code style: ruled input, slash menu, status line below.

Built on prompt_toolkit and kept inline (no alternate screen), so the transcript stays
in normal scrollback. The layout is our own Application rather than PromptSession's
bottom toolbar, because that toolbar stays hidden on terminals that never answer
prompt_toolkit's cursor-position request. Everything drawn here is Anvyl's own text
(constants, enums and numbers from session state) built as FormattedText, never markup.
Typed history is in memory only: nothing the human types is written to disk by this module.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition, is_done
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import (
    ConditionalContainer,
    Float,
    FloatContainer,
    HSplit,
    Layout,
    VSplit,
    Window,
)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.styles import Style

from .theme import ACCENT, COACH, MUTED

if TYPE_CHECKING:
    from .session import Session

COMMANDS = {
    "/help": "list commands",
    "/status": "show step, level, gate and usage",
    "/score": "show the last scorecard",
    "/model": "pick a model (OpenRouter, with prices)",
    "/usage": "session time, tokens, files sent",
    "/clear": "clear the screen",
    "/plugin": "list | load | unload <id>",
    "/skill": "list | load | unload <id>",
    "/graph": "show the loop steps",
    "/rail": "toggle the status rail",
    "/mode": "ship | learn",
    "/level": "coaching level 0-2",
    "/profile": "professional | personal",
    "/keepdiffs": "on | off (personal only)",
    "/done": "finish the ticket (at a work prompt)",
    "/hint": "ask the coach (at a work prompt)",
    "/exit": "leave anvyl (also /quit)",
}
STYLE = Style.from_dict(
    {
        "rule": MUTED,
        "prompt": f"bold {COACH}",
        "bar": MUTED,
        "bar.key": ACCENT,
        "spin.glyph": ACCENT,
        "spin.word": COACH,
        "spin.time": MUTED,
        "completion-menu": "bg:default",
        "completion-menu.completion": f"bg:default {MUTED}",
        "completion-menu.completion.current": f"bg:default bold {ACCENT}",
        "completion-menu.meta.completion": f"bg:default {MUTED}",
        "completion-menu.meta.completion.current": f"bg:default {MUTED}",
    }
)


class SlashCompleter(Completer):
    """Offers slash commands while the line is just a command word."""

    def get_completions(self, document: Document, complete_event: CompleteEvent) -> Iterable:
        text = document.text_before_cursor
        if not text.startswith("/") or " " in text:
            return
        for cmd, meta in COMMANDS.items():
            if cmd.startswith(text.lower()):
                yield Completion(cmd, start_position=-len(text), display_meta=meta)


def _rule() -> FormattedText:
    return FormattedText([("class:rule", "─" * shutil.get_terminal_size().columns)])


def dock(console: Any, header: Any) -> None:
    """Clear the screen and draw the header; `read` pins every prompt to the bottom row."""
    console.clear()
    console.print(header)


def status_fragments(s: Session) -> FormattedText:
    v = s.view
    files, tokens = s.stats()
    gate = "passed" if v.get("gate_passed") else "locked"
    model = str(getattr(getattr(s, "client", None), "model", "") or "")
    parts = [
        *([model.split("/")[-1]] if model else []),
        s.profile.value,
        f"mode {v.get('mode', s.mode)}",
        f"L{v.get('level', s.level)}",
        f"gate {gate}",
        f"files {files}",
        f"tokens {tokens}",
    ]
    return FormattedText(
        [("class:bar", "  " + "  ·  ".join(parts) + "    "), ("class:bar.key", "/help")]
    )


def reader(s: Session, input: Any = None, output: Any = None) -> Callable[[str], str | None]:
    """A `read_line` for Session: ruled input, slash menu, status line below. None on EOF."""
    os.environ.setdefault("PROMPT_TOOLKIT_NO_CPR", "1")  # we never need the cursor row
    history = InMemoryHistory()  # in memory only: typed text never reaches disk

    def read(prompt: str) -> str | None:
        if sys.stdout.isatty() and input is None:  # park the cursor on the last row
            sys.stdout.write(f"\x1b[{shutil.get_terminal_size().lines};1H")
            sys.stdout.flush()
        label = "❯ " if prompt in ("ticket> ", "> ") else prompt
        buf = Buffer(
            history=history,
            completer=SlashCompleter(),
            complete_while_typing=True,
        )
        menu_open = Condition(lambda: buf.text.startswith("/") and " " not in buf.text)
        field = Window(BufferControl(buf), dont_extend_height=True, wrap_lines=True)
        tag = Window(
            FormattedTextControl([("class:prompt", label)]),
            width=len(label),
            dont_extend_width=True,
        )
        status = Window(FormattedTextControl(lambda: status_fragments(s)), height=1)
        below = ConditionalContainer(
            HSplit([Window(FormattedTextControl(_rule), height=1), status]), filter=~is_done
        )
        spacer = ConditionalContainer(Window(height=8), filter=menu_open & ~is_done)
        body = HSplit(
            [Window(FormattedTextControl(_rule), height=1), VSplit([tag, field]), below, spacer]
        )
        float_menu = Float(
            xcursor=True, ycursor=True, content=CompletionsMenu(max_height=8, scroll_offset=1)
        )
        layout = Layout(FloatContainer(body, floats=[float_menu]), focused_element=field)
        kb = KeyBindings()

        @kb.add("enter")
        def _(event: Any) -> None:
            buf.append_to_history()
            event.app.exit(result=buf.text)

        @kb.add("c-c")
        def _(event: Any) -> None:
            event.app.exit(exception=KeyboardInterrupt)

        @kb.add("c-d", filter=Condition(lambda: not buf.text))
        def _(event: Any) -> None:
            event.app.exit(exception=EOFError)

        app: Application[str] = Application(
            layout=layout, key_bindings=kb, style=STYLE, input=input, output=output
        )
        try:
            return app.run()
        except EOFError:
            return None

    return read
