"""Tutor helpers: spotting "I don't know" and extracting the ideas a person implemented."""

from __future__ import annotations

import re

from .grader import MIN_WORDS, _ask, _clean
from .llm import ModelClient, ModelError, fence
from .memory import ASPECTS, LABEL_CAP

UNSURE = {"idk", "i dont know", "no idea", "not sure", "?", "help", "dunno"}
MAX_IDEAS = 5


def is_unsure(text: str) -> bool:
    plain = re.sub(r"[^\w\s?]", "", (text or "").lower().replace("'", "")).strip()
    return not plain or plain in UNSURE or len(plain.split()) < MIN_WORDS


def extract_ideas(client: ModelClient, ticket: str, changes_text: str) -> list[dict]:
    data = _ask(
        client,
        "List the underlying ideas this author implemented: the logic and its depth, never the "
        "syntax or kind of code ('a method on a class' is not an idea). For each give a short "
        "label and which aspects they covered, from happy, edge, errors, perf. "
        'Reply {"ideas": [{"label": str, "aspects": [str]}]} with at most 5.\n'
        + fence("ticket", ticket)
        + "\n"
        + fence("changes", changes_text),
    )
    raw = data.get("ideas")
    if not isinstance(raw, list) or len(raw) > MAX_IDEAS:
        raise ModelError("model reply had the wrong shape")
    out = []
    for i in raw:
        if (
            not isinstance(i, dict)
            or not isinstance(i.get("label"), str)
            or not isinstance(i.get("aspects"), list)
            or not all(isinstance(a, str) for a in i["aspects"])
        ):
            raise ModelError("model reply had the wrong shape")
        label = " ".join(_clean(i["label"], LABEL_CAP).split())
        if label:
            out.append({"label": label, "aspects": [a for a in i["aspects"] if a in ASPECTS]})
    return out
