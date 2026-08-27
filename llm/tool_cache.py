"""AI 검색 도구의 응답을 파일로 담아 두는 얇은 캐시.

같은 답 하나를 만드는 동안 모델은 법령을 대여섯 번씩 오간다. 게다가
Claude는 질문마다 MCP 서버를 새 프로세스로 띄우므로 메모리에 들고
있어 봐야 다음 질문에서는 사라진다. 그래서 파일로만 이어 붙인다.

storage/cache.py를 쓰지 않는 이유는 그쪽이 PySide6를 끌어오기 때문이다.
MCP 서버는 질문마다 새로 뜨는데 Qt까지 얹으면 그만큼 늦어진다. 여기서
필요한 것은 "문자열 하나를 정해진 시간 동안 들고 있기"뿐이라 따로 둔다.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

# 검색 결과는 새 법령이 올라오면 달라진다. 한 시간이면 충분히 최신이다.
SEARCH_TTL_SECONDS = 60 * 60
# 조문 본문은 시행일이 바뀌지 않는 한 그대로다. 하루로 넉넉히 잡는다.
BODY_TTL_SECONDS = 24 * 60 * 60

_SCHEMA = 1


class ToolCache:
    """키 하나에 글 하나. 시간이 지나면 스스로 버린다."""

    def __init__(self, directory: Path, ttl_seconds: int) -> None:
        self.directory = directory
        self.ttl_seconds = ttl_seconds

    def _path_for(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
        return self.directory / f"{digest}.json"

    def load(self, key: str) -> str | None:
        """담아 둔 글을 돌려준다. 없거나 상했으면 None."""
        path = self._path_for(key)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # 파일이 없는 경우가 대부분이고, 깨졌더라도 캐시는 보조
            # 수단이라 조용히 넘어간다. 다시 받아 오면 그만이다.
            return None
        if not isinstance(record, dict) or record.get("schema") != _SCHEMA:
            return None
        # 해시가 겹치는 일은 드물지만, 엉뚱한 조문을 돌려주면 그대로
        # 답변의 근거가 되므로 키를 그대로 넣어 두고 맞춰 본다.
        if record.get("key") != key:
            return None
        saved_at = record.get("saved_at")
        if not isinstance(saved_at, (int, float)):
            return None
        if time.time() - saved_at > self.ttl_seconds:
            try:
                path.unlink()
            except OSError:
                pass
            return None
        value = record.get("value")
        return value if isinstance(value, str) else None

    def save(self, key: str, value: str) -> None:
        """글을 담아 둔다. 실패해도 조용히 넘어간다."""
        if not value:
            return
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self._path_for(key).write_text(
                json.dumps(
                    {
                        "schema": _SCHEMA,
                        "key": key,
                        "saved_at": time.time(),
                        "value": value,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except (OSError, ValueError):
            # 담아 두지 못해도 답은 이미 손에 있다. 막지 않는다.
            return
