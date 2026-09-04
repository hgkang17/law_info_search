"""펼친 콤보 목록이 잘리지 않는지 보는 회귀 테스트.

Qt는 콤보 목록 높이를 행 높이 합으로만 잡고 스타일시트의 안쪽 여백ㆍ
테두리를 세지 않는다. 고정 보정값만 더하면 목록을 감싼 틀과 목록 자신의
테두리가 겹쳐 늘 모자랐다(항목 둘일 때 12px). 실제로 글자가 그려지는
영역을 재서 확인한다.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QFrame

from ui.widgets import DropdownComboBox


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("count", [2, 3, 4, 12])
def test_popup_shows_every_row_without_clipping(qt_app, count: int) -> None:
    combo = DropdownComboBox()
    for index in range(count):
        combo.addItem(f"항목 {index + 1}")
    combo.show()
    qt_app.processEvents()
    try:
        combo.showPopup()
        qt_app.processEvents()
        view = combo.view()
        assert combo.findChild(QFrame) is not None
        visible = min(combo.count(), max(1, combo.maxVisibleItems()))
        needed = sum(
            max(28, view.sizeHintForRow(row)) for row in range(visible)
        )
        assert view.viewport().height() >= needed, (
            f"항목 {count}개: {needed}px이 필요한데 "
            f"{view.viewport().height()}px만 보인다"
        )
        combo.hidePopup()
    finally:
        combo.close()


def test_short_list_has_no_scrollbar(qt_app) -> None:
    """항목이 두세 개면 스크롤 없이 전부 보여야 한다."""
    combo = DropdownComboBox()
    combo.addItem("기본 프로젝트")
    combo.addItem("자연보전권역")
    combo.show()
    qt_app.processEvents()
    try:
        combo.showPopup()
        qt_app.processEvents()
        bar = combo.view().verticalScrollBar()
        assert bar.maximum() == 0, "항목 2개인데 스크롤이 생겼다"
        combo.hidePopup()
    finally:
        combo.close()
