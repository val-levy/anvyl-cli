"""Coach: Claude via OpenRouter (live), or deterministic offline hints.

Live path, in order:

1. ``OPENROUTER_API_KEY`` env var -> direct HTTPS POST to
   ``https://openrouter.ai/api/v1/chat/completions``. This is the
   standard way to run the coach outside the author's machine.
2. ``HARNESS_OPENROUTER_HELPER`` env var -> a helper script with a
   ``chat --model ID --message TEXT`` interface (the author's
   connector helper). Used only if no API key is set.

No credential is ever stored in the repo or in code. If neither is
available the coach falls back to offline hints and says so.

Offline path is the default for demo runs: deterministic, free, and the
same rung ladder the live coach is instructed to follow. Every reply --
live or offline -- passes through the policy stripper and the judge
before it reaches the human, so a model that ignores its instructions
still cannot leak solution code at L1.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

from . import policy
from .judge import judge_check

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = os.environ.get("HARNESS_MODEL", "anthropic/claude-sonnet-4.5")

LIVE_SYSTEM = (
    "You are a coach in a human-most-of-the-loop coding harness. "
    "The human is the driver; you are the navigator. "
    "Ask questions and give hints only. Never write solution code, never "
    "write a full function, never paste a code block, never give the "
    "answer outright. Keep replies short: one question or one hint. "
    "If the human is stuck, go one rung deeper, still without code."
)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):  # type: ignore[override]
        raise RuntimeError("redirect refused, verify the endpoint")


def _direct_api_call(system: str, user: str, model: str, timeout: int) -> str | None:
    """POST to OpenRouter with the env API key. Returns reply or None."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return None
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": 300,
        }
    ).encode("utf-8")
    request = urllib.request.Request(OPENROUTER_URL, data=payload, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "application/json")
    request.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    choices = result.get("choices", [])
    if not choices:
        return None
    return (choices[0].get("message", {}).get("content", "") or "").strip() or None


def _helper_call(system: str, user: str, model: str, timeout: int) -> str | None:
    """Call the external helper script, if HARNESS_OPENROUTER_HELPER is set."""
    helper = os.environ.get("HARNESS_OPENROUTER_HELPER")
    if not helper or not Path(helper).exists():
        return None
    message = f"{system}\n\n---\n\n{user}"
    try:
        proc = subprocess.run(
            [sys.executable, helper, "chat", "--model", model, "--message", message],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or "").strip() or None


class Coach:
    def __init__(self, live: bool = False, model: str = MODEL):
        self.live_requested = live
        self.live_available: bool | None = None  # None = untested
        self.model = model

    def live_call(self, system: str, user: str, timeout: int = 90) -> str | None:
        """One live chat call. Direct API first, helper script second.
        Returns the reply text, or None if no live path worked (caller
        falls back to offline hints)."""
        text = _direct_api_call(system, user, self.model, timeout)
        if text is None:
            text = _helper_call(system, user, self.model, timeout)
        return text

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
