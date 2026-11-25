import json

import pytest
from support import FakeClient

from anvyl.llm import ChatResult, ModelError
from anvyl.tutor import extract_ideas, is_unsure


@pytest.mark.parametrize(
    "text", ["", "  ", "idk", "I don't know.", "?", "no idea", "ok", "Not sure", "dunno"]
)
def test_is_unsure_true(text):
    assert is_unsure(text)


def test_is_unsure_false_for_real_answer():
    assert not is_unsure("add a retry loop around fetch with a delay")


def reply(obj):
    return FakeClient([ChatResult(text=json.dumps(obj), tool_calls=[], tokens=1)])


def test_extract_ideas_valid_and_cleaned():
    c = reply({"ideas": [{"label": "\x1b[31mretry\x1b[0m loop", "aspects": ["edge", "magic"]}]})
    [i] = extract_ideas(c, "t", "d")
    assert i == {"label": "retry loop", "aspects": ["edge"]}


def test_extract_ideas_fenced():
    c = reply({"ideas": []})
    extract_ideas(c, "my ticket", "my diff")
    user = c.calls[0][0][1]["content"]
    assert "<ticket>" in user and "my ticket" in user and "<changes>" in user and "my diff" in user


@pytest.mark.parametrize(
    "bad",
    [
        [],
        {"ideas": [{"label": 3, "aspects": []}]},
        {"ideas": [{"label": f"i{n}", "aspects": []} for n in range(6)]},
        {"nope": 1},
        {"ideas": [{"label": "x", "aspects": "edge"}]},
    ],
)
def test_extract_ideas_bad_shape_raises(bad):
    with pytest.raises(ModelError):
        extract_ideas(reply(bad), "t", "d")


def test_extract_ideas_non_json_raises():
    c = FakeClient([ChatResult(text="sure!", tool_calls=[], tokens=1)])
    with pytest.raises(ModelError):
        extract_ideas(c, "t", "d")
