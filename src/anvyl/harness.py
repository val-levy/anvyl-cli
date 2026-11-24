"""Sub-harnesses: author-written presets that run on Anvyl's own graph.

A bundle is data only: `harness.toml`, an optional `prompt.md` and `skills/*.md`. No code
is ever loaded from one. It can set the base mode (learn|ship), a level cap, a pitch and
coach guidance text, which reaches the model fenced as untrusted. Everything else (gate,
level, scoring, tool access) stays in the policy core, so a bundle changes what the coach
SAYS, never what Anvyl DOES. Loading is fail-closed: any problem rejects the whole bundle.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .policy import REAL_MAX_LEVEL

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
KEYS = {"id", "name", "version", "author", "pitch", "base", "max_level"}
MAX_TEXT = 4000
MAX_SKILLS = 5
MAX_TOML = 4000
BUILTIN_MODES = ("learn", "ship")


class HarnessError(Exception):
    """The bundle is rejected; `.problems` lists every reason."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Harness:
    id: str
    name: str
    version: str
    author: str
    pitch: str
    base: str  # "learn" | "ship": which built-in policy path it runs on
    max_level: int
    prompt: str = ""
    skills: tuple[tuple[str, str], ...] = ()
    files: dict[str, bytes] = field(default_factory=dict, compare=False, repr=False)

    @property
    def guidance(self) -> str:
        parts = [self.prompt, *(f"[{n}]\n{t}" for n, t in self.skills)]
        return "\n\n".join(p for p in parts if p.strip())

    def digest(self) -> str:
        h = hashlib.sha256()
        for name in sorted(self.files):
            h.update(name.encode() + b"\0" + hashlib.sha256(self.files[name]).digest())
        return h.hexdigest()

    def index_entry(self) -> dict:
        """What the registry index lists for this bundle (the URL/commit come from the PR)."""
        return {
            "id": self.id,
            "version": self.version,
            "pitch": self.pitch,
            "base": self.base,
            "max_level": self.max_level,
            "sha256": self.digest(),
        }


def _text(raw: bytes, name: str, problems: list[str]) -> str:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        problems.append(f"{name}: not UTF-8 text")
        return ""
    if len(text) > MAX_TEXT:
        problems.append(f"{name}: over {MAX_TEXT} characters")
    return text


def load(path: Path) -> Harness:
    """Read and validate a bundle directory; raise HarnessError listing every problem."""
    problems: list[str] = []
    root = Path(path)
    files: dict[str, bytes] = {}
    if root.is_symlink() or not root.is_dir():
        raise HarnessError([f"{root}: not a directory"])
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_symlink():
            problems.append(f"{rel}: symlinks are not allowed")
        elif p.is_dir():
            if rel != "skills":
                problems.append(f"{rel}: unexpected folder")
        elif rel in ("harness.toml", "prompt.md") or (
            rel.startswith("skills/") and rel.count("/") == 1 and rel.endswith(".md")
        ):
            files[rel] = p.read_bytes()
        else:
            problems.append(f"{rel}: only harness.toml, prompt.md and skills/*.md are allowed")
    raw = files.get("harness.toml")
    if raw is None:
        raise HarnessError([*problems, "harness.toml is missing"])
    if len(raw) > MAX_TOML:
        raise HarnessError([*problems, "harness.toml is too large"])
    try:
        meta = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        raise HarnessError([*problems, "harness.toml is not valid TOML"]) from None
    for k in sorted(set(meta) - KEYS):
        problems.append(f"harness.toml: unknown key {k!r}")

    def s(key: str, cap: int, required: bool = False) -> str:
        v = meta.get(key, "")
        if not isinstance(v, str) or (required and not v.strip()) or len(v) > cap:
            problems.append(f"harness.toml: {key} must be text of at most {cap} characters")
            return ""
        return v.strip()

    hid, version = s("id", 40, True), s("version", 20, True)
    if hid and not ID_RE.match(hid):
        problems.append("id must be 2-40 characters of a-z, 0-9 and '-'")
    if hid in BUILTIN_MODES:
        problems.append(f"id {hid!r} is a built-in mode")
    base = meta.get("base", "learn")
    if base not in BUILTIN_MODES:
        problems.append("base must be 'learn' or 'ship'")
    cap = meta.get("max_level", REAL_MAX_LEVEL)
    if not isinstance(cap, int) or isinstance(cap, bool) or not 0 <= cap <= REAL_MAX_LEVEL:
        problems.append(f"max_level must be a whole number 0-{REAL_MAX_LEVEL}")
        cap = 0
    prompt = _text(files["prompt.md"], "prompt.md", problems) if "prompt.md" in files else ""
    skill_names = [n for n in files if n.startswith("skills/")]
    if len(skill_names) > MAX_SKILLS:
        problems.append(f"at most {MAX_SKILLS} skills")
    skills = tuple((n[7:-3], _text(files[n], n, problems)) for n in skill_names)
    if problems:
        raise HarnessError(problems)
    return Harness(
        hid, s("name", 60) or hid, version, s("author", 60), s("pitch", 140),
        base, cap, prompt, skills, files,
    )  # fmt: skip


def installed(data_dir: Path) -> dict[str, Harness]:
    """Valid installed harnesses by id. A broken or tampered bundle is simply not listed."""
    out: dict[str, Harness] = {}
    base = Path(data_dir) / "harnesses"
    for d in sorted(base.iterdir()) if base.is_dir() else []:
        try:
            h = load(d)
        except (HarnessError, OSError):
            continue
        if h.id == d.name:
            out[h.id] = h
    return out


def install(src: Path, data_dir: Path) -> Harness:
    """Validate `src`, then copy only its allowed files into <data_dir>/harnesses/<id>."""
    h = load(src)
    dest = Path(data_dir) / "harnesses" / h.id
    tmp = dest.with_name(f".{h.id}.tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    for name, raw in h.files.items():
        f = tmp / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(raw)
    shutil.rmtree(dest, ignore_errors=True)
    tmp.rename(dest)
    return h


TEMPLATE = {
    "harness.toml": (
        'id = "{id}"\nname = "{id}"\nversion = "0.1.0"\nauthor = ""\n'
        'pitch = "One line on what this harness is for"\n'
        '# base is "learn" (attempt gate on) or "ship" (AI may draft)\nbase = "learn"\n'
        f"max_level = {REAL_MAX_LEVEL}\n"
    ),
    "prompt.md": (
        "Guidance for the coach in this harness: what to focus on, what to ask first.\n"
        "It shapes the coach's questions only. It cannot unlock code or change levels.\n"
    ),
}


def scaffold(dest: Path, hid: str) -> Path:
    if not ID_RE.match(hid) or hid in BUILTIN_MODES:
        raise HarnessError(["id must be 2-40 characters of a-z, 0-9 and '-'"])
    if dest.exists():
        raise HarnessError([f"{dest} already exists"])
    dest.mkdir(parents=True)
    for name, body in TEMPLATE.items():
        (dest / name).write_text(body.format(id=hid))
    return dest
