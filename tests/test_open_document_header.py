"""어느 메뉴에서도 보이는 열린 본문 표시줄 회귀 테스트."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QLabel

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
        assert window.header_card.findChild(QLabel, "appTitle") is None
        assert "국가법령정보 통합검색" not in [
            child.text()
            for child in window.header_card.findChildren(QLabel)
        ]
        assert window.header_card.layout().indexOf(
            window.oc_api_settings_button
        ) >= 0
        assert window.ai_review_tab.context_source is None
        assert resource.ai_chat_panel.context_source == resource._chat_context
        assert resource.ai_chat_panel.minimumWidth() == 0
        assert not resource.main_splitter.isCollapsible(2)
        assert resource._chat_context() == ("제1조 목적 본문", "본문 전체")
    finally:
        window.close()
        qt_app.processEvents()


def test_text_selection_does_not_rebuild_open_document_tabs(qt_app) -> None:
    window = LawSearchWindow()
    try:
        view = window.resource_tab.detail_view
        view.setPlainText("선택해 볼 법령 본문")
        qt_app.processEvents()
        window._open_document_refresh_pending = False

        cursor = view.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(4, QTextCursor.MoveMode.KeepAnchor)
        view.setTextCursor(cursor)

        assert not window._open_document_refresh_pending
    finally:
        window.close()
        qt_app.processEvents()


def test_unchanged_documents_do_not_rebuild_header_tabs(qt_app) -> None:
    """화면만 오갈 때 같은 열린 본문 탭을 삭제하고 다시 만들지 않는다."""
    window = LawSearchWindow()
    try:
        resource = window.resource_tab
        key = "law:009294"
        state = resource._empty_document_state()
        state.update(
            {
                "row": {
                    "target": "law",
                    "id": "009294",
                    "name": "국토의 계획 및 이용에 관한 법률",
                    "short_name": "국토계획법",
                },
                "plain_text": "제1조 목적 본문",
            }
        )
        resource._document_states[key] = state
        resource._active_document_key = key
        resource.current_detail_text = "제1조 목적 본문"
        window.navigation.setCurrentRow(1)
        window._refresh_open_documents()

        removals: list[int] = []
        original_remove = window.open_document_tabs.removeTab

        def counted_remove(index: int) -> None:
            removals.append(index)
            original_remove(index)

        window.open_document_tabs.removeTab = counted_remove
        window._refresh_open_documents()

        assert removals == []
        assert window.open_document_tabs.count() == 1
        assert window.open_document_tabs.tabText(0) == "국토계획법"
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
        assert resource.detail_button.isHidden()

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


def test_favorite_article_opens_in_full_reading_mode_with_back_button(
    qt_app,
) -> None:
    """즐겨찾기 조항호목도 전문과 같은 크게 보기와 복귀 단추를 쓴다."""
    window = LawSearchWindow()
    try:
        record = {
            "row": {
                "target": "law",
                "id": "009294",
                "label": "법령",
                "name": "국토의 계획 및 이용에 관한 법률",
            },
            "payload": {
                "법령": {
                    "기본정보": {
                        "법령명_한글": "국토의 계획 및 이용에 관한 법률",
                        "법령ID": "009294",
                    },
                    "조문": {
                        "조문단위": [
                            {
                                "조문번호": "77",
                                "조문내용": "제77조(용도지역의 건폐율) 본문",
                            }
                        ]
                    },
                }
            },
            "favorite_article_jo": "007700",
            "favorite_article_unit": {
                "jo": "007700",
                "hang": "",
                "ho": "",
                "mok": "",
                "label": "제77조",
            },
        }
        window._activate_favorites_page()

        window._open_favorite(record)
        qt_app.processEvents()

        resource = window.resource_tab
        assert window.tabs.currentWidget() is resource
        assert resource._reading_mode is True
        assert resource.search_results_panel.isHidden()
        assert resource.status_label.isHidden()
        assert not resource.detail_card.isHidden()
        assert not resource.restore_view_button.isHidden()
        assert resource.expand_detail_button.text() == "AI\n에이전트"
        assert "제77조(용도지역의 건폐율) 본문" in resource.current_detail_text

        resource.restore_view_button.click()
        qt_app.processEvents()

        assert resource._reading_mode is False
        assert window.tabs.currentWidget() is window.favorites_tab
        assert window.favorite_navigation_button.isChecked()

        # 같은 조항호목을 다시 열어 탭의 ×로 닫아도 빈 ``안내``를
        # 전체 화면에 남기지 않고, ◀와 똑같이 즐겨찾기로 돌아간다.
        window._open_favorite(record)
        qt_app.processEvents()
        article_key = resource._active_document_key
        assert resource._reading_mode is True

        resource._close_document_tab_by_key(article_key)
        qt_app.processEvents()

        assert resource._reading_mode is False
        assert window.tabs.currentWidget() is window.favorites_tab
        assert window.favorite_navigation_button.isChecked()
        assert resource.detail_card.isHidden()
        assert resource._document_tab_index(article_key) == -1
    finally:
        window.close()
        qt_app.processEvents()


def test_favorite_body_is_not_covered_by_keyword_page(qt_app) -> None:
    """직접검색을 보고 있어도 즐겨찾기 본문은 법령 크게 보기로 열린다."""
    window = LawSearchWindow()
    try:
        window._show_keyword_category("ai_search")
        assert (
            window.resource_tab.content_stack.currentWidget()
            is window.resource_tab._keyword_page
        )

        record = {
            "row": {
                "target": "law",
                "id": "009294",
                "label": "법령",
                "name": "국토의 계획 및 이용에 관한 법률",
            },
            "payload": {
                "법령": {
                    "기본정보": {
                        "법령명_한글": "국토의 계획 및 이용에 관한 법률",
                        "법령ID": "009294",
                    },
                    "조문": {
                        "조문단위": [
                            {
                                "조문번호": "1",
                                "조문내용": "제1조(목적) 본문",
                            }
                        ]
                    },
                }
            },
        }
        window._activate_favorites_page()
        window._open_favorite(record)
        qt_app.processEvents()

        resource = window.resource_tab
        assert resource.content_stack.currentWidget() is resource.resource_body
        assert resource.category_target == "law"
        assert resource._reading_mode is True
        assert not resource.detail_card.isHidden()
        assert "제1조(목적) 본문" in resource.current_detail_text
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
