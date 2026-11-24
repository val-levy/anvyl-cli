"""Non-LLM policy core.

This is the enforcement layer. It is pure Python, no model calls, no
prompting. Every decision about whether AI may write code, whether the
attempt gate passes, and whether a plugin is allowed is made here, from
typed state only. The model can ask for anything; this module decides
what is allowed. That is the whole point: prompt alone does not withhold
reliably, so the gate lives in code, not in a system prompt.
"""

from __future__ import annotations

import re

from .judge import CODE_FENCE_RE, CODE_LINE_RE

# A human attempt must be a real try, not "idk" or an empty string.
MIN_ATTEMPT_CHARS = 20
MIN_ATTEMPT_WORDS = 3

MAX_RUNG = 3


def gate_passed(state: dict) -> bool:
    """Hard attempt gate. Ship mode has no gate; Learn mode needs a real
    human attempt in state before any edge to code/coach-solution exists."""
    if state.get("mode") == "ship":
        return True
    attempt = (state.get("human_attempt") or "").strip()
    if len(attempt) < MIN_ATTEMPT_CHARS:
        return False
    if len(attempt.split()) < MIN_ATTEMPT_WORDS:
        return False
    return True


def can_coach_write_code(state: dict) -> bool:
    """May the coach produce solution code for this state?

    L0: AI is silent. L1: coach only, never code. L2+: drafts allowed, but
    only once the gate has passed (Learn) or in Ship mode.
    """
    level = int(state.get("level", 1))
    if level <= 1:
        return False
    if state.get("mode") == "learn" and not gate_passed(state):
        return False
    return True


def strip_solution_code(text: str, state: dict) -> tuple[str, int, list[str]]:
    """Deterministically remove solution code from a coach reply.

    At L0/L1 all code is removed. At L2+ fenced blocks are still removed
    from *coach* replies (drafts go through the implement node, not chat).
    Returns (cleaned_text, removed_count, notes).
    """
    level = int(state.get("level", 1))
    notes: list[str] = []
    removed = 0
    cleaned = text or ""

    fences = CODE_FENCE_RE.findall(cleaned)
    if fences:
        removed += len(fences)
        cleaned = CODE_FENCE_RE.sub("[code removed by policy: type it yourself]", cleaned)
        notes.append(f"removed {len(fences)} fenced code block(s)")

    if level <= 1:
        lines = cleaned.splitlines()
        kept: list[str] = []
        for line in lines:
            if CODE_LINE_RE.match(line):
                removed += 1
                continue
            kept.append(line)
        if removed > len(fences):
            notes.append(f"removed {removed - len(fences)} code line(s)")
        cleaned = "\n".join(kept).strip()

    return cleaned, removed, notes


def plugin_allowed(manifest: dict, state: dict) -> tuple[bool, str]:
    """May this plugin run in this state? Plugins run inside the policy
    core: they cannot bypass the attempt gate and cannot write code at
    L0/L1, whatever their manifest claims."""
    level = int(state.get("level", 1))
    if manifest.get("writes_code") and level <= 1:
        return False, "plugin writes code but level is L0/L1 (coach only)"
    max_level = int(manifest.get("max_level", 4))
    if level > max_level:
        return False, f"plugin is only trusted up to L{max_level}, current level is L{level}"
    if state.get("mode") == "learn" and manifest.get("writes_code") and not gate_passed(state):
        return False, "attempt gate has not passed; plugin may not write code yet"
    if not manifest.get("enabled", True):
        return False, "plugin is disabled in its manifest"
    return True, "allowed"


def auto_drop_level(state: dict) -> int:
    """Loss aversion working for the human: if ownership is low, drop the
    level back toward L1 instead of letting higher autonomy quietly stick."""
    score = state.get("ownership_score")
    level = int(state.get("level", 1))
    if score is None:
        return level
    if score < 0.5 and level > 1:
        return 1
    return level


def explainback_required(state: dict) -> bool:
    """Explain-back runs in Learn mode, and in Ship mode only for
    high-stakes changes."""
    if state.get("mode") == "learn":
        return True
    return bool(state.get("high_stakes"))


# -- real tickets (not the tutorial) -----------------------------------------
REAL_MAX_LEVEL = 2
MIN_DISTINCT_WORDS = 4
MAX_WORD_SHARE = 0.6
MIN_CONTAINMENT_WORDS = 3

_WORD_RE = re.compile(r"\w+")
_HIGH_STAKES_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:auth(?:enticat\w*|oriz\w*)?|login|password|token|payment|billing|invoice|"
    r"migration|schema|encrypt\w*|secret|permission|security)s?(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_HIGH_STAKES_PATHS = {"auth", "payment", "billing", "migrations", "security", "secrets"}


def clamp_real_level(level: int) -> int:
    """Real sessions never reach L3/L4."""
    return min(max(level, 0), REAL_MAX_LEVEL)


def attempt_floor(attempt: str | None, ticket: str | None = "") -> tuple[bool, str]:
    """Stronger attempt gate for real tickets. Returns (ok, reason)."""
    text = (attempt or "").strip()
    if not gate_passed({"mode": "learn", "human_attempt": text}):
        return False, "Write a real plan first: a sentence or two on how you would approach it."
    words = _WORD_RE.findall(text.lower())
    if len(set(words)) < MIN_DISTINCT_WORDS:
        return False, "That repeats the same few words. Say how you would actually do it."
    if max(words.count(w) for w in set(words)) / len(words) > MAX_WORD_SHARE:
        return False, "One word makes up most of that. Describe your approach in your own words."
    ticket_words = _WORD_RE.findall((ticket or "").lower())
    if ticket_words and min(len(words), len(ticket_words)) >= MIN_CONTAINMENT_WORDS:
        a, t = f" {' '.join(words)} ", f" {' '.join(ticket_words)} "
        if a in t or t in a:
            return False, "That is the ticket restated. Say how you would approach it."
    return True, "ok"


def high_stakes(ticket: str | None, paths: list[str]) -> bool:
    """Triage: does this ticket or the files it touches look security/money/data-critical?"""
    if _HIGH_STAKES_RE.search(ticket or ""):
        return True
    for path in paths:
        for seg in re.split(r"[/\\]", path.lower()):
            if seg in _HIGH_STAKES_PATHS or seg.rpartition(".")[0] in _HIGH_STAKES_PATHS:
                return True
    return False
