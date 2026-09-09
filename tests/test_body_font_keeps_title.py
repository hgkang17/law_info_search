"""본문 글꼴을 바꿔도 문서 제목은 화면 UI 글꼴로 남는지 검증."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QApplication

from ui.widgets import apply_body_font_family
from utils.constants import UI_FONT_FAMILIES
from utils.formatting import detail_document_header


def _blocks(document: QTextDocument):
    block = document.begin()
    while block.isValid():
        yield block
        block = block.next()


def test_title_keeps_the_ui_font_when_the_body_font_changes() -> None:
    """제목(h1)은 본문과 달리 맑은 고딕을 일부러 쓴다.

    예전에는 글꼴 칸에서 글꼴을 고르는 길만 문서 전체에 글꼴을 덮어써서,
    한 번이라도 고르면(기본값으로 되돌려도) 제목까지 본문 글꼴로 바뀌었다.
    """
    QApplication.instance() or QApplication([])
    html_parts, _plain = detail_document_header(
        "농지법", [("법령ID", "001"), ("소관부처", "농림축산식품부")]
    )
    document = QTextDocument()
    document.setHtml("".join(html_parts))

    apply_body_font_family(document, "Arial")

    titles = [
        block for block in _blocks(document)
        if block.blockFormat().headingLevel() == 1
    ]
    bodies = [
        block for block in _blocks(document)
        if block.blockFormat().headingLevel() != 1 and block.text().strip()
    ]
    assert titles and bodies
    assert titles[0].charFormat().fontFamilies() == list(UI_FONT_FAMILIES)
    assert bodies[0].charFormat().fontFamilies() == ["Arial"]

    # 다른 글꼴로 다시 바꿔도 제목은 그대로다.
    apply_body_font_family(document, "Gulim")
    assert titles[0].charFormat().fontFamilies() == list(UI_FONT_FAMILIES)
