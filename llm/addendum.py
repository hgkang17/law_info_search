"""현행 법령 부칙에서 적용례·경과조치 문장만 고른다."""

from __future__ import annotations

import re

from utils.parsing import json_list, json_text

_TRANSITION_RE = re.compile(
    r"적용례|경과조치|종전의\s*규정|시행\s*전에?|시행\s*당시|"
    r"행위에\s*대하여|예에\s*따른다|불구하고.{0,20}적용"
)


def _flatten_addendum(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        lines: list[str] = []
        for item in value:
            lines.extend(_flatten_addendum(item))
        return lines
    text = json_text(value)
    return [line.strip() for line in text.splitlines() if line.strip()]


def extract_transition_excerpts(
    payload: dict,
    jo_display: str = "",
    *,
    max_addenda: int = 6,
    max_lines: int = 3,
) -> list[tuple[str, list[str]]]:
    """현행 법령 JSON의 부칙단위에서 경과규정 신호를 잘라 낸다.

    해석하지 않는다. 해당 조 언급 줄을 먼저 두고, 적용례·경과조치 신호를
    그다음에 붙인다.
    """
    law = payload.get("법령", payload) if isinstance(payload, dict) else {}
    if not isinstance(law, dict):
        return []
    addenda = law.get("부칙", {})
    units = addenda.get("부칙단위") if isinstance(addenda, dict) else addenda
    found: list[tuple[str, list[str]]] = []
    for unit in json_list(units):
        if len(found) >= max_addenda:
            break
        if not isinstance(unit, dict):
            continue
        lines = _flatten_addendum(unit.get("부칙내용"))
        if not lines:
            continue
        number = json_text(unit.get("부칙공포번호"))
        date = json_text(unit.get("부칙공포일자"))
        header = lines[0]
        if not (header.startswith("부칙") and re.search(r"제\s*\d+\s*호", header)):
            header = f"부칙 <제{number}호, {date}>" if number or date else "부칙"
        jo_hits = [line for line in lines if jo_display and jo_display in line]
        other = [
            line
            for line in lines
            if _TRANSITION_RE.search(line) and line not in jo_hits
        ]
        picked = (jo_hits + other)[:max_lines]
        if not picked:
            continue
        clipped = [
            line if len(line) <= 250 else line[:250] + "…" for line in picked
        ]
        found.append((header, clipped))
    return found
