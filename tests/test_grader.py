import json
from pathlib import Path

import pytest
from support import FakeClient

from anvyl.grader import Grade, check_attempt, generate_questions, grade_answers
from anvyl.llm import ChatResult, ModelError

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "grading.json").read_text())


def reply(obj) -> ChatResult:
    return ChatResult(text=obj if isinstance(obj, str) else json.dumps(obj))


QA = [("What does it do?", "It retries the call three times."), ("Why?", "Keeps the loop bounded.")]


def results(*flags):
    return {"results": [{"correct": f, "feedback": "fb"} for f in flags]}


def test_check_attempt_parses_verdict():
    c = FakeClient([reply({"genuine": True, "reason": "real effort"})])
    assert check_attempt(c, "ticket", "my attempt") == (True, "real effort")


def test_malformed_json_raises_model_error():
    for call in (
        lambda c: check_attempt(c, "t", "a"),
        lambda c: generate_questions(c, "t", "diff"),
        lambda c: grade_answers(c, "diff", QA),
    ):
        with pytest.raises(ModelError):
            call(FakeClient([reply("not json at all")]))


def test_bad_shape_raises_model_error():
    with pytest.raises(ModelError):
        check_attempt(FakeClient([reply({"genuine": "yes", "reason": "x"})]), "t", "a")
    with pytest.raises(ModelError):
        check_attempt(FakeClient([reply([1, 2])]), "t", "a")
    with pytest.raises(ModelError):
        bad = {"results": [{"correct": "y", "feedback": "f"}] * 2}
        grade_answers(FakeClient([reply(bad)]), "d", QA)


def test_client_failure_raises_model_error():
    with pytest.raises(ModelError):
        check_attempt(FakeClient([RuntimeError("boom")]), "t", "a")
    with pytest.raises(ModelError):
        check_attempt(FakeClient([ModelError("down")]), "t", "a")


def test_wrong_question_count_raises():
    for qs in (["a", "b"], ["a", "b", "c", "d"], ["a", "b", ""]):
        with pytest.raises(ModelError):
            generate_questions(FakeClient([reply({"questions": qs})]), "t", "diff")
    assert generate_questions(FakeClient([reply({"questions": ["a", "b", "c"]})]), "t", "d") == [
        "a",
        "b",
        "c",
    ]


def test_wrong_result_count_raises():
    with pytest.raises(ModelError):
        grade_answers(FakeClient([reply(results(True))]), "diff", QA)


def test_blank_answer_is_incorrect_without_model_call():
    c = FakeClient([])
    g = grade_answers(c, "diff", [("Q1", ""), ("Q2", "   "), ("Q3", "no idea")])
    assert c.calls == []
    assert g.correct == [False, False, False]
    assert g.score == 0.0
    assert all(g.feedback)


def test_only_real_answers_sent_and_mapped_back_in_order():
    c = FakeClient([reply(results(True, False))])
    qa = [("first?", "a real answer here"), ("SKIPPED?", ""), ("third?", "another real answer")]
    g = grade_answers(c, "diff", qa)
    assert g.correct == [True, False, False]
    assert g.feedback[0] == "fb" and g.feedback[2] == "fb"
    assert "SKIPPED?" not in c.calls[0][0][1]["content"]


def test_score_is_fraction_correct():
    g = grade_answers(FakeClient([reply(results(True, False))]), "diff", QA)
    assert isinstance(g, Grade)
    assert g.score == 0.5
    assert grade_answers(FakeClient([]), "diff", []).score == 0.0


def test_prompt_fences_diff_and_answers():
    c = FakeClient([reply(results(True, True))])
    grade_answers(c, "SECRETDIFF", QA)
    messages = c.calls[0][0]
    user = messages[1]["content"]
    assert "<changes>\nSECRETDIFF\n</changes>" in user
    assert "<answers>" in user and "It retries the call three times." in user
    assert "untrusted" in messages[0]["content"]
    c = FakeClient([reply({"questions": ["a", "b", "c"]})])
    generate_questions(c, "TICKETX", "DIFFX")
    user = c.calls[0][0][1]["content"]
    assert "<ticket>\nTICKETX\n</ticket>" in user and "<changes>\nDIFFX\n</changes>" in user
    c = FakeClient([reply({"genuine": True, "reason": "r"})])
    check_attempt(c, "TICKETX", "ATTEMPTX")
    assert "<attempt>\nATTEMPTX\n</attempt>" in c.calls[0][0][1]["content"]


def test_json_in_code_fence_is_accepted():
    wrapped = '```json\n{"genuine": false, "reason": "thin"}\n```'
    assert check_attempt(FakeClient([reply(wrapped)]), "t", "a") == (False, "thin")
    assert check_attempt(FakeClient([reply("```\n" + wrapped[8:])]), "t", "a") == (False, "thin")


@pytest.mark.parametrize("case", FIXTURES, ids=[f["name"] for f in FIXTURES])
@pytest.mark.parametrize("kind", ["good", "vague", "wrong"])
def test_fixture_verdicts_with_scripted_model(case, kind):
    qa = list(zip(case["questions"], case["answers"][kind]))
    flags = [kind == "good"] * 3  # scripted stand-in for the real model's verdict
    c = FakeClient([reply(results(*flags))])
    g = grade_answers(c, case["diff"], qa)
    assert g.score == case["expected"][kind]
    assert len(c.calls) == (0 if kind == "vague" else 1)
