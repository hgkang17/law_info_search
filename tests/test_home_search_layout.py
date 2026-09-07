"""메인 검색 진행 표시가 검색창 위치를 흔들지 않는지 검증."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from storage.recent import RecentSearchManager
from ui.tabs.home import HomeSearchPage


def test_progress_bar_keeps_search_box_at_same_height(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "home.ini"), QSettings.Format.IniFormat)
    page = HomeSearchPage(RecentSearchManager(settings))
    try:
        page.resize(1000, 760)
        page.show()
        app.processEvents()
        idle_y = page.search_box.mapTo(page, page.search_box.rect().topLeft()).y()

        page.begin_search("농지법")
        app.processEvents()
        busy_y = page.search_box.mapTo(page, page.search_box.rect().topLeft()).y()

        assert busy_y == idle_y
    finally:
        page.close()
