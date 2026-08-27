"""현행 검색 0건일 때 폐지·후속 규정 안내."""

from __future__ import annotations

import re

from llm.law_aliases import compact_law_key, name_matches_query
from models.law import RESOURCE_CATEGORIES
from utils.parsing import json_text

_SUCCESSOR_RE = re.compile(
    r"「([^」]{2,60})」\s*(?:으로|로|에)\s*(?:통\s*[ㆍ·]?\s*폐합|통합|이관|흡수|대체)"
)


def _as_list(value: object) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _related(name: str, query: str) -> bool:
    return name_matches_query(query, name) or (
        bool(compact_law_key(name))
        and compact_law_key(query) in compact_law_key(name)
    )


def parse_abolished_laws(data: dict, query: str) -> list[dict]:
    """eflaw 검색에서 법령ID별 최신 이력이 폐지·타법폐지인 것만 고른다."""
    meta = RESOURCE_CATEGORIES["law"]
    block = data.get(meta["root"]) if isinstance(data, dict) else None
    if not isinstance(block, dict):
        return []
    latest: dict[str, dict] = {}
    for row in _as_list(block.get(meta["item"])):
        if not isinstance(row, dict):
            continue
        law_id = json_text(row.get("법령ID"))
        if not law_id:
            continue
        rec = {
            "name": json_text(row.get("법령명한글")),
            "law_id": law_id,
            "mst": json_text(row.get("법령일련번호")),
            "eff_date": json_text(row.get("시행일자")),
            "revision": json_text(row.get("제개정구분명")),
            "law_type": json_text(row.get("법령구분명")),
        }
        prev = latest.get(law_id)
        if prev is None or rec["eff_date"] > prev["eff_date"]:
            latest[law_id] = rec
    return [
        rec
        for rec in latest.values()
        if rec["revision"] in ("폐지", "타법폐지") and _related(rec["name"], query)
    ]


def extract_successor_names(reason: str, exclude_names: list[str]) -> list[str]:
    """폐지사유에서 통·폐합·이관된 「」 규정명을 뽑는다."""
    skip = {compact_law_key(name) for name in exclude_names if name}
    found: list[str] = []
    for match in _SUCCESSOR_RE.finditer(reason or ""):
        name = match.group(1).strip()
        key = compact_law_key(name)
        if not name or key in skip or name in found:
            continue
        found.append(name)
    return found


def extract_abolition_reason(payload: dict) -> str:
    """행정규칙 본문의 제개정이유."""
    if not isinstance(payload, dict):
        return ""
    service = payload.get("LawService", payload)
    if not isinstance(service, dict):
        return ""
    chunks: list[str] = []
    reason = service.get("제개정이유")
    if reason is not None:
        chunks.append(json_text(reason))
        if isinstance(reason, dict):
            chunks.append(json_text(reason.get("제개정이유내용")))
    info = service.get("행정규칙기본정보")
    if isinstance(info, dict):
        chunks.append(json_text(info.get("제개정이유")))
    text = "\n".join(part for part in chunks if part).strip()
    if len(text) > 700:
        return text[:700] + "…"
    return text


def format_abolished_law_note(query: str, abolished: list[dict]) -> str:
    if not abolished:
        return ""
    lines = [
        f"[폐지] '{query}' — 현행 법령 0건. 폐지된 법령이 확인됩니다:",
        "",
    ]
    for index, item in enumerate(abolished[:5], start=1):
        kind = item.get("law_type") or "법령"
        extra = f", id={item['law_id']}" if item.get("law_id") else ""
        lines.append(
            f"{index}. {item['name']} [{kind}] — {item['revision']}, "
            f"최종 시행 {item['eff_date'] or '미상'}{extra}"
        )
    first = abolished[0]
    lines.append("")
    if first.get("law_id") and first.get("eff_date"):
        lines.append(
            f"폐지 경위는 get_historical_law(law_id=\"{first['law_id']}\", "
            f"date=\"{first['eff_date']}\")의 부칙·개정문에서 확인하세요. "
            "타법폐지면 부칙에 폐지시킨 법률명이 나옵니다."
        )
    lines.append(
        "폐지된 법령을 현행 기준으로 인용하지 마세요. 답에는 폐지 사실을 "
        "적고, 제도의 현행 근거는 후속 법령명으로 다시 찾으세요."
    )
    return "\n".join(lines)


def parse_admin_rule_history(data: dict) -> list[dict]:
    meta = RESOURCE_CATEGORIES["admrul"]
    block = data.get(meta["root"]) if isinstance(data, dict) else None
    if not isinstance(block, dict):
        return []
    hits = []
    for row in _as_list(block.get(meta["item"])):
        if not isinstance(row, dict):
            continue
        hits.append(
            {
                "name": json_text(row.get("행정규칙명")),
                "seq": json_text(row.get("행정규칙일련번호")),
                "rule_id": json_text(row.get("행정규칙ID")),
                "prom_date": json_text(row.get("발령일자")),
                "revision": json_text(row.get("제개정구분명")),
                "status": json_text(
                    row.get("현행연혁구분") or row.get("현행연혁코드")
                ),
                "rule_type": json_text(row.get("행정규칙종류")),
                "org": json_text(row.get("소관부처명")),
            }
        )
    return hits


def detect_abolished_admin_rule(
    query: str, hits: list[dict]
) -> tuple[str, list[dict]] | None:
    """nw=2 연혁 목록에서 폐지 또는 제명변경을 찾는다."""
    groups: dict[str, list[dict]] = {}
    for hit in hits:
        key = hit.get("rule_id") or compact_law_key(hit.get("name") or "")
        if not key:
            continue
        groups.setdefault(key, []).append(hit)
    for group in groups.values():
        group.sort(key=lambda item: item.get("prom_date") or "")
        if not any(_related(item.get("name") or "", query) for item in group):
            continue
        latest = group[-1]
        if latest.get("revision") == "폐지":
            return "abolished", group
        if latest.get("status") == "현행" and not _related(
            latest.get("name") or "", query
        ):
            return "renamed", group
    return None


def format_renamed_admin_rule(query: str, group: list[dict]) -> str:
    latest = group[-1]
    old = next(
        (
            item["name"]
            for item in group
            if _related(item.get("name") or "", query)
        ),
        query,
    )
    return (
        f"[제명변경] '{query}' — 현행 행정규칙 0건. 같은 규칙이 이름이 "
        f"바뀌어 현행입니다:\n\n"
        f"「{old}」 → 「{latest['name']}」 "
        f"({latest.get('rule_type') or '행정규칙'}, "
        f"{latest.get('org') or ''}, 발령 {latest.get('prom_date') or '미상'})\n\n"
        f"현행본은 search_admin_rule(\"{latest['name']}\") 또는 "
        f"get_document(item_id=\"{latest['seq']}\", category=\"admrul\")로 "
        "읽으세요."
    )


def format_abolished_admin_rule(
    query: str,
    group: list[dict],
    reason: str = "",
) -> str:
    latest = group[-1]
    prev = group[-2] if len(group) >= 2 else None
    lines = [
        f"[폐지] '{query}' — 현행 행정규칙 0건. 폐지된 행정규칙입니다:",
        "",
        f"「{latest['name']}」 ({latest.get('rule_type') or '행정규칙'}, "
        f"{latest.get('org') or ''}) — {latest.get('prom_date') or '미상'} 폐지",
    ]
    if prev:
        lines.append(
            f"폐지 직전 버전 id={prev['seq']} (발령 {prev.get('prom_date') or '미상'}). "
            "폐지 전 본문이 필요하면 get_document로 이 id를 읽으세요."
        )
    successors = extract_successor_names(
        reason, [item.get("name") or "" for item in group]
    )
    if reason:
        lines.append("")
        lines.append("폐지사유(제개정이유):")
        for line in reason.splitlines():
            if line.strip():
                lines.append(f"  {line}")
    lines.append("")
    if successors:
        joined = ", ".join(f"「{name}」" for name in successors)
        lines.append(
            f"후속(통합) 규정: {joined} — search_admin_rule(\"{successors[0]}\")로 "
            "현행 규정을 찾아 그 기준으로 답하세요."
        )
    else:
        org = latest.get("org") or "소관부처"
        lines.append(
            f"후속 규정 이름을 자동으로 찾지 못했습니다. 폐지사유나 "
            f"{org} 제도 키워드로 search_admin_rule을 다시 쓰세요."
        )
    lines.append(
        "폐지된 행정규칙을 현행 기준으로 인용하지 마세요. 답에는 폐지 "
        "사실과 후속 규정을 적으세요."
    )
    return "\n".join(lines)
