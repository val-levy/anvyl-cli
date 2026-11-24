"""Policy core + judge tests: the attempt gate, the stripper, the judge,
plugin gating, and level auto-drop. All pure functions, no model."""

from harness import policy
from harness.judge import judge_check


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
