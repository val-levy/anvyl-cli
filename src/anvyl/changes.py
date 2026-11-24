"""Session change tracking: transient baseline copies plus in-memory diffs."""

import difflib
import shutil
from dataclasses import dataclass
from pathlib import Path

from anvyl.guard import list_files
from anvyl.profile import Profile


@dataclass
class Changes:
    files: list[str]
    added: int
    removed: int
    added_lines: list[str]
    text: str  # unified diff, in memory only, never persisted


def _read(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def take_snapshot(root: Path, profile: Profile, work_dir: Path) -> None:
    root = root.resolve()
    base = work_dir / "base"
    clear_snapshot(work_dir)
    base.mkdir(parents=True)
    for rel in list_files(root, profile):
        dest = base / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        lines = _read(root / rel)
        dest.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _baseline(base: Path) -> set[str]:
    if not base.is_dir():
        return set()
    return {
        p.relative_to(base).as_posix()
        for p in base.rglob("*")
        if p.is_file() and not p.is_symlink()
    }


def compute_changes(root: Path, profile: Profile, work_dir: Path) -> Changes:
    root = root.resolve()
    base = work_dir / "base"
    old_paths = _baseline(base)
    now = set(list_files(root, profile))
    files: list[str] = []
    added_lines: list[str] = []
    removed = 0
    diffs: list[str] = []
    for rel in sorted(now | old_paths):
        if rel in old_paths and rel not in now and (root / rel).exists():
            continue  # no longer listable (denied/ignored) but still on disk: not a deletion
        old = _read(base / rel) if rel in old_paths else []
        new = _read(root / rel) if rel in now else []
        if old == new:
            continue
        files.append(rel)
        for line in difflib.unified_diff(old, new, f"a/{rel}", f"b/{rel}", lineterm=""):
            diffs.append(line)
            if line.startswith("+") and not line.startswith("+++"):
                added_lines.append(line[1:])
            elif line.startswith("-") and not line.startswith("---"):
                removed += 1
    return Changes(files, len(added_lines), removed, added_lines, "\n".join(diffs))


def _norm(line: str) -> str:
    return " ".join(line.split())


def count_ai_lines(added_lines: list[str], shown_snippets: list[str]) -> int:
    shown = {n for s in shown_snippets for ln in s.splitlines() if (n := _norm(ln))}
    return sum(1 for ln in added_lines if (n := _norm(ln)) and n in shown)


def clear_snapshot(work_dir: Path) -> None:
    shutil.rmtree(work_dir / "base", ignore_errors=True)
