"""OpenRouter model catalogue for /model: ids, context size and price per million tokens.

The list is public, so no key is sent. Every field is untrusted text from the network:
it is cleaned and typed before it is shown, and a model can only be picked by an id that
appears in the fetched list."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

from .grader import _clean
from .llm import _NoRedirect

URL = "https://openrouter.ai/api/v1/models"
MAX_BYTES = 8_000_000


@dataclass(frozen=True)
class Model:
    id: str
    name: str
    context: int
    price_in: float | None  # USD per million prompt tokens; None = unknown
    price_out: float | None
    tools: bool


def _per_million(v: object) -> float | None:
    try:
        x = float(str(v)) * 1_000_000
    except ValueError:
        return None
    return x if x >= 0 else None  # OpenRouter uses -1 for "depends on the routed model"


def parse(payload: object) -> list[Model]:
    rows = payload.get("data") if isinstance(payload, dict) else None
    out: list[Model] = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict) or not isinstance(r.get("id"), str):
            continue
        p: dict = r["pricing"] if isinstance(r.get("pricing"), dict) else {}
        sp = r.get("supported_parameters")
        ctx = r.get("context_length")
        out.append(
            Model(
                id=_clean(r["id"], 100),
                name=_clean(str(r.get("name") or r["id"]), 60),
                context=ctx if isinstance(ctx, int) and ctx > 0 else 0,
                price_in=_per_million(p.get("prompt")),
                price_out=_per_million(p.get("completion")),
                tools=isinstance(sp, list) and "tools" in sp,
            )
        )
    return sorted(out, key=lambda m: m.id)


def fetch(timeout: int = 10) -> list[Model]:
    """All models, or [] when offline. Never raises."""
    try:
        req = urllib.request.Request(URL, headers={"Accept": "application/json"})
        with urllib.request.build_opener(_NoRedirect()).open(req, timeout=timeout) as resp:
            return parse(json.loads(resp.read(MAX_BYTES).decode("utf-8")))
    except Exception:
        return []


def money(p: float | None) -> str:
    if p is None:
        return "  var"
    return " free" if p == 0 else f"{p:5.2f}" if p < 100 else f"{p:5.0f}"


def ctx(n: int) -> str:
    return (
        "   ?"
        if not n
        else f"{n // 1_000_000}M".rjust(4)
        if n >= 1_000_000
        else f"{n // 1000}k".rjust(4)
    )


def search(models: list[Model], text: str) -> list[Model]:
    words = text.lower().split()
    return [m for m in models if all(w in f"{m.id} {m.name}".lower() for w in words)]


def row(i: int, m: Model, current: str) -> str:
    star = "*" if m.id == current else " "
    return f"{star}{i:>2}  {money(m.price_in)} {money(m.price_out)} {ctx(m.context)}  {m.id}"


HEADER = "     $/M in  out   ctx  model"
