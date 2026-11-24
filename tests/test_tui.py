from types import SimpleNamespace

from prompt_toolkit.document import Document
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from anvyl.profile import Profile
from anvyl.tui import SlashCompleter, reader, status_fragments


def fake_session(**view):
    return SimpleNamespace(
        view=view, profile=Profile.PROFESSIONAL, mode="learn", level=1, stats=lambda: (2, 99)
    )


def test_reader_returns_typed_line_and_none_on_eof():
    with create_pipe_input() as pipe:
        read = reader(fake_session(), input=pipe, output=DummyOutput())
        pipe.send_text("fix login\r")
        assert read("ticket> ") == "fix login"
        pipe.send_text("\x04")  # Ctrl-D on an empty line
        assert read("ticket> ") is None


def test_slash_completer_only_for_a_bare_command_word():
    def names(text):
        return [c.text for c in SlashCompleter().get_completions(Document(text), None)]

    assert names("/le") == ["/level"] and "/exit" in names("/")
    assert names("fix /le") == [] and names("/level 1") == []


def test_status_bar_shows_state_and_never_view_text():
    bar = "".join(t for _, t in status_fragments(fake_session(gate_passed=True, ticket="SECRET")))
    assert "professional" in bar and "gate passed" in bar and "tokens 99" in bar
    assert "SECRET" not in bar
