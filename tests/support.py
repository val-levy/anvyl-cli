"""Test doubles. Import as `from support import FakeClient` (tests/ is on sys.path)."""

from __future__ import annotations

from anvyl.llm import ChatResult


class FakeClient:
    """Returns scripted ChatResults (or raises scripted Exceptions) in order."""

    def __init__(self, script: list[ChatResult | Exception]):
        self.script = list(script)
        self.calls: list[tuple[list[dict], list[dict] | None]] = []

    def chat(self, messages, tools=None, max_tokens=600):
        self.calls.append((messages, tools))
        if len(self.calls) > len(self.script):
            raise AssertionError("FakeClient called more times than scripted")
        item = self.script[len(self.calls) - 1]
        if isinstance(item, Exception):
            raise item
        return item
