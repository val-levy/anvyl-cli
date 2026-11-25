"""Task registry.

Two tasks ship with V1. The default is the tiny toy task: a pure-Python
exponential-backoff retry helper with no external deps. It exercises the
full Learn loop but stays trivial to verify by running it. The WiFi CSI
backoff task is the second example only, not the first.
"""

from __future__ import annotations

import ast

TOY_SCRIPTED_ATTEMPT = (
    "Retry should call fn, catch Exception, wait longer each time, and give "
    "up after N tries by re-raising the last error. Plan: loop for attempt "
    "in range(attempts): try return fn(); except Exception as e: remember e; "
    "if this was the last attempt raise it; otherwise sleep "
    "base_delay * factor**attempt."
)

TOY_SCRIPTED_CODE = '''import time


def retry(fn, *, attempts=3, base_delay=0.1, factor=2.0, sleep=time.sleep):
    """Call fn, retrying on Exception with exponential backoff."""
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    last_error = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:
            last_error = exc
            if attempt == attempts - 1:
                raise
            sleep(base_delay * (factor ** attempt))
    raise last_error
'''

TOY_QUIZ = [
    {
        "q": "Why does the delay grow after each failed attempt?",
        "keywords": ["backoff", "hammer", "recover", "spread", "load", "thundering"],
        "answer": "So retries don't hammer a failing service and give it time to recover; the growing delay spreads load out instead of piling retries on top of each other.",
    },
    {
        "q": "What happens after the last attempt fails?",
        "keywords": ["raise", "re-raise", "reraise", "last error", "propagat"],
        "answer": "The last error is re-raised to the caller. The helper doesn't swallow it or return a fake value.",
    },
    {
        "q": "Why take sleep as a parameter instead of calling time.sleep directly?",
        "keywords": ["test", "inject", "fake", "mock", "determin"],
        "answer": "So tests can inject a fake sleep and check the delays without actually waiting. It makes the timing deterministic and fast to test.",
    },
]

TOY_HINTS = [
    "What has to happen between one failed call and the next? What changes each time?",
    "You need a loop, a place to remember the last error, and a delay that grows. Which of those do you have in your attempt, and which is missing?",
    "Try: for attempt in range(attempts). On exception, save the error, sleep base_delay * factor**attempt, and only re-raise when attempt is the last one.",
    "Outline in words: loop N times, try fn(), on failure remember the error, sleep a growing delay, re-raise after the final failure. No code - you type it.",
]

WIFI_SCRIPTED_ATTEMPT = (
    "The CSI packet writer drops packets when the link is flaky. I want the "
    "same retry idea as the toy helper: wrap the send in retry, with backoff, "
    "so a transient drop doesn't lose the packet, but a dead link still "
    "fails loudly after N tries instead of hanging forever."
)

WIFI_SCRIPTED_CODE = '''import time


def retry(fn, *, attempts=3, base_delay=0.1, factor=2.0, sleep=time.sleep):
    """Call fn, retrying on Exception with exponential backoff."""
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    last_error = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:
            last_error = exc
            if attempt == attempts - 1:
                raise
            sleep(base_delay * (factor ** attempt))
    raise last_error


def send_csi_packet(writer, packet, **retry_kw):
    """Send one CSI packet, retrying transient write failures."""
    return retry(lambda: writer(packet), **retry_kw)
'''

WIFI_QUIZ = [
    {
        "q": "Why retry a CSI packet write instead of just dropping the packet?",
        "keywords": ["transient", "flaky", "gap", "lose", "continuity", "drop"],
        "answer": "Most write failures are transient on a flaky link. Retrying keeps the CSI stream continuous instead of leaving gaps in the sensing data.",
    },
    {
        "q": "What happens if the link is actually dead, not just flaky?",
        "keywords": ["raise", "fail", "exhaust", "give up", "last error"],
        "answer": "After the attempts are exhausted the last error is raised, so a dead link fails loudly instead of hanging forever or silently dropping everything.",
    },
    {
        "q": "Why keep the retry helper separate from the packet writer?",
        "keywords": ["test", "reuse", "separat", "pure", "without"],
        "answer": "The retry logic is pure and testable without hardware, and the writer stays thin. Same helper can be reused anywhere a call is flaky.",
    },
]

WIFI_HINTS = [
    "What is flaky here, the packet or the link? Which part should know about retrying?",
    "You already have a retry helper shape from the toy task. What is the one thing the writer adds on top of it?",
    "Try: wrap writer(packet) in retry, with the same backoff. The writer itself stays dumb - it just sends once.",
    "Outline in words: send_csi_packet calls retry around a single writer call. Retry handles the loop, the delay, and giving up.",
]


def _check_no_external_imports(code: str) -> tuple[bool, str]:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return False, f"syntax error: {exc}"
    allowed = {"time"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in allowed:
                    return False, f"external import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] not in allowed:
                return False, f"external import: {node.module}"
    return True, "imports ok (time only)"


def verify_retry_solution(code: str) -> dict:
    """Run the toy retry helper against three checks. No hardware, no
    network, no real waiting (fake sleep records the delays)."""
    checks: list[dict] = []

    ok, detail = _check_no_external_imports(code)
    checks.append({"name": "no external deps", "passed": ok, "detail": detail})
    if not ok:
        return {"passed": False, "checks": checks}

    ns: dict = {}
    try:
        exec(compile(code, "<solution>", "exec"), ns)
    except Exception as exc:  # noqa: BLE001 - report, don't crash the run
        checks.append({"name": "solution executes", "passed": False, "detail": str(exc)})
        return {"passed": False, "checks": checks}
    checks.append({"name": "solution executes", "passed": True, "detail": "ok"})

    retry = ns.get("retry")
    if not callable(retry):
        checks.append(
            {"name": "retry() defined", "passed": False, "detail": "no retry function found"}
        )
        return {"passed": False, "checks": checks}

    # 1. Succeeds after two failures, with delays [0.1, 0.2].
    delays: list[float] = []
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("flaky link")
        return "sent"

    try:
        result = retry(flaky, attempts=3, base_delay=0.1, factor=2.0, sleep=delays.append)
        checks.append(
            {
                "name": "succeeds after 2 failures",
                "passed": result == "sent" and calls["n"] == 3,
                "detail": f"result={result!r} calls={calls['n']}",
            }
        )
    except Exception as exc:  # noqa: BLE001 - a solution that can't be called fails the check
        checks.append({"name": "succeeds after 2 failures", "passed": False, "detail": str(exc)})

    checks.append(
        {
            "name": "delays grow exponentially",
            "passed": delays == [0.1, 0.2],
            "detail": f"delays={delays}",
        }
    )

    # 2. Always failing: raises the last error after exactly 3 calls.
    calls2 = {"n": 0}

    def always_fail():
        calls2["n"] += 1
        raise ValueError("dead link")

    try:
        retry(always_fail, attempts=3, base_delay=0.1, sleep=lambda d: None)
        checks.append(
            {"name": "raises after exhausting attempts", "passed": False, "detail": "did not raise"}
        )
    except ValueError:
        checks.append(
            {
                "name": "raises after exhausting attempts",
                "passed": calls2["n"] == 3,
                "detail": f"calls={calls2['n']}",
            }
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(
            {
                "name": "raises after exhausting attempts",
                "passed": False,
                "detail": f"wrong error: {exc}",
            }
        )

    # 3. First-try success: one call, no sleep.
    calls3 = {"n": 0}
    slept = {"n": 0}

    def ok_fn():
        calls3["n"] += 1
        return 42

    try:
        result3 = retry(ok_fn, sleep=lambda d: slept.__setitem__("n", slept["n"] + 1))
        checks.append(
            {
                "name": "first-try success, no sleep",
                "passed": result3 == 42 and calls3["n"] == 1 and slept["n"] == 0,
                "detail": f"result={result3} calls={calls3['n']} sleeps={slept['n']}",
            }
        )
    except Exception as exc:  # noqa: BLE001 - wrong signature fails the check, doesn't crash the run
        checks.append({"name": "first-try success, no sleep", "passed": False, "detail": str(exc)})

    return {"passed": all(c["passed"] for c in checks), "checks": checks}


def verify_wifi_solution(code: str) -> dict:
    """WiFi task: retry helper checks plus the CSI packet wrapper."""
    base = verify_retry_solution(code)
    checks = base["checks"]
    if not base["passed"]:
        return {"passed": False, "checks": checks}
    ns: dict = {}
    exec(compile(code, "<solution>", "exec"), ns)
    send = ns.get("send_csi_packet")
    if not callable(send):
        checks.append(
            {
                "name": "send_csi_packet() defined",
                "passed": False,
                "detail": "no send_csi_packet wrapper found",
            }
        )
        return {"passed": False, "checks": checks}
    sent: list = []
    tries = {"n": 0}

    def writer(packet):
        tries["n"] += 1
        if tries["n"] < 3:
            raise ConnectionError("drop")
        sent.append(packet)

    try:
        send(writer, b"csi-frame", attempts=3, base_delay=0.1, sleep=lambda d: None)
        checks.append(
            {
                "name": "packet sent after retries",
                "passed": sent == [b"csi-frame"] and tries["n"] == 3,
                "detail": f"sent={sent} tries={tries['n']}",
            }
        )
    except Exception as exc:  # noqa: BLE001
        checks.append({"name": "packet sent after retries", "passed": False, "detail": str(exc)})
    return {"passed": all(c["passed"] for c in checks), "checks": checks}


TASKS: dict[str, dict] = {
    "toy-backoff": {
        "id": "toy-backoff",
        "title": "Exponential-backoff retry helper (toy)",
        "goal_prompt": "Implement retry(fn, attempts=3, base_delay=0.1, factor=2.0, sleep=...) in pure Python: call fn, retry on Exception with exponential backoff, re-raise the last error when attempts run out. No external deps.",
        "est_without_ai_s": 900.0,
        "hints": TOY_HINTS,
        "quiz": TOY_QUIZ,
        "scripted_attempt": TOY_SCRIPTED_ATTEMPT,
        "scripted_code": TOY_SCRIPTED_CODE,
        "scripted_answers": [q["answer"] for q in TOY_QUIZ],
        "verify": verify_retry_solution,
    },
    "wifi-csi-backoff": {
        "id": "wifi-csi-backoff",
        "title": "Backoff retry for the CSI packet writer (WiFi)",
        "goal_prompt": "Add backoff retry to the CSI packet writer: wrap the send in the retry helper so transient write failures are retried with exponential backoff, and a dead link still fails loudly after N tries.",
        "est_without_ai_s": 1800.0,
        "hints": WIFI_HINTS,
        "quiz": WIFI_QUIZ,
        "scripted_attempt": WIFI_SCRIPTED_ATTEMPT,
        "scripted_code": WIFI_SCRIPTED_CODE,
        "scripted_answers": [q["answer"] for q in WIFI_QUIZ],
        "verify": verify_wifi_solution,
    },
}

DEFAULT_TASK = "toy-backoff"


def get_task(task_id: str) -> dict:
    if task_id not in TASKS:
        raise ValueError(f"unknown task {task_id!r}; known: {sorted(TASKS)}")
    return TASKS[task_id]


def score_answer(answer: str, keywords: list[str]) -> bool:
    """Explain-back scoring: does the answer contain any expected idea?
    Keyword match is deliberately loose in V1; the point is retrieval
    (saying it from memory), not exact wording."""
    text = (answer or "").lower()
    return any(kw.lower() in text for kw in keywords)
