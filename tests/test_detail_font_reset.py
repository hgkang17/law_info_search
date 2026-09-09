"""본문 글꼴 기본값 되돌리기 단추 검증."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab
from utils.constants import (
    DEFAULT_DETAIL_FONT_POINT,
    DETAIL_FONT_DEFAULTS_VERSION,
    DETAIL_FONT_FAMILY,
)


def test_reset_button_restores_the_default_font_and_size(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(
        str(tmp_path / "font.ini"), QSettings.Format.IniFormat
    )
    # 사용자가 직접 고른 값이라 마이그레이션이 손대지 않는 상태로 둔다.
    settings.setValue("resource_detail_font_family", "Arial")
    settings.setValue("resource_detail_font_size", 12.0)
    settings.setValue(
        "resource_detail_font_family_defaults_version",
        DETAIL_FONT_DEFAULTS_VERSION,
    )
    tab = ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    tab.resize(1200, 700)
    tab.show()
    app.processEvents()
    assert tab.detail_font_family == "Arial"
    assert tab.detail_font_size == pytest.approx(12.0)

    tab.detail_font_reset.click()
    app.processEvents()

    assert tab.detail_font_family == DETAIL_FONT_FAMILY
    assert tab.detail_font_size == pytest.approx(DEFAULT_DETAIL_FONT_POINT)
    assert settings.value("resource_detail_font_family") == DETAIL_FONT_FAMILY
    assert float(settings.value("resource_detail_font_size")) == pytest.approx(
        DEFAULT_DETAIL_FONT_POINT
    )
    assert tab.detail_font_spin.value() == pytest.approx(
        DEFAULT_DETAIL_FONT_POINT
    )
    tab.close()


def test_reset_button_sits_left_of_the_font_combo(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(
        str(tmp_path / "order.ini"), QSettings.Format.IniFormat
    )
    tab = ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    app.processEvents()

    layout = tab.detail_font_combo.parentWidget().layout()

    def index_of(widget) -> int:
        found: list[int] = []

        def walk(inner) -> None:
            for position in range(inner.count()):
                item = inner.itemAt(position)
                if item.widget() is widget:
                    found.append(position)
                if item.layout() is not None:
                    walk(item.layout())

        walk(layout)
        assert found
        return found[0]

    assert index_of(tab.detail_font_reset) < index_of(tab.detail_font_combo)
    assert index_of(tab.detail_font_combo) < index_of(tab.detail_font_spin)
    tab.close()
