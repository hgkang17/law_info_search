"""본문 머리줄 글꼴 칸과 글자 크기 칸의 높이가 같은지 보는 회귀 테스트.

창 스타일시트에는 입력칸용 ``QLineEdit { min-height: 38px }``가 있는데,
숫자 칸은 안에 QLineEdit을 품고 있어 그 최소 높이를 함께 받는다. 그래서
``QDoubleSpinBox#fontSizeSpin``에 적어 둔 max-height와 위젯 고정 높이가
모두 밀려 옆 글꼴 칸보다 8px 높아졌다.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from ui.main_window import LawSearchWindow
from ui.widgets import DETAIL_HEADER_CONTROL_HEIGHT


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def test_font_family_and_size_boxes_share_one_height(qt_app) -> None:
    window = LawSearchWindow()
    try:
        window.resize(1200, 800)
        window.show()
        qt_app.processEvents()
        tab = window.resource_tab

        combo_height = tab.detail_font_combo.height()
        spin_height = tab.detail_font_spin.height()

        assert combo_height == spin_height, (
            f"글꼴 칸 {combo_height}px, 크기 칸 {spin_height}px로 어긋난다"
        )
        assert spin_height == DETAIL_HEADER_CONTROL_HEIGHT
    finally:
        window.close()


def test_formatting_tools_fit_their_parent_without_clipped_borders(qt_app) -> None:
    window = LawSearchWindow()
    try:
        window.resize(1400, 900)
        window.show()
        qt_app.processEvents()
        tab = window.resource_tab

        controls = [
            *tab.palette_buttons,
            tab.color_reset_button,
            tab.all_color_reset_button,
            tab.memo_button,
        ]
        assert all(
            control.height() == DETAIL_HEADER_CONTROL_HEIGHT
            for control in controls
        )
        assert tab.color_tools.height() == DETAIL_HEADER_CONTROL_HEIGHT
        assert tab.color_reset_tools.height() == DETAIL_HEADER_CONTROL_HEIGHT
        assert all(
            tab.color_tools.rect().contains(button.geometry())
            for button in tab.palette_buttons
        )
        assert all(
            tab.color_reset_tools.rect().contains(button.geometry())
            for button in (
                tab.color_reset_button,
                tab.all_color_reset_button,
            )
        )
    finally:
        window.close()
