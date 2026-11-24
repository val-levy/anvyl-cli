"""`anvyl history`: a table of past sessions plus a one-line summary.

Records are untrusted data. This module only displays a few fields; every
value is type-checked, sanitised (grader._clean) and printed as plain
``Text`` so markup/ANSI in a record can never take effect. It never reads
attempt text or code.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text

from .grader import _clean

MIN_PER_LEVEL = 3
_BIG = 1e11  # beyond any real epoch / duration / line count


def load_sessions(sessions_dir: Path) -> list[dict]:
    """Every readable JSON-object record; schema_version defaults to 1, profile to tutorial."""
    rows: list[dict] = []
    try:
        paths = sorted(Path(sessions_dir).glob("*.json"))
    except OSError:
        return rows
    for p in paths:
        try:
            rec = json.loads(p.read_text())
        except (OSError, ValueError, RecursionError):
            continue
        if isinstance(rec, dict):
            rec.setdefault("schema_version", 1)
            rec.setdefault("profile", "tutorial")
            rows.append(rec)
    return rows


def _num(v: object) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    try:
        f = float(v)
    except OverflowError:
        return None
    return f if math.isfinite(f) and abs(f) < _BIG else None


def _level(rec: dict) -> int | None:
    n = _num(rec.get("level"))
    return int(n) if n is not None and 0 <= n <= 4 else None


def _ownership(rec: dict) -> float | None:
    """0-100, or None when absent/invalid (explain-back skipped stores None for real runs)."""
    n = _num(rec.get("ownership_score"))
    return None if n is None else max(0.0, min(100.0, n * 100))


def _str(v: object, cap: int = 60) -> str:
    return _clean(v, cap).replace("\n", " ") if isinstance(v, str) and v else "-"


def _date(rec: dict) -> str:
    t = _num(rec.get("started_at"))
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t is not None else "-"
    except (OverflowError, OSError, ValueError):
        return "-"


def _you_pct(rec: dict) -> str:
    h, a = _num(rec.get("human_lines")), _num(rec.get("ai_lines"))
    if h is None or a is None or h < 0 or a < 0 or h + a == 0:
        return "-"
    return f"{h / (h + a) * 100:.0f}%"


def _mins(v: object) -> str:
    n = _num(v)
    return "-" if n is None or n < 0 else f"{n / 60:.0f}m"


def summary_lines(rows: list[dict]) -> list[str]:
    by_level: dict[int, list[float]] = {}
    counts: dict[int, int] = {}
    for r in rows:
        lvl = _level(r)
        if lvl is None:
            continue
        counts[lvl] = counts.get(lvl, 0) + 1
        own = _ownership(r)
        if own is not None:
            by_level.setdefault(lvl, []).append(own)
    means = {lvl: sum(v) / len(v) for lvl, v in by_level.items()}
    parts = [f"L{lvl} {means[lvl]:.0f}%" for lvl in sorted(means)]
    lines = ["Mean ownership: " + (", ".join(parts) if parts else "-")]
    if (
        counts.get(1, 0) >= MIN_PER_LEVEL
        and counts.get(2, 0) >= MIN_PER_LEVEL
        and 1 in means
        and 2 in means
        and means[2] < means[1]
    ):
        lines.append("L2 sessions averaged lower ownership than L1.")
    return lines


def render_history(rows: list[dict], console: Console) -> None:
    if not rows:
        console.print("No sessions yet. Run `anvyl` to start one.", markup=False)
        return
    table = Table(title="anvyl history")
    for col in ("date", "title", "mode", "level", "profile", "ownership", "you vs AI", "time"):
        table.add_column(col)
    for r in sorted(rows, key=lambda r: _num(r.get("started_at")) or 0.0, reverse=True):
        lvl, own = _level(r), _ownership(r)
        title = r.get("task_title") if isinstance(r.get("task_title"), str) else None
        cells = [
            _date(r),
            _str(title or r.get("ticket")),
            _str(r.get("mode")),
            "-" if lvl is None else f"L{lvl}",
            _str(r.get("profile")),
            "-" if own is None else f"{own:.0f}%",
            _you_pct(r),
            f"{_mins(r.get('time_with_ai_s'))} / {_mins(r.get('est_without_ai_s'))}",
        ]
        table.add_row(*(Text(c) for c in cells))
    console.print(table)
    for line in summary_lines(rows):
        console.print(Text(line))
