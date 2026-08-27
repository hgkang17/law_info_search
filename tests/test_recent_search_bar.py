from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QLineEdit

from storage.recent import RecentSearchManager
from ui.widgets import RecentSearchBar


def test_showing_same_recent_search_bar_does_not_rewrap_or_rebuild(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(
        str(tmp_path / "recent.ini"), QSettings.Format.IniFormat
    )
    settings.setValue("recent_searches", ["개발제한구역법", "국토계획법"])
    manager = RecentSearchManager(settings)
    bar = RecentSearchBar(QLineEdit(), manager)
    bar.setFixedWidth(420)
    bar.show()
    app.processEvents()
    bar._apply_query_wrapping()

    original_buttons = [button for button, _query in bar._query_buttons]
    bar.hide()
    bar.show()
    app.processEvents()
    bar.refresh(list(manager.items))

    assert not bar._wrap_timer.isActive()
    assert [button for button, _query in bar._query_buttons] == original_buttons

    bar.close()
