"""본문 줄 간격이 실제로 먹는지 보는 회귀 테스트.

Qt는 ``body``에 적은 ``line-height``를 자식에게 물려주지 않는다. 그래서
body 값을 1.45에서 1.75로 올려도 본문 줄 간격은 그대로였다(문서 높이가
같았다). 실제 글이 담기는 ``.content``에 준 값만 화면에 반영된다.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QTextBrowser

from utils.formatting import DETAIL_DOCUMENT_STYLE


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _document_height(qt_app, style: str) -> float:
    body = (
        '<div class="content"><p class="paragraph">'
        + "제15조(용도지역) 토지의 이용 및 건축물의 용도를 제한하는 지역으로서 " * 4
        + "</p></div>"
    )
    browser = QTextBrowser()
    browser.resize(500, 400)
    browser.show()
    try:
        browser.setHtml(style + body)
        qt_app.processEvents()
        document = browser.document()
        document.setTextWidth(480)
        return document.size().height()
    finally:
        browser.close()


def test_content_line_height_actually_changes_layout(qt_app) -> None:
    """.content에 준 줄 간격은 문서 높이를 실제로 바꾼다."""
    tight = _document_height(
        qt_app, DETAIL_DOCUMENT_STYLE.replace("line-height:1.75;", "line-height:1.0;")
    )
    loose = _document_height(qt_app, DETAIL_DOCUMENT_STYLE)

    assert loose > tight, (
        f"줄 간격을 넓혔는데 문서 높이가 그대로다 ({tight} → {loose})"
    )


def test_body_line_height_would_not_reach_the_body_text(qt_app) -> None:
    """body에 적은 값은 본문에 닿지 않는다는 사실을 고정한다.

    Qt가 이 동작을 바꾸면 .content 쪽 지정이 없어도 되므로 함께 알아챈다.
    """
    style = DETAIL_DOCUMENT_STYLE.replace(
        ".content { font-family:", ".content { xx-unused:0; font-family:"
    )
    narrow = _document_height(
        qt_app, style.replace("color:#202124; }", "color:#202124; line-height:1.0; }")
    )
    wide = _document_height(
        qt_app, style.replace("color:#202124; }", "color:#202124; line-height:2.5; }")
    )

    assert narrow == wide, (
        "body의 line-height가 본문에 적용되기 시작했다. "
        ".content 쪽 지정을 다시 살펴볼 것"
    )
