"""본문을 화면에 보여 줄 HTML로 바꾸는 함수.

문단·글머리표 배치와 법령 인용 링크 생성을 담당한다.
"""

from __future__ import annotations

import re
from html import escape
from urllib.parse import quote

from PySide6.QtGui import QFont, QFontMetrics

from .constants import DETAIL_FONT_CSS_FAMILY, FONT_FAMILY
from .patterns import (
    BULLET_PATTERN,
    LAW_HEADING_PATTERN,
    LAW_ARTICLE_PATTERN,
    LAW_PARAGRAPH_PATTERN,
    LAW_SUBPARAGRAPH_PATTERN,
    LAW_ITEM_PATTERN,
    LAW_SUBITEM_PATTERN,
    ADMIN_RULE_CLAUSE_PATTERN,
    ADMIN_RULE_NUMBERED_ITEM_PATTERN,
    ADMIN_RULE_PAREN_ITEM_PATTERN,
    CIRCLED_HANGUL_ITEM_PATTERN,
    LAW_REFERENCE_PATTERN,
    LAW_UNIT_REFERENCE_PATTERN,
)
from .parsing import (
    ADMIN_RULE_IMAGE_MARKER_PATTERN,
    json_text,
    merge_marker_reference_fragments,
    merge_circled_reference_lines,
    merge_bare_clause_reference,
    merge_sentence_tail_item_lines,
    normalize_admin_rule_text,
    split_inline_paren_items,
    split_label_before_first_paren_item,
    split_paren_item_after_sentence_end,
    uses_guideline_numbering,
    _declared_law_alias,
    collect_law_aliases,
    _is_adjacent_gap,
    _is_enumeration_gap,
    whitespace_flexible_pattern,
)


# 폐지ㆍ연혁 법령 안내에 쓰는 기본정보 항목 이름. 화면에서 이 이름이면
# 값에 경고 색을 입힌다.
REPEAL_NOTICE_LABEL = "현행여부"


DETAIL_DOCUMENT_STYLE = (
    "<style>"
    "body { font-family:" + DETAIL_FONT_CSS_FAMILY + "; font-weight:400; color:#172033; "
    "line-height:1.75; }"
    "h1 { font-family:" + DETAIL_FONT_CSS_FAMILY + "; font-size:21px; font-weight:700; "
    "color:#173b63; margin:0 0 6px 0; }"
    # 법제처 본문처럼 제목 아래에 시행일ㆍ공포번호ㆍ제개정구분을 한 줄로 둔다.
    ".doc-subtitle { font-family:" + DETAIL_FONT_CSS_FAMILY + "; font-size:13px; "
    "font-weight:400; color:#3d4c60; margin:0 0 14px 0; }"
    # 약칭은 제목 글자 크기(21px)의 절반으로 둔다.
    ".doc-short-name { font-size:11px; font-weight:400; color:#3d4c60; }"
    ".meta { background:#f3f7fb; border:1px solid #cfdcea; "
    "border-radius:8px; padding:14px 18px; margin-bottom:20px; }"
    ".meta table { width:100%; border-collapse:collapse; table-layout:fixed; }"
    ".meta td { width:33.33%; color:#172033; font-weight:400; "
    "vertical-align:top; padding:7px 14px 7px 0; white-space:normal; }"
    ".meta-label { color:#3d4c60; font-weight:700; margin-right:8px; "
    "white-space:nowrap; }"
    ".meta-value { color:#172033; font-weight:400; }"
    ".meta-warning { color:#c0392b; font-weight:700; }"
    "h2 { font-family:" + DETAIL_FONT_CSS_FAMILY + "; color:#1768aa; font-size:16px; "
    "font-weight:700; border-bottom:2px solid #dbeaf7; padding-bottom:6px; "
    "margin-top:22px; }"
    ".content { font-family:" + DETAIL_FONT_CSS_FAMILY + "; font-weight:400; font-size:14px; }"
    ".paragraph { margin:0 0 10px 0; }"
    ".bullet { margin:0 0 7px 0; border-collapse:collapse; }"
    ".bullet-marker { font-weight:400; padding:0; }"
    ".bullet-text { font-weight:400; padding:0; }"
    "a { color:#1768aa; font-weight:600; text-decoration:none; }"
    "</style>"
)


def full_law_url(value: object) -> str:
    url = json_text(value)
    if not url:
        return ""
    if url.startswith("//"):
        return f"https:{url}"
    if re.match(r"(?i)^http://(?:[^/]+\.)?law\.go\.kr(?::80)?(?:/|$)", url):
        return "https://" + re.sub(r"(?i)^http://", "", url).replace(":80/", "/", 1)
    if re.match(r"(?i)^https?://", url):
        return url
    if url.casefold().startswith("www.law.go.kr/"):
        return f"https://{url}"
    if url.startswith("/"):
        return f"https://www.law.go.kr{url}"
    # 별표 상세링크는 환경에 따라 선행 슬래시 없는 상대주소로도 제공된다.
    if ".do" in url or url.startswith("LSW/"):
        return f"https://www.law.go.kr/{url.lstrip('/')}"
    return url


def highlight_html_text(value: str, terms: tuple[str, ...]) -> str:
    """HTML 이스케이프 후 검색어가 일치한 부분에 음영을 넣는다."""
    if not terms:
        return escape(value)
    patterns = tuple(filter(None, (whitespace_flexible_pattern(term) for term in terms)))
    pattern = re.compile("|".join(patterns), re.IGNORECASE)
    parts: list[str] = []
    last = 0
    for match in pattern.finditer(value):
        parts.append(escape(value[last : match.start()]))
        parts.append(
            '<span style="background-color:#ffe58f;">'
            f"{escape(match.group(0))}</span>"
        )
        last = match.end()
    parts.append(escape(value[last:]))
    return "".join(parts)


def strip_search_highlight_html(value: str) -> str:
    """저장 HTML에서 자동 검색 음영 span만 제거한다."""
    return re.sub(
        r'<span\s+style="(?=[^"]*background-color\s*:\s*#ffe58f\s*;?)[^"]*">(.*?)</span>',
        r"\1",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )


# Qt가 클립보드로 내보내는 HTML은 굵기를 ``font-weight:700`` 숫자값으로,
# 문단 여백을 ``px``로 적는다. 한글(HWP)의 "HTML 문서 붙여넣기" 파서는 둘 다
# 읽지 못해서 조문 표제가 보통 글씨로 붙고 들여쓰기가 전부 사라진다.
# 정보 자체는 Qt가 이미 다 담아 보내므로, 표기법만 한글이 아는 형태
# (``<b>`` 태그와 ``pt`` 단위)로 바꿔 준다.
_QT_SPAN_PATTERN = re.compile(
    r'<span style="(?P<style>[^"]*)">(?P<text>.*?)</span>',
    re.IGNORECASE | re.DOTALL,
)
_QT_FONT_WEIGHT_PATTERN = re.compile(
    r"font-weight\s*:\s*(?P<value>\d{3}|bold)\s*;?", re.IGNORECASE
)
# 화면 본문은 번호를 문단 밖으로 빼는 내어쓰기(``margin-left`` 양수 +
# ``text-indent`` 음수)로 항ㆍ호를 정렬한다. 한글은 이 조합에서
# ``margin-left``를 버리고 ``text-indent``의 절댓값만 첫 줄 들여쓰기로
# 쓰기 때문에, 내어쓰기 폭이 좁은 "1."이 폭이 넓은 "①"보다 왼쪽으로
# 튀어나오는 식으로 위계가 뒤집힌다. 그래서 클립보드로 나갈 때는
# 내어쓰기를 쓰지 않고, 문단 전체를 화면상 첫 줄 위치까지만 밀어 준다.
# 위계는 그대로 남고 음수 여백이 없어 번호가 튀어나올 수 없다.
_QT_BLOCK_STYLE_PATTERN = re.compile(
    r'(?P<open><(?:p|li)\b[^>]*?\bstyle=")(?P<style>[^"]*)(?P<close>")',
    re.IGNORECASE,
)
_QT_MARGIN_LEFT_PATTERN = re.compile(
    r"margin-left\s*:\s*(?P<value>-?\d+(?:\.\d+)?)px", re.IGNORECASE
)
_QT_TEXT_INDENT_PATTERN = re.compile(
    r"text-indent\s*:\s*(?P<value>-?\d+(?:\.\d+)?)px", re.IGNORECASE
)
# CSS 96dpi 기준 1px = 0.75pt. 한글이 소수점 pt를 흘리는 경우가 있어
# 정수로 반올림해서 넘긴다.
_PX_TO_PT = 0.75


def _flatten_block_indent(match: "re.Match[str]") -> str:
    style = match.group("style")
    left = _QT_MARGIN_LEFT_PATTERN.search(style)
    indent = _QT_TEXT_INDENT_PATTERN.search(style)
    if not left and not indent:
        return match.group(0)
    left_px = float(left.group("value")) if left else 0.0
    indent_px = float(indent.group("value")) if indent else 0.0
    # 내어쓰기를 접으면 첫 줄이 있던 자리가 문단 전체의 왼쪽 여백이 된다.
    first_line_px = max(0.0, left_px + indent_px)
    points = round(first_line_px * _PX_TO_PT)
    if left:
        style = _QT_MARGIN_LEFT_PATTERN.sub(
            f"margin-left:{points}pt", style, count=1
        )
    else:
        style = f"{style.rstrip()} margin-left:{points}pt;"
    if indent:
        style = _QT_TEXT_INDENT_PATTERN.sub(
            "text-indent:0pt", style, count=1
        )
    return f"{match.group('open')}{style}{match.group('close')}"


def _hwp_friendly_span(match: "re.Match[str]") -> str:
    style = match.group("style")
    text = match.group("text")
    weight = _QT_FONT_WEIGHT_PATTERN.search(style)
    if not weight:
        return match.group(0)
    raw = weight.group("value").lower()
    if raw != "bold" and int(raw) < 600:
        return match.group(0)
    # 숫자 굵기는 한글이 못 읽으므로 style에서 걷어내고 <b>로 대신한다.
    # style을 남겨 두면 색상ㆍ글꼴은 그대로 살아난다.
    stripped = _QT_FONT_WEIGHT_PATTERN.sub("", style)
    return f'<b><span style="{stripped}">{text}</span></b>'


def hwp_friendly_clipboard_html(value: str) -> str:
    """Qt가 만든 클립보드 HTML을 한글이 읽을 수 있는 표기로 바꾼다.

    변환에 실패해도 붙여넣기 자체는 되어야 하므로 원본을 그대로 돌려준다.
    """
    if not value:
        return value
    try:
        converted = _QT_SPAN_PATTERN.sub(_hwp_friendly_span, value)
        return _QT_BLOCK_STYLE_PATTERN.sub(_flatten_block_indent, converted)
    except Exception:  # pragma: no cover - 변환 실패 시 원본 유지
        return value


def law_base_name(law_name: str) -> str:
    """'○○법 시행규칙' → '○○법'처럼 상위 법률 이름만 남긴다."""
    return re.sub(r"\s*(?:시행령|시행규칙)\s*$", "", str(law_name or "")).strip()


def law_short_name(law_name: str, official_short_name: str = "") -> str:
    """하단 기록 탭에 넣을 법령명.

    약칭은 법제처가 정한 것만 쓴다(법령 목록 API의 법령약칭명).
    임의로 줄이면 실제로 없는 이름이 되므로, 약칭이 없으면 원래 이름을
    그대로 두고 화면에서 잘라 보여 준다.
    """
    official = re.sub(r"\s+", " ", str(official_short_name or "")).strip()
    name = re.sub(r"\s+", " ", str(law_name or "")).strip()
    if not name:
        return official or "법령"
    if not official:
        return name
    # 시행령·시행규칙은 상위 법률의 약칭에 접미어를 붙여 부른다.
    for tail in ("시행규칙", "시행령"):
        if name.endswith(tail):
            return official if official.endswith(tail) else f"{official} {tail}"
    return official


def sibling_law_name(anchor_law_name: str, unit: str) -> str:
    """'법'·'영'·'규칙' 표기를 기준 법령과 같은 계열의 실제 법령명으로 바꾼다."""
    base = law_base_name(anchor_law_name)
    if not base:
        return ""
    if unit in ("영", "시행령", "대통령령"):
        return f"{base} 시행령"
    if unit in ("규칙", "시행규칙"):
        return f"{base} 시행규칙"
    if unit == "총리령" or unit == "부령" or unit.endswith("부령"):
        return f"{base} 시행규칙"
    return base


def law_reference_html_text(
    value: str,
    terms: tuple[str, ...],
    *,
    current_law_name: str = "",
    current_law_id: str = "",
    current_article_jo: str = "",
    current_article_branch: str = "",
    use_api_links: bool = False,
    law_aliases: dict[str, str] | None = None,
) -> str:
    """법령명·조문 인용을 웹 또는 프로그램 내부 API 링크로 변환."""
    parts: list[str] = []
    last = 0
    # "같은 법"은 바로 앞에서 「」로 인용한 법령을 가리키므로 직전 인용을 기억한다.
    last_cited_law = ""
    # 「법령명」(이하 "영"이라 한다) 제4조제2호처럼 법령명 바로 뒤에 붙는
    # 조문 인용은 현재 법령이 아니라 그 법령의 조문이다.
    adjacent_law = ""
    adjacent_end = -1
    # ``제2조제1호 및 제2호``에서 뒤의 호가 이어받을 조 번호.
    adjacent_jo = ""
    adjacent_jo_branch = ""
    # 본문이 (이하 "법"이라 한다)로 선언한 약칭 → 실제 법령명.
    declared_aliases: dict[str, str] = dict(law_aliases or {})
    for match in LAW_REFERENCE_PATTERN.finditer(value):
        parts.append(highlight_html_text(value[last : match.start()], terms))
        explicit_law = match.group("law")
        sibling_unit = match.group("sibling_unit")
        if explicit_law:
            last_cited_law = explicit_law.strip()
            adjacent_law = last_cited_law
            adjacent_end = match.end()
            alias = _declared_law_alias(value[match.end() : match.end() + 60])
            if alias:
                declared_aliases[alias] = last_cited_law
        if sibling_unit:
            if sibling_unit in declared_aliases:
                # 본문이 직접 선언한 약칭이 가장 정확하다.
                law_name = declared_aliases[sibling_unit]
            else:
                anchor = (
                    last_cited_law
                    if match.group("sibling_scope") and last_cited_law
                    else current_law_name
                )
                law_name = sibling_law_name(anchor, sibling_unit)
        elif (
            explicit_law is None
            and adjacent_law
            and (
                _is_adjacent_gap(value[adjacent_end : match.start()])
                or _is_enumeration_gap(value[adjacent_end : match.start()])
            )
        ):
            law_name = adjacent_law
        else:
            law_name = str(explicit_law or current_law_name).strip()
        if law_name and explicit_law is None:
            # 열거가 이어질 수 있도록 기준점을 이 조문 끝으로 옮긴다.
            adjacent_law = law_name
            adjacent_end = match.end()
        reference = match.group(0)
        if not law_name:
            parts.append(highlight_html_text(reference, terms))
            last = match.end()
            continue

        article_reference = str(
            match.group("law_detail")
            or match.group("sibling_article")
            or match.group("current_article")
            or ""
        )
        # "법 "·"같은 영 " 같은 접두어는 링크 밖에 그대로 두고 조문만 링크로 만든다.
        if sibling_unit:
            prefix_length = match.end("sibling_unit") - match.start()
            prefix_text = reference[:prefix_length]
            spacing = reference[prefix_length : match.start("sibling_article") - match.start()]
            parts.append(highlight_html_text(prefix_text + spacing, terms))
            reference = match.group("sibling_article")
        unit_match = LAW_UNIT_REFERENCE_PATTERN.match(article_reference.strip())
        # 조 번호 없이 적힌 `제1항`, `제2항제3호` 등은 현재 보고 있는
        # 같은 조문 내부를 가리킨다. 같은 화면을 다시 팝업으로 여는 링크는
        # 탐색에 도움이 되지 않으므로 일반 본문으로 둔다.
        # 다만 `제2조제1호 및 제2호`처럼 바로 앞에서 조를 밝힌 열거가
        # 이어지는 경우는 그 조의 다른 호를 가리키므로 조를 이어받아 건다.
        carried_jo = ""
        carried_jo_branch = ""
        if unit_match and not unit_match.group("jo"):
            if (
                adjacent_jo
                and _is_enumeration_gap(value[adjacent_end : match.start()])
            ):
                carried_jo = adjacent_jo
                carried_jo_branch = adjacent_jo_branch
            else:
                parts.append(highlight_html_text(reference, terms))
                last = match.end()
                continue
        if unit_match and unit_match.group("jo"):
            adjacent_jo = str(unit_match.group("jo") or "")
            adjacent_jo_branch = str(unit_match.group("jo_branch") or "")
        if use_api_links:
            parameters = [f"name={quote(law_name, safe='')}"]
            # 법령ID는 지금 보고 있는 법령을 가리킬 때만 재사용한다.
            # 다른 법령이면 ID를 붙이지 않아야 이름으로 다시 검색한다.
            if (
                explicit_law is None
                and law_name == current_law_name
                and current_law_id
            ):
                parameters.append(f"id={quote(current_law_id, safe='')}")
            if unit_match:
                for key in (
                    "jo",
                    "jo_branch",
                    "hang",
                    "hang_branch",
                    "ho",
                    "ho_branch",
                    "mok",
                ):
                    unit_value = str(unit_match.group(key) or "")
                    if not unit_value and key == "jo":
                        unit_value = carried_jo
                    if not unit_value and key == "jo_branch":
                        unit_value = carried_jo_branch
                    if unit_value:
                        parameters.append(f"{key}={quote(unit_value, safe='')}")
            url = f"lawref://open?{'&'.join(parameters)}"
        else:
            url = f"https://www.law.go.kr/법령/{quote(law_name, safe='')}"
            if unit_match:
                article_match = re.match(r"제\d+조(?:의\d+)?", unit_match.group(0))
                if article_match:
                    url = f"{url}/{quote(article_match.group(0), safe='')}"
        parts.append(
            f'<a href="{escape(url, quote=True)}" '
            'style="color:#006dcc; text-decoration:underline;">'
            f"{highlight_html_text(reference, terms)}</a>"
        )
        last = match.end()
    parts.append(highlight_html_text(value[last:], terms))
    return "".join(parts)


# 개정 이력 표기를 본문보다 한 단계 작고 연한 파란색으로 둔다. 본문
# ``.content``가 14px이므로 13px가 한 단계 아래다. 인라인 px로 두면
# ``scale_document_font_sizes``가 본문 글자 크기와 같은 비율로 함께 키운다.
AMENDMENT_NOTE_STYLE = "font-size:13px; color:#6f9ec9;"

# 본문 HTML은 이스케이프를 거쳐 ``<개정 …>``이 ``&lt;개정 …&gt;``으로 남는다.
# 꺾쇠 표기는 안쪽에 개정 관련 낱말이 있으면 잡고, 대괄호 표기는 일반 인용
# 대괄호까지 물들이지 않도록 여는 괄호 바로 뒤에 그 낱말이 오는 것만 잡는다.
_HTML_AMENDMENT_ANGLE_PATTERN = re.compile(
    r"&lt;(?:(?!&lt;|&gt;).)*?"
    r"(?:개정|신설|삭제|폐지|이동|제정)"
    r"(?:(?!&lt;|&gt;).)*?&gt;"
)
_HTML_AMENDMENT_BRACKET_PATTERN = re.compile(
    r"\[(?:전문개정|본조신설|본조제목개정|제목개정|개정|신설|삭제|폐지|제정)"
    r"(?:(?!\[|\]).)*?\]"
)


def style_amendment_notes(html: str) -> str:
    """``<개정 2009. 7. 16.>``ㆍ``[전문개정 …]``에 작고 연한 파란색을 입힌다."""
    if not html:
        return html

    def wrap(match: re.Match[str]) -> str:
        return f'<span style="{AMENDMENT_NOTE_STYLE}">{match.group(0)}</span>'

    html = _HTML_AMENDMENT_ANGLE_PATTERN.sub(wrap, html)
    return _HTML_AMENDMENT_BRACKET_PATTERN.sub(wrap, html)


def body_to_html(
    value: str,
    terms: tuple[str, ...] = (),
    *,
    toc_entries: list[tuple[int, str, str]] | None = None,
    anchor_prefix: str = "law",
    current_law_name: str = "",
    current_law_id: str = "",
    use_api_links: bool = False,
    administrative_rule: bool = False,
    administrative_rule_normalized: bool = False,
    embedded_images: dict[str, str] | None = None,
) -> str:
    """일반 본문과 법령 계층·글머리표 문단을 Qt용 HTML로 변환.

    장·절·조 제목은 굵게 구분하고 항·호·목은 단계별 내어쓰기를 적용한다.
    글머리표로 시작한 줄 뒤의 연속된 줄은 같은 항목으로 묶는다.
    ``administrative_rule_normalized``는 이 호출 직전에
    ``normalize_admin_rule_text``를 적용한 값에만 사용한다.
    """
    # 행정규칙은 이름만으로 번호체계를 가릴 수 없다. 본문 앞부분의
    # 첫 조항 표지로 수립지침식(1-1-1.)과 법령식(제1조)을 나눈다.
    # 앞 8,000자만 보므로 본문 전체를 한 번 더 훑지는 않는다.
    guideline_layout = administrative_rule and uses_guideline_numbering(value)
    if administrative_rule and not administrative_rule_normalized:
        # 저장된 구버전 원문도 화면을 열 때 최신 줄바꿈 규칙을 적용한다.
        # 이미 정규화된 텍스트에는 변화가 없어 반복 적용해도 안전하다.
        value = normalize_admin_rule_text(value, guideline=guideline_layout)

    # 지침처럼 첫머리에서 (이하 "법"이라 한다)로 약칭을 정하는 문서를 위해
    # 문단으로 쪼개기 전에 문서 전체에서 약칭 선언을 모아 둔다.
    document_aliases = collect_law_aliases(value)
    parts: list[str] = []
    paragraph_lines: list[str] = []
    bullet_marker = ""
    bullet_lines: list[str] = []
    bullet_level = 0
    anchor_counter = 0
    marker_font = QFont(FONT_FAMILY)
    marker_font.setPixelSize(14)
    marker_metrics = QFontMetrics(marker_font)
    current_article_jo = ""
    current_article_branch = ""

    def flush_paragraph() -> None:
        if not paragraph_lines:
            return
        content = "<br>".join(
            law_reference_html_text(
                line,
                terms,
                current_law_name=current_law_name,
                current_law_id=current_law_id,
                current_article_jo=current_article_jo,
                current_article_branch=current_article_branch,
                use_api_links=use_api_links,
                law_aliases=document_aliases,
            )
            for line in paragraph_lines
        )
        parts.append(f'<div class="paragraph">{content}</div>')
        paragraph_lines.clear()

    def flush_bullet() -> None:
        nonlocal bullet_marker, bullet_level
        if not bullet_lines:
            return
        content = "<br>".join(
            law_reference_html_text(
                line,
                terms,
                current_law_name=current_law_name,
                current_law_id=current_law_id,
                current_article_jo=current_article_jo,
                current_article_branch=current_article_branch,
                use_api_links=use_api_links,
                law_aliases=document_aliases,
            )
            for line in bullet_lines
        )
        # 호(1., 5의2. 등)와 수립지침 번호는 스페이스 한 칸 정도만
        # 들여쓰고, 일반 법령의 항ㆍ호ㆍ목ㆍ세목은 각 단계에 14px를
        # 더한다. 하위 목과 세부항목의 24px 단계 차이는 유지한다.
        if guideline_layout and ADMIN_RULE_PAREN_ITEM_PATTERN.match(
            bullet_marker
        ):
            # 수립지침 고유 번호(3-2-8-1.)와 같은 시작선에 놓이면
            # 위계가 섞여 보이므로, (1)ㆍ(2) 형식만 한 단계 들여쓴다.
            # 다른 글머리표의 기존 여백은 변경하지 않는다.
            left_margin = 12
        elif guideline_layout and bullet_marker in "○◦":
            # 수립지침의 실제 동그라미 세부항목만 12px 들여쓴다.
            # ``○○01년`` 같은 연도 자리표시자는 파싱 단계에서 항목으로
            # 분리되지 않으므로 이 조건에 들어오지 않는다.
            left_margin = 12
        elif (
            not guideline_layout
            and bullet_marker in "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
        ):
            left_margin = 14
        elif guideline_layout and ADMIN_RULE_CLAUSE_PATTERN.match(
            bullet_marker
        ):
            left_margin = 4
        elif guideline_layout and re.fullmatch(
            r"\d{1,2}\.", bullet_marker
        ):
            # 수립지침류의 독립된 ``1.``, ``2.`` 항목만 40px 띄운다.
            # 패턴은 줄 시작의 숫자와 마침표 뒤 공백까지 확인하므로
            # ``2-1-11.`` 내부의 ``1.``에는 적용되지 않는다.
            left_margin = 40
        elif guideline_layout and (
            LAW_ITEM_PATTERN.match(bullet_marker)
            or CIRCLED_HANGUL_ITEM_PATTERN.match(bullet_marker)
        ):
            # 수립지침의 독립 목 표지(가.ㆍ나.ㆍ다. 및 ㉮ㆍ㉯)만 50px
            # 들여쓴다. 줄 전체 표식 패턴을 통과한 경우라 문장 끝
            # ``한다.``의 일부가 이 조건에 들어올 수 없다.
            left_margin = 50
        elif not guideline_layout and LAW_SUBPARAGRAPH_PATTERN.match(
            bullet_marker
        ):
            # 일반 법령의 숫자 호는 항보다 12px 더 들여쓴다.
            left_margin = 26
        else:
            left_margin = (
                0 if bullet_level == 0 else 4 + (bullet_level - 1) * 24
            )
            if not guideline_layout:
                left_margin += 14
        # 표식은 실제 글자 폭만 사용하고, 뒤에는 줄바꿈되지 않는
        # 공백 한 칸만 둔다.
        # QTextDocument의 표는 첫 열을 임의로 늘려 번호 뒤에 큰
        # 빈칸을 만들기 때문에 인라인 표식과 내어쓰기를 사용한다.
        # 글자 수 기반 근사치는 "1-5-2-10."처럼 하이픈이 많은 긴
        # 수립지침 번호에서 실제 폭보다 좁게 계산되어 표식이
        # 줄바꿈되는 문제가 있었으므로 QFontMetrics로 실제 렌더링
        # 폭을 측정한다.
        marker_indent = 4 + marker_metrics.horizontalAdvance(bullet_marker)
        # QTextDocument는 div의 padding-left를 블록 여백으로 반영하지
        # 않으므로, 번호 폭을 margin-left에 포함해야 음수 text-indent로
        # 번호가 문서 바깥으로 잘리지 않는다.
        block_left_margin = left_margin + marker_indent
        parts.append(
            f'<div class="legal-indent level-{bullet_level}" '
            f'style="margin:0 0 7px {block_left_margin}px; '
            f'text-indent:-{marker_indent}px;">'
            '<span class="bullet-marker" style="font-weight:400; padding:0; '
            'white-space:nowrap;">'
            # 이전에는 "1-5-2-10."의 하이픈이 줄바꿈 가능 지점으로
            # 처리되는 걸 막으려고 줄바꿈되지 않는 하이픈(U+2011)으로
            # 치환했는데, 그러면 복사한 번호로 실제 법령 사이트에서
            # 검색이 안 되는 문제가 있었다. 일반 하이픈을 그대로 쓴다.
            f"{escape(bullet_marker)}&nbsp;</span>"
            f'<span class="bullet-text" style="font-weight:400;">'
            f"{content}</span></div>"
        )
        bullet_marker = ""
        bullet_level = 0
        bullet_lines.clear()

    source_lines: list[str] = []
    for raw_line in value.splitlines():
        expanded: list[str] = []
        for piece in split_inline_paren_items(raw_line.strip()):
            expanded.extend(
                split_paren_item_after_sentence_end(
                    piece, administrative_rule=guideline_layout
                )
            )
        source_lines.extend(expanded)
    source_lines = split_label_before_first_paren_item(source_lines)
    if guideline_layout:
        # 원문 API가 "1-5-2-1." 같은 수립지침 번호를 줄바꿈 도중에
        # 하이픈에서 끊어 "1-"만 있는 줄과 "5-2-1. ..." 줄로 나눠
        # 보내는 경우가 있다. 그대로 두면 "1-"이 빈 문단으로 떨어져
        # 나간다. 하이픈으로 끝나고 그 뒤로 이어질 숫자만 있는 줄은
        # 다음 줄과 합쳐서 하나의 번호로 복원한다.
        merged_lines: list[str] = []
        pending_prefix = ""
        for line in source_lines:
            if pending_prefix:
                line = pending_prefix + line
                pending_prefix = ""
            if re.fullmatch(r"\d+(?:-\d+)*-", line):
                pending_prefix = line
                continue
            merged_lines.append(line)
        if pending_prefix:
            merged_lines.append(pending_prefix)
        source_lines = merge_bare_clause_reference(
            merge_circled_reference_lines(
                merge_marker_reference_fragments(merged_lines)
            )
        )
        # 문장 중간에서 끊겨 목 표지처럼 보이는 ``다.)`` 꼬리를
        # 앞 줄로 되돌린다. 실제 목 표지는 뒤에 본문이 있어
        # 이 병합에 걸리지 않는다.
        source_lines = merge_sentence_tail_item_lines(source_lines)
        # 조각난 참조 병합 과정에서 짧은 지침 제목과 첫 하위항목이
        # ``4-9-2-1. 도로(1) 기준도로가...``처럼 다시 붙을 수 있다.
        # 지침번호로 시작하고 (1) 뒤에 독립 본문이 있는 경우만 재분리한다.
        # ``3-2-8-1. (1)에서 정한`` 같은 조항 참조는 공백 조건 때문에
        # 이 규칙에 걸리지 않는다.
        separated_lines: list[str] = []
        first_item_after_title = re.compile(
            r"^(\d+(?:-\d+)+\.\s+.{1,40}?)(\(1\)\s+\S.*)$"
        )
        for line in source_lines:
            title_item_match = first_item_after_title.match(line)
            if title_item_match:
                separated_lines.extend(
                    [title_item_match.group(1).rstrip(), title_item_match.group(2)]
                )
            else:
                separated_lines.append(line)
        source_lines = separated_lines

    for line in source_lines:
        if not line:
            flush_bullet()
            flush_paragraph()
            continue

        image_match = ADMIN_RULE_IMAGE_MARKER_PATTERN.fullmatch(line.strip())
        if image_match:
            flush_bullet()
            flush_paragraph()
            image_id = image_match.group(1)
            image_uri = str((embedded_images or {}).get(image_id) or "")
            if image_uri.startswith("data:image/"):
                parts.append(
                    '<div class="law-source-image" '
                    'style="margin:8px 0 12px 0;">'
                    f'<img src="{escape(image_uri, quote=True)}" '
                    f'alt="원문 표 이미지 {escape(image_id)}" '
                    'style="max-width:100%;" /></div>'
                )
            else:
                image_url = (
                    "https://www.law.go.kr/LSW/flDownload.do?flSeq="
                    f"{image_id}"
                )
                parts.append(
                    '<div class="law-source-image-missing" '
                    'style="margin:8px 0 12px 0; color:#526176;">'
                    f'<a href="{escape(image_url, quote=True)}">'
                    "원문 표 이미지 열기</a></div>"
                )
            continue

        heading_match = LAW_HEADING_PATTERN.match(line)
        if heading_match and administrative_rule:
            # 지침 본문에는 ``제8장까지에서 규정하고 있는 ... 적용할 수
            # 있다.``처럼 다른 장을 인용하는 문장도 있다. 줄 첫머리가
            # 제N장이라는 이유만으로 긴 완결 문장 전체를 장 제목처럼
            # 파란 굵은 글씨로 만들지 않는다.
            heading_body = heading_match.group(2).strip()
            if len(heading_body) > 40 or heading_body.endswith(
                ("다", "다.", "한다", "한다.", "있다", "있다.")
            ):
                heading_match = None
        if heading_match:
            flush_bullet()
            flush_paragraph()
            marker, heading = heading_match.groups()
            size = 17 if marker.endswith(("편", "장")) else 15
            heading_text = f"{marker} {heading}".strip()
            anchor_open = ""
            anchor_close = ""
            if toc_entries is not None:
                depth = {"편": 0, "장": 1, "절": 2, "관": 3}.get(
                    marker[-1], 1
                )
                anchor = f"{anchor_prefix}-{anchor_counter}"
                anchor_counter += 1
                toc_entries.append((depth, heading_text, anchor))
                anchor_open = f'<a name="{escape(anchor)}">'
                anchor_close = "</a>"
            parts.append(
                '<div class="law-heading" '
                f'style="font-weight:700; font-size:{size}px; color:#173b63; '
                'margin:20px 0 10px 0;">'
                f"{anchor_open}{highlight_html_text(heading_text, terms)}"
                f"{anchor_close}</div>"
            )
            continue

        # 수립지침식 번호(1-1-1.) 본문 안의 "제OO조(...)"는 지침 자체의
        # 조문이 아니라 근거 법령을 인용하며 그대로 옮겨 적은 문구일
        # 뿐이다. 법령 문서에서처럼 굵은 독립 표제로 뽑아내면 지침 고유
        # 번호 바로 다음 줄이 굵게 튀므로, 지침식에서만 이 패턴을 빼고
        # 일반 문단(인용문)으로 흘려보낸다. 법령식 행정규칙(제1조)은
        # 조 표제로 본다.
        article_match = (
            None if guideline_layout else LAW_ARTICLE_PATTERN.match(line)
        )
        if article_match:
            flush_bullet()
            flush_paragraph()
            article_title, article_body = article_match.groups()
            article_unit = LAW_UNIT_REFERENCE_PATTERN.match(article_title)
            if article_unit:
                current_article_jo = str(article_unit.group("jo") or "")
                current_article_branch = str(
                    article_unit.group("jo_branch") or ""
                )
            anchor_open = ""
            anchor_close = ""
            if toc_entries is not None:
                anchor = f"{anchor_prefix}-{anchor_counter}"
                anchor_counter += 1
                # 수립지침류 본문 안에 인용·첨부된 법령 조문(제OO조)은
                # 지침 자체의 목차 구조(편·장·절)가 아니므로 목차 트리에
                # 함께 넣지 않는다. 넣으면 지침 목차에 법령 조문이 섞여
                # 보인다.
                if not guideline_layout:
                    toc_entries.append((4, article_title, anchor))
                anchor_open = f'<a name="{escape(anchor)}">'
                anchor_close = "</a>"
            body_html = (
                " "
                + law_reference_html_text(
                    article_body,
                    terms,
                    current_law_name=current_law_name,
                    current_law_id=current_law_id,
                    current_article_jo=current_article_jo,
                    current_article_branch=current_article_branch,
                    use_api_links=use_api_links,
                    law_aliases=document_aliases,
                )
                if article_body
                else ""
            )
            parts.append(
                '<div class="law-article" style="margin:14px 0 8px 0;">'
                f"{anchor_open}"
                '<span class="law-article-title" '
                'style="font-weight:700; color:#173b63;">'
                f"{highlight_html_text(article_title, terms)}</span>"
                f"{anchor_close}{body_html}</div>"
            )
            continue

        marker_match = None
        marker_level = 0
        marker_patterns = (
            (
                (ADMIN_RULE_CLAUSE_PATTERN, 0),
                (LAW_PARAGRAPH_PATTERN, 2),
                (ADMIN_RULE_PAREN_ITEM_PATTERN, 1),
                (ADMIN_RULE_NUMBERED_ITEM_PATTERN, 1),
                (LAW_ITEM_PATTERN, 2),
                (CIRCLED_HANGUL_ITEM_PATTERN, 2),
                (LAW_SUBITEM_PATTERN, 2),
                (BULLET_PATTERN, 0),
            )
            if guideline_layout
            else (
                (LAW_PARAGRAPH_PATTERN, 0),
                (LAW_SUBPARAGRAPH_PATTERN, 1),
                (LAW_ITEM_PATTERN, 2),
                (LAW_SUBITEM_PATTERN, 3),
                (BULLET_PATTERN, 0),
            )
        )
        for pattern, level in marker_patterns:
            marker_match = pattern.match(line)
            if marker_match:
                marker_level = level
                break

        if marker_match:
            flush_bullet()
            flush_paragraph()
            bullet_marker = marker_match.group(1)
            bullet_level = marker_level
            bullet_lines.append(marker_match.group(2).strip())
        elif bullet_lines:
            bullet_lines.append(line)
        else:
            paragraph_lines.append(line)

    flush_bullet()
    flush_paragraph()
    return style_amendment_notes("".join(parts))


def law_headline_text(short_name: str, subtitle: str) -> str:
    """제목 옆 약칭과 아래 시행일 줄을 한 줄 평문으로 합친다(고정 머리글용)."""
    parts = []
    if short_name:
        parts.append(f"( 약칭: {short_name} )")
    if subtitle:
        parts.append(str(subtitle))
    return "  ".join(parts)


def detail_document_header(
    title: str,
    metadata: list,
    terms: tuple[str, ...] = (),
    *,
    short_name: str = "",
    subtitle: str = "",
) -> tuple[list[str], list[str]]:
    """공통 본문 제목과 기본정보를 최대 3개 항목씩 가로 배치.

    ``short_name``ㆍ``subtitle``은 법제처 본문 머리글과 같은 표기를 위한 것이다.
    제목 옆에 ``( 약칭: 국토계획법 )``을, 그 아래에
    ``[시행 2026. 7. 1.] [법률 제21447호, 2026. 3. 5., 타법개정]``을 둔다.
    """
    heading = highlight_html_text(str(title), terms)
    if short_name:
        heading += (
            ' <span class="doc-short-name">'
            f"( 약칭: {highlight_html_text(str(short_name), terms)} )</span>"
        )
    html_parts = [
        DETAIL_DOCUMENT_STYLE,
        f"<h1>{heading}</h1>",
    ]
    plain_parts = [str(title)]
    if short_name:
        plain_parts.append(f"( 약칭: {short_name} )")
    if subtitle:
        html_parts.append(
            '<div class="doc-subtitle">'
            f"{highlight_html_text(str(subtitle), terms)}</div>"
        )
        plain_parts.append(str(subtitle))
    visible_metadata = [
        (str(label), str(value or ""))
        for label, value in metadata
        if str(value or "")
    ]
    if visible_metadata:
        html_parts.append(
            '<div class="meta"><table cellspacing="0" cellpadding="0">'
        )
        for offset in range(0, len(visible_metadata), 3):
            row = visible_metadata[offset : offset + 3]
            html_parts.append("<tr>")
            for label, value in row:
                # 폐지ㆍ연혁 안내는 그냥 지나치기 쉬워 붉게 강조한다.
                value_class = (
                    "meta-warning" if label == REPEAL_NOTICE_LABEL else "meta-value"
                )
                html_parts.append(
                    '<td><span class="meta-label">'
                    f"{escape(label)}</span>&nbsp;"
                    f'<span class="{value_class}">'
                    f"{highlight_html_text(value, terms)}</span></td>"
                )
                plain_parts.append(f"{label} {value}")
            for _unused in range(3 - len(row)):
                html_parts.append("<td></td>")
            html_parts.append("</tr>")
        html_parts.append("</table></div>")
    return html_parts, plain_parts
