"""별표ㆍ서식 첨부 파일을 받아 두고 다시 쓰는 캐시."""

from __future__ import annotations

from pathlib import Path

import pytest

from utils import law_download


class _Response:
    is_redirect = False
    is_permanent_redirect = False

    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self.headers = {"Content-Length": str(len(payload))}

    def raise_for_status(self) -> None:
        return

    def iter_content(self, chunk_size: int = 0):
        yield self._payload

    def close(self) -> None:
        return


@pytest.fixture
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "별표파일"
    directory.mkdir()
    monkeypatch.setattr(law_download, "ANNEX_FILE_CACHE_DIR", directory)
    return directory


def _count_calls(monkeypatch: pytest.MonkeyPatch, payload: bytes) -> list[str]:
    calls: list[str] = []

    def fake_get(url: str, **_kwargs):
        calls.append(url)
        return _Response(payload)

    monkeypatch.setattr(law_download.requests, "get", fake_get)
    return calls


URL = "https://www.law.go.kr/LSW/flDownload.do?flSeq=1"


def test_same_file_is_not_downloaded_twice(cache_dir, monkeypatch) -> None:
    """같은 별표를 다시 열 때마다 법제처를 부르면 느리고 헛되다."""
    calls = _count_calls(monkeypatch, b"PDF-BYTES")
    assert law_download.download_law_file(URL) == b"PDF-BYTES"
    assert law_download.download_law_file(URL) == b"PDF-BYTES"
    assert len(calls) == 1
    assert len(list(cache_dir.iterdir())) == 1


def test_cache_can_be_bypassed(cache_dir, monkeypatch) -> None:
    calls = _count_calls(monkeypatch, b"PDF-BYTES")
    law_download.download_law_file(URL)
    law_download.download_law_file(URL, use_cache=False)
    assert len(calls) == 2


def test_cache_is_pruned_when_it_grows_past_the_cap(
    cache_dir, monkeypatch
) -> None:
    """별표 하나가 수 MB라, 상한 없이 쌓으면 디스크를 다 먹는다."""
    monkeypatch.setattr(law_download, "ANNEX_FILE_CACHE_MAX_BYTES", 20)
    _count_calls(monkeypatch, b"0123456789")
    for index in range(4):
        law_download.download_law_file(f"{URL}&n={index}")
    total = sum(item.stat().st_size for item in cache_dir.iterdir())
    assert total <= 20


def test_clearing_the_cache_removes_the_files(cache_dir, monkeypatch) -> None:
    _count_calls(monkeypatch, b"PDF-BYTES")
    law_download.download_law_file(URL)
    assert law_download.clear_annex_file_cache() == 1
    assert list(cache_dir.iterdir()) == []


def test_a_half_written_file_is_never_served(cache_dir, monkeypatch) -> None:
    """쓰다 만 파일을 다음에 읽으면 깨진 PDF가 열린다."""
    _count_calls(monkeypatch, b"PDF-BYTES")
    law_download.download_law_file(URL)
    cached = next(iter(cache_dir.iterdir()))
    assert cached.read_bytes() == b"PDF-BYTES"
