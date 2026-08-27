"""판례 본문에서 판시사항 발췌와 변경·폐기 신호를 읽는다."""

from __future__ import annotations

import re

from utils.parsing import json_text

_CHANGE_PATTERNS = (
    (re.compile(r"변경하기로\s*(?:한다|하면서|함|하였)"), "판례 변경 선언"),
    (re.compile(r"폐기하기로|폐기한다|폐기되었"), "판례 폐기 선언"),
    (re.compile(r"더\s*이상\s*유지(?:될\s*수\s*없|하기\s*어렵)"), "선례 유지 불가 판시"),
    (
        re.compile(r"배치되는\s*범위\s*에?서?\s*(?:이를\s*)?(?:모두\s*)?변경"),
        "저촉 범위 변경",
    ),
)


def field_text(value: object) -> str:
    """JSON 필드가 문자열·배열·{#text} 중 무엇이든 평문으로 모은다.

    str()로 뭉개면 본문이 '[object Object]'가 되어 변경 문구를 못 찾는다.
    """
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(part for part in (field_text(item) for item in value) if part)
    if isinstance(value, dict):
        wrapped = value.get("#text", value.get("_"))
        if wrapped is not None:
            return field_text(wrapped)
        return " ".join(
            part for part in (field_text(item) for item in value.values()) if part
        )
    return json_text(value).strip()


def extract_holding(
    detail: dict | None, max_chars: int = 240
) -> tuple[str, str] | None:
    """판시사항, 없으면 판결요지를 한두 줄로 잘라 낸다. 전문은 붙이지 않는다."""
    if not isinstance(detail, dict):
        return None
    holding = field_text(detail.get("판시사항"))
    label = "판시사항"
    if not holding:
        holding = field_text(detail.get("판결요지"))
        label = "판결요지"
    clean = re.sub(r"\s+", " ", holding).strip()
    if not clean:
        return None
    if len(clean) > max_chars:
        clean = re.sub(r"\s+\S*$", "", clean[:max_chars]).rstrip() + "…"
    return label, clean


def scan_treatment(
    body: str, target_case_no: str, window: int = 250
) -> tuple[list[str], str]:
    """대상 사건번호(또는 그 별칭) 주변의 변경·폐기 문구를 찾는다."""
    clean = re.sub(r"\s+", " ", body or "")
    target_src = re.sub(
        r"(\d)([가-힣]+)(\d)", r"\1\\s*\2\\s*\3", target_case_no, count=1
    )
    indices: list[int] = [
        match.start() for match in re.finditer(target_src, clean)
    ]
    alias_def = re.compile(
        target_src
        + r"[^(]{0,40}\(\s*이하\s*[‘'\"“]?([^’'\"”)]{2,40}?)[’'\"”]?\s*"
        r"(?:이?라\s*고?\s*)?한다"
    )
    for match in alias_def.finditer(clean):
        alias = match.group(1).strip()
        if not alias:
            continue
        indices.extend(
            found.start() for found in re.finditer(re.escape(alias), clean)
        )
    signals: list[str] = []
    seen: set[str] = set()
    context = ""
    for index in sorted(indices):
        start = max(0, index - window)
        end = min(len(clean), index + window)
        chunk = clean[start:end]
        if not context:
            context = chunk[:300]
        for pattern, label in _CHANGE_PATTERNS:
            if pattern.search(chunk) and label not in seen:
                seen.add(label)
                signals.append(label)
                context = chunk[:300]
    return signals, context
