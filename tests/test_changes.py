from pathlib import Path

from anvyl.changes import clear_snapshot, compute_changes, count_ai_lines, take_snapshot
from anvyl.profile import Profile

P = Profile.PROFESSIONAL


def _repo(tmp_path: Path, files: dict[str, str]) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    root.mkdir()
    for rel, body in files.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body)
    return root, tmp_path / "work" / "deep"


def test_modified_new_deleted_files(tmp_path):
    root, work = _repo(tmp_path, {"a.py": "1\n2\n3\n", "b.py": "x\ny\n", "c.py": "keep\n"})
    take_snapshot(root, P, work)
    (root / "a.py").write_text("1\nTWO\n3\n4\n")  # +2 -1
    (root / "b.py").unlink()  # -2
    (root / "n.py").write_text("p\nq\nr\n")  # +3
    ch = compute_changes(root, P, work)
    assert ch.files == ["a.py", "b.py", "n.py"]
    assert (ch.added, ch.removed) == (5, 3)
    assert sorted(ch.added_lines) == ["4", "TWO", "p", "q", "r"]
    assert "+TWO" in ch.text and "-2" in ch.text


def test_preexisting_uncommitted_edit_excluded(tmp_path):
    root, work = _repo(tmp_path, {"a.py": "1\n"})
    (root / "a.py").write_text("dirty\n")
    take_snapshot(root, P, work)
    ch = compute_changes(root, P, work)
    assert ch.files == [] and ch.added == 0 and ch.removed == 0


def test_edit_to_already_dirty_file_counts_only_delta(tmp_path):
    root, work = _repo(tmp_path, {"a.py": "1\n"})
    (root / "a.py").write_text("1\ndirty\n")
    take_snapshot(root, P, work)
    (root / "a.py").write_text("1\ndirty\nnew\n")
    ch = compute_changes(root, P, work)
    assert (ch.added, ch.removed, ch.added_lines) == (1, 0, ["new"])


def test_no_changes_returns_empty(tmp_path):
    root, work = _repo(tmp_path, {"a.py": "1\n", "b.py": "a\r\nb"})
    take_snapshot(root, P, work)
    ch = compute_changes(root, P, work)
    assert (ch.files, ch.added, ch.removed, ch.added_lines, ch.text) == ([], 0, 0, [], "")


def test_empty_repo(tmp_path):
    root, work = _repo(tmp_path, {})
    take_snapshot(root, P, work)
    assert compute_changes(root, P, work).files == []


def test_crlf_only_difference_ignored(tmp_path):
    root, work = _repo(tmp_path, {})
    (root / "a.py").write_bytes(b"1\r\n2\r\n")
    take_snapshot(root, P, work)
    (root / "a.py").write_bytes(b"1\n2\n")
    assert compute_changes(root, P, work).files == []


def test_renamed_file_is_add_plus_delete(tmp_path):
    root, work = _repo(tmp_path, {"old.py": "a\nb\n"})
    take_snapshot(root, P, work)
    (root / "old.py").rename(root / "new.py")
    ch = compute_changes(root, P, work)
    assert ch.files == ["new.py", "old.py"]
    assert (ch.added, ch.removed) == (2, 2)


def test_now_denied_but_present_not_counted_as_deleted(tmp_path):
    root, work = _repo(tmp_path, {"a.py": "1\n"})
    take_snapshot(root, P, work)
    (root / ".anvylignore").write_text("a.py\n")
    assert "a.py" not in compute_changes(root, P, work).files


def test_count_ai_lines_normalizes_whitespace():
    assert count_ai_lines(["  x =   1", "y"], ["x = 1\n\tz"]) == 1


def test_count_ai_lines_ignores_blank_and_reworded():
    assert count_ai_lines(["", "   ", "x = 2"], ["x = 1", "", "  "]) == 0


def test_snapshot_skips_denied_and_binary(tmp_path):
    root, work = _repo(tmp_path, {"a.py": "1\n", ".env": "K=v\n"})
    (root / "bin.dat").write_bytes(b"\0\1\2")
    take_snapshot(root, P, work)
    got = sorted(
        p.relative_to(work / "base").as_posix() for p in (work / "base").rglob("*") if p.is_file()
    )
    assert got == ["a.py"]


def test_works_without_git(tmp_path):
    root, work = _repo(tmp_path, {"a.py": "1\n"})
    take_snapshot(root, P, work)
    (root / "a.py").write_text("2\n")
    ch = compute_changes(root, P, work)
    assert (ch.added, ch.removed) == (1, 1)


def test_clear_snapshot_only_removes_base_and_is_noop_if_absent(tmp_path):
    clear_snapshot(tmp_path / "nope")
    root, work = _repo(tmp_path, {"a.py": "1\n"})
    take_snapshot(root, P, work)
    (work / "keep.txt").write_text("k")
    clear_snapshot(work)
    assert not (work / "base").exists() and (work / "keep.txt").exists()
