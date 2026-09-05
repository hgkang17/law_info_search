import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QStackedWidget,
    QTextBrowser,
    QWidget,
)

from ui.widgets import DetailSearchBar


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_search_matches_are_yellow_and_current_match_is_orange() -> None:
    app = _app()
    browser = QTextBrowser()
    browser.setPlainText("국토교통부령과 국토교통부령")
    bar = DetailSearchBar(browser)

    bar.query_input.setText("국토교통부령")
    app.processEvents()

    backgrounds = [
        selection.format.background().color().name()
        for selection in browser.extraSelections()
    ]
    assert backgrounds == ["#ff9800", "#ffeb3b"]

    bar.move(1)
    backgrounds = [
        selection.format.background().color().name()
        for selection in browser.extraSelections()
    ]
    assert backgrounds == ["#ffeb3b", "#ff9800"]


def test_ctrl_f_uses_selected_body_text_as_query() -> None:
    app = _app()
    browser = QTextBrowser()
    browser.setPlainText("도시·군계획시설 결정 기준")
    bar = DetailSearchBar(browser)
    assert bar.isHidden()
    cursor = browser.textCursor()
    cursor.setPosition(0)
    cursor.setPosition(8, QTextCursor.MoveMode.KeepAnchor)
    browser.setTextCursor(cursor)

    bar.focus_query()
    app.processEvents()

    assert not bar.isHidden()
    assert bar.query_input.text() == "도시·군계획시설"
    assert len(bar.matches) == 1
    assert bar.query_input.hasSelectedText()


def test_whole_word_option_excludes_partial_matches() -> None:
    app = _app()
    browser = QTextBrowser()
    browser.setPlainText("삭제 삭제조항 삭제")
    bar = DetailSearchBar(browser)

    bar.query_input.setText("삭제")
    app.processEvents()
    assert len(bar.matches) == 3

    bar.whole_word_checkbox.setChecked(True)
    app.processEvents()
    assert len(bar.matches) == 2
    assert bar.count_label.text() == "1/2"


def test_find_bar_closes_on_escape_and_when_the_body_is_hidden() -> None:
    """찾기 창은 본문에서 Esc를 눌러도, 화면을 옮겨도 닫혀야 한다.

    예전에는 검색칸 안에 커서가 있을 때만 Esc가 들었고, 다른 탭으로 옮겨도
    본문 위에 뜬 창이 그대로 남아 엉뚱한 화면을 가렸다.
    """
    qt_app = _app()
    stack = QStackedWidget()
    browser = QTextBrowser()
    browser.setPlainText("제1조 목적\n제2조 정의\n")
    other = QWidget()
    stack.addWidget(browser)
    stack.addWidget(other)
    stack.resize(600, 400)
    stack.show()
    qt_app.processEvents()
    bar = DetailSearchBar(browser)
    try:
        bar.focus_query()
        qt_app.processEvents()
        assert bar.isVisible()

        browser.setFocus()
        qt_app.sendEvent(
            browser,
            QKeyEvent(
                QEvent.Type.KeyPress,
                Qt.Key.Key_Escape,
                Qt.KeyboardModifier.NoModifier,
            ),
        )
        qt_app.processEvents()
        assert not bar.isVisible()

        bar.focus_query()
        qt_app.processEvents()
        stack.setCurrentWidget(other)
        qt_app.processEvents()
        assert not bar.isVisible()

        # 전체 단어 일치는 줄을 차지하지 않고 ⋯ 팝업 안에 있다.
        assert bar.whole_word_checkbox in [
            action.defaultWidget()
            for action in bar.options_menu.actions()
            if hasattr(action, "defaultWidget")
        ]
    finally:
        bar.close()
        stack.close()
