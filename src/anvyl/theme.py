"""Shared terminal look: palette, meters, spinner words, typewriter, fill animation.

Colour is applied only to Anvyl's own strings, through Rich `style=` / `Text`, never
by parsing markup out of model, repo or typed text.
"""

from __future__ import annotations

import os
import random
import time
from collections.abc import Callable, Mapping
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text


def light_terminal(env: Mapping[str, str] | None = None) -> bool:
    """True if COLORFGBG ("fg;bg") reports a light background; dark otherwise."""
    value = (os.environ if env is None else env).get("COLORFGBG", "")
    return value.rsplit(";", 1)[-1] in {"7", "15"}


# Palette (Mistral brand): amber accent, orange coach, red only for locked/errors.
# Dark is the default; the light variant is darkened so it stays readable on white.
if light_terminal():
    ACCENT, COACH, MUTED, RED = "#b86e00", "#c25a00", "#71717b", "#c20f00"
else:
    ACCENT, COACH, MUTED, RED = "#ffaf01", "#ff8204", "#a0a0a8", "#e51300"

FILL_FRAMES = 12
SPIN_WORDS = (
    "Vibing",
    "Subliminating",
    "Noodling",
    "Percolating",
    "Cogitating",
    "Marinating",
    "Discombobulating",
    "Flibbertigibbeting",
    "Reticulating",
    "Combobulating",
    "Pondering",
    "Ruminating",
    "Simmering",
    "Brewing",
    "Conjuring",
    "Spelunking",
    "Wibbling",
    "Moseying",
    "Finagling",
    "Tinkering",
    "Puttering",
    "Smooshing",
    "Schlepping",
    "Wrangling",
    "Musing",
    "Concocting",
    "Cerebrating",
    "Incubating",
    "Germinating",
    "Transmuting",
    "Unfurling",
    "Frolicking",
    "Sussing",
    "Mulling",
    "Churning",
    "Whirring",
    "Shimmying",
    "Pontificating",
)
TYPE_MAX_S = 1.0  # typewriter never delays a reply by more than this


def bar(pct: float, width: int = 20) -> str:
    pct = max(0.0, min(100.0, pct))
    filled = int(round(pct / 100 * width))
    done, todo = "█" * filled, "░" * (width - filled)
    return f"[{ACCENT}]{done}[/{ACCENT}][{MUTED}]{todo}[/{MUTED}] {pct:.0f}%"


def spin_word() -> str:
    return random.choice(SPIN_WORDS) + "..."


def typewrite(console: Console, text: str) -> None:
    """Print text char by char on a terminal (<= TYPE_MAX_S total), else all at once."""
    if not console.is_terminal:
        console.print(text, soft_wrap=True, markup=False, highlight=False, emoji=False)
        return
    delay = min(0.02, TYPE_MAX_S / max(len(text), 1))
    for ch in text:
        console.print(ch, end="", markup=False, highlight=False, emoji=False)
        time.sleep(delay)
    console.print()


def bar_text(pct: float, width: int = 20) -> Text:
    """The same meter as `bar`, built as Text so nothing in it is ever parsed as markup."""
    pct = max(0.0, min(100.0, pct))
    filled = int(round(pct / 100 * width))
    t = Text("█" * filled, style=ACCENT)
    t.append("░" * (width - filled), style=MUTED)
    t.append(f" {pct:.0f}%")
    return t


GLYPHS = "·✢✳✶✻✽"


class _Spin:
    """Claude Code style spinner line: glyph, rotating word, elapsed seconds."""

    def __init__(self) -> None:
        self.t0 = time.monotonic()
        self.words = random.sample(SPIN_WORDS, len(SPIN_WORDS))

    def __rich_console__(self, console: Console, options: Any) -> Any:
        el = time.monotonic() - self.t0
        yield Text.assemble(
            (GLYPHS[int(el * 8) % len(GLYPHS)] + " ", ACCENT),
            (self.words[int(el // 4) % len(self.words)] + "… ", COACH),
            (f"({int(el)}s)", MUTED),
        )


def busy(console: Console) -> Any:
    """Live spinner line while the model works; nothing off a terminal."""
    if ui := getattr(console, "ui", None):  # full-screen UI draws its own spinner
        return ui.busy()
    if not console.is_terminal:
        return nullcontext()
    return Live(_Spin(), console=console, refresh_per_second=12, transient=True)


def animate(console: Console, render: Callable[[float], Any]) -> None:
    """Show `render(fill)` filling 0 -> 1 on a terminal; print `render(1)` once otherwise."""
    if not console.is_terminal or getattr(console, "ui", None):
        console.print(render(1.0))
        return
    with Live(render(0.0), console=console, auto_refresh=False) as live:
        for step in range(1, FILL_FRAMES + 1):
            time.sleep(0.04)
            live.update(render(step / FILL_FRAMES), refresh=True)


def banner(root: Path) -> Any:
    """Welcome panel for the real session (Anvyl-owned text plus the folder path)."""
    body = Text()
    body.append("✻ ", style=ACCENT)
    body.append("anvyl", style=f"bold {ACCENT}")
    body.append("  you drive, the AI navigates\n\n", style=MUTED)
    body.append("cwd  ", style=MUTED)
    body.append(str(root))
    body.append("\n/help for commands  ·  /done when finished  ·  /hint for the coach", style=MUTED)
    return Panel(body, border_style=ACCENT, expand=False)


_LOGO = {
    "a": [" ███ ", "█   █", "█████", "█   █", "█   █"],
    "n": ["█   █", "██  █", "█ █ █", "█  ██", "█   █"],
    "v": ["█   █", "█   █", "█   █", " █ █ ", "  █  "],
    "y": ["█   █", " █ █ ", "  █  ", "  █  ", "  █  "],
    "l": ["█    ", "█    ", "█    ", "█    ", "█████"],
}


def _grid(sx: int, sy: int) -> list[str]:
    rows = ["  ".join(_LOGO[c][r] for c in "anvyl") for r in range(5)]
    rows = ["".join(ch * sx for ch in row) for row in rows]
    return [r for row in rows for r in [row] * sy]


def _lerp(stops: list[str], t: float) -> str:
    t = min(max(t, 0.0), 1.0) * (len(stops) - 1)
    i = min(int(t), len(stops) - 2)
    f = t - i
    a, b = (tuple(int(c[k : k + 2], 16) for k in (1, 3, 5)) for c in stops[i : i + 2])
    return "#" + "".join(f"{round(x + (y - x) * f):02x}" for x, y in zip(a, b, strict=True))


def _frame(grid: list[str], resolved: int, glint: int, rng: random.Random) -> Text:
    """Cells left of `resolved` show the gradient logo (bold near `glint`); the rest scramble."""
    width = len(grid[0])
    stops = [ACCENT, COACH, RED]
    out = Text()
    for row in grid:
        for x, ch in enumerate(row):
            if ch == " ":
                out.append(" ")
            elif x > resolved:
                out.append(rng.choice("░▒▓▚▞"), style=MUTED)
            elif x > resolved - 4 and resolved < width:
                out.append(rng.choice("▒▓█"), style=f"bold {ACCENT}")
            else:
                style = _lerp(stops, x / width)
                out.append(ch, style=f"bold {style}" if abs(x - glint) < 5 else style)
        out.append("\n")
    return out


def intro(console: Console) -> None:
    """Full-window splash (terminal only, ~2s): the logo resolves out of static, centered,
    a glint sweeps across, the tagline appears; then the screen is handed back."""
    if not console.is_terminal:
        return
    cols, rows = console.size
    sx = max(2, min((cols - 4) // 33, 6))
    sy = max(1, min(sx // 2, (rows - 6) // 5))
    grid = _grid(sx, sy)
    width = len(grid[0])
    rng = random.Random()

    def show(live: Live, x: int, glint: int, tag: str = "") -> None:
        body = Group(_frame(grid, x, glint, rng), Text(tag, style=MUTED, justify="center"))
        live.update(Align.center(body, vertical="middle", height=rows))

    with Live(console=console, screen=True, refresh_per_second=30) as live:
        for x in range(0, width + 4, max(2, width // 28)):
            show(live, x, -99)
            time.sleep(0.02)
        tagline = "you drive, the AI navigates"
        step = max(3, width // 20)
        for i, x in enumerate(range(-5, width + 6, step)):
            show(live, width, x, tagline[: (i + 1) * len(tagline) // 18])
            time.sleep(0.025)
        show(live, width, -99, tagline)
        time.sleep(0.5)
