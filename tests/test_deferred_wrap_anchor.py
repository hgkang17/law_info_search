import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ui.widgets import DeferredWrapTextBrowser


def test_resize_preserves_top_visible_text_position() -> None:
    app = QApplication.instance() or QApplication([])
    browser = DeferredWrapTextBrowser()
    browser.resize(420, 260)
    browser.setPlainText(
        "\n".join(
            f"{index}. 창 크기가 바뀌어도 화면 첫 줄의 본문 위치를 유지하는 긴 문장입니다."
            for index in range(1, 180)
        )
    )
    browser.show()
    app.processEvents()
    browser.verticalScrollBar().setValue(
        browser.verticalScrollBar().maximum() // 2
    )
    app.processEvents()
    anchor_cursor = browser.cursorForPosition(QPoint(2, 2))
    position_before = anchor_cursor.position()
    anchor_y_before = browser.cursorRect(anchor_cursor).top()

    browser.resize(760, 420)
    QTest.qWait(browser.WRAP_SETTLE_MS + 80)
    app.processEvents()
    restored_cursor = QTextCursor(browser.document())
    restored_cursor.setPosition(position_before)
    anchor_y_after = browser.cursorRect(restored_cursor).top()

    # 폭이 넓어지면 줄의 시작 문자는 앞당겨질 수 있으므로, 저장한 문자가
    # 기존 첫 줄과 같은 화면 높이에 남는지를 확인한다.
    assert abs(anchor_y_after - anchor_y_before) <= 2
