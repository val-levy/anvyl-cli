"""Persistent memory: what the learner has shown they can do, and where each folder left off.

Two small JSON files under <data_dir>/memory, written only by code. Entries are short cleaned
labels and counts (never code or typed text), so nothing grows with session length and the
coach is rebuilt from a small budgeted recap on every call.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from .grader import _clean
from .llm import fence

FRESH_DAYS = 60
RECAP_MAX_IDEAS = 5
RECAP_MAX_CHARS = 1200
MAX_IDEAS = 500
LABEL_CAP = 80
TICKETS_KEPT = 50
ASPECTS = ("happy", "edge", "errors", "perf")
_WORD = re.compile(r"[a-z0-9]{3,}")


LABEL_WORDS = 8
_UNSAFE = re.compile(r"[^A-Za-z0-9 \-_/,.()']")


def _label(text: str) -> str:
    """Short plain label: strict character set and word count, so a hostile file cannot
    smuggle an instruction sentence into memory that later reaches the coach prompt."""
    words = _UNSAFE.sub(" ", _clean(str(text), LABEL_CAP)).split()
    return " ".join(words[:LABEL_WORDS])[:LABEL_CAP]


def _key(label: str) -> str:
    return label.casefold()


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.casefold()))


class Memory:
    def __init__(self, data_dir: Path, folder: Path, now: Callable[[], float] = time.time):
        self.root = Path(data_dir) / "memory"
        self.now = now
        fid = hashlib.sha1(str(Path(folder).resolve()).encode()).hexdigest()[:16]
        self._learner = self.root / "learner.json"
        self._project = self.root / "projects" / f"{fid}.json"

    # -- storage -------------------------------------------------------------
    def _load(self, path: Path, default: Any) -> Any:
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            return default
        return data if isinstance(data, type(default)) else default

    def _save(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".mem-")
        try:
            os.chmod(tmp, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    # -- ideas ---------------------------------------------------------------
    def ideas(self) -> list[dict]:
        out = []
        for i in self._load(self._learner, []):
            if (
                isinstance(i, dict)
                and isinstance(i.get("label"), str)
                and isinstance(i.get("reps"), int)
                and isinstance(i.get("first"), (int, float))
                and isinstance(i.get("last"), (int, float))
                and isinstance(i.get("aspects"), list)
            ):
                out.append(i)
        return out

    def record(self, label: str, aspects: Iterable[str]) -> None:
        label = _label(label)
        if not label:
            return
        keep = [a for a in aspects if a in ASPECTS]
        now = self.now()
        ideas = self.ideas()
        for i in ideas:
            if _key(i["label"]) == _key(label):
                i["reps"] += 1
                i["aspects"] = sorted(set(i["aspects"]) | set(keep))
                i["last"] = now
                break
        else:
            ideas.append(
                {"label": label, "aspects": sorted(set(keep)), "reps": 1, "first": now, "last": now}
            )
        ideas.sort(key=lambda i: i["last"], reverse=True)
        self._save(self._learner, ideas[:MAX_IDEAS])

    def forget(self, label: str) -> bool:
        ideas = self.ideas()
        left = [i for i in ideas if _key(i["label"]) != _key(_label(label))]
        if len(left) == len(ideas):
            return False
        self._save(self._learner, left)
        return True

    def recap(self, text: str) -> str:
        want = _words(text)
        cutoff = self.now() - FRESH_DAYS * 86400
        scored = []
        for i in self.ideas():
            overlap = len(want & _words(i["label"]))
            if overlap and i["last"] >= cutoff:
                scored.append((overlap, i["reps"], i["last"], i))
        scored.sort(key=lambda t: t[:3], reverse=True)
        lines: list[str] = []
        size = 0
        for *_, i in scored[:RECAP_MAX_IDEAS]:
            line = f"- {i['label']} (x{i['reps']}: {', '.join(i['aspects']) or 'basics'})"
            if size + len(line) > RECAP_MAX_CHARS:
                break
            lines.append(line)
            size += len(line) + 1
        return fence("memory", "\n".join(lines)) if lines else ""

    # -- tickets -------------------------------------------------------------
    def _tickets(self) -> list[dict]:
        return [t for t in self._load(self._project, []) if isinstance(t, dict)]

    def start_ticket(self, goal: str) -> str:
        key = f"{int(self.now() * 1000)}"
        tickets = self._tickets()
        tickets.append(
            {
                "key": key,
                "goal": _clean(goal, 120),
                "outcome": "unfinished",
                "date": self.now(),
                "ideas": [],
            }
        )
        self._save(self._project, tickets[-TICKETS_KEPT:])
        return key

    def finish_ticket(self, key: str, outcome: str, labels: list[str]) -> None:
        if outcome not in ("done", "unfinished", "abandoned"):
            outcome = "unfinished"
        tickets = self._tickets()
        for t in tickets:
            if t.get("key") == key:
                t["outcome"] = outcome
                t["ideas"] = [_label(x) for x in labels][:5]
        self._save(self._project, tickets)

    def last_line(self) -> str:
        for t in reversed(self._tickets()):
            if t.get("outcome") == "unfinished":
                return f"Last time you were working on: {t.get('goal', '')} (unfinished)"
            return ""
        return ""

    # -- housekeeping --------------------------------------------------------
    def export(self) -> dict:
        return {"ideas": self.ideas(), "tickets": self._tickets()}

    def wipe(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
