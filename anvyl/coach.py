"""Coach: a model client (live), or deterministic offline hints.

The live path uses an injected ``ModelClient`` (default: OpenRouter via
``anvyl login``). If it fails the coach falls back to offline hints.

Offline path is the default for demo runs: deterministic, free, and the
same rung ladder the live coach is instructed to follow. Every reply --
live or offline -- passes through the policy stripper and the judge
before it reaches the human, so a model that ignores its instructions
still cannot leak solution code at L1.
"""

from __future__ import annotations

from . import policy
from .judge import judge_check
from .llm import ModelClient, ModelError, default_client

LIVE_SYSTEM = (
    "You are a coach in a human-most-of-the-loop coding tool. "
    "The human is the driver; you are the navigator. "
    "Ask questions and give hints only. Never write solution code, never "
    "write a full function, never paste a code block, never give the "
    "answer outright. Keep replies short: one question or one hint. "
    "If the human is stuck, go one rung deeper, still without code."
)


class Coach:
    def __init__(self, live: bool = False, client: ModelClient | None = None):
        self.live_requested = live
        self.live_available: bool | None = None  # None = untested
        self.client = client

    def live_call(self, system: str, user: str) -> str | None:
        """One live chat call. Returns the reply text, or None on any
        ModelError (caller falls back to offline hints)."""
        try:
            if self.client is None:
                self.client = default_client()
            text = self.client.chat(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                max_tokens=300,
            ).text
        except ModelError:
            return None
        return text or None

    def offline_reply(self, task: dict, state: dict) -> str:
        """Deterministic rung-ladder hint. No code, ever."""
        rung = min(int(state.get("help_rung", 0)), policy.MAX_RUNG)
        hints = task.get("hints", [])
        if not hints:
            return "What is the smallest piece of this you can state in your own words?"
        return hints[rung]

    def reply(self, task: dict, state: dict) -> dict:
        """Produce one coach reply for this state.

        Returns {"text", "live", "stripped", "judge", "tokens"}.
        At L0 the coach is silent by policy.
        """
        if int(state.get("level", 1)) == 0:
            return {
                "text": "",
                "live": False,
                "stripped": 0,
                "judge": {"leaked": False, "reasons": []},
                "tokens": 0,
            }

        text = ""
        live = False
        if self.live_requested:
            prompt = (
                f"Task: {task.get('title', '')}\n"
                f"Goal (human's words): {state.get('goal', '')}\n"
                f"Human attempt so far: {state.get('human_attempt', '')}\n"
                f"Help rung: {int(state.get('help_rung', 0))} of {policy.MAX_RUNG} "
                "(0 = ask a question, higher = more specific hint, still no code).\n"
                "Respond with one short question or hint."
            )
            live_text = self.live_call(LIVE_SYSTEM, prompt)
            if live_text is not None:
                text = live_text
                live = True
                self.live_available = True
            else:
                self.live_available = False

        if not text:
            text = self.offline_reply(task, state)

        # Enforcement: strip, then judge. Never trust the reply as-is.
        verdict = judge_check(text)
        stripped = 0
        if verdict["leaked"] or not policy.can_coach_write_code(state):
            text, stripped, _notes = policy.strip_solution_code(text, state)
            verdict = judge_check(text)
        if verdict["leaked"]:
            # Judge still says leak after stripping: replace, don't deliver.
            text = self.offline_reply(task, state)
            stripped += 1
            verdict = judge_check(text)

        return {
            "text": text,
            "live": live,
            "stripped": stripped,
            "judge": verdict,
            "tokens": max(1, len(text) // 4),
        }
