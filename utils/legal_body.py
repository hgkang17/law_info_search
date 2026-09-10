"""법령ㆍ행정규칙ㆍ자치법규의 화면 공통 본문 렌더링.

API별 응답 해석은 파서, 화면별 여백은 호출자가 담당한다. 별표 인용과
본문 정규화는 전문ㆍ조문검색ㆍ팝업ㆍ3단비교가 이 경로를 함께 쓴다.
"""

import re
from html import escape
from urllib.parse import quote

from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor, QTextDocument

from utils.formatting import body_to_html
from utils.parsing import normalize_legal_body


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
        tokens[token] = (
            match.group(0), annex_reference_href(label, related_law, category), label
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
            if label in entries:
                href = f"annexopen:{entries[label]}"
            elif document_name:
                href = annex_reference_href(label, document_name, category)
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
