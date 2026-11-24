"""Privacy boundary: which files the read-only coach may see, and secret redaction."""

import os
import re
import subprocess
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

from anvyl.profile import Profile

MAX_FILE_BYTES = 200_000

_ALWAYS_DIRS = {".git", "node_modules", ".ssh"}
_ALWAYS = (
    ".env*",
    "*.pem",
    "*.key",
    "id_rsa*",
    "*.p12",
    "id_ed25519*",
    "id_ecdsa*",
    "id_dsa*",
    "*.pfx",
    "*.jks",
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".git-credentials",
)
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
    # Same filters as list_files: ignores, git-ignored, size, binary, symlink targets.
    if PurePosixPath(norm).as_posix() not in set(list_files(base, profile)):
        raise ValueError(f"path not readable: {rel}")
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


def _ignored(rel: str, patterns: list[str]) -> bool:
    parts = rel.split("/")
    for pat in patterns:
        anchored = pat.startswith("/")
        dir_only = pat.endswith("/")
        pat = pat.strip("/")
        if not pat:
            continue
        whole = anchored or "/" in pat
        for i in range(1, len(parts) + 1):
            if dir_only and i == len(parts):
                break
            cand = "/".join(parts[:i]) if whole else parts[i - 1]
            if fnmatch(cand, pat):
                return True
    return False


def _readable(root: Path, rel: str, profile: Profile) -> bool:
    path = root / rel
    try:
        if path.is_symlink():
            if is_denied(path.resolve().relative_to(root).as_posix(), profile):
                return False
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
        and not _ignored(rel, ignores)
        and _readable(root, rel, profile)
    ]
    return sorted(keep)


_KW = r"(?:password|passwd|secret|token|api[_-]?key|access[_-]?key)"
# Unquoted values only on env/YAML-style lines and never call-like (value runs to end of line).
# keyword anywhere in the key; pwd only as PWD or a *_pwd / *-pwd suffix
_KEY = r"(?:[\w.-]{0,64}" + _KW + r"[\w.-]{0,64}|[\w.-]{0,64}[_-]pwd|(?-i:PWD))"
_VAL = r"[^\s\"'`(){}\[\]]{1,500}(?=[ \t]*(?:\#.*)?\r?$)"
_SEP = r"[ \t]*[:=](?!=)[ \t]*"
_REDACTIONS = [
    # Body excludes "-----" so a repeated BEGIN header fails fast (linear time).
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----(?:[A-Za-z0-9+/=:,. \t\r\n]|-(?!----)){0,20000}?"
        r"-----END [A-Z ]*PRIVATE KEY-----"
    ),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*"),  # truncated block
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bgithub_pat_\w{20,}"),
    re.compile(r"\bgh[opsu]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bxox[bp]-[A-Za-z0-9-]{10,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{16,}=*"),
    # quoted literal: keep the key, drop the value
    re.compile(
        r"""(?i)(\b""" + _KEY + r"""["']?""" + _SEP + r""")"""
        r"""(?:"[^"\n]*"?|'[^'\n]*'?)"""  # to closing quote, or end of line
    ),
    # config-file style line (env, INI, properties, YAML): unquoted, not a number/bool/null
    re.compile(
        r"(?mi)(^[ \t]*(?:export[ \t]+|-[ \t]+)?" + _KEY + _SEP + ")"
        r"(?!(?:\d[\d._]*|true|false|none|null)[ \t]*(?:\#.*)?\r?$)" + _VAL
    ),
]


def _sub(m: re.Match[str]) -> str:
    return (m.group(1) if m.re.groups else "") + "[redacted]"


def redact(text: str) -> tuple[str, int]:
    total = 0
    for pat in _REDACTIONS:
        text, n = pat.subn(_sub, text)
        total += n
    return text, total
