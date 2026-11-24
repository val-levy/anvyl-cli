"""API key storage for anvyl: env var, then OS keychain, then a 0600 file.

Phase 1 is paste-only. Browser sign-in (OAuth) would slot in at the
caller of ``store_api_key`` (the login command): obtain the key from the
browser flow instead of a prompt, then store it the same way.
The key is never printed or logged here.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

import keyring
import keyring.errors

from anvyl.storage import resolve_data_dir

ENV_VAR = "OPENROUTER_API_KEY"
SERVICE = "anvyl"
USERNAME = "openrouter"


def get_api_key(data_dir: Path | None = None) -> str | None:
    if key := os.environ.get(ENV_VAR):
        return key
    try:
        if key := keyring.get_password(SERVICE, USERNAME):
            return key
    except keyring.errors.KeyringError:
        pass
    path = resolve_data_dir(data_dir) / "key"
    if path.is_file():
        return path.read_text().strip() or None
    return None


def store_api_key(key: str, data_dir: Path) -> str:
    """Store the key; returns "keychain" or "file"."""
    try:
        keyring.set_password(SERVICE, USERNAME, key)
        return "keychain"
    except keyring.errors.KeyringError:
        pass
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "key"
    # Create with 0600 so the key is never briefly world-readable.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(key)
    with contextlib.suppress(OSError):  # best effort (Windows)
        path.chmod(0o600)
    return "file"


def delete_api_key(data_dir: Path) -> None:
    with contextlib.suppress(keyring.errors.KeyringError):
        keyring.delete_password(SERVICE, USERNAME)
    (data_dir / "key").unlink(missing_ok=True)
