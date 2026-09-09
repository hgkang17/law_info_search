"""머리줄 글꼴ㆍ크기 칸이 지나가는 휠에 바뀌지 않는지 검증.

본문 바로 위에 있는 칸이라, 본문을 굴리려다 커서가 여기에 걸리면 글꼴이
통째로 바뀌고 그 값이 설정에 저장돼 다음 실행까지 따라갔다.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab
from ui.theme import register_bundled_pretendard_fonts
from utils.constants import DEFAULT_DETAIL_FONT_POINT, DETAIL_FONT_FAMILY


def _scroll(app: QApplication, widget, steps: int = 3) -> None:
    position = QPoint(widget.width() // 2, widget.height() // 2)
    for _ in range(steps):
        app.sendEvent(
            widget,
            QWheelEvent(
                position,
                widget.mapToGlobal(position),
                QPoint(0, 0),
                QPoint(0, -120),
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase,
                False,
            ),
        )
        app.processEvents()


def _tab(tmp_path) -> tuple[ResourceSearchTab, QSettings]:
    app = QApplication.instance() or QApplication([])
    register_bundled_pretendard_fonts()
    settings = QSettings(str(tmp_path / "wheel.ini"), QSettings.Format.IniFormat)
    tab = ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    tab.resize(1400, 800)
    tab.show()
    app.processEvents()
    return tab, settings


def test_wheel_over_the_font_controls_changes_nothing(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    tab, settings = _tab(tmp_path)
    assert not tab.detail_font_combo.hasFocus()

    _scroll(app, tab.detail_font_combo)
    _scroll(app, tab.detail_font_spin)

    assert tab.detail_font_family == DETAIL_FONT_FAMILY
    assert tab.detail_font_size == pytest.approx(DEFAULT_DETAIL_FONT_POINT)
    assert settings.value("resource_detail_font_family") in (
        None,
        DETAIL_FONT_FAMILY,
    )
    tab.close()


def test_wheel_still_works_after_the_control_is_focused(tmp_path) -> None:
    """일부러 고른 칸에서는 휠을 그대로 쓴다."""
    app = QApplication.instance() or QApplication([])
    tab, _settings = _tab(tmp_path)
    tab.detail_font_spin.setFocus()
    app.processEvents()
    if not tab.detail_font_spin.hasFocus():
        pytest.skip("이 환경에서는 위젯에 초점을 줄 수 없다")

    _scroll(app, tab.detail_font_spin, steps=1)

    assert tab.detail_font_size < DEFAULT_DETAIL_FONT_POINT
    tab.close()
