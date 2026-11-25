"""Per-folder privacy profile and consent, persisted in <data_dir>/config.json."""

import json
import os
import tempfile
from enum import StrEnum
from pathlib import Path
from typing import Any


class Profile(StrEnum):
    PROFESSIONAL = "professional"
    PERSONAL = "personal"


class FolderConfig:
    def __init__(self, data_dir: Path) -> None:
        self._path = Path(data_dir) / "config.json"

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self._path.read_text())
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".config-")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            os.replace(tmp, self._path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    @staticmethod
    def _key(folder: Path) -> str:
        return str(Path(folder).resolve())

    def _entry(self, folder: Path) -> dict[str, Any]:
        entry = self._load().get("folders", {}).get(self._key(folder))
        return entry if isinstance(entry, dict) else {}

    def _update(self, folder: Path, **fields: Any) -> None:
        data = self._load()
        folders = data.get("folders")
        if not isinstance(folders, dict):
            folders = data["folders"] = {}
        entry = folders.get(self._key(folder))
        if not isinstance(entry, dict):
            entry = folders[self._key(folder)] = {}
        entry.update(fields)
        self._save(data)

    def profile(self, folder: Path) -> Profile | None:
        try:
            return Profile(str(self._entry(folder).get("profile")))
        except ValueError:
            return None

    def set_profile(self, folder: Path, profile: Profile) -> None:
        self._update(folder, profile=str(profile))

    def consented(self, folder: Path) -> bool:
        return self._entry(folder).get("consent") is True

    def consent_asked(self, folder: Path) -> bool:
        return isinstance(self._entry(folder).get("consent"), bool)

    def set_consent(self, folder: Path, yes: bool) -> None:
        self._update(folder, consent=yes)

    def keep_diffs(self, folder: Path) -> bool:
        return self.profile(folder) is Profile.PERSONAL and (
            self._entry(folder).get("keep_diffs") is True
        )

    def set_keep_diffs(self, folder: Path, yes: bool) -> None:
        self._update(folder, keep_diffs=yes)

    def model(self) -> str | None:
        m = self._load().get("model")
        return m if isinstance(m, str) and 0 < len(m) <= 100 else None

    def set_model(self, model: str) -> None:
        data = self._load()
        data["model"] = model
        self._save(data)

    def personal_notice_seen(self) -> bool:
        return self._load().get("personal_notice_seen") is True

    def mark_personal_notice_seen(self) -> None:
        data = self._load()
        data["personal_notice_seen"] = True
        self._save(data)


def effective_profile(config: FolderConfig, folder: Path) -> Profile:
    return config.profile(folder) or Profile.PROFESSIONAL
