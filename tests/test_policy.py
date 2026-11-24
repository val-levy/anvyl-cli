"""Policy core + judge tests: the attempt gate, the stripper, the judge,
plugin gating, and level auto-drop. All pure functions, no model."""

from anvyl import policy
from anvyl.judge import judge_check


def _state(**over):
    base = {"mode": "learn", "level": 1, "human_attempt": "", "ownership_score": 0.0}
    base.update(over)
    return base


# -- attempt gate -------------------------------------------------------
def test_gate_blocks_empty_attempt_in_learn():
    assert policy.gate_passed(_state(human_attempt="")) is False
    assert policy.gate_passed(_state(human_attempt="idk")) is False
    assert policy.gate_passed(_state(human_attempt="do the thing")) is False


def test_gate_passes_with_real_attempt_in_learn():
    attempt = "Loop over attempts, try fn, sleep with growing delay, re-raise at the end."
    assert policy.gate_passed(_state(human_attempt=attempt)) is True


def test_gate_is_open_in_ship_mode():
    assert policy.gate_passed(_state(mode="ship", human_attempt="")) is True


# -- coach code rights ----------------------------------------------------
def test_coach_may_not_write_code_at_l1():
    assert policy.can_coach_write_code(_state(level=1)) is False
    assert policy.can_coach_write_code(_state(level=0)) is False


def test_coach_may_draft_at_l2_only_after_gate():
    assert policy.can_coach_write_code(_state(level=2, human_attempt="")) is False
    assert (
        policy.can_coach_write_code(
            _state(level=2, human_attempt="Loop, try fn, sleep longer each time, re-raise.")
        )
        is True
    )


# -- stripper ---------------------------------------------------------------
def test_stripper_removes_code_blocks_at_l1():
    text = (
        "Here is an idea:\n```python\ndef retry(fn):\n    return fn()\n```\nThink about the loop."
    )
    cleaned, removed, _notes = policy.strip_solution_code(text, _state(level=1))
    assert "```" not in cleaned
    assert "def retry" not in cleaned
    assert removed >= 1
    assert "Think about the loop" in cleaned


def test_stripper_removes_bare_code_lines_at_l1():
    text = "A hint:\ndef retry(fn):\n    return fn()\nWhat should the loop do?"
    cleaned, removed, _notes = policy.strip_solution_code(text, _state(level=1))
    assert "def retry" not in cleaned
    assert removed >= 1
    assert "What should the loop do?" in cleaned


def test_stripper_leaves_plain_prose_alone():
    text = "What changes between one failed call and the next?"
    cleaned, removed, _notes = policy.strip_solution_code(text, _state(level=1))
    assert cleaned == text
    assert removed == 0


# -- judge ------------------------------------------------------------------
def test_judge_flags_code_leak():
    verdict = judge_check("Try this:\n```python\ndef retry(fn):\n    pass\n```")
    assert verdict["leaked"] is True
    assert verdict["reasons"]


def test_judge_passes_plain_hint():
    verdict = judge_check("What has to happen between one failed call and the next?")
    assert verdict["leaked"] is False


# -- plugins ------------------------------------------------------------------
def test_plugin_writing_code_is_blocked_at_l1():
    manifest = {"id": "evil", "enabled": True, "max_level": 4, "writes_code": True}
    allowed, reason = policy.plugin_allowed(manifest, _state(level=1))
    assert allowed is False
    assert "L0/L1" in reason


def test_plugin_writing_code_allowed_at_l3_after_gate():
    manifest = {"id": "ok", "enabled": True, "max_level": 4, "writes_code": True}
    state = _state(level=3, human_attempt="Loop, try fn, sleep longer each time, re-raise.")
    allowed, _reason = policy.plugin_allowed(manifest, state)
    assert allowed is True


def test_plugin_blocked_above_its_max_level():
    manifest = {"id": "low", "enabled": True, "max_level": 2, "writes_code": False}
    allowed, _reason = policy.plugin_allowed(manifest, _state(level=4))
    assert allowed is False


def test_disabled_plugin_is_blocked():
    manifest = {"id": "off", "enabled": False, "max_level": 4, "writes_code": False}
    allowed, _reason = policy.plugin_allowed(manifest, _state(level=1))
    assert allowed is False


# -- level auto-drop + explain-back --------------------------------------------
def test_auto_drop_level_on_low_ownership():
    assert policy.auto_drop_level(_state(level=3, ownership_score=0.3)) == 1
    assert policy.auto_drop_level(_state(level=3, ownership_score=0.9)) == 3
    assert policy.auto_drop_level(_state(level=1, ownership_score=0.0)) == 1


def test_explainback_required_rules():
    assert policy.explainback_required(_state(mode="learn")) is True
    assert policy.explainback_required(_state(mode="ship")) is False
    assert policy.explainback_required(_state(mode="ship", high_stakes=True)) is True


# -- real-ticket attempt floor, triage, level clamp ------------------------------
def test_attempt_floor_rejects_junk():
    for junk in ("asdf asdf asdf asdf asdf", "idk", "", "   ", None):
        ok, reason = policy.attempt_floor(junk)
        assert ok is False
        assert reason


def test_attempt_floor_rejects_copy_of_ticket():
    ticket = "Retry failed API calls with exponential backoff"
    ok, _ = policy.attempt_floor("retry failed api calls with exponential backoff.", ticket)
    assert ok is False
    ok, _ = policy.attempt_floor(f"Plan: {ticket} and then stop", ticket)
    assert ok is False


def test_attempt_floor_accepts_wrong_but_real_plan():
    ticket = "Retry failed API calls with exponential backoff"
    plan = "I would wrap the call in a loop and wait a fixed second between three tries"
    assert policy.attempt_floor(plan, ticket) == (True, "ok")


def test_high_stakes_from_ticket_words():
    assert policy.high_stakes("Fix the LOGIN redirect", []) is True
    assert policy.high_stakes("rotate API tokens", []) is True
    assert policy.high_stakes("Fix authentication bug", []) is True
    assert policy.high_stakes(None, []) is False


def test_high_stakes_from_paths():
    assert policy.high_stakes("tidy", ["src/auth/session.py"]) is True
    assert policy.high_stakes("tidy", ["app\\billing\\x.py"]) is True
    assert policy.high_stakes("tidy", ["db/migrations/001.sql"]) is True
    assert policy.high_stakes("tidy", ["src/security.py"]) is True
    assert policy.high_stakes("tidy", ["src/author.py", "docs/payments_faq.md"]) is False


def test_routine_ticket_not_high_stakes():
    assert policy.high_stakes("add a unit test for the parser", ["src/parser.py"]) is False
    assert policy.high_stakes("", []) is False


def test_clamp_real_level():
    assert [policy.clamp_real_level(n) for n in (-3, 0, 1, 2, 3, 4, 99)] == [0, 0, 1, 2, 2, 2, 2]


def test_attempt_floor_rejects_dominant_repeated_word():
    ok, reason = policy.attempt_floor("fix fix fix fix fix fix a b c")
    assert ok is False
    assert "one word" in reason.lower()


def test_attempt_floor_short_ticket_skips_containment():
    plan = "fix it by reading the config before the retry loop starts"
    assert policy.attempt_floor(plan, "fix it")[0] is True
    assert policy.attempt_floor(plan, "")[0] is True
    assert policy.attempt_floor(plan, None)[0] is True


def test_high_stakes_snake_case_and_false_positives():
    for hit in (
        "fix password_reset flow",
        "auth_token expiry",
        "rotate SECRET_KEY",
        "login_handler crash",
    ):
        assert policy.high_stakes(hit, []) is True, hit
    for miss in ("update the author bio", "secretary", "tokenize input", "authority check"):
        assert policy.high_stakes(miss, []) is False, miss
