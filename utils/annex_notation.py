"""별표·서식 번호 표기를 법제처 6자리 코드로 맞춘다.

'별표 4', '별표 제1호의2', '별지 제17호의12'처럼 사람이 부르는 표기와
API의 AAAABB 코드를 한곳에서만 왕복한다.
"""

from __future__ import annotations

import re

ANNEX_KEYWORDS = ("별표", "서식", "양식", "별지")
_ANNEX_NO = r"(\d{1,6})\s*(?:호)?\s*(?:의\s*(\d{1,2}))?"
_ANNEX_HINT = re.compile(
    rf"(?:{'|'.join(ANNEX_KEYWORDS)})\s*(?:제)?\s*{_ANNEX_NO}\s*(?:서식)?"
)


def parse_annex_number(raw: str) -> tuple[int, int] | None:
    match = re.search(_ANNEX_NO, str(raw or ""))
    if match is None:
        return None
    main = int(match.group(1))
    sub = int(match.group(2)) if match.group(2) else 0
    if main <= 0:
        return None
    return main, sub


def to_annex_code(main: int, sub: int = 0) -> str:
    return f"{int(main):04d}{int(sub):02d}"


def from_annex_code(code: str) -> tuple[int, int] | None:
    text = str(code or "").strip()
    if not re.fullmatch(r"\d{6}", text):
        return None
    main = int(text[:4])
    sub = int(text[4:])
    if main <= 0:
        return None
    return main, sub


def annex_hint_in_query(query: str) -> str:
    """쿼리에 섞인 별표 번호를 6자리 코드 또는 본번호 문자열로 돌려준다."""
    match = _ANNEX_HINT.search(str(query or ""))
    if match is None:
        return ""
    main = int(match.group(1))
    sub = int(match.group(2)) if match.group(2) else 0
    if sub:
        return to_annex_code(main, sub)
    return str(main)


def row_matches_annex_hint(row: dict, hint: str, *, number_field: str = "별표번호") -> bool:
    if not hint:
        return True
    raw = str(row.get(number_field) or "").strip()
    decoded = from_annex_code(raw) if re.fullmatch(r"\d{6}", raw) else parse_annex_number(raw)
    wanted = from_annex_code(hint) if re.fullmatch(r"\d{6}", hint) else parse_annex_number(hint)
    if decoded is None or wanted is None:
        return hint in raw or raw.lstrip("0") == hint.lstrip("0")
    return decoded == wanted


def annex_related_law_name(label: str) -> str:
    """별표·서식 라벨에서 앞의 법령명만 남긴다.

    ``건축법 시행령 별표 1`` → ``건축법 시행령``.
    ``별표 1``처럼 법령명이 없으면 빈 문자열이다.
    """
    title = " ".join(str(label or "").split())
    if not title:
        return ""
    related = re.sub(r"\s*(별표|별지|서식|양식).*$", "", title).strip()
    if related and related != title:
        return related
    return ""
