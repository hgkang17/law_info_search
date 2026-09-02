from __future__ import annotations

import json
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.dialogs import LawReferencePopup
from ui.main_window import LawSearchWindow
import ui.tabs.resource_search as resource_search_module
from ui.tabs.resource_search import ResourceSearchTab


def test_reference_popup_drag_cursor_stays_visible_when_unpinned() -> None:
    _app = QApplication.instance() or QApplication([])
    popup = LawReferencePopup(lambda _url: None)

    assert popup.pin_button.isChecked() is False
    assert popup.drag_bar.cursor().shape() == Qt.CursorShape.SizeAllCursor
    assert popup.arrow_drag_bar.cursor().shape() == Qt.CursorShape.SizeAllCursor
    for button in (
        popup.favorite_button,
        popup.refresh_button,
        popup.pin_button,
        popup.close_button,
    ):
        assert button.cursor().shape() == Qt.CursorShape.PointingHandCursor

    popup.pin_button.setChecked(True)
    popup.pin_button.setChecked(False)

    assert popup.drag_bar.cursor().shape() == Qt.CursorShape.SizeAllCursor
    assert popup.arrow_drag_bar.cursor().shape() == Qt.CursorShape.SizeAllCursor


def test_reference_popup_refresh_button_tracks_request_and_emits_popup() -> None:
    app = QApplication.instance() or QApplication([])
    popup = LawReferencePopup(lambda _url: None)
    emitted: list[object] = []
    popup.refreshRequested.connect(emitted.append)

    assert not popup.refresh_button.isEnabled()
    popup.reference_request = {
        "law_id": "009419",
        "law_name": "국토의 계획 및 이용에 관한 법률 시행령",
        "jo": "003500",
    }
    popup.set_content("시행령 제35조", "<p>저장 본문</p>")
    assert popup.refresh_button.isEnabled()

    popup.refresh_button.click()
    app.processEvents()
    assert emitted == [popup]

    popup.set_loading("시행령 제35조", "API 갱신 중")
    assert not popup.refresh_button.isEnabled()
    popup.set_error("일시 오류")
    assert popup.refresh_button.isEnabled()


def test_reading_mode_does_not_duplicate_reference_refresh_connection(
    tmp_path, monkeypatch
) -> None:
    """크게 보기를 반복해도 팝업 갱신은 클릭당 한 번만 처리한다."""
    app = QApplication.instance() or QApplication([])
    refreshed: list[object] = []
    monkeypatch.setattr(
        ResourceSearchTab,
        "_refresh_reference_popup",
        lambda _self, popup: refreshed.append(popup),
    )
    settings = QSettings(
        str(tmp_path / "resource.ini"), QSettings.Format.IniFormat
    )
    tab = ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    try:
        for _ in range(4):
            tab._set_reading_mode(True)
            tab._set_reading_mode(False)
        tab.reference_popup.refreshRequested.emit(tab.reference_popup)
        app.processEvents()

        assert refreshed == [tab.reference_popup]
    finally:
        tab.close()
        app.processEvents()


def test_reference_popup_favorite_button_tracks_exact_unit() -> None:
    app = QApplication.instance() or QApplication([])
    popup = LawReferencePopup(lambda _url: None)
    emitted: list[object] = []
    favorite = False
    popup.favoriteRequested.connect(emitted.append)
    popup.favorite_checker = lambda request: favorite and (
        request.get("hang") == "000100"
    )
    popup.reference_request = {
        "law_id": "009294",
        "law_name": "국토의 계획 및 이용에 관한 법률",
        "jo": "001000",
        "hang": "000100",
        "ho": "000200",
        "mok": "",
    }

    popup.set_content("제10조제1항제2호", "<p>본문</p>")
    assert popup.favorite_button.isEnabled()
    assert popup.favorite_button.text() == "☆"

    popup.show()
    app.processEvents()
    QTest.mouseClick(popup.favorite_button, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert emitted == [popup]

    popup.set_favorite_pending()
    assert not popup.favorite_button.isEnabled()
    assert popup.favorite_button.text() == "…"

    favorite = True
    popup._refresh_favorite_button()
    assert popup.favorite_button.text() == "★"


def test_cached_reference_popup_reopens_without_api() -> None:
    _app = QApplication.instance() or QApplication([])
    shown: list[tuple[str, str]] = []
    popup = SimpleNamespace(
        reference_key="",
        reference_request={},
        show_content_at=lambda title, html, _position: shown.append((title, html)),
    )
    status_messages: list[str] = []
    tab = SimpleNamespace(
        _reference_popup_states={},
        _reference_popup_for_request=lambda: popup,
        status_label=SimpleNamespace(setText=status_messages.append),
    )
    record = {
        "name": "국토의 계획 및 이용에 관한 법률 시행령 제4조",
        "html": "<p>저장된 제4조</p>",
        "reference_key": "009419:000400:::",
        "reference_request": {
            "law_id": "009419",
            "law_name": "국토의 계획 및 이용에 관한 법률 시행령",
            "jo": "000400",
        },
        "row": {"target": "law_reference"},
    }

    ResourceSearchTab.open_cached_reference_popup(tab, record)

    assert shown == [
        (
            "국토의 계획 및 이용에 관한 법률 시행령 제4조",
            "<p>저장된 제4조</p>",
        )
    ]
    assert popup.reference_request["jo"] == "000400"
    assert status_messages[-1].endswith("API 호출 없음")


def test_law_reference_admin_fallback_keeps_document_refresh_request() -> None:
    name = "훈령·예규 등의 발령 및 관리에 관한 규정"
    shown: list[tuple[str, str]] = []
    saved: list[tuple[str, str, str]] = []
    remembered: list[dict[str, str]] = []
    popup = SimpleNamespace(
        reference_request={},
        reference_key="",
        set_content=lambda title, html: shown.append((title, html)),
    )
    status_messages: list[str] = []

    def remember(*_args, **kwargs):
        remembered.append(dict(kwargs["request_override"]))
        return str(kwargs["key_override"])

    tab = SimpleNamespace(
        _pending_reference_popup=popup,
        _pending_reference_key=f"{name}::::",
        _document_reference_html=lambda _row, payload: (
            name,
            "<p>행정규칙 본문</p>",
        ),
        _remember_reference_popup=remember,
        _save_reference_cache=lambda key, title, html: saved.append(
            (key, title, html)
        ),
        status_label=SimpleNamespace(setText=status_messages.append),
    )
    result = {
        "mode": "admin_rule",
        "payload": {"AdmRulService": {"조문내용": "본문"}},
        "row": {
            "target": "admrul",
            "id": "2200000078285",
            "name": name,
        },
    }

    ResourceSearchTab._show_law_reference_detail(tab, result)

    expected_request = {
        "href": "doc:admrul:2200000078285",
        "category": "admrul",
        "item_id": "2200000078285",
        "name": name,
        "reference_key": f"{name}::::",
        "title": name,
    }
    assert shown == [(name, "<p>행정규칙 본문</p>")]
    assert popup.reference_request == expected_request
    assert remembered == [expected_request]
    assert saved == [
        (f"{name}::::", name, "<p>행정규칙 본문</p>")
    ]
    assert status_messages == [f"{name} 행정규칙 본문 조회 완료"]


def test_blank_reference_cache_is_ignored(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        resource_search_module, "LAW_REFERENCE_CACHE_DIR", tmp_path
    )
    key = "훈령ㆍ예규 등의 발령 및 관리에 관한 규정::::"
    path = ResourceSearchTab._reference_cache_path(key)
    path.write_text(
        json.dumps(
            {
                "schema": resource_search_module.LAW_REFERENCE_CACHE_SCHEMA,
                "kind": "law_reference",
                "key": key,
                "title": "훈령ㆍ예규 등의 발령 및 관리에 관한 규정",
                "html": '<div class="detail-header">제목만 있는 캐시</div>',
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    tab = SimpleNamespace(
        _reference_popup_states={},
        _reference_cache_path=ResourceSearchTab._reference_cache_path,
    )

    cached = ResourceSearchTab._load_reference_cache(tab, key)

    assert cached is None
    assert tab._reference_popup_states == {}


def test_saved_reference_opens_popup_without_leaving_saved_history() -> None:
    opened: list[object] = []
    navigation_changes: list[int] = []
    resource_tab = SimpleNamespace(open_cached_reference_popup=opened.append)
    window = SimpleNamespace(
        resource_tab=resource_tab,
        navigation=SimpleNamespace(setCurrentRow=navigation_changes.append),
    )
    record = {
        "kind": "detail_snapshot",
        "row": {"target": "law_reference"},
        "html": "<p>saved reference</p>",
    }

    result = LawSearchWindow._route_saved_record(window, record)

    assert opened == [record]
    assert navigation_changes == []
    assert result is resource_tab
