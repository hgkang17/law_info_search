"""중앙부처 질의회신 기관을 고른다."""

from __future__ import annotations

import re

from molit_cgm_expc_api import AGENCIES, AGENCY_BY_TARGET, AgencyConfig

_ALL_KEYS = {"", "all", "전체", "전체기관"}


def is_inquiry_target(value: str) -> bool:
    """법제처 중앙부처 질의회신 기관 target인지."""
    return str(value or "").strip() in AGENCY_BY_TARGET


def split_doc_reference(href: str) -> tuple[str, str]:
    """`doc:구분:id`에서 구분과 id를 나눈다.

    질의회신은 `doc:molitCgmExpc:360866`이다. 모델이 행정규칙으로 오인해
    `doc:admrul:molitCgmExpc:360866`처럼 쓰면 기관 target을 찾아 되돌린다.
    """
    raw = str(href or "").strip()
    if raw.startswith("doc:"):
        raw = raw[4:]
    raw = raw.split("?", 1)[0].strip()
    parts = [part.strip() for part in raw.split(":") if part.strip()]
    if not parts:
        return "", ""
    for index, part in enumerate(parts[:-1]):
        if part in AGENCY_BY_TARGET and parts[index + 1]:
            return part, parts[index + 1]
    if len(parts) >= 2:
        return parts[0], ":".join(parts[1:])
    return parts[0], ""


def compact_agency_key(value: str) -> str:
    return re.sub(r"[\s·ㆍ.]", "", str(value or "")).casefold()


def inquiry_title_score(title: str, query: str) -> tuple[int, int]:
    """안건명이 검색어와 얼마나 겹치는지. 앞 기관 순으로 자르지 않기 위해 쓴다."""
    title_key = re.sub(r"\s+", "", str(title or "")).casefold()
    tokens = [
        re.sub(r"\s+", "", token)
        for token in str(query or "").split()
        if len(token) >= 2
    ]
    if not title_key or not tokens:
        return (0, 0)
    hits = sum(1 for token in tokens if token.casefold() in title_key)
    compact_query = "".join(token.casefold() for token in tokens)
    contiguous = 1 if compact_query and compact_query in title_key else 0
    return (hits, contiguous)


def resolve_inquiry_agencies(agency: str = "") -> tuple[AgencyConfig, ...]:
    """기관명·target으로 질의회신 검색 대상을 고른다. 비우면 전체."""
    raw = " ".join(str(agency or "").split())
    if compact_agency_key(raw) in {compact_agency_key(item) for item in _ALL_KEYS}:
        return tuple(AGENCIES)
    compact = compact_agency_key(raw)
    direct = AGENCY_BY_TARGET.get(raw) or AGENCY_BY_TARGET.get(compact)
    if direct is not None:
        return (direct,)
    for item in AGENCIES:
        if item.target.casefold() == compact or compact_agency_key(item.name) == compact:
            return (item,)
    hits = [
        item
        for item in AGENCIES
        if compact in compact_agency_key(item.name)
        or compact in item.target.casefold()
    ]
    if len(hits) == 1:
        return (hits[0],)
    stem = re.sub(r"(부|청|처)$", "", raw)
    if stem and stem != raw:
        stem_key = compact_agency_key(stem)
        stem_hits = [
            item
            for item in AGENCIES
            if item.name.startswith(stem) or stem_key in compact_agency_key(item.name)
        ]
        if len(stem_hits) == 1:
            return (stem_hits[0],)
        if stem_hits:
            hits = stem_hits
    if not hits:
        raise ValueError(
            f"기관 '{agency}'를 찾지 못했습니다. 비우면 전체 기관입니다. "
            "예: 국토교통부, molitCgmExpc"
        )
    names = ", ".join(item.name for item in hits[:8])
    raise ValueError(
        f"기관 '{agency}'가 여러 곳과 맞습니다: {names}. "
        "정식 기관명이나 target을 쓰세요."
    )
