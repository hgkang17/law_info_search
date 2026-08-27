"""어느 메뉴에서도 보이는 열린 본문 표시줄 회귀 테스트."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from ui.main_window import LawSearchWindow


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def test_header_shows_active_document_without_binding_global_ai(qt_app) -> None:
    window = LawSearchWindow()
    try:
        resource = window.resource_tab
        key = "law:009294"
        row = {
            "target": "law",
            "id": "009294",
            "name": "국토의 계획 및 이용에 관한 법률",
            "short_name": "국토계획법",
        }
        state = resource._empty_document_state()
        state.update({"row": row, "plain_text": "제1조 목적 본문"})
        resource._document_states[key] = state
        resource._active_document_key = key
        resource.current_detail_text = "제1조 목적 본문"
        resource.detail_view.setPlainText(resource.current_detail_text)
        index = resource.document_tabs.addTab("국토계획법")
        resource.document_tabs.setTabData(index, key)
        resource.document_tabs.setCurrentIndex(index)
        window.navigation.setCurrentRow(1)

        window._refresh_open_documents()

        tabs = window.open_document_tabs
        assert tabs.tabText(tabs.currentIndex()) == "국토계획법"
        assert tabs.isMovable()
        assert window.open_documents_widget.height() == 38
        assert window.api_input.width() == 110
        assert window.ai_review_tab.context_source is None
        assert resource.ai_chat_panel.context_source == resource._chat_context
        assert resource._chat_context() == ("제1조 목적 본문", "본문 전체")
    finally:
        window.close()
        qt_app.processEvents()


def test_header_document_title_wraps_without_ellipsis() -> None:
    wrap = LawSearchWindow._two_line_open_document_title

    title = "국토의 계획 및 이용에 관한 법률 시행규칙"
    wrapped = wrap(title)
    assert "\n" in wrapped
    assert wrapped.replace("\n", " ") == title
    assert "…" not in wrapped


def test_header_tab_click_keeps_order_and_drag_changes_it(qt_app) -> None:
    window = LawSearchWindow()
    try:
        resource = window.resource_tab
        for key, short_name in (
            ("law:one", "첫째법"),
            ("law:two", "둘째법"),
        ):
            state = resource._empty_document_state()
            state.update(
                {
                    "row": {
                        "target": "law",
                        "id": key,
                        "name": short_name,
                        "short_name": short_name,
                    },
                    "plain_text": f"{short_name} 본문",
                }
            )
            resource._document_states[key] = state
            index = resource.document_tabs.addTab(short_name)
            resource.document_tabs.setTabData(index, key)

        resource._active_document_key = "law:one"
        resource.current_detail_text = "첫째법 본문"
        window.navigation.setCurrentRow(1)
        window._refresh_open_documents()

        tabs = window.open_document_tabs
        assert [tabs.tabText(i) for i in range(tabs.count())] == [
            "첫째법",
            "둘째법",
        ]

        tabs.setCurrentIndex(1)
        qt_app.processEvents()
        window._refresh_open_documents()
        assert [tabs.tabText(i) for i in range(tabs.count())] == [
            "첫째법",
            "둘째법",
        ]

        tabs.moveTab(1, 0)
        window._refresh_open_documents()
        assert [tabs.tabText(i) for i in range(tabs.count())] == [
            "둘째법",
            "첫째법",
        ]
    finally:
        window.close()
        qt_app.processEvents()


def test_law_search_hides_fixed_detail_pane(qt_app) -> None:
    window = LawSearchWindow()
    try:
        resource = window.resource_tab
        assert resource.detail_card.isHidden()
        assert resource.detail_button.parentWidget() is resource.result_card

        resource._set_reading_mode(True)
        assert not resource.detail_card.isHidden()

        resource._set_reading_mode(False)
        assert resource.detail_card.isHidden()
        assert resource.main_splitter.sizes()[1] == 0
    finally:
        window.close()
        qt_app.processEvents()
def test_open_document_strip_can_close_a_document(qt_app) -> None:
    """위쪽 "열린 본문" 띠에서도 × 로 본문을 닫을 수 있어야 한다."""
    window = LawSearchWindow()
    tab = window.resource_tab
    for name, law_id in (("첫 법령", "000001"), ("둘째 법령", "000002")):
        tab._open_document_tab(
            {"target": "law", "id": law_id, "label": "법령", "name": name}
        )
        tab._set_detail_document(
            name, [("법령ID", law_id)], [("제1장", "제1조(목적) …")], build_toc=True
        )
        qt_app.processEvents()
    window._refresh_open_documents()
    qt_app.processEvents()
    assert window.open_document_tabs.count() == 2

    # 닫기 × 는 탭 안에 단추로 달지 않고 모서리에 겹쳐 그린다. 제목이
    # 밀리지 않게 하려는 것이므로, 그 자리를 눌렀을 때 닫히는지를 본다.
    tabs = window.open_document_tabs
    assert tabs.closable_check(0) is True
    spot = tabs._close_center(0)
    assert tabs.close_spot_at(spot) == 0
    tabs.tabCloseRequested.emit(0)
    for _ in range(10):
        qt_app.processEvents()

    assert tab.document_tabs.count() == 1
    assert window.open_document_tabs.count() == 1
