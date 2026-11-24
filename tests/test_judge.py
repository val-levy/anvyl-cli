"""Language-agnostic leak judge: union of common languages, no folder context."""

import pytest

from anvyl import policy
from anvyl.judge import judge_check


@pytest.mark.parametrize(
    "line",
    [
        "const x = fetch(url);",
        "export default handler",
        "func main() {",
        "package main",
        "fn main() {",
        "let mut x = 1;",
        "impl Foo for Bar",
        "public static void main(String[] a) {",
        "#include <stdio.h>",
    ],
)
def test_code_line_in_any_language_leaks(line):
    assert judge_check(f"Try this:\n{line}\nThen run it.")["leaked"] is True
    cleaned, removed, _ = policy.strip_solution_code(f"Hint:\n{line}\nThink.", {"level": 1})
    assert line not in cleaned
    assert removed >= 1


def test_inline_long_code_span_leaks():
    assert judge_check("Use `" + "a" * 61 + "` here")["leaked"] is True
    assert judge_check("Use `x = 1; y = 2` here")["leaked"] is True
    assert judge_check("Use `(x) => x` here")["leaked"] is True


def test_short_inline_span_does_not_leak():
    assert judge_check("Consider `retry()` and `len(x)`.")["leaked"] is False


def test_plain_english_hints_do_not_leak():
    for hint in [
        "What has to happen between one failed call and the next?",
        "What changes between one failed call and the next?",
        "Think about the loop. What should it do on failure?",
        "If you retry, what changes each time?",
        "Public APIs usually need a stable contract; what is yours?",
    ]:
        assert judge_check(hint)["leaked"] is False, hint
