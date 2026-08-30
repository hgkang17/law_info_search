"""저장 목록을 만들 때 본문까지 다시 읽지 않는지 확인한다.

목록 화면은 이름ㆍ구분ㆍ날짜ㆍ즐겨찾기 표시만 쓰는데 예전에는 저장 기록을
통째로 파싱했다. 저장한 법령 하나에 본문이 수백 KB씩 들어 있어, 창을 켤
때마다 저장 건수에 그대로 비례해 느려졌다(저장 62건에서 29.9MB를 읽었다).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from storage.cache import LawDocumentCache


@pytest.fixture
def cache(tmp_path: Path) -> LawDocumentCache:
    return LawDocumentCache(tmp_path / "저장내역")


def _row(identifier: str, name: str) -> dict[str, object]:
    return {"target": "law", "id": identifier, "name": name}


def _write(
    cache: LawDocumentCache,
    identifier: str,
    name: str,
    **extra: object,
) -> Path:
    """저장 기록 하나를 직접 만든다. 본문은 일부러 크게 넣는다."""
    row = _row(identifier, name)
    record: dict[str, object] = {
        "row": row,
        "name": name,
        "saved_at": f"2026-08-30T10:00:{identifier[-2:]}+09:00",
        "effective_date": "20260830",
        "payload": {"본문": "가" * 20000},
    }
    record.update(extra)
    path = cache.path_for_row(row)
    path.write_text(
        json.dumps(record, ensure_ascii=False), encoding="utf-8"
    )
    return path


def test_list_entries_drops_the_body(cache: LawDocumentCache) -> None:
    """목록 항목에는 본문이 들어 있지 않다."""
    _write(cache, "000001", "농지법")

    entries = cache.list_entries()

    assert len(entries) == 1
    assert entries[0]["name"] == "농지법"
    assert entries[0]["row"]["target"] == "law"
    assert "payload" not in entries[0]


def test_repeated_listing_does_not_reread_files(
    cache: LawDocumentCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    """바뀐 파일이 없으면 두 번째 목록은 디스크를 다시 파싱하지 않는다."""
    _write(cache, "000001", "농지법")
    _write(cache, "000002", "건축법")
    cache.list_entries()

    loaded: list[object] = []
    original = LawDocumentCache.load
    monkeypatch.setattr(
        LawDocumentCache,
        "load",
        lambda self, path: (loaded.append(path), original(self, path))[1],
    )

    assert len(cache.list_entries()) == 2
    assert loaded == []


def test_new_process_reuses_the_saved_index(
    cache: LawDocumentCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    """색인을 파일로 남겨 두어 다음에 켤 때도 다시 읽지 않는다."""
    _write(cache, "000001", "농지법")
    cache.list_entries()

    reopened = LawDocumentCache(cache.directory)
    loaded: list[object] = []
    original = LawDocumentCache.load
    monkeypatch.setattr(
        LawDocumentCache,
        "load",
        lambda self, path: (loaded.append(path), original(self, path))[1],
    )

    assert [entry["name"] for entry in reopened.list_entries()] == ["농지법"]
    assert loaded == []


def test_changed_file_is_read_again(cache: LawDocumentCache) -> None:
    """내용이 바뀌면 색인이 아니라 파일을 다시 읽는다."""
    path = _write(cache, "000001", "농지법")
    cache.list_entries()

    record = json.loads(path.read_text(encoding="utf-8"))
    record["name"] = "농지법 시행령"
    record["payload"] = {"본문": "나" * 30000}
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

    assert [entry["name"] for entry in cache.list_entries()] == ["농지법 시행령"]


def test_deleted_file_leaves_the_list(cache: LawDocumentCache) -> None:
    path = _write(cache, "000001", "농지법")
    _write(cache, "000002", "건축법")
    cache.list_entries()

    path.unlink()

    assert [entry["name"] for entry in cache.list_entries()] == ["건축법"]


def test_index_file_is_not_listed_as_a_record(
    cache: LawDocumentCache,
) -> None:
    """색인도 같은 폴더의 .json이므로 목록에서 빠져야 한다."""
    _write(cache, "000001", "농지법")
    cache.list_entries()

    assert (cache.directory / LawDocumentCache.LIST_INDEX_NAME).is_file()
    assert len(cache.list_entries()) == 1
    assert len(cache.list_records()) == 1


def test_favorite_entries_keep_the_saved_order(
    cache: LawDocumentCache,
) -> None:
    _write(cache, "000001", "농지법", favorite=True, favorite_order=2)
    _write(cache, "000002", "건축법", favorite=True, favorite_order=1)
    _write(cache, "000003", "민법")

    assert [entry["name"] for entry in cache.favorite_entries()] == [
        "건축법",
        "농지법",
    ]


def test_broken_index_falls_back_to_reading_files(
    cache: LawDocumentCache,
) -> None:
    """색인이 깨져도 목록은 그대로 나와야 한다."""
    _write(cache, "000001", "농지법")
    cache.list_entries()
    (cache.directory / LawDocumentCache.LIST_INDEX_NAME).write_text(
        "깨진 색인", encoding="utf-8"
    )

    reopened = LawDocumentCache(cache.directory)

    assert [entry["name"] for entry in reopened.list_entries()] == ["농지법"]
