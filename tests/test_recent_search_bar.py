from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QApplication,
    QLineEdit,
    QStyle,
    QStyleOptionButton,
)

from storage.recent import RecentSearchManager
from ui.main_window import LawSearchWindow
from ui.widgets import RecentSearchBar, RecentSearchChip


def test_showing_same_recent_search_bar_does_not_rebuild(tmp_path) -> None:
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
    bar._apply_query_eliding()

    original_buttons = [button for button, _query in bar._query_buttons]
    bar.hide()
    bar.show()
    app.processEvents()
    bar.refresh(list(manager.items))

    assert not bar._wrap_timer.isActive()
    assert [button for button, _query in bar._query_buttons] == original_buttons

    bar.close()


def test_ten_recent_searches_fit_on_one_row(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(
        str(tmp_path / "recent.ini"), QSettings.Format.IniFormat
    )
    queries = [f"검색어{index}" for index in range(10)]
    settings.setValue("recent_searches", queries)
    manager = RecentSearchManager(settings)
    bar = RecentSearchBar(QLineEdit(), manager)
    bar.setFixedWidth(1200)
    bar.show()
    app.processEvents()

    buttons = [button for button, _query in bar._query_buttons]
    assert len(buttons) == 10
    tops = {button.y() for button in buttons}
    assert len(tops) == 1
    assert all("\n" not in button.text() for button in buttons)
    assert bar.height() <= 32

    bar.close()


def test_single_recent_search_uses_compact_chip_width(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(
        str(tmp_path / "recent.ini"), QSettings.Format.IniFormat
    )
    settings.setValue("recent_searches", ["공간재구조화"])
    manager = RecentSearchManager(settings)
    bar = RecentSearchBar(QLineEdit(), manager)
    bar.setFixedWidth(900)
    bar.show()
    app.processEvents()

    button = bar._query_buttons[0][0]
    assert button.width() <= RecentSearchBar.QUERY_BUTTON_MAX_WIDTH
    assert button.width() < bar.width() // 2

    bar.close()


def test_recent_chip_and_remove_button_fit_and_center_in_actual_style(
    tmp_path,
) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(
        str(tmp_path / "recent-style.ini"), QSettings.Format.IniFormat
    )
    settings.setValue("recent_searches", ["국토계획법"])
    window = LawSearchWindow()
    bar = RecentSearchBar(QLineEdit(), RecentSearchManager(settings))
    try:
        bar.setStyleSheet(window.styleSheet())
        bar.setFixedWidth(420)
        bar.show()
        app.processEvents()

        chip = bar.findChild(RecentSearchChip)
        assert chip is not None
        assert chip.height() == RecentSearchChip.HEIGHT
        assert chip.rect().contains(chip.query_button.geometry())
        assert chip.rect().contains(chip.remove_button.geometry())
        assert chip.remove_button.size().toTuple() == (16, 16)
        assert (
            chip.remove_button.geometry().center().y()
            == chip.rect().center().y()
        )
        option = QStyleOptionButton()
        chip.query_button.initStyleOption(option)
        text_rect = chip.query_button.style().subElementRect(
            QStyle.SubElement.SE_PushButtonContents,
            option,
            chip.query_button,
        )
        assert text_rect.center().x() == chip.query_button.rect().center().x()
    finally:
        bar.close()
        window.close()
