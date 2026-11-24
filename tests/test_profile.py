from pathlib import Path

from anvyl.profile import FolderConfig, Profile, effective_profile


def test_unknown_folder_defaults_to_professional(tmp_path: Path) -> None:
    cfg = FolderConfig(tmp_path / "data")
    assert cfg.profile(tmp_path) is None
    assert effective_profile(cfg, tmp_path) is Profile.PROFESSIONAL
    assert cfg.consented(tmp_path) is False


def test_set_profile_persists_across_instances(tmp_path: Path) -> None:
    data = tmp_path / "nested" / "data"
    FolderConfig(data).set_profile(tmp_path, Profile.PERSONAL)
    other = FolderConfig(data)
    assert other.profile(tmp_path) is Profile.PERSONAL
    assert effective_profile(other, tmp_path) is Profile.PERSONAL


def test_consent_is_per_folder(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    cfg = FolderConfig(tmp_path / "data")
    cfg.set_consent(a, True)
    assert cfg.consented(a) is True
    assert cfg.consented(b) is False
    cfg.set_consent(a, False)
    assert cfg.consented(a) is False


def test_keep_diffs_ignored_for_professional(tmp_path: Path) -> None:
    cfg = FolderConfig(tmp_path / "data")
    cfg.set_profile(tmp_path, Profile.PROFESSIONAL)
    cfg.set_keep_diffs(tmp_path, True)
    assert cfg.keep_diffs(tmp_path) is False
    cfg.set_profile(tmp_path, Profile.PERSONAL)
    assert cfg.keep_diffs(tmp_path) is True


def test_personal_notice_seen(tmp_path: Path) -> None:
    cfg = FolderConfig(tmp_path / "data")
    assert cfg.personal_notice_seen() is False
    cfg.mark_personal_notice_seen()
    assert FolderConfig(tmp_path / "data").personal_notice_seen() is True


def test_corrupt_config_file_is_treated_as_empty(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "config.json").write_text("{not json")
    cfg = FolderConfig(data)
    assert cfg.profile(tmp_path) is None
    cfg.set_consent(tmp_path, True)
    assert cfg.consented(tmp_path) is True
