from anvyl.cli import bar, light_terminal


def test_light_terminal_detection():
    assert light_terminal({"COLORFGBG": "0;15"})
    assert light_terminal({"COLORFGBG": "0;default;7"})
    assert not light_terminal({"COLORFGBG": "15;0"})
    assert not light_terminal({})


def test_bar_blocks():
    out = bar(50, width=10)
    assert out.count("█") == 5 and out.count("░") == 5 and out.endswith("50%")


def test_spin_word():
    from anvyl.cli import SPIN_WORDS, spin_word

    assert len(set(SPIN_WORDS)) == len(SPIN_WORDS) and spin_word().endswith("...")
