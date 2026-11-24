import os
import subprocess
from pathlib import Path

import pytest

from anvyl.guard import MAX_FILE_BYTES, is_denied, list_files, redact, resolve_inside
from anvyl.profile import Profile

BOTH = [Profile.PROFESSIONAL, Profile.PERSONAL]


@pytest.mark.parametrize("profile", BOTH)
@pytest.mark.parametrize(
    "rel",
    [
        ".env",
        ".env.local",
        ".ENV",
        "a/b/server.PEM",
        "k.key",
        "id_rsa",
        "id_rsa.pub",
        "x.p12",
        ".git/config",
        "web/node_modules/x/index.js",
        "NODE_MODULES/a.js",
    ],
)
def test_denies_env_and_keys_in_both_profiles(rel: str, profile: Profile) -> None:
    assert is_denied(rel, profile)
    assert not is_denied("src/main.py", profile)


def test_professional_denies_more_than_personal() -> None:
    for rel in ["secrets.json", "aws_credentials.txt", "a.sqlite", "dir/x.db"]:
        assert is_denied(rel, Profile.PROFESSIONAL)
        assert not is_denied(rel, Profile.PERSONAL)


def _write(root: Path, rel: str, data: bytes | str = "x") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data, bytes) else data.encode())


def test_list_files_respects_gitignore_in_git_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    _write(tmp_path, ".gitignore", "ignored.txt\n")
    _write(tmp_path, "ignored.txt")
    _write(tmp_path, "keep.py")
    _write(tmp_path, ".env")
    assert list_files(tmp_path, Profile.PERSONAL) == [".gitignore", "keep.py"]


def test_list_files_non_git_walks_and_skips_denied_and_binary_and_huge(tmp_path: Path) -> None:
    _write(tmp_path, "b/ok.txt")
    _write(tmp_path, "a.py")
    _write(tmp_path, ".env")
    _write(tmp_path, ".git/config")
    _write(tmp_path, "node_modules/p/i.js")
    _write(tmp_path, "bin.dat", b"ab\x00cd")
    _write(tmp_path, "huge.txt", b"a" * (MAX_FILE_BYTES + 1))
    assert list_files(tmp_path, Profile.PROFESSIONAL) == ["a.py", "b/ok.txt"]


def test_anvylignore_patterns_apply(tmp_path: Path) -> None:
    _write(tmp_path, ".anvylignore", "# c\n\n*.log\nprivate/*\n")
    _write(tmp_path, "a.log")
    _write(tmp_path, "d/b.log")
    _write(tmp_path, "private/x.txt")
    _write(tmp_path, "k.txt")
    assert list_files(tmp_path, Profile.PERSONAL) == [".anvylignore", "k.txt"]


def test_empty_folder_lists_nothing(tmp_path: Path) -> None:
    assert list_files(tmp_path, Profile.PERSONAL) == []


def test_folder_with_spaces_works(tmp_path: Path) -> None:
    root = tmp_path / "my project dir"
    _write(root, "sub dir/a file.txt")
    assert list_files(root, Profile.PERSONAL) == ["sub dir/a file.txt"]
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    assert list_files(root, Profile.PERSONAL) == ["sub dir/a file.txt"]


def test_resolve_inside_rejects_dotdot_absolute_and_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _write(root, "ok.txt")
    outside = tmp_path / "outside.txt"
    outside.write_text("hi")
    assert resolve_inside(root, "ok.txt") == (root / "ok.txt").resolve()
    for bad in ["../outside.txt", "a/../../outside.txt", str(outside)]:
        with pytest.raises(ValueError):
            resolve_inside(root, bad)
    try:
        os.symlink(outside, root / "link.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError):
        resolve_inside(root, "link.txt")


def test_resolve_inside_rejects_denied_file(tmp_path: Path) -> None:
    _write(tmp_path, ".env", "A=1")
    with pytest.raises(ValueError):
        resolve_inside(tmp_path, ".env")
    try:
        os.symlink(tmp_path / ".env", tmp_path / "innocent.txt")
    except (OSError, NotImplementedError):
        return
    with pytest.raises(ValueError):
        resolve_inside(tmp_path, "innocent.txt")


def test_redact_aws_key_and_private_key_block() -> None:
    key = "AKIAIOSFODNN7EXAMPLE"
    block = "-----BEGIN RSA PRIVATE KEY-----\nMIIEabc\ndef\n-----END RSA PRIVATE KEY-----"
    text = f"id={key}\n{block}\ntoken = ghp_{'a' * 36}\npassword: hunter2\nsk-{'b' * 24}"
    out, n = redact(text)
    for s in [key, "MIIEabc", "hunter2", "ghp_aaaa", "sk-bbbb"]:
        assert s not in out
    assert n == 5
    assert "[redacted]" in out


def test_redact_leaves_normal_code_alone() -> None:
    code = 'password_field = form.get("x")\ndef token_count(n): return n\n'
    assert redact(code) == (code, 0)
