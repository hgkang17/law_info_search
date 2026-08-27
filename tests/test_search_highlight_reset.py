from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QTextBrowser

from ui.widgets import clear_search_term_backgrounds, replace_search_term_backgrounds
from utils.formatting import highlight_html_text, strip_search_highlight_html


def test_new_search_highlight_does_not_force_text_color() -> None:
    html = highlight_html_text("국토계획법", ("국토",))

    assert "background-color:#ffe58f" in html
    assert "color:#172033" not in html


def test_compact_query_highlights_spaced_text_as_one_range() -> None:
    html = highlight_html_text("설치할 수 있는 건축물", ("설치할수있는건축물",))

    assert html.count("background-color:#ffe58f") == 1
    assert ">설치할 수 있는 건축물</span>" in html


def test_reset_removes_legacy_search_foreground() -> None:
    app = QApplication.instance() or QApplication([])
    browser = QTextBrowser()
    browser.setHtml(
        '<h1 style="color:#173b63">'
        '<span style="background-color:#ffe58f;color:#172033">국토</span>'
        "안전관리원법</h1>"
    )

    clear_search_term_backgrounds(browser, ("국토",))
    app.processEvents()
    cursor = browser.document().find("국토")

    assert cursor.charFormat().background().color().name() != "#ffe58f"
    assert cursor.charFormat().foreground().color().name() != "#172033"


def test_new_search_replaces_old_saved_highlight() -> None:
    app = QApplication.instance() or QApplication([])
    browser = QTextBrowser()
    browser.setHtml(
        '<p><a href="lawref://old"><span style="background-color:#ffe58f;'
        'color:#172033;">국토계획법</span></a> '
        "개발제한구역법</p>"
    )

    replace_search_term_backgrounds(browser, ("개발제한구역법",))
    app.processEvents()

    old_cursor = browser.document().find("국토계획법")
    new_cursor = browser.document().find("개발제한구역법")
    assert old_cursor.charFormat().background().color().name() != "#ffe58f"
    assert old_cursor.charFormat().foreground().color().name() == "#006dcc"
    assert new_cursor.charFormat().background().color().name() == "#ffe58f"


def test_saved_html_does_not_keep_automatic_search_highlight() -> None:
    html = '<p><span style="background-color:#ffe58f;">국토계획법</span></p>'

    assert strip_search_highlight_html(html) == "<p>국토계획법</p>"


def test_shorter_new_query_and_reset_leave_no_old_suffix_highlight() -> None:
    app = QApplication.instance() or QApplication([])
    browser = QTextBrowser()
    browser.setHtml(
        '<h1><span style="background-color:#ffe58f;">'
        "개발제한구역</span>의 지정</h1>"
    )

    replace_search_term_backgrounds(browser, ("개발제한",))
    app.processEvents()

    current_cursor = browser.document().find("개발제한")
    suffix_cursor = browser.document().find("구역")
    assert current_cursor.charFormat().background().color().name() == "#ffe58f"
    assert suffix_cursor.charFormat().background().color().name() != "#ffe58f"
    assert current_cursor.charFormat().fontWeight() >= int(QFont.Weight.Bold)
    assert suffix_cursor.charFormat().fontWeight() >= int(QFont.Weight.Bold)

    replace_search_term_backgrounds(browser, ())
    app.processEvents()
    cleared_cursor = browser.document().find("개발제한구역")
    assert cleared_cursor.charFormat().background().color().name() != "#ffe58f"
    assert cleared_cursor.charFormat().fontWeight() >= int(QFont.Weight.Bold)


def test_reset_preserves_nested_article_title_bold_and_link() -> None:
    app = QApplication.instance() or QApplication([])
    browser = QTextBrowser()
    browser.setHtml(
        '<div><span style="font-weight:700;color:#173b63;">제12조('
        '<a href="https://example.test"><span style="background-color:#ffe58f;">'
        "개발제한구역</span></a>에서의 행위제한)</span></div>"
    )

    replace_search_term_backgrounds(browser, ())
    app.processEvents()

    cursor = browser.document().find("개발제한구역")
    assert cursor.charFormat().background().color().name() != "#ffe58f"
    assert cursor.charFormat().fontWeight() >= int(QFont.Weight.Bold)
    assert cursor.charFormat().isAnchor()
