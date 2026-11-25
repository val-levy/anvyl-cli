import threading
import time
from types import SimpleNamespace

from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from anvyl.fullscreen import FullScreen
from anvyl.profile import Profile


class Out(DummyOutput):
    size = Size(rows=20, columns=60)

    def get_size(self):
        return self.size


def screen(ui):
    sc = ui.app.renderer.last_rendered_screen
    size = ui.app.output.get_size()
    return [
        "".join(sc.data_buffer[y][x].char for x in range(size.columns)).rstrip()
        for y in range(size.rows)
    ]


def wait_for(cond, secs=3.0):
    end = time.time() + secs
    while time.time() < end and not cond():
        time.sleep(0.02)
    return cond()


def test_input_stays_pinned_to_the_bottom_and_reflows_on_resize():
    sess = SimpleNamespace(
        root="/x/proj",
        view={},
        profile=Profile.PERSONAL,
        mode="learn",
        level=1,
        stats=lambda: (0, 0),
    )
    seen: dict = {}
    with create_pipe_input() as pipe:
        out = Out()
        ui = FullScreen(sess, input=pipe, output=out)

        def body():
            sess.console.print("hello world " * 8, soft_wrap=True)
            seen["line"] = sess.read_line("ticket> ")
            sess.console.print("after")
            wait_for(lambda: seen.get("done"))
            return 0

        def drive():
            wait_for(lambda: ui.reading and ui.app.renderer.last_rendered_screen is not None)
            time.sleep(0.3)
            seen["before"] = screen(ui)
            pipe.send_text("fix it\r")
            wait_for(lambda: "line" in seen)
            out.size = Size(rows=10, columns=30)
            time.sleep(0.5)
            seen["after"] = screen(ui)
            seen["done"] = True

        threading.Thread(target=drive, daemon=True).start()
        assert ui.run(body) == 0
    before, after = seen["before"], seen["after"]
    assert seen["line"] == "fix it"
    assert before[-7].startswith("hello world")  # hugs the input
    assert any("anvyl" in r for r in before[:3])  # welcome sits at the top of the screen
    assert before[-3].startswith("❯") and set(before[-4]) == {"─"} and "mode learn" in before[-1]
    assert len(after) == 10 and after[-3].startswith("❯") and "mode learn" in after[-1]
    assert any("❯ fix it" in row for row in after) and any("after" in row for row in after)
    assert max(len(r) for r in after) <= 30


def test_queue_feeds_chat_prompts_only_and_echo_is_a_band():
    ui = FullScreen(SimpleNamespace(root="/x", view={}, stats=lambda: (0, 0)))
    ui.width = 20
    ui.pending += ["first", "second"]
    assert ui.read("ticket> ") == "first" and ui.pending == ["second"]
    assert "\x1b[48;2;43;45;49m" in ui.raw  # the dark band behind your message
    ui.q.put("y")  # a non-chat prompt ignores the queue and waits for fresh input
    assert ui.read("[y/N] ") == "y" and ui.pending == ["second"]


def test_picker_filters_moves_and_returns_index():
    sess = SimpleNamespace(
        root="/x", view={}, profile=Profile.PERSONAL, mode="learn", level=1, stats=lambda: (0, 0)
    )
    got: dict = {}
    with create_pipe_input() as pipe:
        ui = FullScreen(sess, input=pipe, output=Out())

        def body():
            got["i"] = ui.choose("model", [("a/one", "$1"), ("b/two", "$2"), ("b/three", "$3")])
            got["esc"] = ui.choose("model", [("a/one", "$1")])
            return 0

        threading.Thread(target=lambda: ui.run(body), daemon=True).start()
        assert wait_for(lambda: ui.menu is not None)
        assert any("b/two" in r for r in screen(ui))
        pipe.send_text("b")  # filter to b/two, b/three
        assert wait_for(lambda: len(ui._visible()) == 2)
        pipe.send_text("\x1b[B")  # down
        assert wait_for(lambda: ui.menu["sel"] == 1)
        pipe.send_text("\r")
        assert wait_for(lambda: "i" in got and got["i"] == 2)
        assert wait_for(lambda: ui.menu is not None)
        pipe.send_text("\x1b")  # Esc cancels
        assert wait_for(lambda: "esc" in got) and got["esc"] is None
        ui.q.put(None)


def test_next_step_hint_shows_in_empty_input_and_hides_when_typing():
    sess = SimpleNamespace(
        root="/x",
        view={},
        profile=Profile.PERSONAL,
        mode="learn",
        level=1,
        stats=lambda: (0, 0),
        hint="Step 1 of 4: write your plan",
    )
    with create_pipe_input() as pipe:
        ui = FullScreen(sess, input=pipe, output=Out())
        threading.Thread(target=lambda: ui.run(lambda: ui.read("> ") and 0), daemon=True).start()

        def shown() -> bool:
            try:
                return any("Step 1 of 4" in r for r in screen(ui))
            except AttributeError:  # first frame not drawn yet
                return False

        assert wait_for(shown)
        pipe.send_text("x")
        assert wait_for(lambda: not shown())
        ui.q.put(None)


def test_esc_while_working_cancels_the_call_and_returns_queued_text_to_the_input():
    from anvyl import llm

    sess = SimpleNamespace(
        root="/x/proj",
        view={},
        profile=Profile.PERSONAL,
        mode="learn",
        level=1,
        stats=lambda: (0, 0),
        memory=SimpleNamespace(last_line=lambda: ""),
    )
    with create_pipe_input() as pipe:
        ui = FullScreen(sess, input=pipe, output=Out())
        seen: dict = {}

        def body():
            with ui.busy():
                seen["cancelled"] = wait_for(llm.CANCEL.is_set)
            return 0

        def drive():
            wait_for(lambda: ui.busy_since is not None)
            ui.pending.append("queued thought")
            pipe.send_text("\x1b")
            wait_for(lambda: ui.input.text)

        threading.Thread(target=drive, daemon=True).start()
        ui.run(body)
    assert seen["cancelled"] and ui.input.text == "queued thought" and not ui.pending


def test_esc_on_an_empty_prompt_recalls_the_last_message_and_arrows_stay_history():
    sess = SimpleNamespace(
        root="/x/proj",
        view={},
        profile=Profile.PERSONAL,
        mode="learn",
        level=1,
        stats=lambda: (0, 0),
        memory=SimpleNamespace(last_line=lambda: ""),
    )
    seen: dict = {}
    with create_pipe_input() as pipe:
        out = Out()
        out.size = Size(rows=32, columns=100)
        ui = FullScreen(sess, input=pipe, output=out)

        def body():
            seen["first"] = sess.read_line("ticket> ")
            sess.read_line("ticket> ")
            return 0

        def drive():
            wait_for(lambda: ui.reading)
            pipe.send_text("add retry\r")
            wait_for(lambda: ui.reading and not ui.input.text and "first" in seen)
            time.sleep(0.2)
            pipe.send_text("\x1b")
            wait_for(lambda: ui.input.text)
            seen["recalled"] = ui.input.text
            ui.input.text = ""
            pipe.send_text("\x1b[A")  # Up: history, not the welcome menu
            wait_for(lambda: ui.input.text)
            seen["up"] = ui.input.text
            pipe.send_text("\r")

        threading.Thread(target=drive, daemon=True).start()
        ui.run(body)
    assert seen["recalled"] == seen["up"] == "add retry"


def test_cancel_abandons_a_slow_model_call_at_once():
    import http.server

    import pytest

    from anvyl import llm

    class Slow(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            time.sleep(3)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Slow)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    old = llm.OPENROUTER_URL
    llm.OPENROUTER_URL = f"http://127.0.0.1:{srv.server_port}/"
    try:
        llm.CANCEL.clear()
        threading.Timer(0.3, llm.CANCEL.set).start()
        t0 = time.time()
        with pytest.raises(llm.ModelError, match="cancelled"):
            llm.OpenRouterClient("k", "m").chat([{"role": "user", "content": "hi"}])
        assert time.time() - t0 < 1.5
    finally:
        llm.CANCEL.clear()
        llm.OPENROUTER_URL = old
        srv.shutdown()
