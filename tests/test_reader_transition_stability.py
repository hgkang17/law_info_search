"""본문을 열거나 열린 탭으로 돌아갈 때 중간 폭이 노출되지 않는지 검증."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.main_window import LawSearchWindow
from ui.tabs.ai_chat_panel import AiChatPanel
from ui.tabs.resource_search import ResourceSearchTab


ROW = {
    "target": "law",
    "label": "법령",
    "id": "009294",
    "name": "국토의 계획 및 이용에 관한 법률",
    "related": "",
    "organization": "국토교통부",
    "date": "",
    "number": "",
    "effective": "",
    "raw": {},
}


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_resource_body_is_opened_only_after_reader_width_is_final(tmp_path) -> None:
    app = _application()
    settings = QSettings(str(tmp_path / "resource.ini"), QSettings.Format.IniFormat)
    tab = ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    tab.resize(1400, 820)
    tab.show()
    app.processEvents()
    tab.result_rows = [dict(ROW)]
    tab.result_table.setRowCount(1)
    tab.result_table.setCurrentCell(0, 0)
    opened_widths = []
    opened_while_updates_enabled = []

    def record_open(*_args):
        opened_widths.append(tab.detail_view.viewport().width())
        opened_while_updates_enabled.append(tab.updatesEnabled())

    tab.open_selected_detail = record_open

    tab._open_detail_expanded()

    assert tab._reading_mode
    assert opened_widths == [tab.detail_view.viewport().width()]
    assert opened_while_updates_enabled == [False]
    tab.close()


def test_open_document_tab_transition_settles_wrap_while_window_is_frozen(
    tmp_path, monkeypatch
) -> None:
    app = _application()
    monkeypatch.setattr("ui.main_window.LAW_CACHE_DIR", tmp_path / "saved")
    monkeypatch.setattr(AiChatPanel, "_start_visible_background_checks", lambda self: None)
    monkeypatch.setattr(ResourceSearchTab, "_queue_three_stage_link_request", lambda *args: None)
    window = LawSearchWindow()
    try:
        window.resize(1200, 800)
        window.show()
        resource = window.resource_tab
        resource._open_document_tab(dict(ROW))
        resource._set_detail_document(
            ROW["name"],
            [("법령ID", ROW["id"])],
            [("조문", "제1조(목적) 본문 " * 100)],
            build_toc=True,
        )
        window._refresh_open_documents()
        token = next(
            token
            for token, document in window._open_document_descriptors.items()
            if document.get("key") == "law:009294"
        )
        window.navigation.setCurrentRow(0)
        observed_updates = []
        settle_wrap_now = resource.detail_view.settle_wrap_now

        def record_settle():
            observed_updates.append(window.updatesEnabled())
            settle_wrap_now()

        monkeypatch.setattr(resource.detail_view, "settle_wrap_now", record_settle)

        window._activate_open_document(token)

        assert observed_updates
        assert observed_updates[-1] is False
        assert resource._reading_mode
    finally:
        window.close()
        app.processEvents()
