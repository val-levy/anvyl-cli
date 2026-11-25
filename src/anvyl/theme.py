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

from rich.console import Console
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
    USER_BG = "#e9e9ec"  # your own messages sit on a slightly darker band than the page
else:
    ACCENT, COACH, MUTED, RED = "#ffaf01", "#ff8204", "#a0a0a8", "#e51300"
    USER_BG = "#2b2d31"

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
# Busy glyph: 8x4 pixel art drawn with braille dots (4 cells wide): a hammer swings down onto
# an anvil, the strike flashes, sparks fly. '#' = dot on.
_ANVIL = ("........", "........", "...#####", "....###.")
_HAMMER = {  # frame name -> hammer pixels in the top rows
    "up": ("##......", "##......", ".#......", "#......."),
    "mid": ("..##....", "..##....", ".#......", "#......."),
    "hit": ("...##...", "..###...", ".#......", "#......."),
}
_SPARKS = ("......#.", ".....#.#", "........", "........")
_FORGE = (  # (hammer, sparks?, colour role)
    ("up", False, "accent"),
    ("up", False, "accent"),
    ("mid", False, "coach"),
    ("hit", False, "coach"),
    ("hit", True, "red"),
    ("mid", True, "coach"),
)
_DOTS = ((1, 8), (2, 16), (4, 32), (64, 128))  # braille bit per (row, left/right pixel)


def _braille(rows: list[str]) -> str:
    return "".join(
        chr(0x2800 + sum(_DOTS[r][c] for r in range(4) for c in (0, 1) if rows[r][x + c] == "#"))
        for x in range(0, len(rows[0]), 2)
    )


def forge(el: float) -> tuple[str, str]:
    """The hammer-and-anvil glyph at `el` seconds: (text, colour)."""
    hammer, spark, role = _FORGE[int(el * 7) % len(_FORGE)]
    rows = [
        "".join("#" if "#" in px else "." for px in zip(*layers, strict=True))
        for layers in zip(
            _ANVIL, _HAMMER[hammer], _SPARKS if spark else ("........",) * 4, strict=True
        )
    ]
    return _braille(rows), {"accent": ACCENT, "coach": COACH, "red": RED}[role]


class _Spin:
    """Claude Code style spinner line: glyph, rotating word, elapsed seconds."""

    def __init__(self) -> None:
        self.t0 = time.monotonic()
        self.words = random.sample(SPIN_WORDS, len(SPIN_WORDS))

    def __rich_console__(self, console: Console, options: Any) -> Any:
        el = time.monotonic() - self.t0
        yield Text.assemble(
            (forge(el)[0] + " ", forge(el)[1]),
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


Cell = tuple[str, str]  # (character, rich style)


def _frame(
    grid: list[str], resolved: int, glint: int, rng: random.Random
) -> list[list[Cell | None]]:
    """Cells left of `resolved` show the gradient logo (bold near `glint`); the rest scramble.
    Blank logo cells are None so the background shows through."""
    width = len(grid[0])
    stops = [ACCENT, COACH, RED]
    out: list[list[Cell | None]] = []
    for row in grid:
        line: list[Cell | None] = []
        for x, ch in enumerate(row):
            if ch == " ":
                line.append(None)
            elif x > resolved:
                line.append((rng.choice("░▒▓▚▞"), MUTED))
            elif x > resolved - 4 and resolved < width:
                line.append((rng.choice("▒▓█"), f"bold {ACCENT}"))
            else:
                style = _lerp(stops, x / width)
                line.append((ch, f"bold {style}" if abs(x - glint) < 5 else style))
        out.append(line)
    return out


def _embers(
    cols: int, rows: int, t: int, seeds: dict[int, tuple[float, float]]
) -> list[list[Cell | None]]:
    """Dim sparks rising through the window: a bright head with a cooling trail below it."""
    cells: list[list[Cell | None]] = [[None] * cols for _ in range(rows)]
    for c, (speed, phase) in seeds.items():
        head = int(phase - t * speed) % (rows + 8)
        for k, (glyph, colour) in enumerate((("•", ACCENT), ("∙", COACH), ("·", RED))):
            if head + k < rows:
                cells[head + k][c] = (glyph, f"dim {colour}")
    return cells


def intro(console: Console) -> None:
    """Full-window splash (terminal only, ~2s): embers drift up behind the logo as it resolves
    out of static, a glint sweeps across, the tagline appears; then the screen is handed back."""
    if not console.is_terminal:
        return
    cols, rows = console.size
    sx = max(2, min((cols - 4) // 33, 6))
    sy = max(1, min(sx // 2, (rows - 6) // 5))
    grid = _grid(sx, sy)
    width, height = len(grid[0]), len(grid)
    rng = random.Random()
    seeds = {
        c: (rng.uniform(0.3, 1.0), rng.uniform(0, rows + 8))
        for c in range(cols)
        if rng.random() < 0.1
    }
    top, left = max(0, (rows - height - 2) // 2), max(0, (cols - width) // 2)
    tick = 0

    def show(live: Live, x: int, glint: int, tag: str = "") -> None:
        nonlocal tick
        tick += 1
        canvas = _embers(cols, rows, tick, seeds)
        for dy, line in enumerate(_frame(grid, x, glint, rng)):
            for dx, cell in enumerate(line):
                if cell and top + dy < rows and left + dx < cols:
                    canvas[top + dy][left + dx] = cell
        tag_row, tag_col = top + height + 1, max(0, (cols - len(tag)) // 2)
        for i, ch in enumerate(tag):
            if tag_row < rows and tag_col + i < cols:
                canvas[tag_row][tag_col + i] = (ch, MUTED)
        text = Text(no_wrap=True, overflow="crop")
        for r, line in enumerate(canvas):
            for cell in line:
                text.append(*cell) if cell else text.append(" ")
            if r < rows - 1:
                text.append("\n")
        live.update(text)

    with Live(console=console, screen=True, refresh_per_second=30) as live:
        for x in range(0, width + 4, max(2, width // 28)):
            show(live, x, -99)
            time.sleep(0.02)
        tagline = "you drive, the AI navigates"
        step = max(3, width // 20)
        for i, x in enumerate(range(-5, width + 6, step)):
            show(live, width, x, tagline[: (i + 1) * len(tagline) // 18])
            time.sleep(0.025)
        for _ in range(20):  # hold: embers keep drifting behind the finished logo
            show(live, width, -99, tagline)
            time.sleep(0.025)
