"""AI 검색 도구 캐시 검증.

pytest의 tmp_path를 쓰지 않고 직접 임시 폴더를 만든다. 이 환경에서는
pytest가 임시 폴더를 훑다가 권한 오류로 멈추는 일이 있었다.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
from pathlib import Path

import pytest

from llm.tool_cache import ToolCache


@pytest.fixture
def cache_dir():
    directory = Path(tempfile.mkdtemp(prefix="law_tool_cache_"))
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_saved_text_comes_back(cache_dir) -> None:
    cache = ToolCache(cache_dir, ttl_seconds=60)
    cache.save("article:000479:0001", "제1조(목적) ...")
    assert cache.load("article:000479:0001") == "제1조(목적) ..."


def test_missing_key_is_not_an_error(cache_dir) -> None:
    cache = ToolCache(cache_dir, ttl_seconds=60)
    assert cache.load("없는:키") is None


def test_expired_entry_is_dropped(cache_dir) -> None:
    """시간이 지난 값은 돌려주지 않고 파일도 치운다."""
    cache = ToolCache(cache_dir, ttl_seconds=60)
    cache.save("조문", "옛 본문")
    path = next(cache_dir.glob("*.json"))
    record = json.loads(path.read_text(encoding="utf-8"))
    record["saved_at"] = time.time() - 3600
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

    assert cache.load("조문") is None
    assert not path.exists()


def test_key_mismatch_is_ignored(cache_dir) -> None:
    """해시가 겹쳐도 엉뚱한 조문을 돌려주면 안 된다.

    답변의 근거가 되는 값이라, 조금이라도 어긋나면 버리는 편이 낫다.
    """
    cache = ToolCache(cache_dir, ttl_seconds=60)
    cache.save("조문A", "본문 A")
    path = next(cache_dir.glob("*.json"))
    record = json.loads(path.read_text(encoding="utf-8"))
    record["key"] = "조문B"
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

    assert cache.load("조문A") is None


def test_broken_file_is_ignored(cache_dir) -> None:
    cache = ToolCache(cache_dir, ttl_seconds=60)
    cache.save("조문", "본문")
    next(cache_dir.glob("*.json")).write_text("깨진 내용", encoding="utf-8")
    assert cache.load("조문") is None


def test_empty_value_is_not_saved(cache_dir) -> None:
    """빈 답을 담아 두면 하루 내내 빈 답이 돌아온다."""
    cache = ToolCache(cache_dir, ttl_seconds=60)
    cache.save("조문", "")
    assert cache.load("조문") is None
    assert not list(cache_dir.glob("*.json"))


def test_unwritable_directory_does_not_raise() -> None:
    """캐시는 보조 수단이라 저장에 실패해도 답을 막으면 안 된다."""
    cache = ToolCache(Path("Z:/없는드라이브/캐시"), ttl_seconds=60)
    cache.save("조문", "본문")
    assert cache.load("조문") is None
