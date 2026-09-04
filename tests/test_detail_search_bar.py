import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QTextBrowser

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
