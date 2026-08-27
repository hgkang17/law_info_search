"""테스트 공통 준비."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

# UI 시험이 실제 창을 띄우면 작업 화면에 에이전트 창이 깜빡인다.
# 각 테스트 파일이 PySide6를 가져오기 전에 여기서 먼저 막는다.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(autouse=True)
def isolate_ai_tool_cache(monkeypatch: pytest.MonkeyPatch):
    """AI 검색 도구 캐시를 임시 폴더로 돌린다.

    이걸 안 하면 테스트가 이 컴퓨터에 실제로 쌓인 캐시를 읽는다. 가짜
    API 응답을 넣어 두어도 캐시가 먼저 답해 버려서 무엇을 검증하는지
    알 수 없게 되고, 반대로 테스트가 만든 값이 실제 캐시에 남기도 한다.
    """
    directory = Path(tempfile.mkdtemp(prefix="law_test_cache_"))
    try:
        from llm import tools
    except Exception:
        # 화면 쪽 테스트처럼 이 모듈을 쓰지 않는 경우까지 막지 않는다.
        yield
    else:
        monkeypatch.setattr(tools._SEARCH_CACHE, "directory", directory / "검색")
        monkeypatch.setattr(tools._BODY_CACHE, "directory", directory / "본문")
        yield
    finally:
        shutil.rmtree(directory, ignore_errors=True)


class _MemoryDocumentCache:
    """화면 저장내역을 흉내 내는 테스트용 본문 저장소."""

    def __init__(self) -> None:
        self.records: dict[str, dict] = {}

    @staticmethod
    def _key(row: dict) -> str:
        return f"{row.get('target')}:{row.get('id')}"

    def load_for_row(self, row: dict) -> dict | None:
        record = self.records.get(self._key(row))
        if isinstance(record, dict) and isinstance(record.get("payload"), dict):
            return record
        return None

    def load_snapshot(self, row: dict) -> dict | None:
        record = self.records.get(self._key(row))
        if isinstance(record, dict) and record.get("kind") == "detail_snapshot":
            return record
        return None

    def save(self, row: dict, payload: dict, snapshot=None) -> bool:
        record = {"row": dict(row), "payload": payload, "name": row.get("name")}
        if snapshot:
            record.update(snapshot)
        self.records[self._key(row)] = record
        return True

    def save_snapshot(
        self, row: dict, *, html: str = "", plain_text: str = "", extra=None
    ) -> bool:
        record = {
            "kind": "detail_snapshot",
            "row": dict(row),
            "html": html,
            "plain_text": plain_text,
            "name": row.get("name"),
        }
        if extra:
            record.update(dict(extra))
        self.records[self._key(row)] = record
        return True


@pytest.fixture(autouse=True)
def isolate_saved_documents(monkeypatch: pytest.MonkeyPatch):
    """AI 본문 도구가 실제 저장내역 폴더를 읽거나 쓰지 않게 한다."""
    cache = _MemoryDocumentCache()
    monkeypatch.setattr("llm.tools._get_document_cache", lambda: cache)
    monkeypatch.setattr("llm.tools._document_cache", cache)
    yield cache
