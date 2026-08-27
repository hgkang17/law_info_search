from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui.widgets import GroupedNavigationList


def test_navigation_sections_are_two_group_cards() -> None:
    app = QApplication.instance() or QApplication([])
    navigation = GroupedNavigationList()
    navigation.resize(136, 520)
    navigation.setSpacing(8)
    navigation.addItems(
        ["숨김", "법령 검색", "키워드 검색", "중앙부처", "해석례", "판례"]
    )
    navigation.item(0).setHidden(True)
    navigation.set_group_ranges([(1, 2), (3, 5)])
    navigation.show()
    app.processEvents()

    rectangles = navigation._section_rects()

    assert len(rectangles) == 2
    assert rectangles[0].bottom() < rectangles[1].top()
    first_search_item = navigation.visualItemRect(navigation.item(1))
    last_search_item = navigation.visualItemRect(navigation.item(2))
    assert rectangles[0].top() == first_search_item.top()
    assert rectangles[0].bottom() == last_search_item.bottom()
    first_group_item = navigation.visualItemRect(navigation.item(3))
    last_group_item = navigation.visualItemRect(navigation.item(5))
    assert rectangles[1].top() == first_group_item.top()
    assert rectangles[1].bottom() == last_group_item.bottom()

    navigation.close()
