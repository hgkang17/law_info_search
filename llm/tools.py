"""Gemini가 직접 부르는 법제처 검색 도구.

molit_cgm_expc_api.py가 이미 갖고 있는 국가법령정보 API 호출을 그대로
쓴다. 새로 짠 것은 이 얇은 겉껍질뿐이다 — 함수 시그니처와 docstring이
곧 Gemini가 읽는 도구 설명이라, 모델이 무엇을 언제 불러야 하는지 여기
적힌 문장으로 판단한다.

이 도구들이 있어야 "본문에 없으면 추측하지 않는다"는 약속이 성립한다.
도구 없이 대화만 시키면 모델이 훈련 데이터로 외운 조문을 그대로 답할 수
있는데, 그건 최신판이 아닐 수도 있고 애초에 틀렸을 수도 있다. 도구를
강제로 거치게 하면 화면에 뜨는 실제 법제처 자료를 근거로만 답한다.
"""

import functools
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

# 이 파일에는 일부러 `from __future__ import annotations`를 쓰지 않는다.
# 여기 있는 도구 함수의 타입 힌트와 독스트링을 그대로 읽어 Gemini에게
# 넘길 함수 선언을 만든다(gemini_rest.function_declarations). 실제 타입
# 객체(str, int)로 두어야 그 스키마가 어긋날 일이 없다. 예전에 SDK를
# 쓸 때도 같은 이유로 예외였다.

import re

import molit_cgm_expc_api as api
from models.law import RESOURCE_CATEGORIES
from storage.paths import AI_TOOL_BODY_CACHE_DIR, AI_TOOL_SEARCH_CACHE_DIR
from utils.three_stage import compact_three_stage
from utils.old_new import compact_old_new_xml
from utils.annex_notation import annex_hint_in_query, row_matches_annex_hint
from utils.annex_parse import (
    is_download_notice_only,
    kordoc_missing_message,
    parse_annex_bytes,
)
from utils.formatting import full_law_url
from utils.law_download import download_law_file
from utils.parsing import (
    article_jo_label,
    document_plain_text,
    extract_law_article,
    json_text,
    law_article_index,
    law_article_text,
    normalize_admin_rule_text,
    normalize_article_jo,
)

from .addendum import extract_transition_excerpts
from .abolished import (
    detect_abolished_admin_rule,
    extract_abolition_reason,
    format_abolished_admin_rule,
    format_abolished_law_note,
    format_renamed_admin_rule,
    parse_abolished_laws,
    parse_admin_rule_history,
)
from .cite_check import run_cite_check
from .document_labels import persist_document_label
from .impact_map import run_impact_map
from .law_aliases import expand_search_queries, has_related_hit, score_law_relevance
from .ordinance_radar import run_ordinance_radar
from .case_sources import resolve_case_source
from .inquiries import inquiry_title_score, resolve_inquiry_agencies
from .tool_cache import BODY_TTL_SECONDS, SEARCH_TTL_SECONDS, ToolCache

# 답 하나를 만드는 동안 모델은 같은 조문을 여러 번 다시 읽는다. 게다가
# Claude는 질문마다 MCP 서버를 새로 띄우므로 파일로 이어 두어야 다음
# 질문에서도 쓸 수 있다.
_SEARCH_CACHE = ToolCache(AI_TOOL_SEARCH_CACHE_DIR, SEARCH_TTL_SECONDS)
_BODY_CACHE = ToolCache(AI_TOOL_BODY_CACHE_DIR, BODY_TTL_SECONDS)

_SEARCH_ID_LINE = re.compile(r"^- (?:\[[^\]]+\]\s*)?(.+?) \(id=([^,)]+)")
_SEARCH_SHORT_NAME = re.compile(r"약칭=([^,)]+)")


def _remember_names(text: str, id_to_name: dict[str, str]) -> None:
    """담아 둔 검색 결과에서 id와 이름의 짝을 되살린다.

    "이 법령 즐겨찾기에 추가" 단추에 법령 이름을 넣으려면 id마다 이름이
    있어야 한다. 검색을 캐시로 건너뛰면 그 짝이 비어 단추에 숫자 id만
    남는다.
    """
    for line in text.splitlines():
        matched = _SEARCH_ID_LINE.match(line)
        if not matched:
            continue
        name = matched.group(1).strip()
        item_id = matched.group(2).strip()
        id_to_name[item_id] = name
        short = ""
        short_match = _SEARCH_SHORT_NAME.search(line)
        if short_match:
            short = short_match.group(1).strip()
        persist_document_label(item_id, name, short)

# 검색 대상 셋. 별표·서식(licbyl 등)은 첨부물이라 본문 검토용 도구에서는
# 뺀다. 필요하면 나중에 따로 도구를 만든다.
_SEARCHABLE = ("law", "admrul", "ordin")
_ANNEX_CATEGORIES = ("licbyl", "admbyl", "ordinbyl")

_NOT_FOUND_MARK = "[NOT_FOUND]"

# Gemini 자동 함수 호출의 한도. 법률·시행령·지침·해석례를 이어서 읽으려면
# 여유 칸이 필요하다. Claude/Codex는 이 값을 쓰지 않는다.
MAX_TOOL_CALLS_PER_TURN = 20

# 도구가 돌려주는 본문 하나의 최대 글자 수. 법령 전체를 그대로 넘기면
# 토큰이 순식간에 불어나므로 자른다. 잘렸다는 사실도 함께 알려서 모델이
# "이게 전부"라고 오해하지 않게 한다.
_MAX_RESULT_CHARS = 12000
_SEARCH_DISPLAY = 20
# 본문 검색은 가나다순 수십 건이 정상이다. 20이면 ㅈ·ㅎ로 시작하는
# 법령은 창 밖으로 잘린다. 화면 검색과 같이 100건을 받는다.
_BODY_SEARCH_DISPLAY = 100

# 화면 저장내역과 같은 본문을 쓴다. 테스트가 실제 사용자 폴더를
# 더럽히지 않도록 이 함수를 바꿔 끼울 수 있다.
_document_cache = None


def _get_document_cache():
    global _document_cache
    if _document_cache is not None:
        return _document_cache
    from storage.cache import LawDocumentCache
    from storage.paths import LAW_CACHE_DIR

    _document_cache = LawDocumentCache(LAW_CACHE_DIR)
    return _document_cache


def _cache_row(category: str, item_id: str, name: str = "") -> dict:
    meta = RESOURCE_CATEGORIES[category]
    return {
        "target": category,
        "label": meta["label"],
        "id": str(item_id),
        "name": name,
        "related": "",
        "organization": "",
        "date": "",
        "number": "",
        "effective": "",
        "raw": {},
    }


def _enrich_row(row: dict, payload: dict, category: str) -> dict:
    """저장내역 목록에 법령명이 비지 않도록 API 기본정보를 채운다."""
    row = dict(row)
    if category == "law":
        law = payload.get("법령", payload)
        info = law.get("기본정보") if isinstance(law, dict) else {}
        if isinstance(info, dict):
            row["name"] = row.get("name") or json_text(
                info.get("법령명_한글") or info.get("법령명한글")
            )
            row["short_name"] = row.get("short_name") or json_text(
                info.get("법령약칭명")
            )
            row["effective"] = json_text(info.get("시행일자"))
            row["date"] = json_text(info.get("공포일자"))
            row["number"] = json_text(info.get("공포번호"))
            row["organization"] = json_text(
                info.get("소관부처") or info.get("소관부처명")
            )
    elif category == "admrul":
        service = payload.get("AdmRulService", payload)
        info = (
            service.get("행정규칙기본정보") if isinstance(service, dict) else {}
        )
        if isinstance(info, dict):
            row["name"] = row.get("name") or json_text(info.get("행정규칙명"))
            row["effective"] = json_text(info.get("시행일자"))
            row["date"] = json_text(info.get("발령일자"))
            row["number"] = json_text(info.get("발령번호"))
            row["organization"] = json_text(info.get("소관부처명"))
            row["raw"] = dict(info)
    elif category == "ordin":
        service = payload.get("LawService", payload)
        info = (
            service.get("자치법규기본정보") if isinstance(service, dict) else {}
        )
        if isinstance(info, dict):
            row["name"] = row.get("name") or json_text(info.get("자치법규명"))
            row["effective"] = json_text(info.get("시행일자"))
            row["date"] = json_text(info.get("공포일자"))
            row["number"] = json_text(info.get("공포번호"))
            row["organization"] = json_text(info.get("지자체기관명"))
    return row


def _load_saved_record(cache, row: dict, category: str):
    if category == "law":
        record = cache.load_for_row(row)
        if isinstance(record, dict) and isinstance(record.get("payload"), dict):
            return record
        return None
    record = cache.load_snapshot(row)
    return record if isinstance(record, dict) else None


def _payload_from_record(record: dict, category: str):
    if category == "law":
        payload = record.get("payload")
        return payload if isinstance(payload, dict) else None
    payload = record.get("detail_payload")
    return payload if isinstance(payload, dict) else None


def _plain_from_record(record: dict, category: str) -> str:
    payload = _payload_from_record(record, category)
    if payload is not None:
        return document_plain_text(payload, category)
    if category == "admrul":
        sections = record.get("administrative_rule_sections")
        if isinstance(sections, list):
            parts = []
            for section in sections:
                if not isinstance(section, dict):
                    continue
                value = str(section.get("value") or "").strip()
                if value:
                    parts.append(normalize_admin_rule_text(value))
            if parts:
                return "\n\n".join(parts)
    return str(record.get("plain_text") or "")


def _save_fetched_document(cache, row: dict, payload: dict, category: str) -> dict:
    """화면의 본문 저장과 같은 자리에, 같은 형식으로 남긴다."""
    row = _enrich_row(row, payload, category)
    if category == "law":
        cache.save(row, payload)
        return row
    extra = {"detail_payload": payload}
    if category == "admrul":
        from ui.assets import ADMIN_RULE_PARSE_VERSION

        service = payload.get("AdmRulService", payload)
        sections = []
        if isinstance(service, dict):
            body = normalize_admin_rule_text(json_text(service.get("조문내용")))
            if body:
                sections.append({"label": "조문", "value": body})
            appendix = normalize_admin_rule_text(json_text(service.get("부칙")))
            if appendix:
                sections.append({"label": "부칙", "value": appendix})
        extra["administrative_rule_parse_version"] = ADMIN_RULE_PARSE_VERSION
        extra["administrative_rule_sections"] = sections
    cache.save_snapshot(
        row,
        html="",
        plain_text=document_plain_text(payload, category),
        extra=extra,
    )
    return row


def _category_meta(category: str) -> dict:
    meta = RESOURCE_CATEGORIES.get(category)
    if meta is None or category not in _SEARCHABLE:
        raise ValueError(
            f"'{category}'는 검색할 수 없습니다. law, admrul, ordin 중 하나를 쓰세요."
        )
    return meta


def _annex_meta(category: str) -> dict:
    meta = RESOURCE_CATEGORIES.get(category)
    if meta is None or category not in _ANNEX_CATEGORIES:
        raise ValueError(
            f"'{category}'는 별표·서식 검색에 사용할 수 없습니다. "
            "licbyl, admbyl, ordinbyl 중 하나를 쓰세요."
        )
    return meta


def _as_list(value: object) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _not_found_message(query: str, label: str) -> str:
    return (
        f"{_NOT_FOUND_MARK} '{query}'({label})로 법제처에서 확인되지 "
        "않습니다. 추측하지 마세요. 정확한 법령명이나 핵심 단어로 "
        "다시 찾으세요."
    )


def _row_status_label(row: dict) -> str:
    status = json_text(
        row.get("현행연혁코드") or row.get("현행연혁구분")
    )
    if status == "현행":
        return "[현행] "
    if status == "연혁":
        return "[연혁] "
    return ""


def _sort_search_rows(rows: list, query: str = "", meta=None) -> list:
    name_field = (meta or {}).get("name", "")

    def rank(row: dict) -> tuple:
        status = json_text(
            row.get("현행연혁코드") or row.get("현행연혁구분")
        )
        if status == "현행":
            status_rank = 0
        elif status == "연혁":
            status_rank = 1
        else:
            status_rank = 2
        name = json_text(row.get(name_field, "")) if name_field else ""
        relevance = -score_law_relevance(name, query) if query else 0
        return (status_rank, relevance)

    return sorted(rows, key=rank)


def _row_name_pairs(rows: list, meta: dict) -> list:
    pairs = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pairs.append(
            (
                json_text(row.get(meta["name"], "")),
                json_text(
                    row.get("법령약칭명") or row.get("자치법규약칭명") or ""
                ),
            )
        )
    return pairs


def _truncate(text: str) -> str:
    if len(text) <= _MAX_RESULT_CHARS:
        return text
    return text[:_MAX_RESULT_CHARS] + f"\n\n[본문이 길어 {_MAX_RESULT_CHARS}자에서 잘림]"


def _keyword_excerpt(text: str, keyword: str) -> str:
    """긴 문서에서 키워드 주변을 겹치지 않게 모아 도구 한도 안에 담는다."""
    needle = " ".join(str(keyword or "").split()).strip()
    if not needle:
        return _truncate(text)
    positions = [matched.start() for matched in re.finditer(re.escape(needle), text)]
    if not positions:
        return _truncate(text) + f"\n\n[키워드 '{needle}'의 정확한 일치 없음]"
    windows: list[tuple[int, int]] = []
    for position in positions[:20]:
        start = max(0, position - 900)
        end = min(len(text), position + len(needle) + 1500)
        if windows and start <= windows[-1][1]:
            windows[-1] = (windows[-1][0], max(windows[-1][1], end))
        else:
            windows.append((start, end))
    excerpts = [text[start:end] for start, end in windows]
    return _truncate("\n\n[관련 부분]\n".join(excerpts))


def _safe(func: Callable) -> Callable:
    """도구 함수가 예외를 던지지 않고 실패도 글로 돌려주게 감싼다.

    Gemini SDK의 자동 함수 호출은 파이썬 함수가 예외를 던졌을 때를
    문서화해 두지 않았다. 여기서 잡아 두면 국토부 API가 잠깐 죽거나
    OC 키가 틀려도 대화 전체가 끊기지 않고, 모델이 "검색에 실패했다"고
    사용자에게 그대로 알려 줄 수 있다.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as error:  # noqa: BLE001 - 모델에게 그대로 보여 준다.
            return f"도구 실행 중 오류가 났습니다: {error}"

    return wrapper


def _xml_local(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _case_source_meta(source: str) -> dict:
    return resolve_case_source(source)


def build_tools(
    oc_key: str,
    on_document_used: Callable[[str, str, str], None] | None = None,
    law_cache=None,
) -> tuple[Callable, ...]:
    """국토부 OC 인증키를 감춘 도구 함수들을 만든다.

    Gemini에 넘기는 함수는 모델이 스스로 채울 수 있는 인자만 받아야
    한다. 인증키처럼 사용자가 이미 입력해 둔 값은 클로저로 미리 묶어서
    모델이 볼 필요도, 볼 수도 없게 한다.

    on_document_used: 모델이 실제로 조문ㆍ본문을 읽었을 때
        (category, item_id, name)로 알려 준다. 검색 결과 후보는 여러 개일
        수 있어 신호로 삼기 약하지만, get_article/get_document을 부르는
        것은 모델이 그 문서로 확정했다는 뜻이라 화면의 "이 법령
        즐겨찾기에 추가" 단추를 여기서 채운다.
    law_cache: 화면의 저장내역. 없으면 같은 폴더의 저장내역을 연다.
    """
    id_to_name: dict[str, str] = {}
    documents = law_cache if law_cache is not None else _get_document_cache()

    def _search_rows(
        query: str, category: str, *, search_scope: int = 1
    ) -> tuple[dict, list]:
        meta = RESOURCE_CATEGORIES[category]
        # 화면 검색과 같이 분류 키를 API target으로 쓴다. group(law 등)을
        # 쓰면 별표 검색이 법령 목록을 받아 결과가 비게 된다.
        data = api.search_resource(
            oc_key,
            category,
            query,
            search_scope=search_scope,
            display=(
                _BODY_SEARCH_DISPLAY if search_scope == 2 else _SEARCH_DISPLAY
            ),
        )
        return meta, _as_list(data.get(meta["root"], {}).get(meta["item"]))

    def _abolished_search_note(query: str, category: str) -> str:
        """현행 0건이면 연혁에서 폐지·후속 규정만 안내한다. 실패해도 검색을 막지 않는다."""
        try:
            if category == "law":
                data = api.search_resource(
                    oc_key, "eflaw", query, display=50
                )
                return format_abolished_law_note(
                    query, parse_abolished_laws(data, query)
                )
            if category != "admrul":
                return ""
            data = api.search_resource(
                oc_key, "admrul", query, display=50, nw="2"
            )
            hits = parse_admin_rule_history(data)
            detected = detect_abolished_admin_rule(query, hits)
            if detected is None:
                return ""
            kind, group = detected
            if kind == "renamed":
                return format_renamed_admin_rule(query, group)
            reason = ""
            item_id = group[-1].get("seq") or ""
            if item_id:
                try:
                    payload = api.get_resource_detail(
                        oc_key, "admrul", item_id
                    )
                    reason = extract_abolition_reason(payload)
                except Exception:
                    reason = ""
            return format_abolished_admin_rule(query, group, reason)
        except Exception:
            return ""

    def _format_search_rows(
        query: str, category: str, meta: dict, rows: list
    ) -> str:
        if not rows:
            note = _abolished_search_note(query, category)
            if note:
                return note
            return _not_found_message(query, meta["label"])
        rows = _sort_search_rows(rows, query, meta)
        lines = [f"[{meta['label']}] '{query}' 검색 결과 {len(rows)}건:"]
        effective_field = meta.get("effective", "")
        for row in rows:
            name = json_text(row.get(meta["name"], ""))
            item_id = json_text(row.get(meta["id"], ""))
            short_name = json_text(
                row.get("법령약칭명") or row.get("자치법규약칭명") or ""
            )
            if item_id:
                id_to_name[str(item_id)] = str(name)
                persist_document_label(item_id, name, short_name)
            effective = (
                json_text(row.get(effective_field, "")) if effective_field else ""
            )
            extra = f"id={item_id}"
            if short_name:
                extra += f", 약칭={short_name}"
            if effective:
                extra += f", 시행일={effective}"
            related_field = meta.get("related", "")
            if related_field:
                related = json_text(row.get(related_field, ""))
                if related:
                    extra += f", 관련={related}"
            status = _row_status_label(row)
            lines.append(f"- {status}{name} ({extra})")
        if category == "law":
            lines.append(
                "\n다음 행동: 위 id 중 사용자가 물은 법령과 같은 것을 "
                "하나 고르고, 같은 이름으로 또 찾지 말고 바로 get_article을 "
                "불러라. 조 번호는 6자리다. 제8조 → 000800, 제12조의2 → "
                "001202."
            )
        elif category in _SEARCHABLE:
            lines.append(
                "\n다음 행동: 위 id 중 하나를 골라 get_document를 불러라. "
                "긴 문서는 keyword에 핵심어를 넣어라."
            )
        elif category in _ANNEX_CATEGORIES:
            lines.append(
                "\n주의: 별표·서식 API는 목록과 파일 링크만 준다. 제출서류 "
                "요건은 관련 법령·행정규칙 본문에서도 확인하라."
            )
        return "\n".join(lines)

    def _notify(category: str, item_id: str) -> None:
        if on_document_used is None:
            return
        try:
            on_document_used(category, item_id, id_to_name.get(item_id, item_id))
        except Exception:
            # 이 콜백은 화면에 단추를 만들어 줄 뿐인 부가 기능이다. 여기서
            # 나는 오류로 모델의 답변 자체를 막으면 안 된다.
            pass

    def search_law(
        query: str, category: str = "law", search_scope: int = 1
    ) -> str:
        """법제처 국가법령정보에서 이름이나 키워드로 문서를 찾는다.

        법령을 검토해 달라는 요청을 받으면 답하기 전에 반드시 이 도구로
        먼저 찾아라. 정확한 이름으로 찾히지 않으면 search_scope=2로
        본문을 검색하거나, 핵심 단어만 남기고 다시 시도해라
        (예: "간척지의 농업적 이용에 관한 특별법"이 안 나오면 "간척지"로
        다시 찾는다 — 법령명이 개정으로 바뀌었을 수 있다).
        현행이 0건이면 폐지·후속 규정이 있는지 연혁도 본다.

        Args:
            query: 검색할 법령ㆍ행정규칙ㆍ자치법규 이름 또는 키워드.
            category: "law"(법령, 기본값) | "admrul"(행정규칙) |
                "ordin"(자치법규).
            search_scope: 1=문서명(기본값), 2=본문 키워드. 업무 용어로
                찾을 때는 2를 쓴다.
        """
        if search_scope not in (1, 2):
            raise ValueError("search_scope는 1(문서명) 또는 2(본문)여야 합니다.")
        meta = _category_meta(category)
        cache_key = (
            f"search:{category}:{search_scope}:{' '.join(query.split()).casefold()}"
        )
        cached = _SEARCH_CACHE.load(cache_key)
        if cached is not None:
            _remember_names(cached, id_to_name)
            return cached
        used_query = query
        rows = []
        meta = _category_meta(category)
        for candidate in expand_search_queries(query):
            meta, candidate_rows = _search_rows(
                candidate, category, search_scope=search_scope
            )
            names = _row_name_pairs(candidate_rows, meta)
            if not candidate_rows:
                continue
            # 본문 검색은 법령명에 없는 업무 용어로 찾는다. 이름 필터를
            # 그대로 걸면 법제처가 준 결과를 전부 버린다.
            if (
                search_scope == 2
                or has_related_hit(query, names)
                or has_related_hit(candidate, names)
            ):
                rows = candidate_rows
                used_query = candidate
                break
        result = _format_search_rows(query, category, meta, rows)
        if rows and used_query != query:
            result = f"(검색어 '{query}' → '{used_query}')\n" + result
        _SEARCH_CACHE.save(cache_key, result)
        return result

    def search_admin_rule(query: str, search_scope: int = 1) -> str:
        """법제처에서 훈령·예규·고시·지침 등 행정규칙을 찾는다.

        업무절차, 제출서류, 세부기준, 수립지침 질문에는 법률 검색만으로
        끝내지 말고 이 도구도 사용한다. 반환된 id는 get_document에
        category="admrul"과 함께 넘겨 실제 본문을 읽는다.

        Args:
            query: 행정규칙명 또는 업무·지침 키워드.
            search_scope: 1=규칙명(기본값), 2=본문 키워드.
        """
        return search_law(query, category="admrul", search_scope=search_scope)

    def _ensure_document(category: str, item_id: str):
        """저장본이 있으면 그대로 쓰고, 없으면 화면과 같은 본문 API로
        받아 저장내역에 남긴 뒤 돌려준다."""
        cache = documents
        row = _cache_row(category, item_id, id_to_name.get(str(item_id), ""))
        record = _load_saved_record(cache, row, category)
        if record is not None:
            payload = _payload_from_record(record, category)
            saved_name = str(record.get("name") or row.get("name") or "")
            saved_row = record.get("row")
            saved_short = str(row.get("short_name") or "")
            if isinstance(saved_row, dict):
                saved_short = saved_short or str(saved_row.get("short_name") or "")
            if saved_name:
                id_to_name[str(item_id)] = saved_name
                row["name"] = saved_name
                persist_document_label(item_id, saved_name, saved_short)
            if payload is not None or _plain_from_record(record, category):
                return row, record, payload
        meta = _category_meta(category)
        payload = api.get_resource_detail(
            oc_key,
            meta["detail_target"],
            item_id,
            id_param=meta.get("id_param", "ID"),
        )
        if not isinstance(payload, dict):
            raise ValueError("본문 응답 형식이 올바르지 않습니다.")
        row = _save_fetched_document(cache, row, payload, category)
        if row.get("name"):
            id_to_name[str(item_id)] = str(row["name"])
            persist_document_label(
                item_id,
                str(row["name"]),
                str(row.get("short_name") or ""),
            )
        return row, None, payload

    def _saved_payload(category: str, item_id: str):
        """저장내역만 본다. 없으면 본문 API를 치지 않는다."""
        row = _cache_row(category, item_id, id_to_name.get(str(item_id), ""))
        record = _load_saved_record(documents, row, category)
        if record is None:
            return None
        saved_name = str(record.get("name") or row.get("name") or "")
        saved_row = record.get("row")
        saved_short = ""
        if isinstance(saved_row, dict):
            saved_short = str(saved_row.get("short_name") or "")
        if saved_name:
            id_to_name[str(item_id)] = saved_name
            persist_document_label(item_id, saved_name, saved_short)
        return _payload_from_record(record, category)

    def get_article(law_id: str, jo: str, hang: str = "", ho: str = "") -> str:
        """특정 조문만 읽는다. 법령에만 쓴다.

        화면의 조항호목 팝업과 같은 API로 그 조만 가져온다.
        이미 저장해 둔 전문에 해당 조가 있으면 API 없이 그 조를 쓴다.
        인용 조문 스냅샷까지 따로 뒤지지는 않는다. 전문 저장본만 보면
        되고, 없으면 조 하나 API가 전문을 받는 것보다 적다.
        조 하나 읽으려고 법령 전문을 받아 자르지 않는다.
        행정규칙ㆍ자치법규는 get_document를 대신 쓴다.

        Args:
            law_id: search_law가 돌려준 법령ID (id= 뒤의 값).
            jo: 조 번호 6자리. 제8조 → "000800", 제12조의2 → "001202".
                "0008", "8", "12의2"처럼 적어도 자동으로 맞춘다.
            hang: 항 번호. 안 정했으면 비워 둔다.
            ho: 호 번호. 안 정했으면 비워 둔다.
        """
        jo_code = normalize_article_jo(jo)
        payload = _saved_payload("law", law_id)
        text = (
            extract_law_article(payload, jo_code, hang, ho) if payload else ""
        )
        if not text:
            text = _read_josub_article(law_id, jo_code, hang, ho)
        if not text:
            return (
                f"법령ID {law_id}의 {article_jo_label(jo_code)}를 "
                "찾지 못했습니다. 이 값은 법령 검색의 법령ID여야 합니다. "
                "행정규칙 검색의 id이면 get_document를 쓰십시오."
            )
        _notify("law", law_id)
        return _truncate(text)

    def _read_josub_article(
        law_id: str, jo_code: str, hang: str, ho: str
    ) -> str:
        data = api.get_law_article(oc_key, law_id, jo_code, hang=hang, ho=ho)
        text = extract_law_article(data, jo_code, hang, ho)
        if text:
            return text
        if not isinstance(data, dict):
            return ""
        law = data.get("법령", data)
        if not isinstance(law, dict):
            return ""
        units = law.get("조문", {})
        units = units.get("조문단위") if isinstance(units, dict) else units
        return law_article_text(units)

    def get_document(
        item_id: str, category: str = "law", keyword: str = ""
    ) -> str:
        """저장된 법령ㆍ행정규칙ㆍ자치법규 본문을 평문으로 가져온다.

        저장본이 있으면 그 본문을 읽고, 없으면 화면의 본문 조회와 같은
        API로 받아 저장한 뒤 읽는다. 특정 조문 하나만 필요하면 법령은
        get_article이 더 적다. 긴 지침은 반드시 keyword에 핵심어를 넣어
        관련 부분만 읽는다.

        Args:
            item_id: search_law가 돌려준 id 값.
            category: "law" | "admrul" | "ordin".
            keyword: 긴 문서에서 찾을 핵심어. 법령에서 비우면 조문 목차를
                반환한다. 행정규칙은 앞부분만 반환하므로 핵심어를 넣는
                편이 정확하다.
        """
        _category_meta(category)
        normalized_keyword = " ".join(keyword.split()).casefold()
        _row, record, payload = _ensure_document(category, item_id)
        _notify(category, item_id)
        if payload is None and record is not None:
            data_plain = _plain_from_record(record, category)
            if category == "law" and not normalized_keyword:
                result = _truncate(data_plain)
            else:
                result = _keyword_excerpt(data_plain, keyword)
            return result
        if not isinstance(payload, dict):
            raise ValueError("본문을 찾지 못했습니다.")
        if category == "law" and not normalized_keyword:
            index = law_article_index(payload)
            law = payload.get("법령", payload)
            header = ""
            if isinstance(law, dict):
                info = law.get("기본정보")
                if isinstance(info, dict):
                    header = json_text(
                        info.get("법령명_한글") or info.get("법령명한글")
                    )
                    effective = json_text(info.get("시행일자"))
                    if header and effective:
                        header = f"{header} (시행 {effective})"
            if index:
                return _truncate(
                    f"{header}\n\n[조문 목차]\n{index}\n\n"
                    "특정 조문은 get_article로 읽고, 본문에서 찾으려면 "
                    "keyword를 넣어 get_document를 다시 부르십시오."
                )
            return _truncate(document_plain_text(payload, category))
        return _keyword_excerpt(
            document_plain_text(payload, category), keyword
        )

    def get_annexes(
        query: str, category: str = "all", search_scope: int = 2
    ) -> str:
        """법령·행정규칙·자치법규의 별표·별지서식을 검색하고, 한 건으로
        좁혀지면 원문 파일을 Markdown으로 추출한다.

        신청서, 입안서류, 구비서류, 제출서류, 수수료표, 처리기준을 묻는
        질문에는 본문 검색만으로 끝내지 말고 이 도구도 사용한다.
        쿼리에 '별표 4'처럼 번호를 넣으면 그 항목만 고른다.

        Args:
            query: 관련 법령명·행정규칙명 또는 별표·서식명.
            category: "all"(기본값) | "licbyl"(법령) |
                "admbyl"(행정규칙) | "ordinbyl"(자치법규).
            search_scope: 1=별표·서식명, 2=관련 법령·규칙명, 3=별표 본문.
        """
        if search_scope not in (1, 2, 3):
            raise ValueError("search_scope는 1, 2, 3 중 하나여야 합니다.")
        categories = _ANNEX_CATEGORIES if category == "all" else (category,)
        for item in categories:
            _annex_meta(item)

        sections: list[str] = []
        candidates: list[tuple[dict, dict]] = []
        hint = annex_hint_in_query(query)
        for item in categories:
            meta, rows = _search_rows(query, item, search_scope=search_scope)
            if not rows:
                continue
            if hint:
                rows = [
                    row
                    for row in rows
                    if isinstance(row, dict)
                    and row_matches_annex_hint(row, hint)
                ]
            if not rows:
                continue
            lines = [f"[{meta['label']}] {len(rows)}건"]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                candidates.append((meta, row))
                name = json_text(row.get(meta["name"], ""))
                item_id = json_text(row.get(meta["id"], ""))
                related_field = meta.get("related", "")
                related = json_text(row.get(related_field, "")) if related_field else ""
                organization = json_text(row.get(meta.get("organization", ""), ""))
                details = [f"id={item_id}"]
                if related:
                    details.append(f"관련={related}")
                if organization:
                    details.append(f"기관={organization}")
                lines.append(f"- {name} ({', '.join(details)})")
                if item_id:
                    lines.append(
                        f"  인용: [{name}](doc:{item}:{item_id})"
                    )
            sections.append("\n".join(lines))
        if not sections:
            return (
                f"'{query}'과 관련된 별표·서식을 찾지 못했습니다. "
                "정확한 법령명으로 search_scope=2를 쓰거나, 서식명으로 "
                "search_scope=1을 사용해 다시 확인하세요."
            )
        listing = "\n\n".join(sections)
        if len(candidates) != 1:
            return listing + (
                "\n\n다음 행동: 별표 번호나 서식명을 더 좁혀 이 도구를 "
                "다시 부르면 원문 Markdown을 추출합니다. 여러 건이면 "
                "목록만 반환합니다."
            )
        _meta, row = candidates[0]
        title = json_text(row.get(_meta["name"], "")) or "별표·서식"
        file_url = full_law_url(row.get("별표서식파일링크"))
        pdf_url = full_law_url(row.get("별표서식PDF파일링크"))
        url = file_url or pdf_url
        if not url:
            return listing + (
                "\n\n주의: 이 항목의 파일 링크가 없습니다. 화면의 별표 "
                "탭에서 원문을 여세요."
            )
        try:
            data = download_law_file(url)
        except Exception as error:  # noqa: BLE001 - 목록은 이미 있으므로 본문만 포기한다.
            return listing + f"\n\n원문 다운로드 실패: {error}\n파일: {url}"
        parsed = parse_annex_bytes(data)
        if parsed.is_image_based:
            return listing + (
                f"\n\n[{title}]\n이미지 기반 PDF"
                f"({parsed.page_count or '?'}페이지)라 텍스트를 뽑지 "
                f"못했습니다. 원문: {url}"
            )
        if not parsed.success or not parsed.markdown:
            return listing + (
                f"\n\n[{title}] 텍스트 추출 실패: "
                f"{parsed.error or kordoc_missing_message()}\n원문: {url}"
            )
        if is_download_notice_only(parsed.markdown):
            return listing + (
                f"\n\n[{title}]\n파일에 본문이 없고 다운로드 안내만 "
                "있습니다. 이 응답을 근거로 별표 내용을 서술하지 마세요.\n"
                f"원문: {url}"
            )
        return listing + "\n\n" + _truncate(f"[{title}]\n{parsed.markdown}")

    def legal_research(query: str, include_local_rules: bool = False) -> str:
        """복합 법률 질문을 법령·행정규칙·별표 검색으로 나누어 조사한다.

        단일 조문 조회가 아니라 절차, 제출서류, 허가요건, 입안자료,
        업무기준처럼 여러 근거가 필요한 질문에 사용한다. 결과에서 관련성이
        높은 법령과 행정규칙을 골라 get_article/get_document로 실제 본문을
        반드시 읽는다.

        Args:
            query: 사용자의 원래 질문 또는 핵심 업무명.
            include_local_rules: 지자체 조례·규칙과 별표도 함께 검색할지 여부.
        """
        normalized = " ".join(str(query or "").split()).strip()
        if not normalized:
            raise ValueError("query가 비어 있습니다.")

        # 질문형 꼬리말과 요청 표현은 법령명 검색을 방해한다. 원문도
        # 유지하되 핵심어 검색을 함께 수행해 누락을 줄인다.
        core = re.sub(
            r"(?:좀|조금)?\s*(?:찾아|알려|확인|정리|검토)"
            r"(?:줘|주라|주세요|해줘)?[.!?]*$",
            "",
            normalized,
        ).strip()
        core = re.sub(r"(?:에\s*)?(?:필요한|관련된|관한)\s*", " ", core).strip()
        core = re.sub(
            r"(?:입안|신청|제출|구비)?\s*(?:서류|서식|자료|목록)$", "", core
        ).strip()
        expanded = expand_search_queries(core or normalized)
        terms = list(
            dict.fromkeys(
                term for term in (*expanded[:4], normalized) if term
            )
        )
        if not terms:
            terms = [normalized]

        jobs: list[tuple[str, str, int]] = []
        for term in terms[:3]:
            jobs.extend((("law", term, 1), ("admrul", term, 1)))
            jobs.extend((("licbyl", term, 2), ("admbyl", term, 2)))
            if include_local_rules:
                jobs.extend((("ordin", term, 1), ("ordinbyl", term, 2)))
        # 업무 용어는 법령명에 안 걸릴 때가 많다. 핵심어로 본문도 한 번 찾는다.
        if core:
            jobs.extend((("law", core, 2), ("admrul", core, 2)))

        findings: dict[tuple[str, str, int], tuple[dict, list] | str] = {}
        with ThreadPoolExecutor(max_workers=min(8, len(jobs))) as executor:
            future_map = {
                executor.submit(
                    _search_rows, term, category, search_scope=scope
                ): (category, term, scope)
                for category, term, scope in jobs
            }
            for future in as_completed(future_map):
                key = future_map[future]
                try:
                    findings[key] = future.result()
                except Exception as error:  # 한 출처 실패가 전체 조사를 막지 않는다.
                    findings[key] = f"조회 실패: {error}"

        sections = [f"[복합 법령 리서치] {normalized}"]
        seen: set[tuple[str, str]] = set()
        hit_categories: set[str] = set()
        for category, term, scope in jobs:
            found = findings[(category, term, scope)]
            if isinstance(found, str):
                sections.append(f"- {category}/{term}: {found}")
                continue
            meta, rows = found
            fresh_rows = []
            for row in rows:
                identity = (
                    category,
                    str(row.get(meta["id"], "") or row.get(meta["name"], "")),
                )
                if identity in seen:
                    continue
                seen.add(identity)
                fresh_rows.append(row)
            if not fresh_rows:
                continue
            hit_categories.add(category)
            label_query = f"{term}" + (" (본문)" if scope == 2 and category in _SEARCHABLE else "")
            sections.append(_format_search_rows(label_query, category, meta, fresh_rows))

        required = {"law", "admrul", "licbyl", "admbyl"}
        if include_local_rules:
            required.update(("ordin", "ordinbyl"))
        missing = required - hit_categories
        if missing:
            labels = [RESOURCE_CATEGORIES[item]["label"] for item in sorted(missing)]
            sections.append(
                "[미확인 영역] "
                + ", ".join(labels)
                + " — 결과가 없으므로 존재한다고 추측하지 마세요. "
                "정확한 법령명이나 지침명으로 다시 검색할 수 있습니다."
            )
        first_law_id = ""
        first_law_name = ""
        for category, term, scope in jobs:
            if category != "law":
                continue
            found = findings.get((category, term, scope))
            if not isinstance(found, tuple):
                continue
            meta, rows = found
            if not rows:
                continue
            first_law_id = json_text(rows[0].get(meta["id"], ""))
            first_law_name = json_text(rows[0].get(meta["name"], ""))
            if first_law_id:
                break
        if first_law_id:
            try:
                payload = api.get_three_stage_comparison(oc_key, first_law_id)
                summary = compact_three_stage(payload)
            except Exception:
                summary = ""
            if summary:
                if first_law_name:
                    summary = f"{first_law_name}\n{summary}"
                sections.append(summary)
        sections.append(
            "[다음 행동] 관련성이 높은 법령은 get_article(조 번호 6자리), "
            "행정규칙은 get_document로 원문을 읽은 뒤 답하세요. 긴 지침은 "
            "get_document의 keyword에 '입안', '서류', '계획도서' 같은 "
            "핵심어를 넣어 관련 부분을 읽으세요. 제출서류 질문은 별표 "
            "결과가 없더라도 본문상 구비서류 규정을 추가 확인하세요. "
            "부처 질의회신은 search_inquiries, "
            "해석례·판례·헌재·행심은 search_cases도 "
            "찾으세요. 개정 전후가 문제면 compare_old_new, 특정 날짜의 "
            "적용 법령은 get_historical_law를 쓰세요. "
            "3단비교에 나온 시행령·시행규칙 조도 get_article로 읽으세요."
        )
        return "\n\n".join(sections)

    def search_cases(query: str, source: str = "expc") -> str:
        """법령해석례·판례·헌재·행심·위원회 결정례를 찾는다.

        조문만으로 실무 적용이 갈리거나, 허가·처분의 해석이 필요할 때
        쓴다. 나온 id는 get_case로 본문을 읽는다. 중앙부처가 직접 회신한
        1차 해석은 search_inquiries를 쓴다.

        Args:
            query: 안건명·사건명 또는 본문 키워드.
            source: "expc"(법령해석례, 기본값) | "prec"(판례) |
                "central"(중앙부처 질의회신) | "customs"(관세청) |
                "detc"(헌재) | "decc"(행정심판) | "tax"(조세심판) |
                "ftc" | "ppc" | "nlrc" | "acr".
        """
        meta = _case_source_meta(source)
        cache_key = f"cases:{source}:{' '.join(query.split()).casefold()}"
        cached = _SEARCH_CACHE.load(cache_key)
        if cached is not None:
            _remember_names(cached, id_to_name)
            return cached

        agencies = (
            tuple(api.AGENCIES)
            if meta["agency"] is None
            else (meta["agency"],)
        )
        roots, errors = api.search_agencies(
            oc_key,
            agencies,
            query=query,
            search=2,
            display=8,
        )
        lines = [f"[{meta['label']}] '{query}' 검색 결과:"]
        count = 0
        for agency, root in roots:
            for node in root.iter():
                if _xml_local(node.tag).lower() != str(meta["item"]).lower():
                    continue
                item_id = api._find_text(node, meta["id"]) or node.attrib.get(
                    "id", ""
                )
                title = api._find_text(node, meta["title"])
                if not item_id and not title:
                    continue
                if item_id:
                    id_to_name[item_id] = title or item_id
                number = api._find_text(node, meta["number"])
                date = api._find_text(node, meta["date"])
                extra = [f"id={item_id}", f"target={agency.target}"]
                if number:
                    extra.append(number)
                if date:
                    extra.append(date)
                if agency.name and meta["agency"] is None:
                    extra.append(agency.name)
                lines.append(f"- {title or item_id} ({', '.join(extra)})")
                count += 1
                if count >= 12:
                    break
            if count >= 12:
                break
        if errors:
            for agency, message in errors[:4]:
                lines.append(f"- {agency.name} 조회 실패: {message}")
        if count == 0:
            result = (
                f"'{query}'({meta['label']})로 찾히는 사례가 없습니다. "
                "핵심 단어만 남기거나 source를 바꿔 보세요."
            )
        else:
            lines.append(
                "\n다음 행동: 관련 사례의 id와 target을 get_case에 넘겨 "
                "질의요지·회답(또는 판결요지)을 읽으십시오."
            )
            result = "\n".join(lines)
        _SEARCH_CACHE.save(cache_key, result)
        return result

    def get_case(item_id: str, source: str = "expc", target: str = "") -> str:
        """법령해석례·판례·헌재·행심·위원회 결정례 본문을 가져온다.

        Args:
            item_id: search_cases가 돌려준 id.
            source: search_cases와 같은 출처 코드.
            target: 중앙부처 질의회신일 때 기관 target
                (예: molitCgmExpc). search_cases 결과의 target= 값을 그대로
                넘긴다. 그 외 출처는 비워 둔다.
        """
        meta = _case_source_meta(source)
        if meta["agency"] is None:
            agency = api.AGENCY_BY_TARGET.get(str(target or "").strip())
            if agency is None:
                raise ValueError(
                    "central 본문을 읽으려면 search_cases가 준 target "
                    "(예: molitCgmExpc)을 그대로 넘기세요."
                )
            api_target = agency.target
        else:
            api_target = meta["agency"].target
        cache_key = f"case:{api_target}:{item_id}"
        cached = _BODY_CACHE.load(cache_key)
        if cached is not None:
            return cached
        root = api.get_detail(oc_key, item_id, target=api_target)
        title = api._find_text(root, meta["title"]) or meta["label"]
        fields = tuple(meta.get("fields") or ("질의요지", "회답", "이유"))
        parts = [title]
        for label in fields:
            value = api._find_text(root, label)
            if value and value.lower() != "null":
                parts.append(f"[{label}]\n{value}")
        if len(parts) == 1:
            return f"{meta['label']} id={item_id} 본문을 찾지 못했습니다."
        result = _truncate("\n\n".join(parts))
        _BODY_CACHE.save(cache_key, result)
        return result

    def search_inquiries(
        query: str, agency: str = "", search_scope: int = 2
    ) -> str:
        """중앙부처가 민원인·지자체 질의에 회신한 1차 법령해석을 찾는다.

        질의회신·유권해석을 찾아 달라는 질문에는 이 도구를 먼저 쓴다.
        legal_research는 법령·지침 조사이지 질의회신이 아니다.
        법제처 법령해석례(search_cases source=expc)와 다르다. 국토부·행안부
        등 소관 부처가 직접 답한 질의회신·유권해석을 볼 때 쓴다. 나온
        id와 target은 get_inquiry로 본문을 읽는다. 상위 건은 회답 미리보기를
        붙이므로, 미리보기만으로 답을 쓰지 말고 관련 건은 get_inquiry로
        확인한다.

        Args:
            query: 안건명 또는 본문 키워드. 예: '농지전용', '개발행위허가'.
            agency: 기관명 또는 target. 비우면 전체 기관.
                예: '국토교통부', 'molitCgmExpc'.
            search_scope: 1=안건명, 2=본문(기본값).
        """
        if search_scope not in (1, 2):
            raise ValueError("search_scope는 1(안건명) 또는 2(본문)여야 합니다.")
        agencies = resolve_inquiry_agencies(agency)
        cache_key = (
            f"inquiries:{','.join(item.target for item in agencies)}:"
            f"{search_scope}:{' '.join(query.split()).casefold()}"
        )
        cached = _SEARCH_CACHE.load(cache_key)
        if cached is not None:
            _remember_names(cached, id_to_name)
            return cached
        meta = _case_source_meta("central")
        display = 20 if len(agencies) == 1 else 8
        roots, errors = api.search_agencies(
            oc_key,
            agencies,
            query=query,
            search=search_scope,
            display=display,
        )
        header = f"[중앙부처 질의회신] '{query}'"
        if len(agencies) == 1:
            header += f" ({agencies[0].name})"
        lines = [f"{header} 검색 결과:"]
        hits: list[dict] = []
        for item, root in roots:
            per_agency = 0
            agency_cap = 20 if len(agencies) == 1 else 5
            for node in root.iter():
                if _xml_local(node.tag).lower() != str(meta["item"]).lower():
                    continue
                item_id = api._find_text(node, meta["id"]) or node.attrib.get(
                    "id", ""
                )
                title = api._find_text(node, meta["title"])
                if not item_id and not title:
                    continue
                if item_id:
                    id_to_name[item_id] = title or item_id
                hits.append(
                    {
                        "id": item_id,
                        "target": item.target,
                        "agency": item.name,
                        "title": title or item_id,
                        "available": item.detail_available,
                        "number": api._find_text(node, meta["number"]),
                        "date": api._find_text(node, meta["date"]),
                        "inquiry_org": api._find_text(node, "질의기관명"),
                    }
                )
                per_agency += 1
                if per_agency >= agency_cap:
                    break
        if errors:
            for item, message in errors[:4]:
                lines.append(f"- {item.name} 조회 실패: {message}")
        if not hits:
            result = (
                f"'{query}'로 찾히는 중앙부처 질의회신이 없습니다. "
                "핵심 단어만 남기거나 agency를 바꿔 보세요. "
                "법제처 해석례는 search_cases(source=expc)를 쓰세요."
            )
        else:
            grouped: dict[str, list[dict]] = {}
            for hit in hits:
                grouped.setdefault(hit["target"], []).append(hit)
            agency_order = [
                (
                    max(inquiry_title_score(hit["title"], query) for hit in group),
                    index,
                    target,
                    group,
                )
                for index, (target, group) in enumerate(grouped.items())
            ]
            agency_order.sort(key=lambda row: (-row[0][0], -row[0][1], row[1]))
            shown_limit = 20 if len(agencies) == 1 else 24
            shown = 0
            per_group = 20 if len(agencies) == 1 else 3
            for _score, _index, _target, group in agency_order:
                ranked = sorted(
                    group,
                    key=lambda hit: inquiry_title_score(hit["title"], query),
                    reverse=True,
                )
                if len(agencies) > 1:
                    lines.append(f"\n{ranked[0]['agency']}")
                for hit in ranked[:per_group]:
                    extra = [f"id={hit['id']}", f"target={hit['target']}", hit["agency"]]
                    if hit["number"]:
                        extra.append(hit["number"])
                    if hit["date"]:
                        extra.append(hit["date"])
                    if hit["inquiry_org"]:
                        extra.append(f"질의기관={hit['inquiry_org']}")
                    if not hit["available"]:
                        extra.append("본문API없음")
                    lines.append(f"- {hit['title']} ({', '.join(extra)})")
                    if hit["id"] and hit["available"]:
                        lines.append(
                            f"  인용: [{hit['title']}](doc:{hit['target']}:{hit['id']})"
                        )
                    shown += 1
                    if shown >= shown_limit:
                        break
                if shown >= shown_limit:
                    break
            if len(agencies) > 1:
                lines.append(
                    "\n다른 부처 건이 먼저 나와도 질문 소관 부처 제목을 "
                    "골라 get_inquiry로 읽으십시오."
                )
            lines.append(
                "목록 제목만으로 답하지 마십시오. 아래 미리보기와 "
                "get_inquiry로 질의요지·회답을 확인한 뒤에만 인용하십시오."
            )
            ranked_hits = sorted(
                hits,
                key=lambda hit: inquiry_title_score(hit["title"], query),
                reverse=True,
            )
            preview_queue: list[dict] = []
            seen_targets: set[str] = set()
            for hit in ranked_hits:
                if not hit["id"] or not hit["available"]:
                    continue
                if len(agencies) > 1 and hit["target"] in seen_targets:
                    continue
                preview_queue.append(hit)
                seen_targets.add(hit["target"])
                if len(preview_queue) >= 2:
                    break
            if len(preview_queue) < 2:
                for hit in ranked_hits:
                    if hit in preview_queue or not hit["id"] or not hit["available"]:
                        continue
                    preview_queue.append(hit)
                    if len(preview_queue) >= 2:
                        break
            previewed = 0
            for hit in preview_queue:
                try:
                    body = get_inquiry(hit["id"], hit["target"])
                except Exception:
                    continue
                if "본문을 주지 않습니다" in body or "찾지 못했습니다" in body:
                    continue
                previewed += 1
                lines.append(
                    f"\n[미리보기 {previewed}] {hit['title']} "
                    f"(id={hit['id']}, target={hit['target']})\n{body}"
                )
            result = "\n".join(lines)
        _SEARCH_CACHE.save(cache_key, result)
        return result

    def get_inquiry(item_id: str, target: str) -> str:
        """중앙부처 질의회신 본문(질의요지·회답·이유)을 읽는다.

        Args:
            item_id: search_inquiries가 돌려준 id.
            target: search_inquiries 결과의 target= 값
                (예: molitCgmExpc). 기관명(국토교통부)도 됩니다.
        """
        agencies = resolve_inquiry_agencies(target)
        if len(agencies) != 1:
            raise ValueError(
                "본문을 읽으려면 search_inquiries가 준 target "
                "(예: molitCgmExpc)을 그대로 넘기세요."
            )
        agency = agencies[0]
        if not agency.detail_available:
            return (
                f"{agency.name} 질의회신은 법제처 API가 본문을 주지 않습니다. "
                "화면의 중앙부처 질의회신 탭이나 법제처 사이트에서 확인하세요."
            )
        result = get_case(item_id, source="central", target=agency.target)
        if (
            result
            and "본문을 주지 않습니다" not in result
            and "찾지 못했습니다" not in result
        ):
            title = result.splitlines()[0].strip() or item_id
            result += (
                f"\n\n인용: [{title}](doc:{agency.target}:{item_id})"
            )
        return result

    def _normalize_date(value: str) -> str:
        digits = re.sub(r"\D", "", str(value or ""))
        if len(digits) != 8:
            raise ValueError("date는 YYYYMMDD 형식이어야 합니다. 예: 20240101")
        return digits

    def _compact_article_history(payload: object) -> str:
        rows: list[dict] = []

        def walk(value: object) -> None:
            if isinstance(value, list):
                for item in value:
                    walk(item)
                return
            if not isinstance(value, dict):
                return
            keys = set(value)
            if keys & {"시행일자", "공포일자", "법령명한글", "조문번호", "제개정구분명"}:
                rows.append(value)
                return
            for nested in value.values():
                walk(nested)

        walk(payload)
        if not rows:
            return ""
        lines = []
        for row in rows[:20]:
            name = json_text(
                row.get("법령명한글") or row.get("조문번호") or row.get("조문키")
            )
            effective = json_text(row.get("시행일자"))
            announced = json_text(row.get("공포일자"))
            kind = json_text(row.get("제개정구분명"))
            extra = ", ".join(
                part
                for part in (
                    f"시행 {effective}" if effective else "",
                    f"공포 {announced}" if announced else "",
                    kind,
                )
                if part
            )
            lines.append(f"- {name or '이력'} ({extra})" if extra else f"- {name or '이력'}")
        return "\n".join(lines)

    def get_historical_law(law_id: str, date: str = "", jo: str = "") -> str:
        """특정 날짜의 적용 법령(행위시법) 또는 조문 개정 이력을 읽는다.

        date를 주면 그날 시행 중이던 본문이다. 현행본으로 추측하지 않는다.
        그날 조문과 함께, 현행 부칙에서 적용례·경과조치 문장을 잘라 붙인다.
        부칙이 적용을 뒤집는지까지 해석하지는 않는다.
        date 없이 jo만 주면 그 조의 개정 일자 목록을 돌려준다.

        Args:
            law_id: search_law가 돌려준 법령ID.
            date: 적용 기준일 YYYYMMDD. 예: 20240101.
            jo: 조 번호 6자리 또는 '12의2'. date와 함께 쓰면 그 조만 추출.
        """
        jo_code = normalize_article_jo(jo) if str(jo or "").strip() else ""
        if not str(date or "").strip():
            if not jo_code:
                raise ValueError(
                    "행위시법은 date(YYYYMMDD)가 필요하고, 조문 이력은 jo가 "
                    "필요합니다."
                )
            payload = api.get_article_history(oc_key, law_id, jo_code)
            summary = _compact_article_history(payload)
            if not summary:
                return (
                    f"{_NOT_FOUND_MARK} 법령ID {law_id} "
                    f"{article_jo_label(jo_code)}의 개정 이력을 찾지 "
                    "못했습니다. 추측하지 마세요."
                )
            return _truncate(
                f"[조문 이력] {article_jo_label(jo_code)}\n{summary}"
            )
        when = _normalize_date(date)
        payload = api.get_historical_law(
            oc_key, law_id, date=when, jo=jo_code
        )
        if not api._has_law_node(payload):
            return (
                f"{_NOT_FOUND_MARK} 법령ID {law_id}의 {when} 시행본을 "
                "찾지 못했습니다. 현행본으로 추측하지 마세요."
            )
        if jo_code:
            text = extract_law_article(payload, jo_code)
            if not text:
                return (
                    f"{_NOT_FOUND_MARK} {when} 시행본에서 "
                    f"{article_jo_label(jo_code)}를 찾지 못했습니다."
                )
            result = f"(시행 {when})\n{text}"
        else:
            index = law_article_index(payload)
            header = f"법령ID {law_id} (시행 {when})"
            if index:
                result = (
                    f"{header}\n\n[조문 목차]\n{index}\n\n"
                    "특정 조는 jo를 넣어 다시 부르십시오."
                )
            else:
                result = (
                    f"{header}\n\n{document_plain_text(payload, 'law')}"
                )
        jo_label = article_jo_label(jo_code) if jo_code else ""
        try:
            current = api.get_resource_detail(
                oc_key, "eflaw", law_id, id_param="ID"
            )
            excerpts = extract_transition_excerpts(current, jo_label)
        except Exception:
            excerpts = None
        if excerpts:
            parts = [
                result,
                "",
                "적용례·경과조치 발췌 (기준일 사건에 영향할 수 있음. "
                "해석하지 마세요.)",
            ]
            for header, lines in excerpts:
                parts.append(f"- {header}")
                parts.extend(f"  {line}" for line in lines)
            parts.append(
                "부칙이 조문보다 우선할 수 있습니다. 원문을 직접 확인하세요."
            )
            result = "\n".join(parts)
        elif excerpts is not None:
            result += (
                "\n\n적용례·경과조치: 관련 부칙에서 경과규정 신호를 찾지 "
                "못했습니다. 부칙 원문을 확인하세요."
            )
        return _truncate(result)

    def compare_old_new(law_id: str) -> str:
        """최근 개정의 신구법 대조표를 읽는다.

        무엇이 바뀌었는지가 쟁점일 때 현행 조문만 읽지 말고 이 도구를
        함께 쓴다.

        Args:
            law_id: search_law가 돌려준 법령ID.
        """
        root = api.get_old_and_new(oc_key, law_id)
        summary = compact_old_new_xml(root)
        if not summary:
            return (
                f"{_NOT_FOUND_MARK} 법령ID {law_id}의 신구대조 자료가 "
                "없습니다. 개정 내용을 추측하지 마세요."
            )
        return _truncate(summary)

    def ordinance_radar(query: str = "", item_id: str = "") -> str:
        """조례 목적 조문의 근거 상위법령과 현행 시행일을 대조한다.

        조례가 인용한 상위법이 조례 시행 이후에 개정됐으면 정비 검토
        대상으로 표시한다. 정비 필요는 단정하지 않는다. 목적 조문의
        「」 인용만 근거법으로 본다.

        Args:
            query: 자치법규명. 예: '서울특별시 광진구 주차장 설치 및 관리 조례'.
            item_id: search_law(category=ordin)이 돌려준 자치법규일련번호.
                있으면 검색을 건너뛴다.
        """
        return _truncate(
            run_ordinance_radar(oc_key, query=query, item_id=item_id)
        )

    def cite_check(
        case_number: str, display: int = 20, deep_scan: bool = True
    ) -> str:
        """판례가 후속 판결에서 변경·폐기됐는지 추적한다.

        사건번호로 대상 판례를 특정한 뒤, 그 번호를 인용한 후속 판례를
        찾고 전원합의체 우선으로 본문의 변경·폐기 문구를 스캔한다.
        법제처 미검색을 부존재로 단정하지 않는다.

        Args:
            case_number: 사건번호. 예: '2013다61381'. 문장에 섞여 있어도 된다.
            display: 후속 인용 표시 건수. 기본 20.
            deep_scan: 후속 상위 판례 본문을 정밀 스캔할지. 기본 True.
        """
        return _truncate(
            run_cite_check(
                oc_key,
                case_number,
                display=display,
                deep_scan=bool(deep_scan),
            )
        )

    def impact_map(
        law_name: str, jo: str, include_ordinances: bool = True
    ) -> str:
        """특정 조문이 판례·해석례·헌재·행심·조례에 인용된 영향을 모은다.

        법제처 검색은 조번호를 부분 일치로 물어오므로, 제103조와
        제1032조를 가려 경계가 맞는 건만 센다. 법령명이 검색 1위와
        다르면 지도를 그리지 않는다.

        Args:
            law_name: 법령명. 예: '민법', '근로기준법'.
            jo: 조 번호. '제103조', '제10조의2', 또는 6자리 '010300'.
            include_ordinances: 자치법규 검색 포함. 기본 True.
                조례 검색은 조번호를 반영하지 못한다.
        """
        return _truncate(
            run_impact_map(
                oc_key,
                law_name,
                jo,
                include_ordinances=bool(include_ordinances),
            )
        )

    return (
        _safe(search_law),
        _safe(get_article),
        _safe(get_document),
        _safe(search_admin_rule),
        _safe(get_annexes),
        _safe(legal_research),
        _safe(search_cases),
        _safe(get_case),
        _safe(search_inquiries),
        _safe(get_inquiry),
        _safe(get_historical_law),
        _safe(compare_old_new),
        _safe(ordinance_radar),
        _safe(cite_check),
        _safe(impact_map),
    )
