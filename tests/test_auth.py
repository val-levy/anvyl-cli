import sys

import keyring
import keyring.errors
import pytest

from anvyl import auth


@pytest.fixture
def kr(monkeypatch):
    """In-memory keyring; never touches the real keychain."""
    store: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(keyring, "get_password", lambda s, u: store.get((s, u)))
    monkeypatch.setattr(keyring, "set_password", lambda s, u, p: store.__setitem__((s, u), p))

    def delete(s, u):
        if (s, u) not in store:
            raise keyring.errors.PasswordDeleteError("missing")
        del store[(s, u)]

    monkeypatch.setattr(keyring, "delete_password", delete)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    return store


def _broken(monkeypatch):
    def boom(*a, **k):
        raise keyring.errors.KeyringError("no backend")

    for name in ("get_password", "set_password", "delete_password"):
        monkeypatch.setattr(keyring, name, boom)


def test_env_wins_over_stored(kr, tmp_path, monkeypatch):
    auth.store_api_key("stored", tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "from-env")
    assert auth.get_api_key(tmp_path) == "from-env"


def test_store_uses_keychain_when_available(kr, tmp_path):
    assert auth.store_api_key("k1", tmp_path) == "keychain"
    assert auth.get_api_key(tmp_path) == "k1"
    assert not (tmp_path / "key").exists()


def test_store_falls_back_to_0600_file_when_keyring_errors(kr, tmp_path, monkeypatch):
    _broken(monkeypatch)
    assert auth.store_api_key("k2", tmp_path) == "file"
    assert auth.get_api_key(tmp_path) == "k2"
    if sys.platform != "win32":
        assert (tmp_path / "key").stat().st_mode & 0o777 == 0o600


def test_get_returns_none_when_nothing(kr, tmp_path):
    assert auth.get_api_key(tmp_path) is None


def test_delete_removes_both(kr, tmp_path, monkeypatch):
    kr[("anvyl", "openrouter")] = "a"
    (tmp_path / "key").write_text("b")
    auth.delete_api_key(tmp_path)
    assert not kr
    assert not (tmp_path / "key").exists()
    assert auth.get_api_key(tmp_path) is None


def test_get_uses_resolved_data_dir_when_none(kr, tmp_path, monkeypatch):
    monkeypatch.setenv("ANVYL_HOME", str(tmp_path))
    (tmp_path / "key").write_text("filekey\n")
    assert auth.get_api_key() == "filekey"
