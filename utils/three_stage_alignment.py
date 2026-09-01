"""3단 비교 표의 항ㆍ호ㆍ목 분해와 행 선택 계산."""

import re
from html import unescape

from utils.parsing import law_unit_code
from utils.patterns import CIRCLED_NUMBER_MARKERS, KOREAN_ITEM_MARKERS


_LAW_BLOCK_START_PATTERN = re.compile(r'<div class="legal-indent level-[012]"')
_MOK_MARKER_PATTERN = re.compile(rf"^([{KOREAN_ITEM_MARKERS}])\.$")
_BULLET_MARKER_PATTERN = re.compile(
    r'<span class="bullet-marker"[^>]*>(.*?)&nbsp;</span>', re.DOTALL
)


def html_to_plain_text(html: str) -> str:
    """표시용 HTML에서 조문 인용 분석에 쓸 평문을 만든다."""
    text = unescape(re.sub(r"<[^>]+>", " ", html or ""))
    return re.sub(r"\s+", " ", text).strip()


def law_content_blocks(inner_html: str) -> list[dict[str, str]]:
    """본문을 항ㆍ호ㆍ목 덩어리로 나누고 각 단위 코드를 붙인다."""
    starts = [match.start() for match in _LAW_BLOCK_START_PATTERN.finditer(inner_html)]
    if not starts:
        return [{"hang": "", "ho": "", "mok": "", "html": inner_html}]
    blocks: list[dict[str, str]] = []
    if starts[0] > 0:
        blocks.append(
            {"hang": "", "ho": "", "mok": "", "html": inner_html[: starts[0]]}
        )
    bounds = starts + [len(inner_html)]
    current_hang = ""
    current_ho = ""
    for index, start in enumerate(starts):
        chunk = inner_html[start : bounds[index + 1]]
        marker_match = _BULLET_MARKER_PATTERN.search(chunk)
        marker = marker_match.group(1).strip() if marker_match else ""
        hang, ho, mok = current_hang, current_ho, ""
        circled = CIRCLED_NUMBER_MARKERS.find(marker)
        number_match = re.fullmatch(r"(\d+)(?:의(\d+))?\.", marker)
        mok_match = _MOK_MARKER_PATTERN.fullmatch(marker)
        if len(marker) == 1 and circled >= 0:
            current_hang = law_unit_code(str(circled + 1))
            current_ho = ""
            hang, ho, mok = current_hang, "", ""
        elif number_match:
            try:
                current_ho = law_unit_code(
                    number_match.group(1), number_match.group(2) or ""
                )
            except ValueError:
                current_ho = ""
            hang, ho, mok = current_hang, current_ho, ""
        elif mok_match:
            mok = mok_match.group(1)
            hang, ho = current_hang, current_ho
        blocks.append({"hang": hang, "ho": ho, "mok": mok, "html": chunk})
    return blocks


def hang_groups_from_blocks(
    blocks: list[dict[str, str]],
) -> list[list[dict[str, str]]]:
    """항 덩어리와 그에 딸린 호를 묶고 다음 항부터 새 묶음을 만든다."""
    groups: list[list[dict[str, str]]] = []
    current: list[dict[str, str]] = []
    for block in blocks:
        starts_new_hang = bool(block.get("hang") and not block.get("ho"))
        if starts_new_hang and current:
            groups.append(current)
            current = [block]
            continue
        current.append(block)
    if current:
        groups.append(current)
    if (
        len(groups) >= 2
        and not groups[0][0].get("hang")
        and not groups[0][0].get("ho")
        and not groups[0][0].get("mok")
        and not html_to_plain_text("".join(block["html"] for block in groups[0]))
    ):
        groups[1] = groups[0] + groups[1]
        groups = groups[1:]
    return groups


def block_index_for_unit_or_none(
    blocks: list[dict[str, str]], hang: str, ho: str, mok: str = ""
) -> int | None:
    """근거 항ㆍ호ㆍ목이 이 묶음 안에 있으면 인덱스를 돌려준다."""
    if mok:
        for index, block in enumerate(blocks):
            if block.get("mok") != mok:
                continue
            if ho and block.get("ho") != ho:
                continue
            if hang and block.get("hang") and block["hang"] != hang:
                continue
            return index
        return None
    if ho:
        for index, block in enumerate(blocks):
            if block.get("ho") != ho or block.get("mok"):
                continue
            if hang and block.get("hang") and block["hang"] != hang:
                continue
            return index
        for index, block in enumerate(blocks):
            if block.get("ho") != ho:
                continue
            if hang and block.get("hang") and block["hang"] != hang:
                continue
            return index
    if hang:
        for index, block in enumerate(blocks):
            if block.get("hang") == hang and not block.get("ho"):
                return index
    return None


def block_index_for_unit(
    blocks: list[dict[str, str]], hang: str, ho: str, mok: str = ""
) -> int:
    """근거 단위를 찾되 없으면 조문 머리 행(0)을 선택한다."""
    found = block_index_for_unit_or_none(blocks, hang, ho, mok)
    return 0 if found is None else found


def primary_source_unit(units: list[dict[str, str]]) -> tuple[str, str, str]:
    """인용 목록에서 실제 항ㆍ호ㆍ목이 있는 첫 단위를 돌려준다."""
    for unit in units:
        hang = str(unit.get("source_hang") or "")
        ho = str(unit.get("source_ho") or "")
        mok = str(unit.get("source_mok") or "")
        if hang or ho or mok:
            return hang, ho, mok
    return "", "", ""
