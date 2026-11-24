from conftest import run_real  # noqa: F401
from test_session import go, prep

from anvyl import models
from anvyl.profile import FolderConfig


def row(id, pricing, params):
    return {"id": id, "pricing": pricing, "supported_parameters": params}


PAYLOAD = {
    "data": [
        {
            "id": "a/cheap",
            "name": "Cheap\x1b[31m!",
            "context_length": 128000,
            "pricing": {"prompt": "0.0000005", "completion": "0.000002"},
            "supported_parameters": ["tools"],
        },
        {
            "id": "b/free",
            "pricing": {"prompt": "0", "completion": "0"},
            "supported_parameters": ["tools"],
        },
        {
            "id": "c/router",
            "pricing": {"prompt": "-1", "completion": "-1"},
            "supported_parameters": ["tools"],
        },
        {
            "id": "d/notools",
            "pricing": {"prompt": "1", "completion": "1"},
            "supported_parameters": [],
        },
        {"id": 5},
        "junk",
    ]
}


def test_parse_prices_cleaning_and_tool_flag():
    ms = {m.id: m for m in models.parse(PAYLOAD)}
    assert set(ms) == {"a/cheap", "b/free", "c/router", "d/notools"}
    assert ms["a/cheap"].price_in == 0.5 and ms["a/cheap"].price_out == 2.0
    assert "\x1b" not in ms["a/cheap"].name
    assert ms["b/free"].price_in == 0 and ms["c/router"].price_in is None
    assert ms["d/notools"].tools is False
    assert models.parse(None) == [] and models.parse({"data": 3}) == []


def test_model_command_picks_by_number_and_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "fetch", lambda: models.parse(PAYLOAD))
    root, data = prep(tmp_path)
    r = go(root, data, ["/model", "1", "/quit"])
    assert "a/cheap" in r.out and "$0.50 in" in r.out and "notools" not in r.out
    assert r.client.model == "a/cheap" if hasattr(r.client, "model") else True
    assert FolderConfig(data).model() == "a/cheap"


def test_model_command_filters_then_picks_exact_id_and_offline(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "fetch", lambda: models.parse(PAYLOAD))
    root, data = prep(tmp_path)
    go(root, data, ["/model", "free", "b/free", "/quit"])
    assert FolderConfig(data).model() == "b/free"
    monkeypatch.setattr(models, "fetch", lambda: [])
    assert "could not load" in go(root, data, ["/model", "/quit"]).out


def test_history_and_copy(tmp_path, monkeypatch):
    import subprocess

    from anvyl import session

    sent = []
    monkeypatch.setattr(session.shutil, "which", lambda n: "/x/" + n if n == "pbcopy" else None)
    monkeypatch.setattr(session.subprocess, "run", lambda a, **k: sent.append((a, k["input"])))
    root, data = prep(tmp_path)
    r = go(root, data, ["/history", "/copy", "/copy all", "/quit"])
    assert "No sessions yet" in r.out and "nothing to copy" in r.out
    s = session.Session(root, data, __import__("rich.console").console.Console(), None, str)
    s.copy("hello", "x")
    assert sent == [(["pbcopy"], b"hello")] and subprocess
