"""법원 사건번호 추출. 실재 사건부호만 인정한다."""

from __future__ import annotations

import re

# 긴 부호가 짧은 부호보다 앞에 있어야 `재고합`이 `재`로 잘리지 않는다.
CASE_CODES = tuple(
    sorted(
        (
            "가소",
            "가단",
            "가합",
            "가",
            "나",
            "다카",
            "다",
            "머",
            "자",
            "차전",
            "차",
            "카단",
            "카합",
            "카기",
            "카명",
            "카확",
            "카",
            "그",
            "마",
            "라",
            "바",
            "사",
            "아",
            "타",
            "하단",
            "하합",
            "하",
            "고단",
            "고합",
            "고정",
            "고약",
            "고",
            "노",
            "도",
            "오",
            "초",
            "감",
            "전",
            "보",
            "모",
            "로",
            "코",
            "구단",
            "구합",
            "구",
            "누",
            "두",
            "루",
            "부",
            "수",
            "우",
            "주",
            "드단",
            "드합",
            "드",
            "르",
            "므",
            "브",
            "스",
            "너",
            "버",
            "즈단",
            "즈합",
            "즈",
            "느단",
            "느합",
            "느",
            "허",
            "후",
            "취",
            "헌가",
            "헌나",
            "헌다",
            "헌라",
            "헌마",
            "헌바",
            "헌사",
            "헌아",
            "회단",
            "회합",
            "회확",
            "회기",
            "회",
            "개회",
            "개확",
            "간회",
            "간확",
            "파",
            "재고합",
            "재나",
            "재다",
            "재두",
            "재누",
            "재",
        ),
        key=len,
        reverse=True,
    )
)

_CASE_CODE_PATTERN = "(?:" + "|".join(re.escape(code) for code in CASE_CODES) + ")"
_NON_CASE_SYLLABLES = "명개원건회차호년월일조항목억천"
_CASE_NO_RE = re.compile(
    rf"(?<![\d제])(\d{{2,4}})({_CASE_CODE_PATTERN})(\d{{1,7}})"
    rf"(?![\d{_NON_CASE_SYLLABLES}])"
)


def extract_case_numbers(text: str) -> list[str]:
    """본문에서 공백 없는 사건번호만 뽑는다. 예: 2013다61381, 96누4671."""
    found: list[str] = []
    seen: set[str] = set()
    for match in _CASE_NO_RE.finditer(text or ""):
        case_no = f"{match.group(1)}{match.group(2)}{match.group(3)}"
        if case_no not in seen:
            seen.add(case_no)
            found.append(case_no)
    return found


def field_has_exact_case(field: str, case_no: str) -> bool:
    """업스트림 사건번호 필드의 정확 일치. nb= 전방 일치 오인을 막는다."""
    needle = str(case_no or "").replace(" ", "")
    if not needle:
        return False
    return any(
        part == needle
        for part in re.split(r"[,·;/]", str(field or "").replace(" ", ""))
        if part
    )
