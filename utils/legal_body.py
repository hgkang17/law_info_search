"""법령ㆍ행정규칙ㆍ자치법규의 화면 공통 본문 렌더링.

API별 응답 해석은 파서, 화면별 여백은 호출자가 담당한다. 별표 인용과
본문 정규화는 전문ㆍ조문검색ㆍ팝업ㆍ3단비교가 이 경로를 함께 쓴다.
"""

import re
from html import escape
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit

from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor, QTextDocument

from utils.formatting import body_to_html
from utils.parsing import normalize_legal_body, _is_enumeration_gap
from utils.patterns import LAW_UNIT_REFERENCE_PATTERN


def repair_enumerated_reference_links(document: QTextDocument) -> None:
    """원문 없는 구버전 HTML의 호 링크에 누락된 상위 항만 보충한다.

    같은 문단의 직전 링크가 같은 법령/조이고 열거 접속어로 연결된 경우만
    고친다. 글자ㆍ서식ㆍ메모 위치를 바꾸거나 다른 종류의 링크를 만들지 않는다.
    """
    edits = []
    block = document.begin()
    while block.isValid():
        anchors = []
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            href = fragment.charFormat().anchorHref()
            if href:
                start, end = fragment.position(), fragment.position() + fragment.length()
                if anchors and anchors[-1][1] == start and anchors[-1][2] == href:
                    anchors[-1][1] = end
                    anchors[-1][3] += fragment.text()
                else:
                    anchors.append([start, end, href, fragment.text()])
            iterator += 1
        previous = None
        for start, end, href, label in anchors:
            url = urlsplit(href)
            params = parse_qs(url.query)
            unit = LAW_UNIT_REFERENCE_PATTERN.fullmatch(label)
            if (
                previous and url.scheme == "lawref" and unit
                and unit.group("ho") and not unit.group("jo")
                and not unit.group("hang")
            ):
                previous_end, previous_url, previous_params = previous
                gap_cursor = QTextCursor(document)
                gap_cursor.setPosition(previous_end)
                gap_cursor.setPosition(start, QTextCursor.MoveMode.KeepAnchor)
                gap = gap_cursor.selectedText()
                if (
                    previous_url.scheme == "lawref"
                    and params.get("jo") and previous_params.get("hang")
                    and not params.get("hang")
                    and params.get("ho") == [unit.group("ho")]
                    and all(params.get(key) == previous_params.get(key)
                            for key in ("name", "id", "jo", "jo_branch"))
                    and gap.strip() and _is_enumeration_gap(gap)
                ):
                    for key in ("hang", "hang_branch"):
                        if previous_params.get(key):
                            params[key] = previous_params[key]
                    new_href = urlunsplit(url._replace(
                        query=urlencode(params, doseq=True, quote_via=quote)
                    ))
                    edits.append((start, end, new_href))
            previous = end, url, params
        block = block.next()
    if edits:
        cursor = QTextCursor(document)
        cursor.beginEditBlock()
        for start, end, href in edits:
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            style = QTextCharFormat()
            style.setAnchorHref(href)
            cursor.mergeCharFormat(style)
        cursor.endEditBlock()


ANNEX_CATEGORY_BY_TARGET = {
    "law": "licbyl",
    "law_article": "licbyl",
    "admrul": "admbyl",
    "ordin": "ordinbyl",
}
INLINE_ANNEX_REFERENCE_PATTERN = re.compile(
    r"별지\s*제\s*(?P<form>\d+)\s*호(?:\s*의\s*(?P<form_branch>\d+))?"
    r"\s*서식"
    r"|별표\s*제?\s*(?P<table>\d+)(?:\s*의\s*(?P<table_branch>\d+))?"
)
_ANNEX_LAW_PREFIX_PATTERN = re.compile(
    r"「(?P<law>[^」\n]{1,80}(?:법률|법|시행령|시행규칙|조례|규칙|규정|지침|고시))」\s*(?:의\s*)?$"
)


def _annex_context(text: str, start: int, document_name: str, category: str) -> tuple[str, str]:
    """별표 바로 앞에서 명시한 다른 법령을 현재 문서보다 우선한다."""
    match = _ANNEX_LAW_PREFIX_PATTERN.search(text[max(0, start - 120):start])
    if not match:
        return document_name, category
    name = match.group("law").strip()
    if name == document_name:
        return name, category
    if name.endswith(("법", "법률", "시행령", "시행규칙")):
        return name, "licbyl"
    if name.endswith(("조례", "규칙")):
        return name, "ordinbyl"
    return name, "admbyl"


def inline_annex_label(match: re.Match[str]) -> str:
    if match.group("form"):
        branch = match.group("form_branch") or ""
        suffix = f"의{branch}" if branch else ""
        return f"별지 제{int(match.group('form'))}호{suffix}서식"
    number = match.group("table")
    if not number:
        return ""
    branch = match.group("table_branch") or ""
    return f"별표 {int(number)}" + (f"의{int(branch)}" if branch else "")


def annex_reference_href(label: str, related_law: str, category: str) -> str:
    return (
        "annexref://open?"
        f"name={quote(label, safe='')}"
        f"&category={quote(category, safe='')}"
        f"&related={quote(related_law, safe='')}"
    )


def mask_annex_mentions(
    text: str, *, related_law: str, category: str
) -> tuple[str, dict[str, tuple[str, str, str]]]:
    tokens: dict[str, tuple[str, str, str]] = {}
    if not related_law:
        return text, tokens

    def replace(match: re.Match[str]) -> str:
        if match.start() and text[match.start() - 1] == "[":
            return match.group(0)
        label = inline_annex_label(match)
        if not label:
            return match.group(0)
        token = f"INLINEANNEXLINK{len(tokens)}TOKEN"
        owner, target = _annex_context(text, match.start(), related_law, category)
        tokens[token] = (
            match.group(0), annex_reference_href(label, owner, target), label
        )
        return token

    return INLINE_ANNEX_REFERENCE_PATTERN.sub(replace, text), tokens


def restore_annex_mentions(
    html: str, tokens: dict[str, tuple[str, str, str]]
) -> str:
    for token, (mention, href, label) in tokens.items():
        html = html.replace(
            token,
            f'<a href="{escape(href, quote=True)}" '
            'style="color:#006dcc; text-decoration:underline;" '
            f'title="{escape(label)}을(를) 엽니다.">{escape(mention)}</a>',
        )
    return html


def apply_annex_links(
    document: QTextDocument, *, document_name: str, document_target: str,
    entries_by_label: dict[str, int] | None = None,
) -> None:
    """저장된 Qt 문서도 같은 규칙으로 보강한다. 글자ㆍ메모 위치는 바꾸지 않는다."""
    repair_enumerated_reference_links(document)
    text = document.toPlainText()
    entries = entries_by_label or {}
    category = ANNEX_CATEGORY_BY_TARGET.get(document_target, "licbyl")
    cursor = QTextCursor(document)
    cursor.beginEditBlock()
    try:
        for match in INLINE_ANNEX_REFERENCE_PATTERN.finditer(text):
            if match.start() and text[match.start() - 1] == "[":
                continue
            label = inline_annex_label(match)
            owner, target = _annex_context(text, match.start(), document_name, category)
            is_local = owner == document_name and target == category
            if is_local and label in entries:
                href = f"annexopen:{entries[label]}"
            elif (
                is_local and document_target == "ordin" and label.startswith("별표 ")
                and "별표" in entries
                and not any(key.startswith("별표 ") for key in entries)
            ):
                # 번호별 파일이 없고 [별표] 하나에 몰아 둔 자치법규만 적용한다.
                # 별지서식이나 다른 법령의 별표에는 이 묶음을 사용하지 않는다.
                href = f"annexopen:{entries['별표']}"
            elif owner:
                href = annex_reference_href(label, owner, target)
            else:
                continue
            cursor.setPosition(match.start())
            cursor.setPosition(match.end(), QTextCursor.MoveMode.KeepAnchor)
            style = QTextCharFormat()
            style.setAnchor(True)
            style.setAnchorHref(href)
            style.setForeground(QColor("#006dcc"))
            style.setFontUnderline(True)
            style.setToolTip(f"{label}을(를) 엽니다.")
            cursor.mergeCharFormat(style)
    finally:
        cursor.endEditBlock()


def legal_body_to_html(
    value: str, terms: tuple[str, ...] = (), *,
    document_target: str = "law", document_name: str = "", **options,
) -> str:
    value = normalize_legal_body(value, document_target)
    value, tokens = mask_annex_mentions(
        value, related_law=document_name,
        category=ANNEX_CATEGORY_BY_TARGET.get(document_target, "licbyl"),
    )
    if document_target == "admrul":
        options["administrative_rule"] = True
        options["administrative_rule_normalized"] = True
    return restore_annex_mentions(body_to_html(value, terms, **options), tokens)
