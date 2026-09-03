"""창 하나에 하나만 두는 하단 상태줄 검증."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from ui.main_window import LawSearchWindow


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qt_app):
    window = LawSearchWindow()
    window.resize(1400, 900)
    window.show()
    qt_app.processEvents()
    yield window
    window.close()


def test_each_screen_hides_its_own_status_row(window) -> None:
    """화면마다 있던 상태줄은 숨고 공용 하단바 하나만 남는다."""
    for tab in (
        window.resource_tab,
        window.ai_search_tab,
        window.ai_related_tab,
        window.central_tab,
        window.expc_tab,
        window.prec_tab,
        window.viewed_laws_tab,
        window.favorites_tab,
    ):
        assert tab.status_row.isHidden()
        # 화면 코드가 쓰던 이름은 그대로 두고 실체만 공용 자리로 바뀐다.
        assert not hasattr(tab.status_label, "setWordWrap")


def test_update_and_about_buttons_share_the_status_line(window, qt_app) -> None:
    """상태 문구와 오픈소스 고지 단추가 같은 줄에 선다."""
    qt_app.processEvents()

    def middle(widget) -> int:
        top = widget.mapTo(window, widget.rect().topLeft()).y()
        return top + widget.height() // 2

    # 높이가 저마다 달라도 같은 줄에서 가운데가 맞아야 한 줄로 읽힌다.
    label_middle = middle(window.status_bar.label)
    for button in (window.update_button, window.about_button):
        assert abs(middle(button) - label_middle) <= 1


def test_status_text_follows_the_screen_in_front(window, qt_app) -> None:
    """뒤에 있는 화면이 앞 화면의 문구를 덮어쓰지 않는다."""
    resource = window.resource_tab
    resource.select_category("law")
    qt_app.processEvents()
    resource.status_label.setText("법령 목록 문구")
    assert window.status_bar.label.text() == "법령 목록 문구"

    # 다른 화면으로 옮기면 그 화면이 들고 있던 문구가 올라온다.
    resource.select_category("ai_related")
    qt_app.processEvents()
    assert window.status_bar.label.text() == window.ai_related_tab.idle_status_text()

    # 뒤로 물러난 목록 화면이 문구를 바꿔도 지금 보이는 줄은 그대로다.
    resource.status_label.setText("뒤에서 끝난 검색")
    assert window.status_bar.label.text() == window.ai_related_tab.idle_status_text()

    # 저장내역으로 옮기면 그 화면이 들고 있던 문구로 바뀐다.
    window.viewed_laws_tab.status_label.setText("저장내역 문구")
    window.navigation.setCurrentRow(5)
    window._activate_viewed_laws_page()
    qt_app.processEvents()
    assert window.status_bar.label.text() == "저장내역 문구"


def test_keyword_screens_show_their_guidance_in_the_status_line(window, qt_app) -> None:
    """닫히던 상단 배너 대신 안내가 늘 상태줄에 보인다."""
    resource = window.resource_tab
    resource.select_category("ai_search")
    qt_app.processEvents()
    assert "키워드가 직접 포함된" in window.status_bar.label.text()

    resource.select_category("ai_related")
    qt_app.processEvents()
    assert "연관성이 높은" in window.status_bar.label.text()
