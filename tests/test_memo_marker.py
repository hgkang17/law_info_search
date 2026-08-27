from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPalette, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QApplication, QTextBrowser, QWidget

from ui.widgets import (
    MemoMarkerBar,
    build_restore_view_button,
    replace_search_term_backgrounds,
)
from ui.tabs.resource_search import ResourceSearchTab


def test_restore_view_button_has_back_shortcut() -> None:
    _app = QApplication.instance() or QApplication([])

    class Owner(QWidget):
        def _exit_reading_mode(self) -> None:
            pass

    owner = Owner()
    button = build_restore_view_button(owner)

    assert button.shortcut().toString() == "Alt+Left"

    owner.close()


def test_cached_law_render_state_keeps_saved_memos() -> None:
    saved_memos = [
        {"start": 10, "end": 15, "excerpt": "선택 문구", "text": "메모"}
    ]

    restored = ResourceSearchTab._cached_memos_for_state(
        {"memos": saved_memos}
    )

    assert restored == saved_memos
    assert restored is not saved_memos


def test_only_visible_memo_marker_is_clickable() -> None:
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(500, 400)
    browser = QTextBrowser(parent)
    browser.setGeometry(0, 0, 470, 400)
    browser.setPlainText("첫 문장\n" * 80)
    bar = MemoMarkerBar(browser, parent)
    bar.setGeometry(480, 0, 14, 400)
    bar.set_memos(
        [{"start": 30, "end": 38, "excerpt": "문장", "text": "메모"}]
    )
    parent.show()
    app.processEvents()

    marker = bar._marker_rects()[0]
    assert bar._marker_index_at(QPointF(marker.center())) == 0
    blank_y = marker.bottom() + 20
    assert bar._marker_index_at(QPointF(marker.center().x(), blank_y)) == -1

    parent.close()


def test_search_highlight_keeps_red_memo_underline() -> None:
    _app = QApplication.instance() or QApplication([])
    browser = QTextBrowser()
    browser.setPlainText("국토계획 메모 문구")
    memo_cursor = QTextCursor(browser.document())
    memo_cursor.setPosition(0)
    memo_cursor.setPosition(4, QTextCursor.MoveMode.KeepAnchor)

    ResourceSearchTab._apply_memo_marker(memo_cursor, "메모")
    replace_search_term_backgrounds(browser, ("국토",))

    check_cursor = QTextCursor(browser.document())
    check_cursor.setPosition(0)
    check_cursor.setPosition(1, QTextCursor.MoveMode.KeepAnchor)
    character_format = check_cursor.charFormat()
    assert (
        character_format.underlineStyle()
        == QTextCharFormat.UnderlineStyle.SingleUnderline
    )
    assert character_format.underlineColor() == QColor("#d9362e")


def test_memo_navigation_buttons_move_in_document_order() -> None:
    _app = QApplication.instance() or QApplication([])
    browser = QTextBrowser()
    browser.setPlainText("가" * 200)
    bar = MemoMarkerBar(browser)
    bar.set_memos(
        [
            {"start": 120, "end": 125, "text": "두 번째"},
            {"start": 20, "end": 25, "text": "첫 번째"},
        ]
    )

    bar._move_active_memo(1)
    assert browser.textCursor().selectionStart() == 20
    assert browser.textCursor().selectionEnd() == 25
    bar._move_active_memo(1)
    assert browser.textCursor().selectionStart() == 120
    assert browser.textCursor().selectionEnd() == 125
    bar._move_active_memo(-1)
    assert browser.textCursor().selectionStart() == 20
    assert browser.textCursor().selectionEnd() == 25


def test_memo_navigation_buttons_use_compact_height() -> None:
    assert MemoMarkerBar.NORMAL_WIDTH == 11
    assert MemoMarkerBar.NAV_BUTTON_HEIGHT == 10
    assert MemoMarkerBar.MARKER_HEIGHT == 6


def test_memo_jump_places_start_at_top_and_uses_white_selection_text() -> None:
    app = QApplication.instance() or QApplication([])
    browser = QTextBrowser()
    browser.resize(420, 180)
    browser.setPlainText("\n".join(f"본문 {index}" for index in range(200)))
    bar = MemoMarkerBar(browser)
    text = browser.toPlainText()
    start = text.index("본문 120")
    bar.set_memos(
        [{"start": start, "end": start + len("본문 120"), "text": "메모"}]
    )
    browser.show()
    app.processEvents()

    bar._jump_to_memo(0)
    app.processEvents()

    start_cursor = QTextCursor(browser.document())
    start_cursor.setPosition(start)
    assert browser.cursorRect(start_cursor).top() <= 2
    palette = browser.palette()
    assert palette.color(QPalette.ColorRole.HighlightedText) == QColor("#ffffff")

    browser.close()
