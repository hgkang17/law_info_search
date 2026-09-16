"""본문 제목 고정 바의 API 갱신은 선택한 본문 저장본을 건너뛴다."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from ui.main_window import LawSearchWindow


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize(
    ("source", "target"),
    (
        ("resource", "law"),
        ("resource", "admrul"),
        ("resource", "ordin"),
        ("central", "molit"),
        ("expc", "expc"),
        ("prec", "prec"),
    ),
)
def test_header_refresh_uses_active_document_and_forces_api(
    qt_app, monkeypatch, source: str, target: str
) -> None:
    window = LawSearchWindow()
    try:
        row = {
            "target": target,
            "id": "12345",
            "name": "갱신할 본문",
            "label": "본문",
            "detail_available": True,
        }
        if source == "resource":
            tab = window.resource_tab
            tab._open_document_tab(row)
            tab._document_states[tab._active_document_key]["plain_text"] = "이전 본문"
            tab.current_detail_text = "이전 본문"
            token = f"resource:{target}:12345"
            request_name = "_request_resource_detail"
        else:
            tab = {"central": window.central_tab,
                   "expc": window.expc_tab, "prec": window.prec_tab}[source]
            tab._active_detail_row = dict(row)
            tab.current_detail_text = "이전 본문"
            token = f"{source}:12345"
            request_name = "_request_detail"
        window._refresh_open_documents()
        window._set_active_document_token(token)
        activated: list[str] = []
        called: list[tuple[dict, bool]] = []
        monkeypatch.setattr(window, "_activate_open_document", activated.append)
        monkeypatch.setattr(
            tab, request_name,
            lambda selected, *, force_api=False: called.append(
                (dict(selected), force_api)
            ),
        )

        button_row = (
            window.resource_tab.pinned_headline_row
            if source == "resource" else tab.detail_head_layout
        )
        assert button_row.itemAt(button_row.count() - 1).widget() is (
            window.open_document_api_refresh_button
        )
        assert window.open_document_api_refresh_button.isEnabled()
        window.open_document_api_refresh_button.click()

        assert activated == [token]
        assert called == [(row, True)]
    finally:
        window.close()
        qt_app.processEvents()


def test_header_refresh_replaces_saved_article_html(
    qt_app, monkeypatch, tmp_path
) -> None:
    window = LawSearchWindow()
    try:
        tab = window.resource_tab
        tab.law_cache.directory = tmp_path / "saved"
        source_row = {
            "target": "law", "id": "12345", "name": "법령", "label": "법령"
        }
        unit = {"jo": "000100", "hang": "", "ho": "", "mok": ""}
        row = {
            "target": "law_article", "id": "12345:000100:::",
            "name": "법령 제1조", "label": "조항호목",
            "source_row": source_row, "favorite_unit": unit,
        }
        tab._open_document_tab(row)
        tab._document_states[tab._active_document_key]["plain_text"] = "이전 조문"
        tab.current_detail_text = "이전 조문"
        assert tab.law_cache.save_snapshot(
            row, html="<p>이전 조문</p>", plain_text="이전 조문"
        )
        window._refresh_open_documents()
        window._set_active_document_token(
            f"resource:law_article:{row['id']}"
        )
        monkeypatch.setattr(window, "_activate_open_document", lambda _token: None)
        monkeypatch.setattr(tab, "oc_provider", lambda: "test-key")
        monkeypatch.setattr(
            tab, "_queue_three_stage_link_request", lambda *_args: None
        )
        loaded: list[bool] = []
        started: list[str] = []
        monkeypatch.setattr(
            tab, "_load_favorite_article_cache",
            lambda *_args: loaded.append(True) or {"구본문": "저장 조문"},
        )
        monkeypatch.setattr(
            tab, "_start_worker",
            lambda worker, _message: started.append(worker.operation),
        )

        window.open_document_api_refresh_button.click()
        fresh = {
            "법령": {
                "기본정보": {"법령명_한글": "법령", "법령ID": "12345"},
                "조문": {"조문단위": [
                    {"조문번호": "1", "조문내용": "제1조 새 API 본문"}
                ]},
            },
        }
        tab._show_favorite_article_api_result({"payload": fresh})

        assert loaded == []
        assert started == ["favorite_article_detail"]
        saved = tab.law_cache.load_snapshot(row)
        assert saved is not None
        assert "새 API 본문" in saved["html"]
        assert "이전 조문" not in saved["html"]
    finally:
        window.close()
        qt_app.processEvents()


def test_header_refresh_is_disabled_without_refreshable_document(qt_app) -> None:
    window = LawSearchWindow()
    try:
        assert not window.open_document_api_refresh_button.isEnabled()
        window._open_document_descriptors = {
            "ai_search:1": {"source": "ai_search", "token": "ai_search:1"}
        }
        window._set_active_document_token("ai_search:1")
        assert not window.open_document_api_refresh_button.isEnabled()
    finally:
        window.close()
        qt_app.processEvents()


def test_fresh_law_response_replaces_saved_html(qt_app, monkeypatch, tmp_path) -> None:
    window = LawSearchWindow()
    try:
        tab = window.resource_tab
        tab.law_cache.directory = tmp_path / "saved"
        monkeypatch.setattr(
            tab, "_queue_three_stage_link_request", lambda *_args: None
        )
        row = {
            "target": "law", "id": "12345", "name": "법령", "label": "법령"
        }
        old = {
            "법령": {
                "기본정보": {"법령명_한글": "법령", "법령ID": "12345"},
                "조문": {"조문단위": [
                    {"조문번호": "1", "조문내용": "제1조 이전 본문"}
                ]},
            },
        }
        fresh = {
            "법령": {
                "기본정보": {"법령명_한글": "법령", "법령ID": "12345"},
                "조문": {"조문단위": [
                    {"조문번호": "1", "조문내용": "제1조 새 API 본문"}
                ]},
            },
        }
        assert tab.law_cache.save(
            row, old, snapshot={"rendered_html": "<p>이전 본문</p>"}
        )

        tab.pending_row = dict(row)
        tab._show_detail(fresh)

        saved = tab.law_cache.load_for_row(row)
        assert saved is not None
        assert saved["payload"] == fresh
        assert "새 API 본문" in saved["rendered_html"]
        assert "이전 본문" not in saved["rendered_html"]
        assert "새 API 본문" in tab.current_detail_text
    finally:
        window.close()
        qt_app.processEvents()
