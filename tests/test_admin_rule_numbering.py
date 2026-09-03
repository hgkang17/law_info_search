"""행정규칙 본문의 법령식·수립지침식 번호체계 구분."""

import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QApplication

from utils.constants import FONT_FAMILY
from utils.formatting import ARTICLE_BODY_LEFT_MARGIN, body_to_html
from utils.parsing import (
    insert_admin_clause_breaks,
    insert_law_style_article_breaks,
    normalize_admin_rule_text,
    uses_guideline_numbering,
)


LAW_STYLE_SNIPPET = (
    "[시행 2025. 3. 31.] [국토교통부고시 제2025-168호, 2025. 3. 31., 일부개정.]\n"
    "제1장 총칙\n"
    "제1조(목적) 이 지침은「산업입지 및 개발에 관한 법률」(이하 "
    '"「산업입지법」"이라 한다) 제5조에 따른 산업입지의 개발에 관한 '
    "기본적인 지침을 규정한다.\n"
    "제4조(산업단지개발 기본방향) ① 산업단지개발은 충분한 면적을 공급한다.\n"
    "1. 국가기간산업의 육성을 위하여 필요한 경우"
)

GUIDELINE_SNIPPET = (
    "제1장 총칙\n"
    "1-1-1. 목적\n"
    "이 지침은 「국토의 계획 및 이용에 관한 법률」 "
    "제25조(도시ㆍ군관리계획)에 따라 수립한다.\n"
    "1-1-2. 적용범위"
)


def test_uses_guideline_numbering_skips_chapter_and_reads_first_clause() -> None:
    assert uses_guideline_numbering(LAW_STYLE_SNIPPET) is False
    assert uses_guideline_numbering(GUIDELINE_SNIPPET) is True
    assert uses_guideline_numbering("제1장 총칙\n제2절 통칙") is True
    assert uses_guideline_numbering("") is True
    assert uses_guideline_numbering("① 허가 대상") is True
    # 앞부분만 본다. 뒤에 다른 번호가 있어도 첫 표지를 따른다.
    assert (
        uses_guideline_numbering("제1조(목적) " + ("가" * 9000) + "1-1-1. 뒤")
        is False
    )
    assert uses_guideline_numbering("1-1-1. 목적\n제1조(목적) 인용") is True


def test_law_style_article_breaks_split_glued_title_only() -> None:
    source = "제1장 총칙제1조(목적) 이 지침은 제5조에 따른 사항을 규정한다."
    assert insert_law_style_article_breaks(source).splitlines() == [
        "제1장 총칙",
        "제1조(목적) 이 지침은 제5조에 따른 사항을 규정한다.",
    ]
    citation = (
        "적용한다. 「국토의 계획 및 이용에 관한 법률」 "
        "제25조(도시ㆍ군관리계획)에 따른 사항"
    )
    assert insert_law_style_article_breaks(citation) == citation


def test_law_style_admin_rule_renders_article_titles() -> None:
    QApplication.instance() or QApplication([])
    html = body_to_html(LAW_STYLE_SNIPPET, administrative_rule=True)

    assert 'class="law-article-title"' in html
    assert "제1조(목적)" in html
    assert "law-article-title" in html
    titles = re.findall(
        r'class="law-article-title"[^>]*>([^<]+)</span>',
        html,
    )
    assert "제1조(목적)" in titles
    assert "제4조(산업단지개발 기본방향)" in titles
    assert "제5조에 따른" in html.replace("&nbsp;", " ")

    items = re.findall(
        r'style="margin:0 0 7px (\d+)px;[^>]*>\s*'
        r'<span class="bullet-marker"[^>]*>([^<]+)&nbsp;',
        html,
    )
    marker_font = QFont(FONT_FAMILY)
    marker_font.setPixelSize(14)
    law_item_margin = (
        ARTICLE_BODY_LEFT_MARGIN
        + 12
        + 4
        + QFontMetrics(marker_font).horizontalAdvance("1.")
    )
    guideline_item_margin = 40 + 4 + QFontMetrics(marker_font).horizontalAdvance(
        "1."
    )
    assert (str(law_item_margin), "1.") in items
    assert (str(guideline_item_margin), "1.") not in items


def test_guideline_quoted_law_article_stays_a_paragraph() -> None:
    QApplication.instance() or QApplication([])
    html = body_to_html(GUIDELINE_SNIPPET, administrative_rule=True)

    assert 'class="law-article-title"' not in html
    # 법령 링크가 ``제25조``와 ``(도시ㆍ군관리계획)`` 사이를 갈라
    # 한 덩어리로는 안 남는다. 표제로 뽑히지 않은지만 보면 된다.
    assert "제25조" in html
    assert "(도시ㆍ군관리계획)" in html
    assert "1-1-1.&nbsp;" in html


def test_guideline_standalone_article_citation_is_not_a_title() -> None:
    QApplication.instance() or QApplication([])
    source = (
        "1-1-1. 목적\n"
        "제25조(도시ㆍ군관리계획)에 따른 사항을 적용한다."
    )
    html = body_to_html(source, administrative_rule=True)
    assert 'class="law-article-title"' not in html
    assert "제25조(도시ㆍ군관리계획)에 따른 사항을 적용한다." in html.replace(
        "&nbsp;", " "
    )


def test_normalize_admin_rule_text_follows_numbering() -> None:
    glued = "제1장 총칙제1조(목적) 이 지침은 규정한다."
    assert normalize_admin_rule_text(glued).splitlines() == [
        "제1장 총칙",
        "제1조(목적) 이 지침은 규정한다.",
    ]
    guideline = "1-1-1. 목적(1) 공통기준"
    normalized = normalize_admin_rule_text(guideline)
    assert normalized == insert_admin_clause_breaks(guideline)
    assert normalized.splitlines()[0].startswith("1-1-1.")
    assert "(1) 공통기준" in normalized
    # 지침 본문의 법령 인용 조문은 기존 줄바꿈을 그대로 둔다.
    cited = (
        "1-1-1. 목적\n"
        "이 지침은 제25조(도시ㆍ군관리계획)에 따라 수립한다."
    )
    assert normalize_admin_rule_text(cited) == insert_admin_clause_breaks(cited)
