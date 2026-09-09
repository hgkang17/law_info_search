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
    # 단추는 탭 오른쪽 끝에 바짝 붙는다(레이아웃 간격만큼만 떨어진다).
    gap = button.x() - (strip.x() + strip.width())
    assert 0 <= gap <= 12
    # 늘어나지 않는 작은 단추다.
    assert button.width() <= 90
