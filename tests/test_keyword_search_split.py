"""직접검색·연관검색의 목록/본문/AI 패널 전환 검증."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHeaderView,
    QLineEdit,
    QTableWidgetItem,
)

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs import ai_search as ai_search_module
from ui.tabs.ai_search import AiLawSearchTab


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _tab(tmp_path, service: str = "ai_search") -> AiLawSearchTab:
    settings = QSettings(
        str(tmp_path / f"{service}.ini"), QSettings.Format.IniFormat
    )
    tab = AiLawSearchTab(
        service,
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / f"{service}-saved"),
    )
    tab.resize(1200, 720)
    tab.show()
    return tab


def _row(service: str = "ai_search") -> dict[str, str]:
    return {
        "target": service,
        "kind": "법령",
        "name": "국토의 계획 및 이용에 관한 법률",
        "provision": "제2조(정의)",
        "date": "2026.08.28",
        "agency": "국토교통부",
        "content": "제2조 이 법에서 사용하는 용어의 뜻은 다음과 같다.",
        "source_id": "001234",
        "article_number": "2",
        "article_branch": "",
        "jo_code": "000200",
        "article_loading": "",
        "article_error": "",
        "publication_date": "2026.08.28",
        "publication_number": "법률 제1호",
    }


def _select_first_row(tab: AiLawSearchTab, row: dict[str, str]) -> None:
    tab.result_rows = [row]
    tab.result_table.setRowCount(1)
    tab.result_table.setItem(0, 2, QTableWidgetItem(row["provision"]))
    tab.result_table.selectRow(0)


def _assert_search_controls_share_one_row(tab) -> None:
    combo_mid = tab.scope_combo.geometry().center().y()
    query_mid = tab.query_input.geometry().center().y()
    assert abs(combo_mid - query_mid) <= 4
    assert tab.scope_combo.geometry().right() <= tab.query_input.geometry().left()
    assert tab.query_input.geometry().right() <= tab.search_button.geometry().left()


@pytest.mark.parametrize("service", ["ai_related", "ai_search"])
def test_keyword_scope_and_query_share_one_row(qt_app, tmp_path, service) -> None:
    tab = _tab(tmp_path, service)
    try:
        qt_app.processEvents()
        _assert_search_controls_share_one_row(tab)
    finally:
        tab.close()
        qt_app.processEvents()


@pytest.mark.parametrize("service", ["ai_related", "ai_search"])
def test_keyword_provision_and_name_columns_stretch(
    qt_app, tmp_path, service
) -> None:
    tab = _tab(tmp_path, service)
    try:
        tab.resize(1200, 720)
        tab.show()
        qt_app.processEvents()
        header = tab.result_table.horizontalHeader()
        assert header.sectionResizeMode(2) == QHeaderView.ResizeMode.Stretch
        assert header.sectionResizeMode(3) == QHeaderView.ResizeMode.Stretch
        used = sum(
            tab.result_table.columnWidth(index)
            for index in range(tab.result_table.columnCount())
        )
        assert used >= tab.result_table.viewport().width() - 4
    finally:
        tab.close()
        qt_app.processEvents()


@pytest.mark.parametrize("service", ["ai_related", "ai_search"])
def test_keyword_search_starts_with_results_only(
    qt_app, tmp_path, service
) -> None:
    tab = _tab(tmp_path, service)
    try:
        qt_app.processEvents()
        assert tab.detail_card.isHidden()
        assert tab.main_splitter.sizes()[1] == 0
        assert not tab._reading_mode
    finally:
        tab.close()
        qt_app.processEvents()


def test_single_click_only_selects_until_split_is_open(
    qt_app, tmp_path, monkeypatch
) -> None:
    tab = _tab(tmp_path)
    shown: list[bool] = []
    monkeypatch.setattr(
        tab,
        "_show_selected_result",
        lambda force_live=False: shown.append(force_live),
    )
    try:
        row = _row()
        _select_first_row(tab, row)
        qt_app.processEvents()
        assert shown == []
        assert tab.detail_card.isHidden()

        tab._show_detail_split()
        tab.result_table.clearSelection()
        tab.result_table.selectRow(0)
        qt_app.processEvents()
        assert shown == [False]
    finally:
        tab.close()
        qt_app.processEvents()


def test_double_click_opens_keyword_detail_in_reading_mode(
    qt_app, tmp_path, monkeypatch
) -> None:
    tab = _tab(tmp_path)
    shown: list[bool] = []
    monkeypatch.setattr(
        tab,
        "_show_selected_result",
        lambda force_live=False: shown.append(force_live),
    )
    try:
        _select_first_row(tab, _row())
        tab._open_detail_expanded()
        qt_app.processEvents()

        assert shown == [False]
        assert not tab.detail_card.isHidden()
        assert tab._reading_mode
        assert tab.main_splitter.sizes()[0] == 0
        assert tab.search_results_panel.isHidden()
        assert tab.expand_detail_button.isHidden()
        assert tab.ai_agent_button.isVisible()

        tab.restore_view_button.click()
        qt_app.processEvents()
        assert tab.detail_card.isHidden()
        assert not tab._reading_mode
        assert tab.main_splitter.sizes()[1] == 0
        assert not tab.search_results_panel.isHidden()
    finally:
        tab.close()
        qt_app.processEvents()


def test_keyword_detail_has_ai_button_without_corner_close(
    qt_app, tmp_path
) -> None:
    tab = _tab(tmp_path)
    try:
        tab._show_detail_split()
        qt_app.processEvents()

        assert not hasattr(tab, "close_detail_button")
        assert not hasattr(tab, "detail_button")
        assert tab.ai_agent_button.text() == "AI\n에이전트"
        assert tab.ai_agent_button.x() > tab.expand_detail_button.x()

        tab._hide_detail_split()
        qt_app.processEvents()
        assert tab.detail_card.isHidden()
        assert tab.main_splitter.sizes()[1] == 0
    finally:
        tab.close()
        qt_app.processEvents()


def test_new_keyword_search_closes_detail_split(
    qt_app, tmp_path, monkeypatch
) -> None:
    tab = _tab(tmp_path)
    monkeypatch.setattr(tab, "_start_worker", lambda *_args, **_kwargs: None)
    try:
        tab._show_detail_split()
        tab.query_input.setText("도시계획")
        tab.start_search()
        qt_app.processEvents()

        assert tab.detail_card.isHidden()
        assert tab.main_splitter.sizes()[1] == 0
    finally:
        tab.close()
        qt_app.processEvents()


def test_saved_keyword_detail_opens_in_reading_mode(qt_app, tmp_path) -> None:
    tab = _tab(tmp_path, "ai_related")
    try:
        tab.open_cached_snapshot(
            {
                "row": _row("ai_related"),
                "html": "<p>저장된 연관검색 본문</p>",
                "plain_text": "저장된 연관검색 본문",
            }
        )
        qt_app.processEvents()

        assert not tab.detail_card.isHidden()
        assert "저장된 연관검색 본문" in tab.detail_view.toPlainText()
        assert tab._reading_mode
        assert tab.main_splitter.sizes()[0] == 0
    finally:
        tab.close()
        qt_app.processEvents()


def test_related_admin_rule_extracts_only_requested_article() -> None:
    payload = {
        "AdmRulService": {
            "조문내용": (
                "제1조(목적) 첫 조문"
                "제2조(일반원칙) 선택 조문"
                "제3조(적용) 다음 조문"
            )
        }
    }

    assert AiLawSearchTab._extract_related_admin_article(
        payload, "2", "0"
    ) == "제2조(일반원칙) 선택 조문"


def test_keyword_ai_agent_uses_current_detail(
    qt_app, tmp_path, monkeypatch
) -> None:
    class FakeAiChatPanel(QFrame):
        chatHistoryCleared = Signal(str)
        closeRequested = Signal()

        def __init__(self, _settings, parent=None) -> None:
            super().__init__(parent)
            self.input_edit = QLineEdit(self)
            self.shutdown_called = False

        def apply_external_history_clear(self, _provider_name: str) -> None:
            pass

        def shutdown(self) -> None:
            self.shutdown_called = True

    monkeypatch.setattr(ai_search_module, "AiChatPanel", FakeAiChatPanel)
    tab = _tab(tmp_path)
    try:
        tab._show_detail_split()
        tab.detail_view.setPlainText("직접검색 조문 본문")
        tab.ai_agent_button.click()
        qt_app.processEvents()

        assert tab.ai_chat_panel is not None
        assert tab.ai_chat_panel.isVisible()
        assert tab.main_splitter.sizes()[2] > 0
        assert not tab.main_splitter.isCollapsible(2)
        sizes = tab.main_splitter.sizes()
        total = sum(sizes)
        tab.main_splitter.setSizes(
            [sizes[0], max(1, total - sizes[0] - 40), 40]
        )
        qt_app.processEvents()
        assert 0 < tab.main_splitter.sizes()[2] < 100
        assert tab.ai_chat_panel.context_source() == (
            "직접검색 조문 본문",
            "본문 전체",
        )

        tab._hide_detail_split()
        qt_app.processEvents()
        assert tab.detail_card.isHidden()
        assert not tab.ai_chat_panel.isVisible()
        assert tab.main_splitter.sizes()[1:] == [0, 0]

        panel = tab.ai_chat_panel
        tab.shutdown()
        assert panel.shutdown_called
    finally:
        tab.close()
        qt_app.processEvents()
