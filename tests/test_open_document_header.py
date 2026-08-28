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


def test_closing_active_document_in_reading_mode_returns_to_previous_page(
    qt_app,
) -> None:
    """크게 보기의 ×는 빈 안내 대신 들어오기 전 화면으로 돌아간다."""
    window = LawSearchWindow()
    try:
        resource = window.resource_tab
        row = {
            "target": "law",
            "id": "009294",
            "label": "법령",
            "name": "국토의 계획 및 이용에 관한 법률",
        }
        resource._open_document_tab(row)
        resource._set_detail_document(
            row["name"],
            [("법령ID", row["id"])],
            [("조문", "제1조(목적) 본문")],
            build_toc=True,
        )
        returned = []
        resource._reading_mode_exit_callback = lambda: returned.append(
            (resource._reading_mode, resource.detail_card.isHidden())
        )
        resource._set_reading_mode(True)

        resource._close_document_tab_by_key("law:009294")
        qt_app.processEvents()

        assert returned == [(False, True)]
        assert resource._reading_mode is False
        assert resource.detail_card.isHidden()
        # 테스트 창 자체는 show()하지 않으므로 조상 가시성까지 보는
        # isVisible() 대신 위젯이 명시적으로 숨겨지지 않았는지 확인한다.
        assert not resource.search_results_panel.isHidden()
        assert resource._active_document_key == "__preview__"
        assert resource.document_tabs.count() == 0
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
