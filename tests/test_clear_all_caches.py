from __future__ import annotations

from pathlib import Path

from ui.tabs.viewed_laws import ViewedLawsTab


def test_delete_cache_files_clears_only_files_inside_given_directories(
    tmp_path: Path,
) -> None:
    saved = tmp_path / "saved"
    references = tmp_path / "references"
    search = tmp_path / "search"
    outside = tmp_path / "keep.json"
    for directory in (saved, references, search):
        directory.mkdir()
        (directory / "cache.json").write_text("{}", encoding="utf-8")
    nested = references / "nested"
    nested.mkdir()
    (nested / "more.json").write_text("{}", encoding="utf-8")
    outside.write_text("{}", encoding="utf-8")

    deleted, errors = ViewedLawsTab._delete_cache_files(
        (saved, references, search)
    )

    assert deleted == 4
    assert errors == []
    assert outside.is_file()
    assert all(
        not cached_file.is_file()
        for directory in (saved, references, search)
        for cached_file in directory.rglob("*")
    )
    assert all(directory.is_dir() for directory in (saved, references, search))
