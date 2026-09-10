"""어느 메뉴에서도 보이는 열린 본문 표시줄 회귀 테스트."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QFont, QTextCursor
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
        # 머리글에는 로고만 둔다. 프로그램 이름 라벨은 없앴다.
        assert window.header_card.findChild(QLabel, "appNameLabel") is None
        assert window.header_card.findChild(QLabel, "logoLabel") is not None
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


def test_favorite_back_keeps_open_document_scroll_until_tab_is_closed(
    qt_app,
) -> None:
    """즐겨찾기로 돌아가도 살아 있는 상단 본문 탭의 읽던 자리는 남는다."""
    window = LawSearchWindow()
    try:
        window.resize(1200, 800)
        window.show()
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
            [("조문", "\n".join(f"제{n}조 본문 내용" for n in range(1, 301)))],
            build_toc=False,
        )
        resource._set_reading_mode(True)
        qt_app.processEvents()
        bar = resource.detail_view.verticalScrollBar()
        assert bar.maximum() > 600
        bar.setValue(600)
        key = resource._active_document_key

        resource._reading_mode_exit_callback = window._activate_favorites_page
        resource._exit_reading_mode()
        qt_app.processEvents()

        assert resource._document_states[key]["scroll"] == 600
        window._refresh_open_documents()
        token = next(
            token
            for token, document in window._open_document_descriptors.items()
            if document.get("key") == key
        )
        window._activate_open_document(token)
        qt_app.processEvents()

        assert resource.detail_view.verticalScrollBar().value() == 600

        resource._close_document_tab_by_key(key)
        assert key not in resource._document_states
    finally:
        window.close()
        qt_app.processEvents()


def test_home_then_favorite_reuses_scroll_and_font_of_open_document(
    qt_app, monkeypatch, tmp_path
) -> None:
    """메인 화면을 거쳐 즐겨찾기로 재진입해도 열린 문서를 다시 그리지 않는다."""
    from pathlib import Path
    from ui.tabs.ai_chat_panel import AiChatPanel
    from ui.tabs.resource_search import ResourceSearchTab

    monkeypatch.setattr("ui.main_window.LAW_CACHE_DIR", tmp_path / "saved")
    monkeypatch.setattr(AiChatPanel, "_start_visible_background_checks", lambda self: None)
    monkeypatch.setattr(ResourceSearchTab, "_queue_three_stage_link_request", lambda *a: None)
    window = LawSearchWindow()
    try:
        assert Path(window.settings.fileName()).is_relative_to(tmp_path)
        window.resize(1200, 800)
        window.show()
        resource = window.resource_tab
        row = {
            "target": "admrul",
            "id": "100001",
            "label": "행정규칙",
            "name": "도시관리계획수립지침",
        }
        resource._open_document_tab(row)
        resource._set_detail_document(
            row["name"],
            [("행정규칙일련번호", row["id"])],
            [("조문", "\n".join(f"제{n}절 지침 내용" for n in range(1, 401)))],
            build_toc=False,
            administrative_rule=True,
        )
        resource._set_detail_font_family(QFont("Arial"))
        resource._set_reading_mode(True)
        qt_app.processEvents()
        bar = resource.detail_view.verticalScrollBar()
        assert bar.maximum() > 700
        bar.setValue(700)
        expected_family = resource.detail_view.document().defaultFont().family()

        window._refresh_open_documents()
        window._activate_home_page()
        qt_app.processEvents()
        monkeypatch.setattr(
            resource,
            "_open_cached_resource_snapshot",
            lambda *_args: (_ for _ in ()).throw(
                AssertionError("열린 문서는 저장본으로 다시 그리면 안 된다")
            ),
        )
        window._route_saved_record(
            {"kind": "detail_snapshot", "row": dict(row), "html": "다른 본문"},
            reading_mode=True,
        )
        qt_app.processEvents()

        assert bar.value() == 700
        assert resource.detail_view.document().defaultFont().family() == expected_family
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
        normal_margins = window.centralWidget().layout().getContentsMargins()
        assert resource.detail_card.isHidden()
        assert resource.detail_button.parentWidget() is resource.result_card
        assert resource.detail_button.isHidden()

        resource._set_reading_mode(True)
        assert not resource.detail_card.isHidden()
        assert window.centralWidget().layout().getContentsMargins() == normal_margins

        resource._set_reading_mode(False)
        assert resource.detail_card.isHidden()
        assert resource.main_splitter.sizes()[1] == 0
    finally:
        window.close()
        qt_app.processEvents()


def test_header_document_switch_keeps_favorites_as_back_destination(qt_app) -> None:
    """즐겨찾기에서 연 뒤 상단 본문 탭을 바꿔도 ◀는 즐겨찾기로 간다."""
    window = LawSearchWindow()
    try:
        resource = window.resource_tab
        other_row = {
            "target": "law",
            "id": "000002",
            "label": "법령",
            "name": "다른 법령",
        }
        resource._open_document_tab(other_row)
        resource._set_detail_document(
            other_row["name"],
            [("법령ID", other_row["id"])],
            [("조문", "제1조 다른 법령 본문")],
            build_toc=True,
        )

        favorite_record = {
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
                    "조문": {"조문단위": []},
                }
            },
        }
        window._activate_favorites_page()
        window._open_favorite(favorite_record)
        window._refresh_open_documents()

        other_token = next(
            token
            for token in window._open_document_descriptors
            if token.endswith("law:000002")
        )
        window._activate_open_document(other_token)
        resource._exit_reading_mode()
        qt_app.processEvents()

        assert window.tabs.currentWidget() is window.favorites_tab
        assert window.favorite_navigation_button.isChecked()
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
        # 이 회귀 시험은 API가 없을 때 저장 전문 fallback으로 즉시 여는
        # 경로를 본다. 개발 PC의 실제 OC 설정값에 좌우되지 않게 한다.
        window.resource_tab.oc_provider = lambda: ""

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


def test_header_opens_case_body_instead_of_the_result_list(qt_app) -> None:
    """열린 본문 띠에서 해석례를 누르면 목록이 아니라 본문이 떠야 한다.

    법령ㆍ조문 본문은 크게 보기로 들어가는데 질의회신ㆍ해석례ㆍ판례만
    왼쪽 메뉴 자리만 옮겨, 열어 둔 회신을 목록에서 다시 찾아 눌러야 했다.
    """
    window = LawSearchWindow()
    try:
        tab = window.expc_tab
        tab._active_detail_row = {"id": "331111", "title": "법령해석 사례"}
        tab.current_detail_text = "안건번호 ...\n질의요지 ..."
        documents = window._collect_open_documents()
        token = next(
            str(document["token"])
            for document in documents
            if document["source"] == "expc"
        )
        window._open_document_descriptors = {
            str(document["token"]): document for document in documents
        }
        window.navigation.setCurrentRow(0)

        window._activate_open_document(token)

        assert window.navigation.currentRow() == 3
        assert tab._reading_mode is True
        assert not tab.search_results_panel.isVisible()
    finally:
        window.close()


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
