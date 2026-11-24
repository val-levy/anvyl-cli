"""Task verification + answer scoring tests."""

from harness import tasks


def test_toy_solution_verifies():
    result = tasks.verify_retry_solution(tasks.TOY_SCRIPTED_CODE)
    assert result["passed"] is True
    assert all(c["passed"] for c in result["checks"])


def test_broken_solution_fails_verification():
    broken = "def retry(fn, *, attempts=3):\n    return fn()\n"
    result = tasks.verify_retry_solution(broken)
    assert result["passed"] is False


def test_solution_with_external_import_fails():
    code = "import requests\n\ndef retry(fn, *, attempts=3):\n    return fn()\n"
    result = tasks.verify_retry_solution(code)
    assert result["passed"] is False
    assert any("external import" in c["detail"] for c in result["checks"])


def test_wifi_solution_verifies():
    result = tasks.verify_wifi_solution(tasks.WIFI_SCRIPTED_CODE)
    assert result["passed"] is True


def test_score_answer_matches_keywords():
    item = tasks.TOY_QUIZ[0]
    assert (
        tasks.score_answer("So retries don't hammer the service, it can recover.", item["keywords"])
        is True
    )
    assert tasks.score_answer("I don't know, something about loops.", item["keywords"]) is False


def test_unknown_task_raises():
    try:
        tasks.get_task("nope")
    except ValueError as exc:
        assert "unknown task" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")
