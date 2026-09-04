"""API 응답과 원문 텍스트를 다루는 순수 함수.

Qt에 의존하지 않으므로 화면 없이도 시험할 수 있다.
"""

from __future__ import annotations

import ast
import re
import xml.etree.ElementTree as ET
from html import unescape

from molit_cgm_expc_api import AgencyConfig

from .patterns import (
    CIRCLED_HANGUL_ITEM_MARKERS,
    CIRCLED_NUMBER_MARKERS,
    KOREAN_ITEM_MARKERS,
    LAW_HEADING_PATTERN,
    LAW_PARAGRAPH_PATTERN,
    ADMIN_RULE_INLINE_KOREAN_ITEM_PATTERN,
    ADMIN_RULE_SENTENCE_TAIL_ITEM_PATTERN,
    _INLINE_PAREN_ITEM_PATTERN,
    _CIRCLED_REFERENCE_TAIL_PATTERN,
    _ADMIN_CLAUSE_REFERENCE_TAIL_PATTERN,
    _PAREN_ITEM_REFERENCE_TAIL_PATTERN,
    _PAREN_ITEM_RANGE_TAIL_PATTERN,
    _PAREN_ITEM_ENUMERATION_TAIL_PATTERN,
    _PAREN_ITEM_RANGE_PREFIX_PATTERN,
    _PAREN_ITEM_PARTICLE_TAIL_PATTERN,
    _PAREN_ITEM_PART_REFERENCE_PATTERN,
    _CIRCLED_PARTICLE_TAIL_PATTERN,
    _CLOSING_PAREN_ITEM_PATTERN,
    _FOOTNOTE_MARK_TAIL_PATTERN,
    _HEADING_RANGE_TAIL_PATTERN,
    _MARKER_ONLY_LINE_PATTERN,
    ADMIN_RULE_PAREN_REFERENCE_LINE_PATTERN,
    ADMIN_RULE_PAREN_ITEM_PATTERN,
    ADMIN_RULE_CLAUSE_PATTERN,
    ADMIN_RULE_CLAUSE_SUBREFERENCE_LINE_PATTERN,
    ADMIN_RULE_NUMBERED_CLAUSE_REFERENCE_PATTERN,
    _CIRCLED_REFERENCE_LINE_PATTERN,
    _SENTENCE_END_SUFFIXES,
    _FRAGMENT_MARKER_PATTERNS,
    _FRAGMENT_LEADING_PARTICLES,
    _BARE_CLAUSE_REFERENCE_PATTERN,
    LAW_REFERENCE_PATTERN,
    _ADJACENT_GAP_PATTERN,
    _ENUMERATION_GAP_PATTERN,
    _LAW_ALIAS_PATTERN,
)


def json_list(value: object) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _python_list_repr_items(text: str) -> list | None:
    """필드 전체가 ``str(리스트)``로 저장된 경우만 항목을 되돌린다.

    본문 속 ``[별표 1]``이나 ``'법'이라 한다``는 Python 리스트가 아니라서
    그대로 둔다. 구버전 캐시는 그 표기를 저장한 뒤 ``제1장`` 앞에서
    줄을 갈라 ``['`` / ``', '``가 본문에 남기도 한다. 줄바꿈만 없애
    다시 읽히면 항목을 되돌리고, 법령 본문 괄호는 읽히지 않는다.
    """
    stripped = str(text or "").strip()
    if not stripped:
        return None
    candidates = [stripped]
    collapsed = stripped.replace("\r\n", "").replace("\n", "").replace("\r", "")
    if collapsed != stripped:
        candidates.append(collapsed)
    for candidate in candidates:
        if len(candidate) < 2 or candidate[0] != "[" or candidate[-1] != "]":
            continue
        try:
            parsed = ast.literal_eval(candidate)
        except (SyntaxError, ValueError, MemoryError, TypeError):
            continue
        if not isinstance(parsed, list) or not parsed:
            continue
        if not all(isinstance(item, (str, dict, list)) for item in parsed):
            continue
        return parsed
    return None


# 법제처 본문의 개정 이력은 ``<개정 2009.7.16>``ㆍ``<신설 2016.1.19>``처럼
# 꺾쇠로 온다. HTML 태그 제거에 함께 지워지지 않도록 이 표기만 골라낸다.
# 안쪽에 꺾쇠가 없고 개정 관련 낱말이 든 것만 보므로 ``<p>``ㆍ``<img …>``
# 같은 실제 태그는 걸리지 않는다.
_AMENDMENT_NOTE_TAG_PATTERN = re.compile(
    r"<[^<>]*(?:개정|신설|삭제|폐지|이동|제정)[^<>]*>"
)


# 조문 끝에 따로 한 줄로 붙는 개정 표기(``[본조신설 2018. 12. 27.]``).
# 화면에서 그 줄만 조문보다 왼쪽으로 튀어나오지 않게 가려낼 때 쓴다.
AMENDMENT_NOTE_LINE_PATTERN = re.compile(
    r"\[(?:전문개정|본조신설|본조제목개정|제목개정|개정|신설|삭제|폐지|제정)"
    r"[^\[\]]*\]"
)


def json_text(value: object) -> str:
    """JSON 필드의 content 래퍼와 검색 강조 태그를 일반 문자열로 정리."""
    if isinstance(value, list):
        parts = [json_text(item) for item in value]
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        inner = value.get("content", "")
        if isinstance(inner, (list, dict)):
            return json_text(inner)
        value = inner
    text = str(value or "")
    dumped = _python_list_repr_items(text)
    if dumped is not None:
        return json_text(dumped)
    # API에 따라 HTML 엔티티가 한 번 더 이스케이프되어
    # ``&amp;#x20;`` → ``&#x20;`` 상태로 남기도 한다. 두 단계까지만
    # 풀어 실제 공백으로 정규화한다.
    for _ in range(2):
        decoded = unescape(text)
        if decoded == text:
            break
        text = decoded
    # 일부 수립지침 원문은 ⑯~⑳을 ``<16>``처럼 제공한다. 일반 HTML
    # 태그 제거보다 먼저 동그라미 번호로 복원하지 않으면 번호만 사라져
    # 앞 항목의 문장에 합쳐진다.
    text = re.sub(
        r"<(20|1\d|[1-9])>",
        lambda match: CIRCLED_NUMBER_MARKERS[int(match.group(1)) - 1],
        text,
    )
    deleted_marker = "\ufff0ADMIN_RULE_DELETED\ufff1"
    text = re.sub(r"<\s*삭제\s*>", deleted_marker, text)
    # ``<개정 2009.7.16, 2010.2.18>``처럼 꺾쇠로 적는 개정 이력은 HTML
    # 태그가 아닌데도 아래 태그 제거에 통째로 지워졌다. 법제처 본문은 이
    # 표기를 조ㆍ항 문장 끝에 두므로, 태그를 지우기 전에 빼돌렸다 되돌린다.
    held_notes: list[str] = []

    def hold_amendment_note(match: re.Match[str]) -> str:
        held_notes.append(match.group(0))
        return f"￰AMENDMENT_NOTE_{len(held_notes) - 1}￱"

    text = _AMENDMENT_NOTE_TAG_PATTERN.sub(hold_amendment_note, text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(?:p|div|li|tr|h[1-6])>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace(deleted_marker, "<삭제>")
    for index, note in enumerate(held_notes):
        text = text.replace(f"￰AMENDMENT_NOTE_{index}￱", note)
    text = text.replace("　", "\n").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip()


ADMIN_RULE_IMAGE_MARKER_PATTERN = re.compile(r"\[\[LAW_IMAGE:(\d+)\]\]")
_ADMIN_RULE_IMAGE_TAG_PATTERN = re.compile(
    r"(?is)<img\b[^>]*\bid\s*=\s*[\"']?(\d+)[\"']?[^>]*>\s*(?:</img\s*>)?"
)
_LAW_IMAGE_CONTAINER_PATTERN = re.compile(
    r"(?is)<img\b(?P<attrs>[^>]*)>(?P<fallback>.*?)</img\s*>"
)
_LAW_IMAGE_OPEN_PATTERN = re.compile(r"(?is)<img\b(?P<attrs>[^>]*)/?>")
_LAW_IMAGE_FLSEQ_PATTERN = re.compile(r"(?i)\bflSeq\s*=\s*(\d+)")
_LAW_IMAGE_ID_ATTR_PATTERN = re.compile(r"(?i)\bid\s*=\s*[\"']?(\d+)")


def _law_image_id(attrs: str) -> str:
    match = _LAW_IMAGE_FLSEQ_PATTERN.search(attrs)
    if match is None:
        match = _LAW_IMAGE_ID_ATTR_PATTERN.search(attrs)
    return match.group(1) if match is not None else ""


def law_text(value: object) -> str:
    """법령 본문 이미지는 위치만 남기고 선문자 대체표는 제거한다.

    법제처 법령 JSON은 ``img`` 태그의 ``src``에 flSeq를 넣으면서 태그
    안쪽에 ``┌─│└``로 그린 대체표를 함께 주는 사례가 있다. 다운로드할
    이미지 번호를 확인한 경우에만 그 대체표 전체를 이미지 토큰 하나로
    바꾼다. 번호 없는 태그의 안쪽 텍스트는 정보 유실을 막기 위해 보존한다.
    """
    if isinstance(value, list):
        parts = [law_text(item) for item in value]
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        inner = value.get("content", "")
        if isinstance(inner, (list, dict)):
            return law_text(inner)
        value = inner
    text = str(value or "")
    for _ in range(2):
        decoded = unescape(text)
        if decoded == text:
            break
        text = decoded

    def replace_container(match: re.Match[str]) -> str:
        image_id = _law_image_id(match.group("attrs"))
        if image_id:
            return f"\n[[LAW_IMAGE:{image_id}]]\n"
        return match.group("fallback")

    def replace_open_tag(match: re.Match[str]) -> str:
        image_id = _law_image_id(match.group("attrs"))
        return f"\n[[LAW_IMAGE:{image_id}]]\n" if image_id else ""

    text = _LAW_IMAGE_CONTAINER_PATTERN.sub(replace_container, text)
    text = _LAW_IMAGE_OPEN_PATTERN.sub(replace_open_tag, text)
    return json_text(text)


def admin_rule_text(value: object) -> str:
    """행정규칙 원문의 이미지 위치를 보존하면서 텍스트를 정리한다."""
    if isinstance(value, list):
        parts = [admin_rule_text(item) for item in value]
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        # 행정규칙에 따라 본문이 문자열로 바로 오기도 하고
        # ``조문: {조문내용: [...]}``, ``부칙: {부칙내용: [...]}``처럼
        # 한 단계 더 감싸져 오기도 한다.
        parts = [
            admin_rule_text(value.get(key))
            for key in ("content", "조문내용", "부칙내용")
            if value.get(key) is not None
        ]
        return "\n".join(part for part in parts if part)
    text = str(value or "")
    for _ in range(2):
        decoded = unescape(text)
        if decoded == text:
            break
        text = decoded
    text = _ADMIN_RULE_IMAGE_TAG_PATTERN.sub(
        lambda match: f"\n[[LAW_IMAGE:{match.group(1)}]]\n",
        text,
    )
    return json_text(text)


def admin_rule_plain_text(value: str) -> str:
    """복사·검색용 평문에서는 내부 이미지 토큰 대신 짧은 설명을 쓴다."""
    return ADMIN_RULE_IMAGE_MARKER_PATTERN.sub("[원문 표 이미지]", str(value or ""))


def _is_marker_fragment(text: str) -> bool:
    remainder = text
    for _ in range(12):
        peeled = _peel_fragment_layer(remainder)
        if peeled is None:
            break
        remainder = peeled
    return len(remainder.strip()) == 0


def _peel_fragment_layer(text: str) -> str | None:
    for pattern in _FRAGMENT_MARKER_PATTERNS:
        match = pattern.match(text)
        if match:
            return match.group(2)
    for particle in _FRAGMENT_LEADING_PARTICLES:
        if text.startswith(particle):
            return text[len(particle) :]
    return None


def merge_marker_reference_fragments(lines: list[str]) -> list[str]:
    """"①(1)의①부터⑥까지의 어느 하나에 해당하는 경우"처럼 문장 안에서
    다른 항목을 가리키는 표현이 원문 API에서 "①" / "(1)의" / "①부터" /
    "⑥까지의..."로 조각조각 끊겨 오는 경우가 있다. 표식만 있고 실제
    내용이 전혀 없는(또는 조사만 남는) 줄은 다음 줄과 계속 합쳐서
    실질적인 내용이 나올 때까지 하나의 줄로 복원한다."""
    result: list[str] = []
    pending = ""
    for line in lines:
        pending = pending + line if pending else line
        if _is_marker_fragment(pending):
            continue
        result.append(pending)
        pending = ""
    if pending:
        result.append(pending)
    return result


def merge_circled_reference_lines(lines: list[str]) -> list[str]:
    """지침 항목 안에서 인용한 동그라미 번호 줄을 원래 항목에 붙인다.

    예를 들어 API 전처리의 이전 결과인 ``⑩ / ①ㆍ / ②ㆍ / ... /
    ⑨의 규정``이나 ``⑦ 상기 / ① 및 / ②의 규정``은 새 항목들의
    나열이 아니라 한 문장 안의 참조번호다. 번호 뒤가 가운데점·접속사·
    조사인 경우만 앞줄에 붙여 실제 새 항목과 구별한다.
    """
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if result and _CIRCLED_REFERENCE_LINE_PATTERN.match(stripped):
            previous = result[-1].rstrip()
            separator = "" if previous.endswith(("ㆍ", "·", ",")) else " "
            result[-1] = f"{previous}{separator}{stripped}"
        else:
            result.append(stripped)
    return result


def merge_bare_clause_reference(lines: list[str]) -> list[str]:
    """"...변경 등\n1-6-2-1.의 각 검토가...생략할 수 있다."처럼, 문장이
    다른 지침 항목 번호를 그대로 인용하며 이어지는 경우가 있다. 정상
    항목은 "1-6-2-1. 계획설명서에는..."처럼 번호 뒤에 공백이 있는데,
    이런 인용은 번호 바로 뒤에 공백 없이 조사가 붙는다. 이 신호로
    새 항목이 아니라 앞 문장이 이어지는 것으로 보고 이전 줄에 붙인다."""
    result: list[str] = []
    for line in lines:
        if _BARE_CLAUSE_REFERENCE_PATTERN.match(line) and result:
            result[-1] = result[-1] + line
        else:
            result.append(line)
    return result


def merge_sentence_tail_item_lines(lines: list[str]) -> list[str]:
    """줄 앞으로 밀려난 문장 끝 ``다.``를 앞 줄에 되돌린다.

    원문 API는 ``...명칭을 사용할 수 있`` / ``다.)``처럼 문장 한가운데서
    줄을 끊어 보내는 경우가 있다. 그대로 두면 ``다.``가 목 표지로 읽혀
    ``가.ㆍ나.`` 다음의 새 목처럼 들여쓰기되어 나온다. 표지 뒤에 닫는
    괄호나 따옴표만 남는 줄은 목이 될 수 없으므로 앞 줄 끝에 붙인다.
    끊긴 자리가 낱말 중간이므로 사이에 공백을 넣지 않는다.
    """
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if result and ADMIN_RULE_SENTENCE_TAIL_ITEM_PATTERN.match(stripped):
            result[-1] = result[-1].rstrip() + stripped
        else:
            result.append(line)
    return result


def split_inline_paren_items(line: str) -> list[str]:
    """원문 API가 "(1) ...(2) ...(3) ..."처럼 항목을 한 줄에 이어붙여
    보내는 경우가 있다. "7-3-2-2. 지형(1) ...(2) ..."처럼 (1) 앞에 짧은
    표제가 붙어 있는 경우도 있어, (1)이 줄 맨 앞이 아니어도 된다.
    이미 앞 항목들이 별도 줄인 원문은 ``(3) ...(4) ...(5) ...``처럼
    중간 번호부터 이어지기도 한다. 이 경우에는 첫 번호가 줄 맨 앞에
    있을 때만 허용한다. 어느 쪽이든 번호가 정확히 이어질 때만 쪼개서,
    문장 속 참조나 "(20260701)" 같은 괄호 숫자를 잘못 자르지 않는다."""
    matches = [
        match
        for match in _INLINE_PAREN_ITEM_PATTERN.finditer(line)
        # ``3-2-8-1. (3)에 해당하는``의 (3)은 목록이 아니라 다른
        # 지침 항목의 참조다. 화면 변환 단계가 정규화된 문장을 다시
        # 훑더라도 새 항목으로 재분리하지 않는다.
        if not _PAREN_ITEM_REFERENCE_TAIL_PATTERN.match(line, match.end())
        # ``※ (1) 단서 중``은 목록이 아니라 각주 번호다.
        and not _FOOTNOTE_MARK_TAIL_PATTERN.search(line, 0, match.start())
        # ``(1), (2), (3) 및 (4)의 개정규정은``처럼 번호만 이어 적는
        # 나열도 목록이 아니라 인용이다. 부칙에서 흔한 표기라, 쪼개면
        # 부칙 한 문장이 번호마다 토막 나 화면에 흩어졌다.
        and not _PAREN_ITEM_ENUMERATION_TAIL_PATTERN.match(line, match.end())
    ]
    for first_index, first in enumerate(matches):
        # ``(1)부터(3)까지``, ``(1) 부터 (4)까지``는 연속 목록이 아니라
        # 범위를 가리키는 한 표현이다. 뒤의 (3)ㆍ(4)을 새 항목으로
        # 쪼개지 않도록 목록 판정보다 먼저 제외한다.
        if _PAREN_ITEM_RANGE_TAIL_PATTERN.match(line, first.end()):
            continue
        first_number = int(first.group(1))
        starts_line = not line[: first.start()].strip()
        if first_number != 1 and not starts_line:
            continue
        positions = [first.start()]
        expected = first_number + 1
        for match in matches[first_index + 1 :]:
            number = int(match.group(1))
            if starts_line:
                # 이미 괄호 번호로 시작한 목록 줄은 API에서 일부 항목이
                # 누락되어 (13) 다음이 (16)으로 이어지기도 한다. 뒤 번호가
                # 증가하기만 하면 새 항목으로 본다.
                if number < expected:
                    continue
            elif number != expected:
                break
            positions.append(match.start())
            expected = number + 1
        if len(positions) < 2:
            continue
        pieces: list[str] = []
        prefix = line[: positions[0]].strip()
        if prefix:
            pieces.append(prefix)
        for index, start in enumerate(positions):
            end = (
                positions[index + 1]
                if index + 1 < len(positions)
                else len(line)
            )
            piece = line[start:end].strip()
            if piece:
                pieces.append(piece)
        return pieces
    return [line]


def split_inline_closing_paren_items(line: str) -> list[str]:
    """API가 ``용도1) 발전용2) 산업용``처럼 붙여 보낸 세부항목 복원.

    1)부터 시작해 번호가 연속해서 두 개 이상 확인될 때만 목록으로
    분리한다. 따라서 문장 속 단독 ``1)``이나 번호가 건너뛴 표기는
    임의로 자르지 않는다.
    """
    # ``1) 용도, 2) 규모``만 대상으로 한다. ``※ (1)과 (2)에 따른``의
    # 괄호 번호는 숫자 앞에 여는 괄호가 있으므로 닫는 괄호형 목록에서
    # 제외한다.
    matches = list(_CLOSING_PAREN_ITEM_PATTERN.finditer(line))
    for first_index, first in enumerate(matches):
        if int(first.group(1)) != 1:
            continue
        positions = [first.start()]
        expected = 2
        for match in matches[first_index + 1 :]:
            number = int(match.group(1))
            if number != expected:
                break
            positions.append(match.start())
            expected += 1
        if len(positions) < 2:
            continue
        pieces: list[str] = []
        prefix = line[: positions[0]].strip()
        if prefix:
            pieces.append(prefix)
        for index, start in enumerate(positions):
            end = positions[index + 1] if index + 1 < len(positions) else len(line)
            piece = line[start:end].strip()
            if piece:
                pieces.append(piece)
        return pieces
    return [line]


def split_label_before_first_paren_item(lines: list[str]) -> list[str]:
    """"7-3-2-2. 지형(1) 기존 지형의..." 다음 줄이 "(2) ..."로 시작하는
    경우처럼, (2) 이후 항목은 이미 줄이 나뉘어 있는데 (1)만 앞의 짧은
    표제와 한 줄에 붙어 오는 경우가 있다. 다음 줄이 실제로 "(2)"로
    시작할 때만 (1) 앞에서 잘라 표제와 (1) 항목을 분리한다."""
    result: list[str] = []
    for index, line in enumerate(lines):
        match = re.search(r"\(1\)", line)
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if match and match.start() > 0 and next_line.startswith("(2)"):
            prefix = line[: match.start()].strip()
            rest = line[match.start() :].strip()
            if prefix:
                result.append(prefix)
            if rest:
                result.append(rest)
        else:
            result.append(line)
    return result


def split_paren_item_after_sentence_end(
    line: str, *, administrative_rule: bool = False
) -> list[str]:
    """"...대체하려는 경우(2) 환경성 검토를..." 처럼, 완결된 문장 바로
    뒤에 다음 항목 번호 "(N)"이 줄바꿈 없이 붙어 오는 경우를 분리한다.
    직전 내용이 문장을 끝맺는 어미로 끝날 때만 자른다(우연히 등장한
    괄호 숫자까지 잘못 자르지 않도록)."""
    for match in _INLINE_PAREN_ITEM_PATTERN.finditer(line):
        if match.start() == 0:
            continue
        tail = line[match.end() :].lstrip()
        if _FOOTNOTE_MARK_TAIL_PATTERN.search(line, 0, match.start()):
            continue
        # ``(1)부터(3)까지``와 ``(1) ~ (8)의``는 새 항목이 아니라
        # 범위 참조다. 앞 문장이 완결형이어도 여기서는 자르지 않는다.
        if _PAREN_ITEM_RANGE_PREFIX_PATTERN.match(tail):
            continue
        # ``경우 (1)에서 정한 변경``처럼 괄호번호 뒤에 조사가 붙으면
        # 새 목록이 아니라 앞 문장의 참조다. HTML 변환 단계에서 이미
        # 병합한 참조를 다시 분리하지 않는다.
        if administrative_rule and _PAREN_ITEM_PARTICLE_TAIL_PATTERN.match(
            tail
        ):
            continue
        # ``3-2-7-1. (3) ③에서 정하는``도 같은 조항 내부 참조다.
        # 정규화 단계에서 붙인 문장을 HTML 변환 단계가 다시 (3) 항목으로
        # 분리하지 않도록 동그라미 번호+조사 형식도 제외한다.
        if administrative_rule and _CIRCLED_PARTICLE_TAIL_PATTERN.match(tail):
            continue
        # ``④ ... (2) 단서에 따른 경우``의 (2)는 새 하위항목이
        # 아니라 다른 항목의 특정 부분을 가리키는 참조다.
        if _PAREN_ITEM_PART_REFERENCE_PATTERN.match(tail):
            continue
        prefix = line[: match.start()].rstrip()
        circled_prefix = LAW_PARAGRAPH_PATTERN.match(prefix)
        completed_circled_item = bool(
            circled_prefix and circled_prefix.group(2).strip()
        )
        if prefix.endswith(_SENTENCE_END_SUFFIXES) or (
            administrative_rule and completed_circled_item
        ):
            rest = line[match.start() :].strip()
            pieces = []
            if prefix:
                pieces.append(prefix)
            if rest:
                # 한 줄에 ``...것(5) ...경우(6) ...``처럼 같은 단계의
                # 다음 항목이 여러 개 붙을 수 있으므로 나머지도 반복해
                # 분리한다.
                pieces.extend(
                    split_paren_item_after_sentence_end(
                        rest,
                        administrative_rule=administrative_rule,
                    )
                )
            return pieces
    return [line]


# 자기 조문 표지. ``제5조에 따른`` 같은 인용은 괄호·삭제 표가 없어 빼 둔다.
_LAW_STYLE_ARTICLE_TOKEN = re.compile(r"제\d+조(?:의\d+)?(?:\s*\(|\s*<|\s+삭제)")

_ADMIN_RULE_STRUCTURE_MARK = re.compile(
    r"(?P<div>제\d+(?:편|장|절|관))"
    r"|(?P<article>제\d+조(?:의\d+)?(?:\s*\(|\s*<|\s+삭제))"
    # 연도(2025-03-31.)는 빼고, 수립지침 번호(1-1-1. · 8-2-1.)만 본다.
    r"|(?P<guide>(?<!\d)[1-9]\d?-\d{1,3}(?:-\d{1,3})*\.)"
)


def uses_guideline_numbering(text: str) -> bool:
    """행정규칙 본문이 수립지침식 ``1-1-1.`` 번호인지.

    앞부분에서 편·장·절·관을 건너뛰고 첫 조항 표지만 본다.
    ``제1조(목적)``이면 법령 번호, ``1-1-1.``이면 지침 번호다.
    둘 다 없으면 기존처럼 지침 번호로 본다.
    """
    sample = str(text or "")[:8000]
    if not sample.strip():
        return True
    for match in _ADMIN_RULE_STRUCTURE_MARK.finditer(sample):
        if match.group("div"):
            continue
        if match.group("guide"):
            return True
        if match.group("article"):
            return False
    return True


def insert_law_style_article_breaks(text: str) -> str:
    """법령 번호체계 행정규칙에서 ``총칙제1조(목적)``처럼 붙은 조 표지를 줄로 나눈다.

    장·절 제목 뒤나 한글이 바로 붙은 자기 조문만 가른다. ``제5조에 따른``
    인용은 괄호가 없어 건드리지 않는다.
    """
    if not text or not _LAW_STYLE_ARTICLE_TOKEN.search(text):
        return text
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line
        if not _LAW_STYLE_ARTICLE_TOKEN.search(line):
            lines.append(line)
            continue
        stripped = line.strip()
        if not stripped:
            lines.append(line)
            continue
        start = 0
        for match in _LAW_STYLE_ARTICLE_TOKEN.finditer(stripped):
            if match.start() == start:
                continue
            prefix = stripped[start : match.start()].strip()
            previous = stripped[match.start() - 1]
            if (
                prefix.endswith(".")
                or prefix.endswith("삭제")
                or LAW_HEADING_PATTERN.match(prefix)
                or (not previous.isspace() and previous not in "([「」")
            ):
                if prefix:
                    lines.append(prefix)
                start = match.start()
        remainder = stripped[start:].strip()
        if remainder:
            lines.append(remainder)
    return "\n".join(lines)


def normalize_admin_rule_text(
    text: str, *, guideline: bool | None = None
) -> str:
    """행정규칙 본문을 번호체계에 맞는 줄바꿈으로 정규화한다.

    수립지침식은 기존 ``insert_admin_clause_breaks``만 쓴다. 그 함수의
    정규식은 여기서 바꾸지 않는다. 법령식만 그 결과 위에 조 표지 분리를
    한 겹 더 얹는다. ``guideline``을 넘기면 앞부분 번호체계를 다시 보지
    않는다.
    """
    if not text:
        return text
    dumped = _python_list_repr_items(text) if isinstance(text, str) else None
    if dumped is not None:
        text = json_text(dumped)
    if guideline is None:
        guideline = uses_guideline_numbering(text)
    normalized = insert_admin_clause_breaks(text)
    if guideline:
        return normalized
    return insert_law_style_article_breaks(normalized)


def extract_admin_rule_article(
    text: str, article_number: str, article_branch: str = ""
) -> str:
    """행정규칙 전문에서 지정한 제N조(의M)만 돌려준다."""
    normalized = normalize_admin_rule_text(str(text or ""))
    if not normalized:
        return ""
    try:
        target = (int(article_number or 0), int(article_branch or 0))
    except (TypeError, ValueError):
        return ""
    selected: list[str] = []
    collecting = False
    for line in normalized.splitlines():
        match = re.match(r"^제\s*(\d+)조(?:의\s*(\d+))?", line.strip())
        if match:
            current = (int(match.group(1)), int(match.group(2) or 0))
            if collecting and current != target:
                break
            collecting = current == target
        if collecting:
            selected.append(line)
    return "\n".join(selected).strip()


def insert_admin_clause_breaks(text: str) -> str:
    """훈령·예규·지침처럼 원문에 줄바꿈이 거의 없는 행정규칙 조문을 위해,
    '1-1-1.' 식 조항번호·'(1)' 식 하위번호·■·○·'제N편/장/절' 앞의
    줄바꿈을 보정한다."""
    if not text:
        return text
    # 이미 잘린 구버전 캐시의 각주 번호를 먼저 되붙인 뒤, 전체 파싱이
    # 끝날 때까지 괄호 번호를 보호한다. 중간의 일반 항목 분리 정규식이
    # ``※ (1)``을 다시 새 (1) 항목으로 자르는 것을 막는다.
    text = re.sub(r"(※)\s*\n\s*(\(\d+\))", r"\1 \2", text)
    text = re.sub(
        r"※\s*\((\d+)\)",
        lambda match: f"※ \ufff0ADMIN_RULE_FOOTNOTE_{match.group(1)}\ufff1",
        text,
    )
    # 구버전 캐시나 API 원문에서 괄호 번호 범위가 중간에 잘린 경우를
    # 먼저 복구한다: ``(3)부터\n(5) 까지를``. 시작·끝 조사까지 모두
    # 확인하므로 독립된 (3), (5) 항목에는 적용되지 않는다.
    text = re.sub(
        r"(\(\d+\)\s*부터)\s*\n\s*(\(\d+\)\s*까지)",
        r"\1 \2",
        text,
    )
    # ``3-2-8-3.의\n(5)ㆍ(6)에 따른``은 하위항목이 아니라 앞 지침
    # 번호의 조항 열거 참조다. 열거기호와 마지막 조사가 함께 있을 때만
    # 원래 문장에 붙인다.
    text = re.sub(
        r"(\d+(?:-\d+)+\.\s*의)\s*\n\s*"
        r"(\(\d+\)(?:\s*[ㆍ·,]\s*\(\d+\))+\s*"
        r"(?:의|에|에서|부터|까지|대로|와|과|를|을))",
        r"\1 \2",
        text,
    )
    # 이전 보정 규칙으로 날짜의 월ㆍ일이 목록 번호처럼 잘려 저장된
    # 수립지침도 API를 다시 받지 않고 열 때 복구한다.
    text = re.sub(
        r"(\b\d{4}\.)[ \t]*\n?[ \t]*(\d{1,2}\.)"
        r"[ \t]*\n?[ \t]*(\d{1,2}\.)",
        r"\1 \2 \3",
        text,
    )
    # 구버전 보정 또는 API 원문이 ``건축선(\n3-10-1.에 따른 ...``처럼
    # 괄호 안의 지침 참조번호 앞에서 끊긴 경우 먼저 되붙인다.
    text = re.sub(
        r"\(\s*\n\s*(\d+(?:-\d+)+\.)",
        r"(\1",
        text,
    )
    # 원문에 닫는 대괄호 없이 ``한다.[3-4-2.``처럼 다음 지침 번호가
    # 붙는 경우가 있다. 문장 종결부 뒤의 고립된 여는 괄호만 제거하고
    # 다음 연속 항목을 새 줄로 복구한다.
    text = re.sub(
        r"(?<=[.!?])\s*\[\s*(\d+(?:-\d+)+\.)",
        r"\n\1",
        text,
    )
    # 삭제된 수립지침 조항은 원문에서 마침표 없이 ``1-7-1-1 삭제``로
    # 제공된다. 화면 평문에 붙은 경우에도 '삭제' 조항에 한해서 번호 앞
    # 경계를 복구하되, 일반 문장 속 숫자열에는 적용하지 않는다.
    text = re.sub(
        r"(?<![\d\n-])(\d+(?:-\d+)+)(?=\s*삭제"
        r"(?=\s|$|\d+(?:-\d+)+|제\d+(?:편|장|절|관)))",
        r"\n\1",
        text,
    )
    # 구버전 화면 평문에는 소수점 뒤가 벌어진 ``0. 753-2-2-4.`` 형태도
    # 남아 있다. 먼저 0.75와 다음 지침 번호 3-2-2-4.로 복구한다.
    text = re.sub(
        r"(?<!\d)(\d+\.)[ \t]*\n?[ \t]*(\d{1,2})(\d+(?:-\d+)+\.)",
        r"\1\2\n\3",
        text,
    )
    # API 원문에서 계산 결과의 소수와 다음 수립지침 번호가 붙는 경우가 있다.
    # 예: ``... = 0.753-2-2-4. 지구단위계획...``. 여기서 0.75는 앞
    # 문장의 값이고 3-2-2-4.부터 새 항목이므로 둘 사이만 분리한다.
    text = re.sub(
        r"(?<!\d)(\d+\.\d{1,2})(\d+(?:-\d+)+\.)",
        r"\1\n\2",
        text,
    )
    # 구버전 파싱에서 ``0.``을 번호로 보아 계산식과 소수값 사이에 이미
    # 줄바꿈이 들어간 경우도 되돌린다: ``=\n0.75\n3-2-2-4.``.
    text = re.sub(
        r"(?m)(=\s*)\n\s*(\d+\.\d+)(?=\n\d+(?:-\d+)+\.)",
        lambda match: f"{match.group(1).rstrip()} {match.group(2)}",
        text,
    )
    sparse_layout = text.count("\n") <= len(text) / 200
    def clause_break(match: re.Match[str]) -> str:
        # ``2-6-6.의 계획도서``처럼 번호 바로 뒤에 조사가 붙으면 다른
        # 항목을 인용한 문장이다. 실제 항목(``2-6-8. 주민제안...``)과
        # 구분하지 않으면 인용 번호에서 문단이 끊기고 다음 항목의 경계도
        # 함께 무너진다.
        # 꼬리를 슬라이스로 떠서 넘기면 매치마다 본문 나머지를 통째로
        # 복사한다. 조문이 길수록 제곱으로 늘어나므로 위치만 넘긴다.
        if _ADMIN_CLAUSE_REFERENCE_TAIL_PATTERN.match(text, match.end()):
            return match.group(1)
        # ``4-2-1-8., 8-1-2-5 및 8-1-3-3의 개정규정``처럼 번호만 이어
        # 적는 나열도 인용이다. 부칙 한 문장이 번호마다 토막 났다.
        if _PAREN_ITEM_ENUMERATION_TAIL_PATTERN.match(text, match.end()):
            return match.group(1)
        return f"\n{match.group(1)}"

    text = re.sub(
        r"(?<![\d\n\-(])(\d+(?:-\d+)+\.)",
        clause_break,
        text,
    )
    # 수립지침 API에는 ``3-1-2-2. 전용주거지역(1) 공통기준``처럼
    # 조항 제목과 첫 하위 항목이 붙어서 내려오는 경우가 있다. 일반적인
    # 괄호 숫자와 달리 지침 번호로 시작한 줄의 ``(1) + 본문``은 독립
    # 항목이므로 제목 아래로 내린다.
    text = re.sub(
        r"(?m)^(\d+(?:-\d+)+\.\s+[^\n]*?)"
        rf"(\((?:\d+|[{KOREAN_ITEM_MARKERS}])\))"
        r"(?!\s+(?:부터|까지|내지|에서|에|의|항|호|목|및|또는)(?=\s|$))"
        r"(?=\s+\S)",
        r"\1\n\2",
        text,
    )
    text = re.sub(
        r"(?<!\n)(?<!^)(?<![0-9A-Za-z가-힣])"
        rf"(\((?:\d+|[{KOREAN_ITEM_MARKERS}])\))"
        r"(?!\s+(?:부터|까지|내지|에서|에|의|항|호|목|및|또는)(?=\s|$))"
        r"(?=\s+\S)",
        r"\n\1",
        text,
    )
    # API의 ``(3) 에 해당``, ``(4) 의 규정``처럼 참조번호와 조사
    # 사이에 낀 공백은 목록 구분이 아니므로 정상 표기로 붙인다.
    text = re.sub(
        rf"(\((?:\d+|[{KOREAN_ITEM_MARKERS}])\))\s+"
        r"(에서|에|의|부터|까지)(?=\s|\()",
        r"\1\2",
        text,
    )
    def circled_break(match: re.Match) -> str:
        # ``⑩ ①ㆍ②ㆍ⑤ㆍ⑥ㆍ⑧ 및 ⑨의 규정``의 ①~⑨는 새 항목이
        # 아니라 ⑩ 본문에서 다른 항목을 가리키는 참조번호다.
        if _CIRCLED_REFERENCE_TAIL_PATTERN.match(text, match.end()):
            return match.group(1)
        return f"\n{match.group(1)}"

    text = re.sub(
        rf"(?<!\n)(?<!^)([{CIRCLED_NUMBER_MARKERS}{CIRCLED_HANGUL_ITEM_MARKERS}])",
        circled_break,
        text,
    )
    # ``기준년도(○○01년)~목표년도(○○10년)``의 연속 동그라미는
    # 연도 자리표시자이지 목록 기호가 아니다. 단독 ○ 항목을 나누기 전에
    # 보호하고, 기호 줄바꿈 처리가 끝난 뒤 원래 표기로 되돌린다.
    year_placeholder = "\ufff0ADMIN_RULE_YEAR_PLACEHOLDER\ufff1"
    text = re.sub(
        r"○\s*○\s*(?=\d{2,4}년)",
        year_placeholder,
        text,
    )
    symbol_markers = "■□○◦●•◎◇◆▪▫"
    text = re.sub(
        rf"(?<!\n)(?<!^)\s*([{symbol_markers}])\s*",
        r"\n\1 ",
        text,
    )
    text = re.sub(
        rf"(?m)^([{symbol_markers}])\s*",
        r"\1 ",
        text,
    )
    text = text.replace(year_placeholder, "○○")
    if sparse_layout:
        text = re.sub(
            # ``2002. 12. 31.`` 같은 시행일을 12번ㆍ31번 항목으로
            # 오인하지 않는다. 월은 네 자리 연도 뒤, 일은 한두 자리
            # 월 뒤에 오므로 각각 고정 길이 lookbehind로 제외한다.
            # ``5의2.``ㆍ``5의3.``처럼 가지번호가 붙은 호는 통째로 한
            # 표지다. 뒷자리만 잘라내면 ``말한다.5의`` + ``2. 삭제``로
            # 쪼개져 번호가 실제 조문과 어긋나므로, 가지번호를 표지에
            # 포함하고 ``의`` 뒤에서는 자르지 않는다.
            r"(?<![\d\n\-의])(?<!\d{4}\. )(?<!\d{2}\. )(?<!\d\. )"
            r"(\d{1,2}(?:의\d{1,2})?\.)\s+",
            lambda match: f"\n{match.group(1)} ",
            text,
        )

    # 3단비교 API의 조문은 다른 항·호에 줄바꿈이 충분히 들어 있어도
    # 목(가.ㆍ나.ㆍ다.)만 한 줄로 이어 붙여 보내는 경우가 있다. 따라서
    # sparse_layout 여부와 관계없이 독립 목 표식을 복원한다. 한글 단어
    # 끝의 ``가.``(예: ``결과.``)는 앞에 다른 한글이 붙어 있으므로 이
    # 패턴에 걸리지 않는다.
    text = ADMIN_RULE_INLINE_KOREAN_ITEM_PATTERN.sub(
        lambda match: f"\n{match.group(1)} ",
        text,
    )

    # 3단비교 API에는 목 표식 앞 공백까지 빠져 ``경우가. 주차장`` 또는
    # ``폐차장나. 도시공원``처럼 앞 문장ㆍ항목과 붙어 오는 응답도 있다.
    # 단어 끝의 평범한 ``가.``를 무조건 자르면 오탐이 많으므로, 한 줄
    # 안에서 가.→나.→다.가 순서대로 모두 확인되는 목록만 복원한다.
    korean_item_order = KOREAN_ITEM_MARKERS
    # ``바. 삭제 사. 도시혁신구역...``처럼 표지 앞에 공백이 하나라도
    # 있으면 앞 단계가 그 자리에서 줄을 가른다. 그러면 남은 줄이
    # ``사.``로 시작해 가.부터 세는 연쇄에 걸리지 않아 뒤따르는 아.ㆍ자.가
    # 앞 문장에 붙은 채 남는다. 줄 첫머리 표지를 연쇄의 시작점으로 삼는다.
    leading_item_pattern = re.compile(
        rf"^([{KOREAN_ITEM_MARKERS}])\.[ \t]"
    )
    repaired_lines: list[str] = []
    for line in text.splitlines():
        # 붙어 온 목 표식도 반드시 ``가. 내용``처럼 마침표 뒤에 공백과
        # 실제 본문이 있어야 한다. ``...사용할 수 있다.)``의 문장 종결
        # ``다.``는 뒤가 닫는 괄호이므로 목 표식 후보에서 제외한다.
        candidates = list(
            re.finditer(
                rf"[{KOREAN_ITEM_MARKERS}]\.[ \t]+(?=[^\s)])",
                line,
            )
        )
        chain: list[re.Match[str]] = []
        expected_index = 0
        # 줄 첫머리 표지도 목록의 증거 한 개로 센다. 표지가 순서대로
        # 필요한 개수만큼 확인될 때만 잘라 오탐을 막는다.
        leading_match = leading_item_pattern.match(line)
        leading_evidence = 0
        if leading_match:
            expected_index = (
                korean_item_order.index(leading_match.group(1)) + 1
            )
            leading_evidence = 1
            candidates = [
                candidate for candidate in candidates if candidate.start() > 0
            ]
        for candidate in candidates:
            marker_index = korean_item_order.index(candidate.group(0)[0])
            if marker_index == expected_index:
                chain.append(candidate)
                expected_index += 1
            elif (
                marker_index == 0
                and expected_index < 3
                and leading_match is None
            ):
                chain = [candidate]
                expected_index = 1
        # ``...다음 각 목의 시설로서 ... 말한다.가. 둘 이상의...``처럼
        # 목록을 예고하고 문장이 끝난 자리에 붙어 온 표지는 둘만
        # 이어져도 목록으로 본다. 8호 ``광역시설``처럼 목이 가.ㆍ나.
        # 둘뿐인 조문이 실제로 있다. 예고 문구가 없거나 표지가 낱말
        # 중간에서 시작하면(``신청한 자가.``) 종전처럼 셋을 요구한다.
        announces_items = False
        if chain and chain[0].start() > 0:
            intro = line[: chain[0].start()]
            announces_items = bool(
                intro.endswith(".") and re.search(r"각\s*목", intro)
            )
        required_evidence = 2 if announces_items else 3
        if leading_evidence + len(chain) >= required_evidence:
            for candidate in reversed(chain):
                position = candidate.start()
                if position > 0 and line[position - 1] != "\n":
                    line = line[:position].rstrip() + "\n" + line[position:]
        repaired_lines.append(line)
    text = "\n".join(repaired_lines)

    # 한 줄에 (1)~(N)이 연속된 진짜 목록은 번호가 순서대로 이어지는지
    # 확인한 뒤 모두 분리한다. 단독 ``상기 (1)에서`` 같은 참조는 연속
    # 번호가 아니므로 이 단계에서도 그대로 유지된다.
    expanded_paren_lines: list[str] = []
    for line in text.splitlines():
        for paren_line in split_inline_paren_items(line):
            for sentence_line in split_paren_item_after_sentence_end(
                paren_line,
                administrative_rule=True,
            ):
                expanded_paren_lines.extend(
                    split_inline_closing_paren_items(sentence_line)
                )
    text = "\n".join(expanded_paren_lines)

    # 장·절 인용(예: "환경성검토(제7편 참조)")은 문단 제목이 아니다.
    # 문장 끝 뒤에 나오거나, 이미 편·장·절 제목으로 시작한 줄에 연속해서
    # 나오는 표지만 분리한다.
    heading_token = re.compile(r"제\d+(?:편|장|절|관)")
    corrected_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        segment_start = 0
        for match in heading_token.finditer(line):
            if match.start() == segment_start:
                continue
            if _HEADING_RANGE_TAIL_PATTERN.match(line, match.end()):
                # ``제1장부터 제3장까지``는 제목이 아니라 범위 인용이다.
                continue
            prefix = line[segment_start : match.start()].strip()
            previous_character = line[match.start() - 1]
            if (
                prefix.endswith(".")
                or prefix.endswith("삭제")
                or LAW_HEADING_PATTERN.match(prefix)
                or (
                    not previous_character.isspace()
                    and previous_character not in "(["
                )
            ):
                if prefix:
                    corrected_lines.append(prefix)
                segment_start = match.start()
        remainder = line[segment_start:].strip()
        if remainder:
            corrected_lines.append(remainder)

    range_rejoined_lines: list[str] = []
    for line in corrected_lines:
        if (
            range_rejoined_lines
            and re.match(
                r"^제\d+(?:편|장|절|관)\s*(?:부터|까지)", line
            )
        ):
            range_rejoined_lines[-1] = (
                f"{range_rejoined_lines[-1].rstrip()} {line.strip()}"
            )
        else:
            range_rejoined_lines.append(line)
    corrected_lines = range_rejoined_lines

    # ``3-2-7-1.\n(3)\n③에서 정하는``처럼 참조 조항과 동그라미
    # 번호가 각각 분리된 경우, 병합 단계가 하나의 참조 표현으로 판별할
    # 수 있도록 먼저 ``(3) ③에서``로 복원한다.
    reference_rejoined_lines: list[str] = []
    line_index = 0
    while line_index < len(corrected_lines):
        line = corrected_lines[line_index]
        if (
            re.fullmatch(r"\(\d+\)", line)
            and line_index + 1 < len(corrected_lines)
            and re.match(
                rf"^[{CIRCLED_NUMBER_MARKERS}]\s*"
                r"(?:의|에|에서|부터|까지|대로|와|과|를|을)"
                r"(?=\s|[,.;:)\]]|$)",
                corrected_lines[line_index + 1],
            )
        ):
            reference_rejoined_lines.append(
                f"{line} {corrected_lines[line_index + 1]}"
            )
            line_index += 2
            continue
        reference_rejoined_lines.append(line)
        line_index += 1
    corrected_lines = reference_rejoined_lines

    # 번호만 남은 줄은 뒤따르는 줄과 다시 이어 붙인다.
    merged_lines: list[str] = []
    pending_markers: list[str] = []
    pending_range = ""
    for line in corrected_lines:
        if (
            merged_lines
            and re.search(r"\d+(?:-\d+)+\.\s*의\s*$", merged_lines[-1])
            and _CIRCLED_REFERENCE_LINE_PATTERN.match(line)
            and not pending_markers
        ):
            merged_lines[-1] = f"{merged_lines[-1].rstrip()} {line.strip()}"
            continue
        if (
            merged_lines
            and re.search(r"\d+(?:-\d+)+\.\s*의\s*$", merged_lines[-1])
            and re.match(
                r"^\(\d+\)(?:\s*[ㆍ·,]\s*\(\d+\))+\s*"
                r"(?:의|에|에서|부터|까지|대로|와|과|를|을)"
                r"(?=\s|[,.;:)\]]|$)",
                line,
            )
            and not pending_markers
        ):
            merged_lines[-1] = f"{merged_lines[-1].rstrip()} {line.strip()}"
            continue
        if (
            pending_markers
            and merged_lines
            and len(pending_markers) == 1
            and re.fullmatch(r"\d+(?:-\d+)+\.", pending_markers[0])
            and re.match(
                rf"^\(\d+\)\s*[{CIRCLED_NUMBER_MARKERS}]\s*"
                r"(?:의|에|에서|부터|까지|대로|와|과|를|을)"
                r"(?=\s|[,.;:)\]]|$)",
                line,
            )
        ):
            # ``② 각 시ㆍ군은 3-2-7-1.\n(3) ③에서 정하는``에서
            # 단독으로 분리된 지침 번호는 삭제 조항이 아니라 뒤의 (3)을
            # 가리키는 참조 번호다. 삭제 복원보다 먼저 원문 문장에 합친다.
            merged_lines[-1] = (
                f"{merged_lines[-1].rstrip()} {pending_markers[0]} "
                f"{line.strip()}"
            )
            pending_markers.clear()
            continue
        if (
            merged_lines
            and merged_lines[-1].rstrip().endswith(":")
            and re.match(r"^\(\d+\)\s*[~∼～]\s*\(\d+\)", line)
        ):
            # ``(9) 복합구역 :`` 다음의 ``(1) ~ (8)의 지정목적...``은
            # 새 목록이 아니라 (9)의 설명 범위이므로 같은 줄에 둔다.
            merged_lines[-1] = f"{merged_lines[-1].rstrip()} {line.strip()}"
            continue
        # 구버전 저장본의 ``(1) ~`` / ``(8) 의 지정목적`` 두 줄은
        # 하나의 범위 참조다. 직전 상위 항목 문장에 다시 붙인다.
        if re.fullmatch(r"\(\d+\)\s*[~∼～]\s*", line) and merged_lines:
            pending_range = re.sub(r"\s+", "", line)
            continue
        if pending_range:
            endpoint = re.sub(r"^(\(\d+\))\s+", r"\1", line)
            merged_lines[-1] = f"{merged_lines[-1]} {pending_range}{endpoint}"
            pending_range = ""
            continue
        if (
            ADMIN_RULE_NUMBERED_CLAUSE_REFERENCE_PATTERN.match(line)
            and merged_lines
            and ADMIN_RULE_PAREN_ITEM_PATTERN.match(merged_lines[-1])
            and not pending_markers
        ):
            merged_lines[-1] = f"{merged_lines[-1]} {line}"
            continue
        # 구버전 파서가 이미 ``상기\n(1)에서``처럼 저장해 둔 본문도
        # 화면을 다시 열 때 복구한다. 번호 뒤에 조사까지 붙어 있으면
        # 독립 목록 표식이 아니라 앞 문장의 참조 표현이다.
        if (
            ADMIN_RULE_PAREN_REFERENCE_LINE_PATTERN.match(line)
            and merged_lines
            and not pending_markers
        ):
            # ``(1) 에서``처럼 표식과 조사 사이에 들어간 API의 불규칙
            # 공백도 정상적인 참조 표기 ``(1)에서``로 복원한다.
            reference = re.sub(r"^(\([^)]*\))\s+", r"\1", line)
            merged_lines[-1] = f"{merged_lines[-1]} {reference}"
            continue
        # ``2-2-5 (2) 단서``는 새 (2) 항목이 아니라 다른 지침 조항의
        # 내부 참조다. API가 항 번호 앞에서 줄을 끊은 경우에만 복원한다.
        if (
            ADMIN_RULE_CLAUSE_SUBREFERENCE_LINE_PATTERN.match(line)
            and merged_lines
            and (
                re.search(r"\d+(?:-\d+)+\s*$", merged_lines[-1])
                or LAW_PARAGRAPH_PATTERN.match(merged_lines[-1])
            )
            and not pending_markers
        ):
            merged_lines[-1] = f"{merged_lines[-1]} {line}"
            continue
        if (
            merged_lines
            and re.search(r"\d+(?:-\d+)+\.\s*$", merged_lines[-1])
            and re.match(
                rf"^\(\d+\)\s*[{CIRCLED_NUMBER_MARKERS}]\s*"
                r"(?:의|에|에서|부터|까지|대로|와|과|를|을)"
                r"(?=\s|[,.;:)\]]|$)",
                line,
            )
            and not pending_markers
        ):
            # ``② ... 3-2-7-1.\n(3) ③에서 정하는``은 새 (3)
            # 항목이 아니라 앞 수립지침 번호의 세부 참조다.
            merged_lines[-1] = f"{merged_lines[-1].rstrip()} {line.strip()}"
            continue
        if pending_markers and (
            ADMIN_RULE_PAREN_ITEM_PATTERN.match(line)
            or ADMIN_RULE_CLAUSE_PATTERN.match(line)
            or LAW_HEADING_PATTERN.match(line)
        ):
            # 구버전 캐시에서 ``<삭제>``가 사라져 번호만 남은 뒤 바로
            # 다음 번호·조항이 시작하면, 앞의 빈 번호를 삭제 항목으로
            # 복원한다. 일반 본문 줄이면 기존처럼 번호와 본문을 합친다.
            merged_lines.extend(
                f"{marker} <삭제>" for marker in pending_markers
            )
            pending_markers.clear()
        if _MARKER_ONLY_LINE_PATTERN.match(line):
            if pending_markers:
                merged_lines.extend(
                    f"{marker} <삭제>" for marker in pending_markers
                )
                pending_markers.clear()
            pending_markers.append(line)
            continue
        if pending_markers:
            line = " ".join(pending_markers + [line])
            pending_markers.clear()
        merged_lines.append(line)
    merged_lines.extend(f"{marker} <삭제>" for marker in pending_markers)
    if pending_range:
        merged_lines.append(pending_range)

    # 상위 항목 본문에 이전 조항 번호를 열거한 문장이 줄 단위로 넘어오면
    # 실제 새 항목으로 오인하지 않는다. 예를 들어 3-2-8.의 적용 제외
    # 목록에 있는 3-2-2-4, 3-2-3.은 본문 참조이고, 그 뒤의 3-2-9.가
    # 실제 다음 항목이다.
    hierarchy_merged: list[str] = []
    current_clause: tuple[int, ...] | None = None
    leading_clause = re.compile(
        r"^(\d+(?:-\d+)+)(\.,|[.,])(?=\s|\(|$)"
    )
    for line in merged_lines:
        clause_match = leading_clause.match(line)
        if clause_match is None:
            hierarchy_merged.append(line)
            # 장·절·관 제목부터는 새로운 번호 계열이 시작된다. 이전 절의
            # 마지막 번호를 유지하면 `제2절 ...` 다음의 `1-2-1.`을 본문
            # 참조로 오인하여 제목 뒤에 붙이게 된다.
            if LAW_HEADING_PATTERN.match(line):
                current_clause = None
            continue
        candidate = tuple(int(part) for part in clause_match.group(1).split("-"))
        punctuation = clause_match.group(2)
        if current_clause is None:
            is_forward_heading = True
        elif candidate == current_clause + (1,):
            # 바로 아래 위계의 첫 항목: 1-1-1. -> 1-1-1-1.
            is_forward_heading = True
        elif len(candidate) <= len(current_clause):
            # 같은 위계의 다음 항목 또는 하위 위계에서 상위의 다음 항목으로
            # 복귀하는 경우: 1-1-1. -> 1-1-2.,
            # 1-1-1-3. -> 1-1-2.
            compared_current = current_clause[: len(candidate)]
            is_forward_heading = (
                candidate[:-1] == compared_current[:-1]
                and candidate[-1] == compared_current[-1] + 1
            )
        else:
            is_forward_heading = False
        if (
            hierarchy_merged
            and current_clause is not None
            and (punctuation.endswith(",") or not is_forward_heading)
        ):
            hierarchy_merged[-1] = f"{hierarchy_merged[-1].rstrip()} {line.strip()}"
            continue
        hierarchy_merged.append(line)
        current_clause = candidate
    result = "\n".join(hierarchy_merged)
    return re.sub(
        r"\ufff0ADMIN_RULE_FOOTNOTE_(\d+)\ufff1",
        lambda match: f"({match.group(1)})",
        result,
    )


def law_unit_code(number: str, branch: str = "") -> str:
    """조·항·호 번호를 조항목 API의 6자리 코드로 변환."""
    return f"{int(number):04d}{int(branch or 0):02d}"


def normalize_article_jo(jo: str) -> str:
    """조 번호 표기를 조항목 API용 6자리로 맞춘다.

    제12조의2는 ``001202``다. 네 자리(``0012``)만 주면 본조로 보고
    ``001200``이 된다. 예전 도구가 네 자리를 링크에 심어 둔 답과도
    호환되게 한다.
    """
    text = str(jo or "").strip()
    if not text:
        raise ValueError("조 번호가 비어 있습니다.")
    if re.fullmatch(r"\d{6}", text):
        return text
    if re.fullmatch(r"\d{4}", text):
        return text + "00"
    if re.fullmatch(r"\d{1,3}", text):
        return f"{int(text):04d}00"
    labeled = re.fullmatch(r"(?:제)?(\d+)조(?:의(\d+))?", text)
    if labeled:
        return law_unit_code(labeled.group(1), labeled.group(2) or "")
    branched = re.fullmatch(r"(\d+)\s*의\s*(\d+)", text)
    if branched:
        return law_unit_code(branched.group(1), branched.group(2))
    digits = re.sub(r"\D", "", text)
    if len(digits) == 6:
        return digits
    if len(digits) == 4:
        return digits + "00"
    if digits:
        return f"{int(digits):04d}00"
    raise ValueError(f"조 번호 '{jo}'를 해석하지 못했습니다.")


def article_jo_label(jo: str) -> str:
    """6자리(또는 그와 같은 뜻의) 조 번호를 '제12조의2' 형태로 돌린다."""
    code = normalize_article_jo(jo)
    main = int(code[:4])
    branch = int(code[4:])
    return f"제{main}조" + (f"의{branch}" if branch else "")


def document_plain_text(data: object, category: str = "law") -> str:
    """법령ㆍ행정규칙ㆍ자치법규 JSON 본문을 사람이 읽는 평문으로 바꾼다.

    AI 도구가 ``str(딕셔너리)``를 그대로 넘기면 중괄호와 키 이름만 잔뜩
    보이고 조문 문장은 잘린다. 화면 파서와 같은 필드를 집어 평문으로
    모은다.
    """
    if not isinstance(data, dict):
        return json_text(data)
    if category == "law":
        law = data.get("법령", data)
        if isinstance(law, str):
            return json_text(law)
        if isinstance(law, dict):
            return _law_document_plain(law)
    elif category == "admrul":
        service = data.get("AdmRulService", data)
        if isinstance(service, dict):
            return _admrul_document_plain(service)
    elif category == "ordin":
        service = data.get("LawService", data)
        if isinstance(service, dict):
            return _ordin_document_plain(service)
    return _collect_content_strings(data)


def law_article_index(data: object) -> str:
    """법령 상세 JSON에서 조 제목 줄만 모아 목차를 만든다."""
    if not isinstance(data, dict):
        return ""
    law = data.get("법령", data)
    if not isinstance(law, dict):
        return ""
    units = law.get("조문", {})
    units = units.get("조문단위") if isinstance(units, dict) else units
    headings: list[str] = []
    for unit in json_list(units):
        if not isinstance(unit, dict):
            continue
        content = json_text(unit.get("조문내용"))
        if not content:
            continue
        first = content.split("\n", 1)[0].strip()
        heading = re.match(r"(제\d+조(?:의\d+)?(?:\([^)]+\))?)", first)
        if heading:
            headings.append(heading.group(1))
        elif first.startswith("제") and "조" in first[:12]:
            headings.append(first[:80])
    return "\n".join(headings)


def _law_document_plain(law: dict) -> str:
    parts: list[str] = []
    info = law.get("기본정보")
    if isinstance(info, dict):
        title = json_text(info.get("법령명_한글") or info.get("법령명한글"))
        effective = json_text(info.get("시행일자"))
        if title:
            parts.append(title + (f" (시행 {effective})" if effective else ""))
    units = law.get("조문", {})
    units = units.get("조문단위") if isinstance(units, dict) else units
    article = law_article_text(units)
    if article:
        parts.append(article)
    return "\n".join(parts).strip()


def _admrul_document_plain(service: dict) -> str:
    parts: list[str] = []
    info = service.get("행정규칙기본정보")
    if isinstance(info, dict):
        title = json_text(info.get("행정규칙명"))
        effective = json_text(info.get("시행일자"))
        if title:
            parts.append(title + (f" (시행 {effective})" if effective else ""))
    body_source = service.get("조문내용") or service.get("조문")
    body = admin_rule_plain_text(
        normalize_admin_rule_text(admin_rule_text(body_source))
    )
    if body:
        parts.append(body)
    appendix = admin_rule_plain_text(
        normalize_admin_rule_text(admin_rule_text(service.get("부칙")))
    )
    if appendix:
        parts.append("[부칙]\n" + appendix)
    return "\n".join(parts).strip()


def _ordin_document_plain(service: dict) -> str:
    parts: list[str] = []
    info = service.get("자치법규기본정보")
    if isinstance(info, dict):
        title = json_text(info.get("자치법규명"))
        if title:
            parts.append(title)
    articles = service.get("조문", {})
    articles = articles.get("조") if isinstance(articles, dict) else articles
    body = "\n".join(
        json_text(article.get("조내용"))
        for article in json_list(articles)
        if isinstance(article, dict) and json_text(article.get("조내용"))
    )
    if body:
        parts.append(body)
    return "\n".join(parts).strip()


_CONTENT_KEYS = (
    "조문내용",
    "항내용",
    "호내용",
    "목내용",
    "조내용",
    "부칙",
)


def _collect_content_strings(value: object, depth: int = 0) -> str:
    """구조를 모를 때 조문·항·호 문장만 골라 모은다."""
    found: list[str] = []

    def walk(node: object, level: int) -> None:
        if level > 10:
            return
        if isinstance(node, dict):
            for key, child in node.items():
                if key in _CONTENT_KEYS:
                    text = (
                        insert_admin_clause_breaks(json_text(child))
                        if key in ("조문내용", "부칙")
                        else json_text(child)
                    )
                    if text:
                        found.append(text)
                else:
                    walk(child, level + 1)
        elif isinstance(node, list):
            for child in node:
                walk(child, level + 1)

    walk(value, depth)
    return "\n".join(found).strip()


def document_title(data: object, category: str = "law", fallback: str = "") -> str:
    """상세 JSON에서 문서 제목만 꺼낸다. 팝업 제목줄에 쓴다."""
    if not isinstance(data, dict):
        return fallback
    if category == "law":
        law = data.get("법령", data)
        if isinstance(law, dict):
            info = law.get("기본정보")
            if isinstance(info, dict):
                return json_text(
                    info.get("법령명_한글") or info.get("법령명한글")
                ) or fallback
    elif category == "admrul":
        service = data.get("AdmRulService", data)
        if isinstance(service, dict):
            info = service.get("행정규칙기본정보")
            if isinstance(info, dict):
                return json_text(info.get("행정규칙명")) or fallback
    elif category == "ordin":
        service = data.get("LawService", data)
        if isinstance(service, dict):
            info = service.get("자치법규기본정보")
            if isinstance(info, dict):
                return json_text(info.get("자치법규명")) or fallback
    return fallback



_REPEALED_REVISIONS = frozenset({"폐지", "타법폐지"})


def _law_reference_match_rank(candidate: dict) -> tuple:
    """연혁 목록에서 같은 이름이면 폐지본보다 마지막 유효본을 고른다."""
    revision = json_text(candidate.get("제개정구분명"))
    effective = json_text(candidate.get("시행일자"))
    return (0 if revision in _REPEALED_REVISIONS else 1, effective)


def resolve_law_reference_row(payload: object, law_name: str) -> dict[str, object]:
    """법령 목록 응답에서 인용 법령명과 정확히 일치하는 행을 찾는다.

    띄어쓰기는 무시한다. 연혁 검색처럼 같은 이름이 여러 건이면 폐지가
    아닌 행 가운데 시행일이 가장 늦은 것을 쓴다.
    """
    if not isinstance(payload, dict):
        raise ValueError("인용 법령 검색 응답 형식이 올바르지 않습니다.")
    root = payload.get("LawSearch")
    if not isinstance(root, dict):
        raise ValueError("인용 법령 검색 결과를 찾지 못했습니다.")
    expected = re.sub(r"\s+", "", law_name)
    matched: dict | None = None
    matched_rank: tuple | None = None
    for candidate in json_list(root.get("law")):
        if not isinstance(candidate, dict):
            continue
        candidate_name = json_text(candidate.get("법령명한글"))
        if re.sub(r"\s+", "", candidate_name) != expected:
            continue
        rank = _law_reference_match_rank(candidate)
        if matched is None or rank > matched_rank:
            matched = candidate
            matched_rank = rank
    if matched is None:
        raise ValueError(f"'{law_name}'의 정확한 법령 ID를 찾지 못했습니다.")

    item_id = json_text(matched.get("법령ID"))
    if not item_id:
        raise ValueError(f"'{law_name}'의 법령 ID가 없습니다.")
    return {
        "target": "law",
        "label": "법령",
        "id": item_id,
        "name": json_text(matched.get("법령명한글")) or law_name,
        "related": json_text(matched.get("소관부처명")),
        "organization": json_text(matched.get("소관부처명")),
        "date": json_text(matched.get("공포일자")),
        "number": json_text(matched.get("공포번호")),
        "effective": json_text(matched.get("시행일자")),
        "short_name": json_text(matched.get("법령약칭명")),
        "mst": json_text(matched.get("법령일련번호")),
        "revision": json_text(matched.get("제개정구분명")),
        # 폐지ㆍ연혁 법령을 현행처럼 읽지 않도록 화면에서 표시할 근거.
        "history_code": json_text(matched.get("현행연혁코드")),
        "raw": matched,
    }


def choose_law_reference_row(
    *,
    item_id: str = "",
    law_name: str = "",
    named_row: dict[str, object] | None = None,
) -> dict[str, object]:
    """링크의 법령 ID와 이름 검색 결과가 다르면 이름을 따른다.

    모델이 「건축법」 제19조에 시행령 ID를 붙인 경우가 있다. 이름 검색이
    다른 ID를 내면 그 행으로 연다. 약칭처럼 이름 검색이 실패하면 링크
    ID를 유지한다.
    """
    linked_id = str(item_id or "").strip()
    if named_row is not None:
        named_id = str(named_row.get("id") or "").strip()
        if named_id and (not linked_id or named_id != linked_id):
            return named_row
        if named_id:
            return named_row
    if linked_id:
        return {
            "target": "law",
            "label": "법령",
            "id": linked_id,
            "name": law_name,
            "related": "",
            "organization": "",
            "date": "",
            "number": "",
            "effective": "",
            "raw": {},
        }
    raise ValueError(f"'{law_name}'의 정확한 법령 ID를 찾지 못했습니다.")


def row_search_text(row: dict[str, object]) -> str:
    """검색결과 내부검색(필터)용으로 행의 주요 텍스트 필드를 모아 하나의 문자열로 합침."""
    keys = (
        "title",
        "name",
        "case_number",
        "related",
        "agency",
        "inquiry_org",
        "organization",
        "court",
        "label",
        "provision",
    )
    return " ".join(str(row.get(key) or "") for key in keys).casefold()


def search_terms(query: str) -> tuple[str, ...]:
    """공백·쉼표로 구분한 검색어를 중복 없이 긴 순서로 반환."""
    terms = {
        term.strip()
        for term in re.split(r"[\s,，]+", query)
        if term.strip()
    }
    # ``도시관리계획``은 결과에서 ``도시ㆍ군관리계획``처럼 중간에
    # 다른 한정어가 끼어 나타나는 경우가 많다. 정확 검색어 강조는
    # 유지하면서 앞말 ``도시``와 법정 계획명 ``관리계획``도 함께
    # 강조해 이런 결과에서도 검색 연관 부분을 바로 알아볼 수 있게 한다.
    for term in tuple(terms):
        suffix = "관리계획"
        if term.endswith(suffix) and len(term) > len(suffix) + 1:
            terms.add(term[: -len(suffix)])
            terms.add(suffix)
    return tuple(sorted(terms, key=len, reverse=True))


def whitespace_flexible_pattern(term: str) -> str:
    """공백 유무와 관계없이 같은 검색어로 인식하는 정규식 조각."""
    compact = re.sub(r"\s+", "", str(term or ""))
    if not compact:
        return ""
    return r"\s*".join(re.escape(character) for character in compact)


def whitespace_insensitive_contains(text: str, query: str) -> bool:
    """검색 대상과 검색어 양쪽의 공백을 무시하여 포함 여부를 판정한다."""
    compact_query = re.sub(r"\s+", "", str(query or "")).casefold()
    if not compact_query:
        return True
    compact_text = re.sub(r"\s+", "", str(text or "")).casefold()
    return compact_query in compact_text


def _declared_law_alias(text_after_citation: str) -> str:
    """법령명 뒤 (이하 "법"이라 한다)에서 선언한 약칭을 돌려준다."""
    match = _LAW_ALIAS_PATTERN.match(text_after_citation)
    return match.group("alias").strip() if match else ""


def collect_law_aliases(text: str) -> dict[str, str]:
    """문서 전체에서 「법령명」(이하 "법"이라 한다) 선언을 모은다.

    지침처럼 첫머리에서 한 번 약칭을 정해 두고 이후 계속 쓰는 문서에서,
    문단별로 나눠 변환하더라도 약칭을 잃지 않도록 미리 훑어 둔다.
    """
    aliases: dict[str, str] = {}
    for match in LAW_REFERENCE_PATTERN.finditer(str(text or "")):
        law_name = match.group("law")
        if not law_name:
            continue
        alias = _declared_law_alias(
            text[match.end() : match.end() + 60]
        )
        if alias and alias not in aliases:
            aliases[alias] = law_name.strip()
    return aliases


def _is_adjacent_gap(gap: str) -> bool:
    """법령명 인용과 조문 사이가 약칭 괄호·공백뿐이면 같은 법령의 조문으로 본다."""
    return bool(_ADJACENT_GAP_PATTERN.match(gap))


def _is_enumeration_gap(gap: str) -> bool:
    """앞 조문과 열거로만 이어지면(부터·까지·및·쉼표) 같은 법령의 조문이다."""
    return bool(_ENUMERATION_GAP_PATTERN.match(gap))


def serialize_agency_search_payload(payload: object) -> dict[str, object]:
    """기관 검색 XML 응답을 검색목록 캐시에 저장 가능한 JSON 구조로 변환."""
    if not isinstance(payload, dict):
        raise ValueError("검색 목록 응답 형식이 올바르지 않습니다.")
    serialized_roots: list[dict[str, object]] = []
    for agency, root in list(payload.get("roots") or []):
        serialized_roots.append(
            {
                "agency": {
                    "name": str(agency.name),
                    "target": str(agency.target),
                    "detail_available": bool(agency.detail_available),
                },
                "xml": ET.tostring(root, encoding="unicode"),
            }
        )
    serialized_errors: list[dict[str, object]] = []
    for agency, message in list(payload.get("errors") or []):
        serialized_errors.append(
            {
                "agency": {
                    "name": str(agency.name),
                    "target": str(agency.target),
                    "detail_available": bool(agency.detail_available),
                },
                "message": str(message),
            }
        )
    return {
        "format": "agency_xml_v1",
        "roots": serialized_roots,
        "errors": serialized_errors,
    }


def deserialize_agency_search_payload(payload: object) -> dict[str, object]:
    """검색목록 캐시의 XML 문자열을 기존 기관 검색 응답 구조로 복원."""
    if not isinstance(payload, dict) or payload.get("format") != "agency_xml_v1":
        raise ValueError("저장된 검색목록 형식이 올바르지 않습니다.")

    def agency_from(value: object) -> AgencyConfig:
        data = value if isinstance(value, dict) else {}
        return AgencyConfig(
            str(data.get("name") or "기관"),
            str(data.get("target") or ""),
            bool(data.get("detail_available", True)),
        )

    roots: list[tuple[AgencyConfig, object]] = []
    for entry in json_list(payload.get("roots")):
        if not isinstance(entry, dict):
            continue
        xml_text = str(entry.get("xml") or "")
        if not xml_text:
            continue
        roots.append((agency_from(entry.get("agency")), ET.fromstring(xml_text)))
    errors: list[tuple[AgencyConfig, str]] = []
    for entry in json_list(payload.get("errors")):
        if not isinstance(entry, dict):
            continue
        errors.append(
            (
                agency_from(entry.get("agency")),
                str(entry.get("message") or ""),
            )
        )
    return {"roots": roots, "errors": errors}


def _collect_article_children(node: object, output: list[str]) -> None:
    """항 아래의 호ㆍ목까지 파고들어 본문을 모은다."""
    if not isinstance(node, dict):
        return
    content = law_text(
        node.get("항내용") or node.get("호내용") or node.get("목내용")
    )
    if content:
        output.append(normalize_amendment_note_dates(content))
    for key in ("호", "목"):
        for child in json_list(node.get(key)):
            _collect_article_children(child, output)


# 개정 표기 안의 날짜. 법제처는 ``2009. 2. 6.``로 쓰는데 API는 ``2009.2.6``
# 으로 준다. 본문 아무 데나 고치면 ``제3조제1항`` 같은 인용이나 금액ㆍ면적의
# 소수점까지 건드리므로, <개정 …> [전문개정 …] 같은 표기 안에서만 바꾼다.
_AMENDMENT_NOTE_PATTERN = re.compile(r"<[^<>]*>|\[[^\[\]]*\]")
_AMENDMENT_NOTE_KEYWORDS = ("개정", "신설", "폐지", "삭제", "이동", "제정")
_AMENDMENT_DATE_PATTERN = re.compile(
    r"(?<!\d)(\d{4})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?(?!\d)"
)


def normalize_amendment_note_dates(text: str) -> str:
    """개정 표기 안의 날짜를 법제처 표기(``2009. 2. 6.``)로 맞춘다."""
    if not text:
        return text

    def fix_note(match: re.Match[str]) -> str:
        note = match.group(0)
        if not any(word in note for word in _AMENDMENT_NOTE_KEYWORDS):
            return note
        fixed = _AMENDMENT_DATE_PATTERN.sub(
            lambda date: f"{date.group(1)}. {int(date.group(2))}. "
            f"{int(date.group(3))}.",
            note,
        )
        # ``2012.12.18법률 제11579호``처럼 날짜에 글자가 바로 붙어 오는
        # 표기가 있다. 마침표를 붙인 뒤에는 한 칸 띄어야 읽힌다.
        return re.sub(r"(\d{1,2}\.)(?=[가-힣])", r"\1 ", fixed)

    return _AMENDMENT_NOTE_PATTERN.sub(fix_note, text)


def law_article_note(unit: object) -> str:
    """조문단위의 ``조문참고자료``(``[전문개정 2009. 2. 6.]``)를 한 줄로.

    법제처 본문은 조문 끝에 이 표기를 따로 한 줄로 둔다. 본문 필드와 달리
    별도 항목으로 오기 때문에 읽지 않으면 화면에서 통째로 빠진다.
    """
    if not isinstance(unit, dict):
        return ""
    return normalize_amendment_note_dates(json_text(unit.get("조문참고자료")))


def law_article_text(units: object) -> str:
    """법령 상세 응답의 조문단위에서 본문을 통째로 뽑는다.

    국가법령정보 API는 조 제목만 ``조문내용``에 담고 실제 내용은
    ``항``ㆍ``호``ㆍ``목`` 배열에 나눠 넣는다. 조문내용만 읽으면 제목 한
    줄만 남는다. 실제로 국토계획법 시행령 제18조를 조회했을 때 조문단위
    세 덩이 중 앞의 둘에는 조문내용조차 없고 본문이 전부 항 배열에만
    들어 있었다.
    """
    parts: list[str] = []
    for unit in json_list(units):
        if not isinstance(unit, dict):
            continue
        content = law_text(unit.get("조문내용"))
        if content:
            parts.append(normalize_amendment_note_dates(content))
        for paragraph in json_list(unit.get("항")):
            _collect_article_children(paragraph, parts)
        # 법제처 본문처럼 ``[전문개정 …]``은 조문 끝에 따로 한 줄로 둔다.
        note = law_article_note(unit)
        if note:
            parts.append(note)
    return "\n".join(parts)


def law_payload_has_body(payload: object) -> bool:
    """법령 JSON에 조문 본문이 있는지. 제목만 있고 항·호에 본문이 있는 경우도 포함한다."""
    if not isinstance(payload, dict):
        return False
    law = payload.get("법령", payload)
    if not isinstance(law, dict):
        return False
    units = law.get("조문", {})
    units = units.get("조문단위") if isinstance(units, dict) else units
    return bool(law_article_text(units))


def _jo_code_from_unit_key(key: str) -> str:
    """조문키에서 6자리 조 번호만 남긴다.

    법제처 전문 JSON의 조문키는 ``00300020210701``처럼 뒤에 시행일이
    붙는 경우가 많다. 숫자 전체를 조 번호로 읽으면 제30조가 안 잡힌다.
    """
    digits = re.sub(r"\D", "", str(key or ""))
    if len(digits) >= 6:
        return digits[:6]
    return normalize_article_jo(key)


def _unit_jo_code(unit: dict) -> str:
    """조문단위에서 6자리 조 번호를 읽는다. 모르면 빈 문자열."""
    number = json_text(unit.get("조문번호"))
    if number:
        try:
            return law_unit_code(number, json_text(unit.get("조문가지번호")))
        except ValueError:
            pass
    key = json_text(unit.get("조문키") or unit.get("조문Key"))
    if key:
        try:
            return _jo_code_from_unit_key(key)
        except ValueError:
            pass
    heading = re.match(
        r"제(\d+)조(?:의(\d+))?",
        json_text(unit.get("조문내용")),
    )
    if heading is None:
        return ""
    try:
        return law_unit_code(heading.group(1), heading.group(2) or "")
    except ValueError:
        return ""


def extract_law_article(
    data: object,
    jo: str,
    hang: str = "",
    ho: str = "",
    mok: str = "",
) -> str:
    """저장된 법령 상세 JSON에서 한 조만 뽑는다.

    화면 본문 조회(eflaw)로 받아 둔 전문에서 읽으므로, 조항호목 API를
    따로 부르지 않는다. 항·호를 지정하면 그 단위만 남긴다.
    """
    if not isinstance(data, dict):
        return ""
    try:
        jo_code = normalize_article_jo(jo)
    except ValueError:
        return ""
    law = data.get("법령", data)
    if not isinstance(law, dict):
        return ""
    units = law.get("조문", {})
    units = units.get("조문단위") if isinstance(units, dict) else units
    matched = [
        unit
        for unit in json_list(units)
        if isinstance(unit, dict) and _unit_jo_code(unit) == jo_code
    ]
    if not matched:
        return ""
    if hang or ho or mok:
        filtered = _filter_article_hang_ho(matched, hang, ho, mok)
        if filtered:
            return law_article_text(filtered)
    return law_article_text(matched)


def slice_law_detail_to_article(
    data: object,
    jo: str,
    hang: str = "",
    ho: str = "",
    mok: str = "",
) -> object:
    """전문 JSON에서 요청한 조·항·호·목만 남긴다. 조문 팝업이 연혁 전문을 통째로 보여 주지 않게."""
    if not isinstance(data, dict) or not jo:
        return data
    try:
        jo_code = normalize_article_jo(jo)
    except ValueError:
        return data
    law = data.get("법령", data)
    if not isinstance(law, dict):
        return data
    units = law.get("조문", {})
    raw_units = units.get("조문단위") if isinstance(units, dict) else units
    matched = [
        unit
        for unit in json_list(raw_units)
        if isinstance(unit, dict) and _unit_jo_code(unit) == jo_code
    ]
    if hang or ho or mok:
        filtered = _filter_article_hang_ho(matched, hang, ho, mok)
        if filtered:
            matched = filtered
    if not matched:
        return data
    new_law = dict(law)
    if isinstance(units, dict):
        new_law["조문"] = {**units, "조문단위": matched}
    else:
        new_law["조문"] = matched
    if "법령" in data:
        return {**data, "법령": new_law}
    return new_law


def _hang_ho_number(value: str) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits:
        return str(value or "").strip()
    try:
        return str(int(digits[:4] if len(digits) >= 4 else digits))
    except ValueError:
        return digits.lstrip("0") or digits


def _filter_article_hang_ho(
    units: list, hang: str, ho: str, mok: str = ""
) -> list:
    hang_number = _hang_ho_number(hang) if hang else ""
    ho_number = _hang_ho_number(ho) if ho else ""
    mok_number = re.sub(r"[\s.ㆍ·목]", "", str(mok or ""))
    sliced: list[dict] = []
    for unit in units:
        if not hang_number:
            sliced.append(unit)
            continue
        paragraphs = []
        for paragraph in json_list(unit.get("항")):
            if not isinstance(paragraph, dict):
                continue
            number = _hang_ho_number(
                json_text(paragraph.get("항번호"))
                or json_text(paragraph.get("항번호값"))
            )
            if number != hang_number:
                continue
            if not ho_number:
                paragraphs.append(paragraph)
                continue
            items = []
            for item in json_list(paragraph.get("호")):
                if (
                    not isinstance(item, dict)
                    or _hang_ho_number(json_text(item.get("호번호")))
                    != ho_number
                ):
                    continue
                if not mok_number:
                    items.append(item)
                    continue
                subitems = [
                    subitem
                    for subitem in json_list(item.get("목"))
                    if isinstance(subitem, dict)
                    and re.sub(
                        r"[\s.ㆍ·목]",
                        "",
                        json_text(subitem.get("목번호")),
                    )
                    == mok_number
                ]
                if subitems:
                    narrowed_item = dict(item)
                    narrowed_item["목"] = subitems
                    items.append(narrowed_item)
            if items:
                narrowed = dict(paragraph)
                narrowed["호"] = items
                paragraphs.append(narrowed)
        if paragraphs:
            narrowed_unit = dict(unit)
            narrowed_unit["항"] = paragraphs
            sliced.append(narrowed_unit)
    return sliced
