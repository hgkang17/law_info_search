"""목차 검색이 편ㆍ장ㆍ절 제목까지 찾는지 검증."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab


def _tab(tmp_path) -> ResourceSearchTab:
    QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "toc.ini"), QSettings.Format.IniFormat)
    return ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )


def test_toc_search_finds_guideline_section_titles(tmp_path) -> None:
    """지침류 목차는 조문(깊이 4)이 없다. 절 제목에서도 찾아야 한다."""
    tab = _tab(tmp_path)
    tab._populate_toc(
        [
            (0, "제3편 용도지구", "toc-0-0"),
            (1, "제1장 용도지구의 지정", "toc-0-1"),
            (2, "제8절 개발진흥지구", "toc-0-2"),
            (2, "제9절 특정용도제한지구", "toc-0-3"),
        ]
    )

    tab.toc_search_input.setText("개발진흥지구")

    assert len(tab._toc_search_matches) == 1
    assert tab._toc_search_matches[0].text(0) == "제8절 개발진흥지구"


def test_toc_search_still_finds_articles(tmp_path) -> None:
    tab = _tab(tmp_path)
    tab._populate_toc(
        [
            (0, "조문", "toc-0-0"),
            (4, "제76조(용도지역에서의 건축물의 제한)", "toc-0-1"),
            (4, "제77조(건폐율)", "toc-0-2"),
        ]
    )

    tab.toc_search_input.setText("건폐율")

    assert [item.text(0) for item in tab._toc_search_matches] == [
        "제77조(건폐율)"
    ]
