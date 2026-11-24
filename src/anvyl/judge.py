"""Separate judge: did solution code leak into a coach reply?

The judge is deliberately separate from the policy core and from the
model. In V1 it is deterministic (regex, not a model): it reports a
verdict, and the caller decides what to do with it (strip, replace).
A future version can add an LLM judge behind the same ``judge_check``
interface without touching the graph.
"""

from __future__ import annotations

import re

# Fenced code blocks, inline spans that look like code, and lines that are
# statements in a union of common languages (no per-folder detection).
CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
CODE_LINE_RE = re.compile(
    # Python
    r"^\s*(def |class |return |import |from |for |while |if |elif |else:|"
    r"try:|except|finally:|with |raise |print\(|@|async def |await |"
    # JS/TS, Go, Rust
    r"function |const |let |export |func |package |fn |let mut |impl |"
    # Java/C#, C
    r"public |private |static |#include)"
    # any language: statement terminator or block opener
    r"|[;{]\s*$"
)
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
MAX_INLINE_CHARS = 60


def _code_span(span: str) -> bool:
    return len(span) > MAX_INLINE_CHARS or any(t in span for t in (";", "{", "=>"))


def judge_check(text: str) -> dict:
    """Verdict on whether solution code leaked into this text.

    Returns ``{"leaked": bool, "reasons": [...]}``.
    """
    reasons: list[str] = []
    if "```" in (text or ""):
        reasons.append("fenced code block present")
    for line in (text or "").splitlines():
        if CODE_LINE_RE.match(line):
            reasons.append(f"code line leaked: {line.strip()[:60]}")
            break
    if any(_code_span(m) for m in INLINE_CODE_RE.findall(text or "")):
        reasons.append("inline code span leaked")
    return {"leaked": bool(reasons), "reasons": reasons}
