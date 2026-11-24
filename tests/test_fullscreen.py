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
