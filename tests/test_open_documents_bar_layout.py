"""창 위 열린 본문 띠가 왼쪽에서 시작하고 단추가 탭 옆에 붙는지 검증."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from ui.main_window import LawSearchWindow


ROW = {
    "target": "law",
    "label": "법령",
    "id": "009419",
    "name": "국토의 계획 및 이용에 관한 법률 시행령",
    "related": "",
    "organization": "국토교통부",
    "date": "",
    "number": "",
    "effective": "",
    "short_name": "",
    "raw": {},
}


@pytest.fixture()
def window():
    app = QApplication.instance() or QApplication([])
    window = LawSearchWindow()
    window.resize(1400, 900)
    window.show()
    app.processEvents()
    yield window, app
    window.close()


def test_open_documents_bar_starts_at_the_left(window) -> None:
    """탭은 왼쪽 끝에서 시작하고, 전체 끄기 단추가 그 오른쪽에 붙는다."""
    main_window, app = window
    tab = main_window.resource_tab
    for index in range(3):
        tab._open_document_tab(
            dict(ROW, id=f"00941{index}", name=f"테스트 법령 {index}")
        )
    for key, state in tab._document_states.items():
        if isinstance(state, dict) and key != "__preview__":
            state["plain_text"] = "제1조(목적) 본문이다."
    main_window._refresh_open_documents()
    app.processEvents()

    strip = main_window.open_document_tab_strip
    button = main_window.close_all_documents_button

    assert main_window.open_document_tabs.count() == 3
    assert strip.x() == 0
    assert button.isVisible()
    # 탭 스타일에는 위ㆍ아래 margin이 없어 칠해지는 면이 곧 tabRect다.
    # 예전에는 여백이 있다고 보고 2px을 뺐는데, 그만큼 단추가 짧아져 띠
    # 가운데로 밀리면서 윗선이 탭보다 한 픽셀 위에 있는 것처럼 보였다.
    tabs = main_window.open_document_tabs
    assert button.height() == tabs.tabRect(0).height()
    holder = main_window.open_documents_widget
    assert (
        button.mapTo(holder, button.rect().topLeft()).y()
        == tabs.mapTo(holder, tabs.tabRect(0).topLeft()).y()
    )
    # 화살표가 필요 없을 때는 폭까지 0으로 접혀 탭 띠와 전체 끄기 사이에
    # 빈 단추 자리를 남기지 않는다.
    gap = button.x() - (strip.x() + strip.width())
    assert 0 <= gap <= 12
    # 탭 띠는 내용 너비까지만 차지한다. 따라서 전체 끄기는 창 오른쪽 끝에
    # 고정되지 않고 마지막 열린본문 바로 옆을 따라간다.
    tabs_right = tabs.mapTo(holder, tabs.tabRect(tabs.count() - 1).topRight()).x()
    assert 0 <= button.x() - tabs_right <= 12
    assert button.x() + button.width() < holder.width() - 100
    assert main_window.open_document_scroll_left.width() == 0
    assert main_window.open_document_scroll_right.width() == 0
    # 늘어나지 않는 작은 단추다.
    assert button.width() <= 90


def test_open_documents_bar_stops_at_right_edge_and_shows_overflow_arrows(window) -> None:
    main_window, app = window
    main_window.resize(620, 720)
    tab = main_window.resource_tab
    for index in range(14):
        tab._open_document_tab(
            dict(ROW, id=f"overflow-{index}", name=f"아주 긴 열린 법령 이름 {index}")
        )
    for key, state in tab._document_states.items():
        if isinstance(state, dict) and key != "__preview__":
            state["plain_text"] = "제1조(목적) 본문이다."
    main_window._refresh_open_documents()
    app.processEvents()

    strip = main_window.open_document_tab_strip
    bar = strip.horizontalScrollBar()
    assert bar.maximum() > 0
    assert main_window.open_document_scroll_left.isVisible()
    assert main_window.open_document_scroll_right.isVisible()
    assert main_window.open_document_scroll_left.width() == 24
    assert main_window.open_document_scroll_right.width() == 24
    assert not main_window.open_document_scroll_left.isEnabled()
    assert main_window.open_document_scroll_right.isEnabled()
    holder = main_window.open_documents_widget
    button = main_window.close_all_documents_button
    button_right = button.x() + button.width()
    assert holder.width() - button_right < 20
