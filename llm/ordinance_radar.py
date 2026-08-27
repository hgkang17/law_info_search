"""조례 제1조(목적)의 근거 상위법과 현행 시행일을 대조한다."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import molit_cgm_expc_api as api
from llm.law_aliases import compact_law_key, resolved_law_matches, score_law_relevance
from models.law import RESOURCE_CATEGORIES
from utils.parsing import json_list, json_text

_NOT_FOUND = "[NOT_FOUND]"
_LAW_NAME_TAIL = re.compile(r"(법|법률|시행령|시행규칙|규정)$")
_BASE_LAW_TAIL = re.compile(r"(법|법률)$")
_QUOTE_RE = re.compile(r"「([^」]+)」")


def find_purpose_article(articles: list) -> str:
    """제목에서 '목적'을 찾고, 없으면 첫 조문의 조내용만 쓴다."""
    picked = None
    for article in articles:
        if not isinstance(article, dict):
            continue
        if "목적" in json_text(article.get("조제목")):
            picked = article
            break
        if picked is None:
            picked = article
    if not isinstance(picked, dict):
        return ""
    return json_text(picked.get("조내용"))


def extract_basis_laws(purpose_text: str, self_name: str) -> list[str]:
    """목적 조문의 「」 인용과 '같은 법 시행령/시행규칙'만 근거법으로 본다.

    본문 전체를 스캔하면 별표의 무관 법률이 섞인다.
    """
    self_key = compact_law_key(self_name)
    result: list[str] = []
    seen: set[str] = set()
    base_law = ""

    def push(name: str) -> None:
        key = compact_law_key(name)
        if not key or key == self_key or key in seen:
            return
        seen.add(key)
        result.append(name)

    for raw in _QUOTE_RE.findall(purpose_text or ""):
        name = raw.strip()
        if not _LAW_NAME_TAIL.search(name):
            continue
        if compact_law_key(name) == self_key:
            continue
        if _BASE_LAW_TAIL.search(name) and not base_law:
            base_law = name
        push(name)
    if base_law:
        if "시행령" in (purpose_text or ""):
            push(f"{base_law} 시행령")
        if "시행규칙" in (purpose_text or ""):
            push(f"{base_law} 시행규칙")
    return result


def months_between(from_ymd: str, to_ymd: str) -> int | None:
    if not re.fullmatch(r"\d{8}", from_ymd or "") or not re.fullmatch(
        r"\d{8}", to_ymd or ""
    ):
        return None
    from_m = int(from_ymd[:4]) * 12 + int(from_ymd[4:6])
    to_m = int(to_ymd[:4]) * 12 + int(to_ymd[4:6])
    return to_m - from_m


def _as_list(value: object) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _ordin_rows(data: dict) -> list:
    meta = RESOURCE_CATEGORIES["ordin"]
    block = data.get(meta["root"]) if isinstance(data, dict) else None
    if not isinstance(block, dict):
        return []
    return [
        row
        for row in _as_list(block.get(meta["item"]))
        if isinstance(row, dict)
    ]


def _law_rows(data: dict, query: str = "") -> list:
    meta = RESOURCE_CATEGORIES["law"]
    block = data.get(meta["root"]) if isinstance(data, dict) else None
    if not isinstance(block, dict):
        return []
    rows = [
        row
        for row in _as_list(block.get(meta["item"]))
        if isinstance(row, dict)
    ]

    def rank(row: dict) -> tuple:
        status = json_text(row.get("현행연혁코드") or row.get("현행연혁구분"))
        status_rank = 0 if status == "현행" else 1 if status == "연혁" else 2
        name = json_text(row.get("법령명한글"))
        return (status_rank, -score_law_relevance(name, query))

    return sorted(rows, key=rank)


def _row_law_status(row: dict, fallback_name: str) -> dict:
    name = json_text(row.get("법령명한글"))
    return {
        "name": name or fallback_name,
        "eff_date": json_text(row.get("시행일자")),
        "prom_date": json_text(row.get("공포일자")),
        "law_id": json_text(row.get("법령ID")),
        "mst": json_text(row.get("법령일련번호")),
        "short": json_text(row.get("법령약칭명")),
    }


def fetch_law_status(oc_key: str, law_name: str) -> dict | None:
    """정확 법령명 매칭을 우선하고, 없으면 LIKE 1위는 가드를 통과할 때만 쓴다."""
    data = api.search_resource(oc_key, "law", law_name, display=50)
    rows = _law_rows(data, law_name)
    query_key = compact_law_key(law_name)
    first = None
    for row in rows:
        info = _row_law_status(row, law_name)
        if first is None:
            first = info
        if compact_law_key(info["name"]) == query_key or (
            info["short"] and compact_law_key(info["short"]) == query_key
        ):
            return info
    if first and resolved_law_matches(law_name, first["name"], first.get("short", "")):
        return first
    return None


def run_ordinance_radar(oc_key: str, query: str = "", item_id: str = "") -> str:
    ordin_seq = str(item_id or "").strip()
    search_name = str(query or "").strip()
    if not ordin_seq and search_name:
        data = api.search_resource(oc_key, "ordin", search_name, display=5)
        rows = _ordin_rows(data)
        if rows:
            ordin_seq = json_text(rows[0].get("자치법규일련번호"))
        if not ordin_seq:
            return (
                f"{_NOT_FOUND} 자치법규 '{search_name}'을(를) 찾지 못했습니다. "
                "search_law(category=ordin)로 조례명이나 일련번호를 먼저 "
                "확인하세요. 추측하지 마세요."
            )
    if not ordin_seq:
        return (
            f"{_NOT_FOUND} 조례명(query) 또는 자치법규일련번호(item_id)가 "
            "필요합니다."
        )

    payload = api.get_resource_detail(
        oc_key, "ordin", ordin_seq, id_param="MST"
    )
    service = payload.get("LawService", payload) if isinstance(payload, dict) else {}
    if not isinstance(service, dict) or not service.get("자치법규기본정보"):
        return (
            f"{_NOT_FOUND} 자치법규 본문을 찾지 못했습니다. "
            "search_law(category=ordin)로 일련번호를 확인하세요."
        )
    info = service.get("자치법규기본정보") or {}
    if not isinstance(info, dict):
        info = {}
    ord_name = json_text(info.get("자치법규명")) or "알 수 없음"
    ord_eff = json_text(info.get("시행일자"))
    dept = json_text(info.get("담당부서명"))
    govt = json_text(info.get("지자체기관명"))
    articles_node = service.get("조문", {})
    if isinstance(articles_node, dict):
        articles_node = articles_node.get("조")
    articles = [
        article
        for article in json_list(articles_node)
        if isinstance(article, dict)
    ]
    purpose = find_purpose_article(articles)
    parents = extract_basis_laws(purpose, ord_name)
    if not parents:
        return (
            f"[NO_PARENT] '{ord_name}' 제1조(목적)에서 근거 상위법령"
            "(법률/시행령/시행규칙)을 찾지 못했습니다. 조례가 상위법을 "
            "명시 인용하지 않는 유형일 수 있습니다. get_document로 본문을 "
            "직접 확인하세요."
        )

    statuses: list[dict | None] = [None] * len(parents)

    def lookup(index: int, name: str) -> tuple[int, dict | None]:
        try:
            return index, fetch_law_status(oc_key, name)
        except Exception:
            return index, None

    with ThreadPoolExecutor(max_workers=min(4, len(parents))) as pool:
        futures = [
            pool.submit(lookup, index, name) for index, name in enumerate(parents)
        ]
        for future in as_completed(futures):
            index, status = future.result()
            statuses[index] = status

    lines = [
        "[조례 정비 레이더]",
        f"조례: {ord_name}",
    ]
    header = f"시행일: {ord_eff or '미상'}"
    if govt:
        header += f" | 자치단체: {govt}"
    if dept:
        header += f" | 소관: {dept}"
    lines.append(header)
    lines.append("")
    lines.append(f"근거 상위법령 {len(parents)}건 대조:")

    need_review = 0
    unknown = 0
    for name, status in zip(parents, statuses):
        if not status or not status.get("eff_date"):
            unknown += 1
            lines.append(
                f"  - {name} — 현행 시행일 확인 불가 "
                "(search_law로 개별 확인하세요)"
            )
            continue
        gap = months_between(ord_eff, status["eff_date"]) if ord_eff else None
        ident = status.get("law_id") or status.get("mst") or ""
        ident_note = f", id={ident}" if ident else ""
        if gap is not None and status["eff_date"] > ord_eff:
            need_review += 1
            if gap > 0:
                gap_text = f"약 {gap}개월 뒤"
            else:
                gap_text = "조례 시행 이후"
            lines.append(
                f"  - [정비 검토] {status['name']} — 현행 시행 "
                f"{status['eff_date']} (조례보다 {gap_text} 개정{ident_note})"
            )
        else:
            lines.append(
                f"  - {status['name']} — 현행 시행 {status['eff_date']} "
                f"(조례 시행 시점까지 반영{ident_note})"
            )

    lines.append("")
    if need_review:
        lines.append(
            f"요약: 근거 상위법 {len(parents)}건 중 {need_review}건이 "
            "조례 시행 이후 개정됨 → 정비 검토 대상."
        )
        lines.append(
            "개정 내용이 조례 위임사항과 관련되는지는 get_article과 "
            "compare_old_new로 확인하세요."
        )
    elif unknown == len(parents):
        lines.append(
            "요약: 상위법 현행 시행일을 확인하지 못했습니다. "
            "개별 search_law로 확인하세요."
        )
    else:
        lines.append(
            "요약: 근거 상위법이 조례 시행 시점까지 반영된 것으로 보입니다 "
            "(개정 시행일 기준)."
        )
    lines.append(
        "시행일 선후 비교는 정비 가능성 신호이며, 실제 정비 필요 여부는 "
        "개정 조문 확인이 필요합니다. 정비 필요를 단정하지 마세요."
    )
    return "\n".join(lines)
