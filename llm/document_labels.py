"""검색으로 알게 된 법령 id → 이름.

도구 호출 인자에는 법령 id만 있고 이름이 없다. 진행줄에 숫자 id를 그리지
않도록, 검색 결과가 나올 때마다 여기 적어 두고 화면이 약칭을 찾는다.
"""

from __future__ import annotations

import json

from storage.paths import AI_TOOL_SEARCH_CACHE_DIR

_NAME_INDEX_PATH = AI_TOOL_SEARCH_CACHE_DIR / "id_names.json"


def _load_index() -> dict[str, dict[str, str]]:
    try:
        data = json.loads(_NAME_INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    index: dict[str, dict[str, str]] = {}
    for item_id, record in data.items():
        if isinstance(record, dict):
            index[str(item_id)] = {
                "name": str(record.get("name") or ""),
                "short_name": str(record.get("short_name") or ""),
            }
        elif isinstance(record, str) and record.strip():
            index[str(item_id)] = {"name": record.strip(), "short_name": ""}
    return index


def persist_document_label(
    item_id: str, name: str = "", short_name: str = ""
) -> None:
    """검색·본문에서 알게 된 이름을 진행줄이 나중에 쓰도록 남긴다."""
    item_id = str(item_id or "").strip()
    name = " ".join(str(name or "").split())
    short_name = " ".join(str(short_name or "").split())
    if not item_id or not (name or short_name):
        return
    index = _load_index()
    previous = index.get(item_id) or {}
    index[item_id] = {
        "name": name or str(previous.get("name") or ""),
        "short_name": short_name or str(previous.get("short_name") or ""),
    }
    try:
        AI_TOOL_SEARCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _NAME_INDEX_PATH.write_text(
            json.dumps(index, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        return


def lookup_cached_document_label(item_id: str) -> str:
    """검색 때 적어 둔 이름으로 진행줄용 정식 명칭을 돌려준다."""
    item_id = str(item_id or "").strip()
    if not item_id:
        return ""
    record = _load_index().get(item_id)
    if not record:
        return ""
    full_name = " ".join(str(record.get("name") or "").split())
    # 구버전 기록에 약칭만 남은 경우에만 대체값으로 쓴다.
    return full_name or " ".join(str(record.get("short_name") or "").split())
