"""최근 검색어 한 건만 지우는 기능 검증."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton

from storage.recent import RecentSearchManager
from ui.widgets import RecentSearchBar


@pytest.fixture
def manager(tmp_path) -> RecentSearchManager:
    QApplication.instance() or QApplication([])
    settings = QSettings(
        str(tmp_path / "recent.ini"), QSettings.Format.IniFormat
    )
    return RecentSearchManager(settings)


def test_remove_drops_only_the_named_query(manager) -> None:
    """고른 검색어 하나만 빠지고 나머지 차례는 그대로다."""
    for query in ("건축법", "국토계획법", "주차장법"):
        manager.add(query)
    assert manager.items == ["주차장법", "국토계획법", "건축법"]

    manager.remove("국토계획법")
    assert manager.items == ["주차장법", "건축법"]


def test_remove_ignores_unknown_and_blank(manager) -> None:
    """없는 값이나 빈 값으로는 아무것도 지우지 않는다."""
    manager.add("건축법")
    manager.remove("없는 검색어")
    manager.remove("   ")
    assert manager.items == ["건축법"]


def test_remove_keeps_settings_in_step(manager, tmp_path) -> None:
    """지운 결과가 설정에도 남아 다음 실행에 되살아나지 않는다."""
    manager.add("건축법")
    manager.add("주차장법")
    manager.remove("주차장법")

    reopened = RecentSearchManager(
        QSettings(str(tmp_path / "recent.ini"), QSettings.Format.IniFormat)
    )
    assert reopened.items == ["건축법"]


def test_bar_shows_a_remove_mark_for_each_query(manager) -> None:
    """검색어마다 지우기 표시가 하나씩 붙고, 누르면 그 검색어만 빠진다."""
    for query in ("건축법", "국토계획법"):
        manager.add(query)
    bar = RecentSearchBar(QLineEdit(), manager)
    bar.refresh()

    marks = [
        button
        for button in bar.findChildren(QPushButton)
        if button.objectName() == "recentSearchRemove"
    ]
    assert len(marks) == len(manager.items)

    # 맨 앞 검색어(가장 최근)를 지운다.
    marks[0].click()
    assert manager.items == ["건축법"]
