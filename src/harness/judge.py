"""Separate judge: did solution code leak into a coach reply?

The judge is deliberately separate from the policy core and from the
model. In V1 it is deterministic (regex, not a model): it reports a
verdict, and the caller decides what to do with it (strip, replace).
A future version can add an LLM judge behind the same ``judge_check``
interface without touching the graph.
"""

from __future__ import annotations

import re

# Fenced code blocks, and lines that are plainly Python statements.
CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
CODE_LINE_RE = re.compile(
    r"^\s*(def |class |return |import |from |for |while |if |elif |else:|"
    r"try:|except|finally:|with |raise |print\(|@|async def |await )"
)


def judge_check(text: str) -> dict:
    """Verdict on whether solution code leaked into this text.

    Returns ``{"leaked": bool, "reasons": [...]}``.
    """
    reasons: list[str] = []
    if "```" in (text or ""):
        reasons.append("fenced code block present")
    for line in (text or "").splitlines():
        if re.match(r"^\s*(def |class )", line):
            reasons.append(f"definition line leaked: {line.strip()[:60]}")
            break
    return {"leaked": bool(reasons), "reasons": reasons}
