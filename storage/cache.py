"""본문·검색결과를 로컬 파일로 보관한다. API 호출을 줄이는 층."""

from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QObject, Signal
from utils.parsing import (
    json_text,
)


class SearchResultCache:
    """동일한 검색 조건의 목록 응답을 로컬 JSON으로 저장하고 재사용."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.last_error = ""
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.last_error = str(exc)

    @staticmethod
    def _normalized_query(query: str) -> str:
        return " ".join(str(query).split()).casefold()

    def path_for(self, target: str, query: str, search_scope: int) -> Path:
        normalized = self._normalized_query(query)
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]
        safe_target = re.sub(r"[^0-9A-Za-z_-]+", "_", str(target))
        return self.directory / f"{safe_target}_{int(search_scope)}_{digest}.json"

    def load(
        self, target: str, query: str, search_scope: int
    ) -> dict[str, object] | None:
        self.last_error = ""
        path = self.path_for(target, query, search_scope)
        try:
            if not path.is_file():
                return None
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict) or record.get("schema") != 1:
                return None
            if record.get("target") != target:
                return None
            stored_scope = record.get("search_scope")
            if stored_scope is None:
                stored_scope = 1
            if int(stored_scope) != int(search_scope):
                return None
            if self._normalized_query(str(record.get("query") or "")) != (
                self._normalized_query(query)
            ):
                return None
            if not isinstance(record.get("payload"), dict):
                return None
            return record
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.last_error = str(exc)
            return None

    def save(
        self,
        target: str,
        query: str,
        search_scope: int,
        payload: object,
    ) -> bool:
        self.last_error = ""
        if not isinstance(payload, dict):
            self.last_error = "검색 목록 응답 형식이 올바르지 않습니다."
            return False
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.path_for(target, query, search_scope)
            record = {
                "schema": 1,
                "target": target,
                "query": " ".join(str(query).split()),
                "search_scope": int(search_scope),
                "saved_at": datetime.now().astimezone().isoformat(
                    timespec="seconds"
                ),
                "payload": payload,
            }
            temporary_path = path.with_suffix(".json.tmp")
            temporary_path.write_text(
                json.dumps(record, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_path.replace(path)
            return True
        except (OSError, TypeError, ValueError) as exc:
            self.last_error = str(exc)
            return False


class LawDocumentCache(QObject):
    """조회한 법령 API 원문을 실행 폴더에 저장하고 다시 불러옴."""

    changed = Signal()

    def __init__(self, directory: Path, parent=None) -> None:
        super().__init__(parent)
        self.directory = directory
        self.last_error = ""
        # 검색 결과의 저장 여부 확인과 실제 열기가 연달아 같은 JSON을
        # 읽는다. 최근 문서만 작게 유지해 중복 디스크 읽기/파싱을 없앤다.
        self._snapshot_memory: OrderedDict[
            Path, tuple[int, int, dict[str, object]]
        ] = OrderedDict()
        self._snapshot_memory_limit = 6
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.last_error = str(exc)

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _cache_key(row: dict[str, object]) -> str:
        target = str(row.get("target") or "law")
        identifier = str(
            row.get("id")
            or row.get("source_id")
            or row.get("name")
            or "document"
        )
        provision = str(row.get("jo_code") or row.get("provision") or "")
        if provision:
            identifier = f"{identifier}_{provision}"
        safe_identifier = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", identifier)
        return f"{target}_{safe_identifier[:80]}"

    def path_for_row(self, row: dict[str, object]) -> Path:
        return self.directory / f"{self._cache_key(row)}.json"

    def has(self, row: dict[str, object]) -> bool:
        return self.path_for_row(row).is_file()

    def load_for_row(
        self, row: dict[str, object]
    ) -> dict[str, object] | None:
        if not self.has(row):
            return None
        return self.load(self.path_for_row(row))

    def load_snapshot(
        self, row: dict[str, object]
    ) -> dict[str, object] | None:
        """법령 외 검색 탭에서 저장한 상세 화면을 불러옴."""
        self.last_error = ""
        path = self.path_for_row(row)
        try:
            if not path.is_file():
                self._snapshot_memory.pop(path, None)
                return None
            stat = path.stat()
            cached = self._snapshot_memory.get(path)
            if cached is not None and cached[:2] == (
                stat.st_mtime_ns,
                stat.st_size,
            ):
                self._snapshot_memory.move_to_end(path)
                return cached[2]
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict) or record.get("kind") != "detail_snapshot":
                return None
            if not isinstance(record.get("row"), dict):
                return None
            if not isinstance(record.get("html"), str):
                return None
            record["path"] = str(path)
            self._snapshot_memory[path] = (
                stat.st_mtime_ns,
                stat.st_size,
                record,
            )
            self._snapshot_memory.move_to_end(path)
            while len(self._snapshot_memory) > self._snapshot_memory_limit:
                self._snapshot_memory.popitem(last=False)
            return record
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.last_error = str(exc)
            return None

    def has_snapshot(self, row: dict[str, object]) -> bool:
        return self.load_snapshot(row) is not None

    def delete(self, row: dict[str, object]) -> bool:
        """저장 체크를 해제했을 때 캐시된 본문 파일을 실제로 삭제."""
        self.last_error = ""
        path = self.path_for_row(row)
        try:
            if path.is_file():
                path.unlink()
            self._snapshot_memory.pop(path, None)
        except OSError as exc:
            self.last_error = str(exc)
            return False
        self.changed.emit()
        return True

    def save_snapshot(
        self,
        row: dict[str, object],
        *,
        html: str,
        plain_text: str,
        extra: dict[str, object] | None = None,
    ) -> bool:
        """법령 외 검색 탭의 표시 완료 본문을 로컬 JSON으로 저장."""
        self.last_error = ""
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.path_for_row(row)
            first_viewed_at = self._timestamp()
            if path.is_file():
                try:
                    previous = json.loads(path.read_text(encoding="utf-8"))
                    first_viewed_at = str(
                        previous.get("first_viewed_at") or first_viewed_at
                    )
                except (OSError, TypeError, ValueError, json.JSONDecodeError):
                    pass
            record = {
                "schema": 1,
                "kind": "detail_snapshot",
                "key": self._cache_key(row),
                "first_viewed_at": first_viewed_at,
                "saved_at": self._timestamp(),
                "name": str(row.get("title") or row.get("name") or "본문"),
                "row": dict(row),
                "html": str(html),
                "plain_text": str(plain_text),
            }
            if extra:
                record.update(dict(extra))
            temporary_path = path.with_suffix(".json.tmp")
            temporary_path.write_text(
                json.dumps(record, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_path.replace(path)
        except (OSError, TypeError, ValueError) as exc:
            self.last_error = str(exc)
            return False
        self.changed.emit()
        return True

    def update_formatting(
        self,
        row: dict[str, object],
        formatting: dict[str, object],
    ) -> bool:
        """저장된 법령에 사용자가 적용한 음영·글자색 범위를 덧붙임."""
        self.last_error = ""
        path = self.path_for_row(row)
        try:
            if not path.is_file():
                raise ValueError("법령 저장본을 찾지 못했습니다.")
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                raise ValueError("저장 파일 형식이 올바르지 않습니다.")
            spans = record.get("formatting_spans")
            if not isinstance(spans, list):
                spans = []
            spans.append(
                {
                    "start": int(formatting.get("start") or 0),
                    "end": int(formatting.get("end") or 0),
                    "mode": str(formatting.get("mode") or "background"),
                    "color": str(formatting.get("color") or "#000000"),
                }
            )
            record["formatting_spans"] = spans
            record["formatted_at"] = self._timestamp()
            temporary_path = path.with_suffix(".json.tmp")
            temporary_path.write_text(
                json.dumps(record, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_path.replace(path)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.last_error = str(exc)
            return False
        return True

    def clear_formatting_range(
        self, row: dict[str, object], start: int, end: int
    ) -> bool:
        """선택 범위의 저장 색상 서식을 제거하고 겹친 범위는 분할."""
        self.last_error = ""
        path = self.path_for_row(row)
        try:
            if not path.is_file():
                raise ValueError("법령 저장본을 찾지 못했습니다.")
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                raise ValueError("저장 파일 형식이 올바르지 않습니다.")
            spans = record.get("formatting_spans")
            if not isinstance(spans, list):
                spans = []
            remaining: list[dict[str, object]] = []
            for span in spans:
                if not isinstance(span, dict):
                    continue
                span_start = int(span.get("start") or 0)
                span_end = int(span.get("end") or 0)
                if span_end <= start or span_start >= end:
                    remaining.append(span)
                    continue
                if span_start < start:
                    left = dict(span)
                    left["end"] = start
                    remaining.append(left)
                if span_end > end:
                    right = dict(span)
                    right["start"] = end
                    remaining.append(right)
            record["formatting_spans"] = remaining
            record["formatted_at"] = self._timestamp()
            temporary_path = path.with_suffix(".json.tmp")
            temporary_path.write_text(
                json.dumps(record, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_path.replace(path)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.last_error = str(exc)
            return False
        return True

    def update_memo(
        self,
        row: dict[str, object],
        memo: dict[str, object],
    ) -> bool:
        """선택 본문 범위의 메모를 추가·수정하고 빈 내용이면 삭제."""
        self.last_error = ""
        path = self.path_for_row(row)
        try:
            if not path.is_file():
                raise ValueError("법령 저장본을 찾지 못했습니다.")
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                raise ValueError("저장 파일 형식이 올바르지 않습니다.")
            start = int(memo.get("start") or 0)
            end = int(memo.get("end") or 0)
            memos = record.get("memos")
            if not isinstance(memos, list):
                memos = []
            memos = [
                existing
                for existing in memos
                if not (
                    isinstance(existing, dict)
                    and int(existing.get("start") or 0) == start
                    and int(existing.get("end") or 0) == end
                )
            ]
            text = str(memo.get("text") or "").strip()
            if text:
                memos.append(
                    {
                        "start": start,
                        "end": end,
                        "excerpt": str(memo.get("excerpt") or ""),
                        "text": text,
                        "updated_at": self._timestamp(),
                    }
                )
            record["memos"] = memos
            temporary_path = path.with_suffix(".json.tmp")
            temporary_path.write_text(
                json.dumps(record, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_path.replace(path)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.last_error = str(exc)
            return False
        return True

    @staticmethod
    def _law_info(payload: dict) -> dict:
        law = payload.get("법령")
        if not isinstance(law, dict):
            return {}
        info = law.get("기본정보")
        return info if isinstance(info, dict) else {}

    def save(
        self,
        row: dict[str, object],
        payload: dict,
        *,
        snapshot: dict[str, object] | None = None,
    ) -> bool:
        """API 응답을 원문 JSON으로 저장하며 같은 법령은 최신 파일로 교체.

        snapshot을 주면 이미 만들어 둔 HTML·목차·3단비교 링크 등도
        함께 저장해서, 다음에 열 때 원문을 처음부터 다시 조립하지
        않고 그 화면을 바로 쓸 수 있게 한다."""
        self.last_error = ""
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.path_for_row(row)
            first_viewed_at = self._timestamp()
            previous: dict[str, object] = {}
            if path.exists():
                try:
                    loaded = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        previous = loaded
                    first_viewed_at = str(
                        previous.get("first_viewed_at") or first_viewed_at
                    )
                except (OSError, ValueError, TypeError):
                    pass

            info = self._law_info(payload)
            record = {
                "schema": 1,
                "key": self._cache_key(row),
                "first_viewed_at": first_viewed_at,
                "saved_at": self._timestamp(),
                "name": str(
                    row.get("name")
                    or json_text(info.get("법령명_한글"))
                    or "법령"
                ),
                "effective_date": str(
                    row.get("effective")
                    or json_text(info.get("시행일자"))
                    or ""
                ),
                "row": dict(row),
                "payload": payload,
            }
            # 즐겨찾기 표시나 메모처럼 다른 화면에서 관리하는 값은
            # 새로 저장할 때도 그대로 유지한다.
            for preserved_key in (
                "favorite",
                "favorite_folder",
                "favorite_order",
                "favorite_articles",
                "memos",
                "formatting_spans",
            ):
                if preserved_key in previous:
                    record[preserved_key] = previous[preserved_key]
            if snapshot:
                record.update(snapshot)
            temporary_path = path.with_suffix(".json.tmp")
            temporary_path.write_text(
                json.dumps(record, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_path.replace(path)
        except (OSError, TypeError, ValueError) as exc:
            self.last_error = str(exc)
            return False
        self.changed.emit()
        return True

    def update_snapshot(
        self,
        row: dict[str, object],
        snapshot: dict[str, object],
        *,
        remove: tuple[str, ...] = (),
    ) -> bool:
        """저장 원문은 건드리지 않고 렌더링용 부가 정보만 갱신."""
        self.last_error = ""
        path = self.path_for_row(row)
        try:
            if not path.is_file():
                return False
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                raise ValueError("저장 파일 형식이 올바르지 않습니다.")
            for key in remove:
                record.pop(str(key), None)
            record.update(dict(snapshot))
            temporary_path = path.with_suffix(".json.tmp")
            temporary_path.write_text(
                json.dumps(record, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_path.replace(path)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.last_error = str(exc)
            return False
        # 내부 렌더링 캐시가 보강됐을 뿐 즐겨찾기·열람내역의 목록은
        # 달라지지 않는다. changed를 내보내면 큰 JSON들을 전부 다시
        # 읽어 목록을 재구성하므로 여기서는 알리지 않는다.
        return True

    def set_favorite(self, row: dict[str, object], is_favorite: bool) -> bool:
        """즐겨찾기 표시를 저장 파일에 기록. 저장된 본문이 있어야 표시할 수 있음."""
        self.last_error = ""
        path = self.path_for_row(row)
        try:
            if not path.is_file():
                raise ValueError("저장된 본문이 없어 즐겨찾기를 표시할 수 없습니다.")
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                raise ValueError("저장 파일 형식이 올바르지 않습니다.")
            record["favorite"] = bool(is_favorite)
            if not is_favorite:
                record.pop("favorite_order", None)
                record.pop("favorite_folder", None)
            temporary_path = path.with_suffix(".json.tmp")
            temporary_path.write_text(
                json.dumps(record, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_path.replace(path)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.last_error = str(exc)
            return False
        self.changed.emit()
        return True

    def _read_json_cached(self, path: Path) -> dict[str, object] | None:
        """저장 JSON을 mtime·크기 기준으로 기억해 같은 파일을 반복 파싱하지 않는다."""
        try:
            if not path.is_file():
                self._snapshot_memory.pop(path, None)
                return None
            stat = path.stat()
            cached = self._snapshot_memory.get(path)
            if cached is not None and cached[:2] == (
                stat.st_mtime_ns,
                stat.st_size,
            ):
                self._snapshot_memory.move_to_end(path)
                return cached[2]
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                return None
            self._snapshot_memory[path] = (
                stat.st_mtime_ns,
                stat.st_size,
                record,
            )
            self._snapshot_memory.move_to_end(path)
            while len(self._snapshot_memory) > self._snapshot_memory_limit:
                self._snapshot_memory.popitem(last=False)
            return record
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def article_favorites(self, row: dict[str, object]) -> list[dict[str, object]]:
        """이 법령에서 조·항·호·목 단위로 걸어 둔 즐겨찾기를 돌려준다.

        조문 즐겨찾기는 따로 저장하지 않고 그 법령의 저장 파일 안에
        ``favorite_articles``로 함께 둔다. 조문만 따로 저장하면 본문이
        없어 열 수도, 현행 여부를 볼 수도 없기 때문이다.
        """
        record = self._read_json_cached(self.path_for_row(row))
        if record is None:
            return []
        return self._article_favorites(record)

    @staticmethod
    def _article_favorites(record: dict[str, object]) -> list[dict[str, object]]:
        entries = record.get("favorite_articles")
        if not isinstance(entries, list):
            return []
        cleaned: list[dict[str, object]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            jo = str(entry.get("jo") or "").strip()
            if not jo:
                continue
            normalized: dict[str, object] = {
                "jo": jo,
                "hang": str(entry.get("hang") or "").strip(),
                "ho": str(entry.get("ho") or "").strip(),
                "mok": str(entry.get("mok") or "").strip(),
                "label": str(entry.get("label") or ""),
            }
            folder = str(entry.get("favorite_folder") or "").strip()
            if folder:
                normalized["favorite_folder"] = folder
            if "favorite_order" in entry:
                try:
                    normalized["favorite_order"] = int(entry["favorite_order"])
                except (TypeError, ValueError):
                    pass
            cleaned.append(normalized)
        cleaned.sort(
            key=lambda entry: int(entry.get("favorite_order", 1_000_000_000))
        )
        return cleaned

    def set_article_favorite(
        self,
        row: dict[str, object],
        jo: str,
        label: str,
        is_favorite: bool,
        *,
        hang: str = "",
        ho: str = "",
        mok: str = "",
    ) -> bool:
        """조·항·호·목 하나를 즐겨찾기에 걸거나 뺀다.

        조문을 걸면 그 법령 자체도 즐겨찾기로 올려 둔다. 목록에 법령이
        안 보이면 그 밑에 달린 조문도 찾아갈 길이 없다.
        """
        self.last_error = ""
        jo = str(jo or "").strip()
        hang = str(hang or "").strip()
        ho = str(ho or "").strip()
        mok = str(mok or "").strip()
        if not jo:
            self.last_error = "조 번호가 없습니다."
            return False
        path = self.path_for_row(row)
        try:
            if not path.is_file():
                raise ValueError(
                    "저장된 본문이 없어 조문을 즐겨찾기에 걸 수 없습니다."
                )
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                raise ValueError("저장 파일 형식이 올바르지 않습니다.")
            entries = [
                entry
                for entry in self._article_favorites(record)
                if (
                    entry["jo"],
                    entry["hang"],
                    entry["ho"],
                    entry["mok"],
                )
                != (jo, hang, ho, mok)
            ]
            if is_favorite:
                entries.append(
                    {
                        "jo": jo,
                        "hang": hang,
                        "ho": ho,
                        "mok": mok,
                        "label": label or f"제{jo}조",
                    }
                )
                record["favorite"] = True
            if entries:
                record["favorite_articles"] = entries
            else:
                record.pop("favorite_articles", None)
            temporary_path = path.with_suffix(".json.tmp")
            temporary_path.write_text(
                json.dumps(record, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_path.replace(path)
            self._snapshot_memory.pop(path, None)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.last_error = str(exc)
            return False
        self.changed.emit()
        return True

    def is_article_favorite(
        self,
        row: dict[str, object],
        jo: str,
        *,
        hang: str = "",
        ho: str = "",
        mok: str = "",
    ) -> bool:
        jo = str(jo or "").strip()
        if not jo:
            return False
        key = (
            jo,
            str(hang or "").strip(),
            str(ho or "").strip(),
            str(mok or "").strip(),
        )
        return any(
            (
                entry["jo"],
                entry["hang"],
                entry["ho"],
                entry["mok"],
            )
            == key
            for entry in self.article_favorites(row)
        )

    def set_article_favorite_layout(
        self,
        layout: list[tuple[object, dict[str, object], str, int]],
    ) -> bool:
        """조항호목 즐겨찾기의 폴더와 표시 순서를 저장한다."""
        self.last_error = ""
        grouped: dict[str, list[tuple[dict[str, object], str, int]]] = {}
        for path, unit, folder_id, order in layout:
            grouped.setdefault(str(path), []).append(
                (dict(unit), str(folder_id or ""), int(order))
            )
        try:
            for raw_path, updates in grouped.items():
                path = Path(raw_path)
                if not path.is_file():
                    continue
                record = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(record, dict):
                    continue
                entries = self._article_favorites(record)
                locations = {
                    (
                        str(unit.get("jo") or ""),
                        str(unit.get("hang") or ""),
                        str(unit.get("ho") or ""),
                        str(unit.get("mok") or ""),
                    ): (folder_id, order)
                    for unit, folder_id, order in updates
                }
                for entry in entries:
                    key = (
                        str(entry.get("jo") or ""),
                        str(entry.get("hang") or ""),
                        str(entry.get("ho") or ""),
                        str(entry.get("mok") or ""),
                    )
                    location = locations.get(key)
                    if location is None:
                        continue
                    folder_id, order = location
                    if folder_id:
                        entry["favorite_folder"] = folder_id
                    else:
                        entry.pop("favorite_folder", None)
                    entry["favorite_order"] = order
                record["favorite_articles"] = entries
                temporary_path = path.with_suffix(".json.tmp")
                temporary_path.write_text(
                    json.dumps(record, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                temporary_path.replace(path)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.last_error = str(exc)
            return False
        return True

    def is_favorite(self, row: dict[str, object]) -> bool:
        path = self.path_for_row(row)
        try:
            if not path.is_file():
                return False
            record = json.loads(path.read_text(encoding="utf-8"))
            return bool(isinstance(record, dict) and record.get("favorite"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return False

    def list_favorites(self) -> list[dict[str, object]]:
        records = [
            record for record in self.list_records() if record.get("favorite")
        ]

        def favorite_order(record: dict[str, object]) -> int:
            try:
                return int(record.get("favorite_order"))
            except (TypeError, ValueError):
                return 1_000_000_000

        records.sort(key=favorite_order)
        return records

    def set_favorite_order(self, paths: list[object]) -> bool:
        """드래그로 정한 즐겨찾기 표시 순서를 저장 파일에 기록."""
        self.last_error = ""
        changed = False
        try:
            for order, raw_path in enumerate(paths):
                path = Path(str(raw_path)).resolve()
                if path.parent != self.directory.resolve():
                    raise ValueError("저장된 법령 폴더 밖의 파일은 정렬할 수 없습니다.")
                record = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(record, dict) or not record.get("favorite"):
                    continue
                if record.get("favorite_order") == order:
                    continue
                record["favorite_order"] = order
                temporary_path = path.with_suffix(".json.tmp")
                temporary_path.write_text(
                    json.dumps(record, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                temporary_path.replace(path)
                changed = True
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.last_error = str(exc)
            return False
        if changed:
            self.changed.emit()
        return True

    def set_favorite_layout(
        self, entries: list[tuple[object, str, int]]
    ) -> bool:
        """Persist each favorite's folder and its order inside that folder."""
        self.last_error = ""
        changed = False
        try:
            cache_directory = self.directory.resolve()
            for raw_path, folder_id, order in entries:
                path = Path(str(raw_path)).resolve()
                if path.parent != cache_directory:
                    raise ValueError(
                        "저장된 법령 폴더 밖의 파일은 정리할 수 없습니다."
                    )
                record = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(record, dict) or not record.get("favorite"):
                    continue
                normalized_folder = str(folder_id or "").strip()
                normalized_order = max(0, int(order))
                if (
                    record.get("favorite_folder") == normalized_folder
                    and record.get("favorite_order") == normalized_order
                ):
                    continue
                record["favorite_folder"] = normalized_folder
                record["favorite_order"] = normalized_order
                temporary_path = path.with_suffix(".json.tmp")
                temporary_path.write_text(
                    json.dumps(record, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                temporary_path.replace(path)
                changed = True
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.last_error = str(exc)
            return False
        if changed:
            self.changed.emit()
        return True

    def list_records(self) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        self.last_error = ""
        try:
            paths = list(self.directory.glob("*.json"))
        except OSError as exc:
            self.last_error = str(exc)
            return records
        for path in paths:
            record = self.load(path)
            if record is not None:
                records.append(record)
        records.sort(
            key=lambda item: str(item.get("saved_at") or ""), reverse=True
        )
        return records

    def load(self, path: Path | str) -> dict[str, object] | None:
        self.last_error = ""
        try:
            resolved = Path(path).resolve()
            if resolved.parent != self.directory.resolve():
                raise ValueError("저장된 법령 폴더 밖의 파일은 열 수 없습니다.")
            record = json.loads(resolved.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                raise ValueError("저장 파일 형식이 올바르지 않습니다.")
            if record.get("kind") == "detail_snapshot":
                if not isinstance(record.get("row"), dict) or not isinstance(
                    record.get("html"), str
                ):
                    raise ValueError("저장 파일에 본문 화면이 없습니다.")
                record["path"] = str(resolved)
                return record
            if not isinstance(record.get("row"), dict) or not isinstance(
                record.get("payload"), dict
            ):
                raise ValueError("저장 파일에 법령 본문이 없습니다.")
            record["path"] = str(resolved)
            return record
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            self.last_error = str(exc)
            return None
