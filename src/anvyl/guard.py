"""Privacy boundary: which files the read-only coach may see, and secret redaction."""

import os
import re
import subprocess
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

from anvyl.profile import Profile

MAX_FILE_BYTES = 200_000

_ALWAYS_DIRS = {".git", "node_modules"}
_ALWAYS = (".env*", "*.pem", "*.key", "id_rsa*", "*.p12")
_PROFESSIONAL = ("*secret*", "*credential*", "*.sqlite", "*.db")


def is_denied(rel: str, profile: Profile) -> bool:
    patterns = _ALWAYS + (_PROFESSIONAL if profile is Profile.PROFESSIONAL else ())
    for part in PurePosixPath(rel.replace("\\", "/")).parts:
        low = part.lower()
        if low in _ALWAYS_DIRS or any(fnmatch(low, p) for p in patterns):
            return True
    return False


def resolve_inside(root: Path, rel: str, profile: Profile = Profile.PROFESSIONAL) -> Path:
    # ponytail: defaults to the stricter profile; callers with a profile should pass it.
    norm = rel.replace("\\", "/")
    if (
        not norm
        or Path(rel).is_absolute()
        or PurePosixPath(norm).is_absolute()
        or ".." in PurePosixPath(norm).parts
    ):
        raise ValueError(f"path not allowed: {rel}")
    base = root.resolve()
    target = (base / norm).resolve()
    try:
        inner = target.relative_to(base).as_posix()
    except ValueError:
        raise ValueError(f"path escapes root: {rel}") from None
    if is_denied(norm, profile) or is_denied(inner, profile):
        raise ValueError(f"path denied: {rel}")
    return target


def _git_files(root: Path) -> list[str] | None:
    try:
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return None
        out = subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard", "-z"],
            cwd=root,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if out.returncode != 0:
        return None
    return [p for p in out.stdout.decode("utf-8", "replace").split("\0") if p]


def _walk_files(root: Path) -> list[str]:
    found: list[str] = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _ALWAYS_DIRS]
        base = Path(dirpath)
        found += [(base / f).relative_to(root).as_posix() for f in files]
    return found


def _ignore_patterns(root: Path) -> list[str]:
    try:
        lines = (root / ".anvylignore").read_text(errors="replace").splitlines()
    except OSError:
        return []
    return [s for s in (ln.strip() for ln in lines) if s and not s.startswith("#")]


def _readable(root: Path, rel: str) -> bool:
    path = root / rel
    try:
        if path.is_symlink():
            path.resolve().relative_to(root)
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            return False
        with path.open("rb") as f:
            return b"\0" not in f.read(1024)
    except (OSError, ValueError):
        return False


def list_files(root: Path, profile: Profile) -> list[str]:
    root = root.resolve()
    candidates = _git_files(root)
    if candidates is None:
        candidates = _walk_files(root)
    ignores = _ignore_patterns(root)
    keep = [
        rel
        for rel in set(candidates)
        if not is_denied(rel, profile)
        and not any(fnmatch(rel, p) or fnmatch(Path(rel).name, p) for p in ignores)
        and _readable(root, rel)
    ]
    return sorted(keep)


_REDACTIONS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*"),  # truncated block
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}"),
    re.compile(r"\bxox[bp]-[A-Za-z0-9-]{10,}"),
    re.compile(r"(?i)\b(?:password|secret|token|api_key)\s*[:=]\s*(?!\[redacted\])\S+"),
]


def redact(text: str) -> tuple[str, int]:
    total = 0
    for pat in _REDACTIONS:
        text, n = pat.subn("[redacted]", text)
        total += n
    return text, total
