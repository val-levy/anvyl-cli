"""First-run welcome menu: what Anvyl is and how to get the most out of it.

Plain Anvyl-owned text. In the full-screen UI the pages sit behind the existing picker;
everywhere else (pipes, `anvyl --welcome`) they print as plain text, so it never blocks.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from . import tui

if TYPE_CHECKING:
    from .session import Session

PAGES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "What Anvyl is",
        (
            "Anvyl is a coding tutor, not a code generator: you drive, the AI teaches.",
            "It only does things for you that you have already shown you can do,",
            "and it keeps track of what you know so it never re-teaches it.",
        ),
    ),
    (
        "Your first session",
        (
            "Type one task. Anvyl asks what done looks like and how you would go about it.",
            "'I don't know' is a fine answer: it teaches, it never locks you out.",
            "Then you write the code in your editor, type /done, and explain your change.",
        ),
    ),
    (
        "Get the most out of it",
        (
            "Say 'I don't know' freely: that is how the tutor finds the gap to teach.",
            "/hint asks for another question. /memory shows what you have shown you know.",
            "/mode ship skips the teaching when you just need speed.",
            "/model picks the model. /level sets how much help; your score after each",
            "ticket tells you how well you could explain your own change.",
        ),
    ),
    ("Commands", tuple(f"{c:<11}{d}" for c, d in tui.COMMANDS.items())),
    (
        "Privacy",
        (
            "Sent to the model: your ticket, what you type, and (only if you allow it)",
            "non-secret files in the folder, with secrets redacted first.",
            "Stored locally: sessions and a short list of ideas you showed you know.",
            "/memory forget <idea> removes one. 'anvyl reset' deletes everything.",
        ),
    ),
    ("Start", ("Press Esc, or type your first task at the ticket prompt.",)),
)


def seen(data_dir: Path) -> bool:
    return (Path(data_dir) / "welcomed").exists()


def mark_seen(data_dir: Path) -> None:
    path = Path(data_dir) / "welcomed"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.close(fd)


def lines() -> list[str]:
    return [x for title, body in PAGES for x in (title, *body, "")]


def show(s: Session) -> None:
    """Picker in the full-screen UI (Enter opens a page, Esc or Start closes); plain otherwise."""
    ui = getattr(s.console, "ui", None)
    if not ui:
        for line in lines():
            s.say(line)
        return
    rows = [(title, body[0]) for title, body in PAGES]
    while (i := ui.choose("welcome", rows)) is not None and i < len(PAGES) - 1:
        for line in (PAGES[i][0], *PAGES[i][1]):
            s.say(line)
