from pathlib import Path

from support import FakeClient

from anvyl.profile import Profile
from anvyl.real_coach import RealCoach

STATE = {"level": 1, "ticket": "t", "human_attempt": "a"}


def coach(**kw):
    return RealCoach(FakeClient([]), Path("."), Profile.PROFESSIONAL, False, **kw)


def msgs(c, **extra):
    m = c.build_messages({**STATE, **extra})
    return m[0]["content"], m[1]["content"]


def test_prompt_describes_a_tutor_not_a_grader():
    sys, _ = msgs(coach())
    for w in (
        "tutor",
        "what they actually said",
        "different toy problem",
        "never their own",
        "one question",
    ):
        assert w in sys
    assert "never write code" in sys


def test_stage_teach_asks_for_a_short_lesson():
    _, user = msgs(coach(), tutor_stage="teach")
    assert "Stage: teach" in user and "short lesson" in user


def test_stage_feedback_reacts_to_approach_and_steps():
    _, user = msgs(
        coach(), tutor_stage="feedback", goal_detail="G1", approach="A1", steps=["S1", "S2"]
    )
    assert "Stage: feedback" in user
    for tag, val in (("goal", "G1"), ("approach", "A1"), ("steps", "S1 | S2")):
        assert tag in user and val in user


def test_known_is_in_user_message_and_system_says_dont_reteach():
    sys, user = msgs(coach(known="<memory>loops</memory>"))
    assert "loops" in user and "do not re-teach" in sys and "loops" not in sys


def test_known_empty_adds_nothing():
    sys, user = msgs(coach())
    assert "memory" not in sys and "memory" not in user


def test_known_is_not_in_state():
    state = dict(STATE)
    coach(known="K").build_messages(state)
    assert state == STATE
