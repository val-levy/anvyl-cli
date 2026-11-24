"""Plugin and skill registries.

Plugins are bundles (skills + commands + tools + hooks) declared by a
manifest. Skills are SKILL.md files loaded on demand only. The registry
code is real; fetching remote plugins is a stub for later.

Both registries run inside the policy core: ``policy.plugin_allowed``
decides, from typed state, whether a plugin may run at the current
level and mode. A plugin can add tools and commands; it cannot change
the level, skip the attempt gate, or write code at L0/L1.
"""

from __future__ import annotations

import builtins
import json
from pathlib import Path

from . import policy


class PluginRegistry:
    def __init__(self, plugins_dir: str | Path):
        self.dir = Path(plugins_dir)
        self.manifests: dict[str, dict] = {}
        self.loaded: set[str] = set()
        self._load_manifests()

    def _load_manifests(self) -> None:
        if not self.dir.exists():
            return
        for manifest_path in sorted(self.dir.glob("*/manifest.json")):
            try:
                manifest = json.loads(manifest_path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            self.manifests[manifest["id"]] = manifest

    def list(self) -> builtins.list[dict]:
        return [{**m, "loaded": m["id"] in self.loaded} for m in self.manifests.values()]

    def load(self, plugin_id: str, state: dict) -> tuple[bool, str]:
        manifest = self.manifests.get(plugin_id)
        if manifest is None:
            return False, f"no plugin {plugin_id!r} (known: {sorted(self.manifests)})"
        allowed, reason = policy.plugin_allowed(manifest, state)
        if not allowed:
            return False, f"blocked by policy: {reason}"
        self.loaded.add(plugin_id)
        return True, f"loaded {plugin_id} v{manifest.get('version', '?')}"

    def unload(self, plugin_id: str) -> tuple[bool, str]:
        if plugin_id not in self.loaded:
            return False, f"{plugin_id} is not loaded"
        self.loaded.discard(plugin_id)
        return True, f"unloaded {plugin_id}"

    def install(self, plugin_id: str) -> str:
        """Stub: real fetching comes later. The install line is real
        syntax for the future installer; today it only works for plugins
        already present in the plugins dir."""
        if plugin_id in self.manifests:
            return f"{plugin_id} is already present in plugins/; use /plugin load {plugin_id}"
        return (
            f"/plugin install {plugin_id}\n"
            "  -> not implemented yet: plugin fetching from a registry is a stub in V1.\n"
            "  Add a folder plugins/<id>/ with a manifest.json to install locally."
        )

    def allowed_tools(self, state: dict) -> builtins.list[str]:
        """Tools from loaded plugins that are allowed in this state."""
        tools: list[str] = []
        for plugin_id in sorted(self.loaded):
            manifest = self.manifests.get(plugin_id, {})
            allowed, _ = policy.plugin_allowed(manifest, state)
            if allowed:
                tools.extend(manifest.get("tools", []))
        return tools


class SkillRegistry:
    """A skill is a SKILL.md file. Loaded on demand only -- when the task
    matches, or when the human runs ``/skill load``."""

    def __init__(self, skills_dir: str | Path):
        self.dir = Path(skills_dir)
        self.loaded: set[str] = set()

    def list(self) -> builtins.list[dict]:
        out: builtins.list[dict] = []
        if not self.dir.exists():
            return out
        for skill_dir in sorted(self.dir.iterdir()):
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                out.append({"id": skill_dir.name, "loaded": skill_dir.name in self.loaded})
        return out

    def load(self, skill_id: str) -> tuple[bool, str]:
        path = self.dir / skill_id / "SKILL.md"
        if not path.exists():
            known = [s["id"] for s in self.list()]
            return False, f"no skill {skill_id!r} (known: {known})"
        self.loaded.add(skill_id)
        return True, f"loaded skill {skill_id}"

    def unload(self, skill_id: str) -> tuple[bool, str]:
        if skill_id not in self.loaded:
            return False, f"skill {skill_id} is not loaded"
        self.loaded.discard(skill_id)
        return True, f"unloaded skill {skill_id}"

    def text(self, skill_id: str) -> str:
        path = self.dir / skill_id / "SKILL.md"
        return path.read_text() if path.exists() else ""

    def loaded_text(self) -> str:
        """Combined text of loaded skills, for the coach's context."""
        parts = [self.text(s) for s in sorted(self.loaded)]
        return "\n\n".join(p for p in parts if p)
