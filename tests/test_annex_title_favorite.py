"""별표ㆍ서식 본문 제목 왼쪽 즐겨찾기 별 검증."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab


ANNEX_ROW = {
    "target": "licbyl",
    "label": "법령 별표·서식",
    "id": "8899",
    "name": "용도지역 안에서의 건축물의 제한(제71조 관련)",
    "related": "국토의 계획 및 이용에 관한 법률 시행령",
    "organization": "국토교통부",
    "date": "",
    "number": "",
    "effective": "",
    "short_name": "",
    "raw": {
        "별표번호": "000100",
        "별표종류": "별표",
        "별표서식PDF파일링크": "/LSW/flDownload.do?flSeq=1",
        "별표서식파일링크": "/LSW/flDownload.do?flSeq=2",
    },
}

LAW_ROW = {
    "target": "law",
    "label": "법령",
    "id": "009294",
    "name": "국토의 계획 및 이용에 관한 법률",
    "related": "",
    "organization": "국토교통부",
    "date": "",
    "number": "",
    "effective": "",
    "short_name": "",
    "raw": {},
}


def _tab(tmp_path) -> ResourceSearchTab:
    QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "title.ini"), QSettings.Format.IniFormat)
    tab = ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    tab.resize(1200, 800)
    tab.show()
    return tab


def test_annex_body_shows_a_star_left_of_the_title(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    tab.result_rows = [dict(ANNEX_ROW)]

    tab._show_annex_links(dict(ANNEX_ROW))
    app.processEvents()

    star = tab._title_favorite_button
    assert star.isVisible()
    # 제목 글자 크기를 따라 커지지 않고 다른 별과 같은 크기를 쓴다.
    assert star.width() == ResourceSearchTab._ARTICLE_FAVORITE_SIZE
    assert star.height() == ResourceSearchTab._ARTICLE_FAVORITE_SIZE

    position = tab._first_visible_block_position()
    cursor = QTextCursor(tab.detail_view.document())
    cursor.setPosition(position)
    title_rect = tab.detail_view.cursorRect(cursor)
    assert ANNEX_ROW["name"] in tab.detail_view.document().findBlock(
        position
    ).text()
    # 제목 왼쪽에 붙는다.
    assert star.geometry().right() <= title_rect.left()


def test_star_toggles_the_favorite_both_ways(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    tab.result_rows = [dict(ANNEX_ROW)]
    tab._show_annex_links(dict(ANNEX_ROW))
    app.processEvents()

    star = tab._title_favorite_button
    assert not tab.law_cache.is_favorite(ANNEX_ROW)

    star.click()
    app.processEvents()
    assert tab.law_cache.is_favorite(ANNEX_ROW)

    star.click()
    app.processEvents()
    assert not tab.law_cache.is_favorite(ANNEX_ROW)


def test_star_hides_on_other_documents(tmp_path) -> None:
    """법령 본문에는 조문별 별이 따로 있다. 제목 옆 별은 별표만 쓴다."""
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    tab.result_rows = [dict(ANNEX_ROW)]
    tab._show_annex_links(dict(ANNEX_ROW))
    app.processEvents()
    assert tab._title_favorite_button.isVisible()

    tab._open_document_tab(dict(LAW_ROW))
    app.processEvents()

    assert not tab._title_favorite_button.isVisible()
