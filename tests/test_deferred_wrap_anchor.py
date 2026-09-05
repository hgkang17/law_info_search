import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QTextCursor, QTextDocument
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTextEdit

from ui.widgets import DETAIL_DOCUMENT_MARGIN, DeferredWrapTextBrowser


class _ControlWheelEvent:
    @staticmethod
    def modifiers():
        return Qt.KeyboardModifier.ControlModifier

    def accept(self) -> None:
        self.accepted = True


def test_control_wheel_is_ignored_in_law_body() -> None:
    QApplication.instance() or QApplication([])
    browser = DeferredWrapTextBrowser()
    event = _ControlWheelEvent()
    event.accepted = False

    browser.wheelEvent(event)

    assert event.accepted


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


def test_document_margin_keeps_text_off_the_viewer_edge() -> None:
    """본문 글자가 표시 영역 테두리에 붙지 않도록 문서 여백을 넓혀 둔다."""
    app = QApplication.instance() or QApplication([])
    browser = DeferredWrapTextBrowser()
    browser.setPlainText("제1조(목적) 본문 여백을 확인한다.")
    app.processEvents()
    assert browser.document().documentMargin() == DETAIL_DOCUMENT_MARGIN
    browser.deleteLater()


def test_replacing_document_resets_margin_unless_it_is_set_again() -> None:
    """문서를 갈아 끼우면 여백이 Qt 기본값으로 돌아간다는 사실을 고정한다.

    본문 탭을 오갈 때 ResourceSearchTab이 setDocument로 문서를 통째로
    바꾼다. 그 경로에서 여백을 다시 지정하지 않으면 탭을 옮긴 뒤에만
    글자가 테두리에 붙어 보였다. Qt가 이 동작을 바꾸면 보정 코드가
    필요 없어지므로 여기서 함께 알아챈다.
    """
    app = QApplication.instance() or QApplication([])
    browser = DeferredWrapTextBrowser()
    plain = QTextDocument()
    browser.setDocument(plain)
    app.processEvents()
    assert browser.document().documentMargin() != DETAIL_DOCUMENT_MARGIN

    # ResourceSearchTab._set_active_text_document이 하는 보정과 같다.
    plain.setDocumentMargin(DETAIL_DOCUMENT_MARGIN)
    assert browser.document().documentMargin() == DETAIL_DOCUMENT_MARGIN
    browser.deleteLater()


def test_settle_wrap_now_restores_widget_width_before_new_content() -> None:
    """내용을 갈아 끼우기 전에 미뤄 둔 줄바꿈을 끝낸다.

    지연 줄바꿈이 남은 채 새 문서를 넣으면 이전 폭이 고정된 채 배치되고,
    뒤늦게 도착한 타이머가 이전 문서 기준 스크롤을 되살리려 든다. 글자
    크기를 바꾼 직후 본문이 빈 것처럼 보이던 원인이다.
    """
    app = QApplication.instance() or QApplication([])
    browser = DeferredWrapTextBrowser()
    browser.resize(400, 300)
    browser.setPlainText("본문 " * 200)
    app.processEvents()

    # 창 크기 조절 중인 상태를 흉내 낸다.
    browser._wrap_deferred = True
    browser._resize_anchor_position = 5
    browser.setLineWrapMode(QTextEdit.LineWrapMode.FixedPixelWidth)
    browser.setLineWrapColumnOrWidth(120)

    browser.settle_wrap_now()

    assert browser._wrap_deferred is False
    assert browser.lineWrapMode() == QTextEdit.LineWrapMode.WidgetWidth
    assert browser._resize_anchor_position == -1
    browser.deleteLater()
