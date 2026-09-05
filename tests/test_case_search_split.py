"""질의회신·법령해석례·판례의 목록/본문 전환 검증."""

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
from ui.tabs import law_search as law_search_module
from ui.tabs.law_search import LawSearchTab


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _tab(tmp_path, service: str = "central") -> LawSearchTab:
    settings = QSettings(
        str(tmp_path / f"{service}.ini"), QSettings.Format.IniFormat
    )
    tab = LawSearchTab(
        service,
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / f"{service}-saved"),
    )
    tab.resize(1200, 720)
    tab.show()
    return tab


def _row(service: str = "central") -> dict[str, object]:
    target = {
        "central": "molitCgmExpc",
        "expc": "expc",
        "prec": "prec",
    }[service]
    return {
        "agency": "국토교통부",
        "target": target,
        "detail_available": True,
        "id": "123",
        "title": "시험 안건",
        "case_number": "24-0001",
        "date": "20260827",
        "inquiry_org": "시험기관",
        "court": "대법원",
        "data_source": "국가법령정보센터",
    }


def _select_first_row(tab: LawSearchTab, row: dict[str, object]) -> None:
    tab.result_rows = [row]
    tab.result_table.setRowCount(1)
    tab.result_table.setItem(0, tab.title_column, QTableWidgetItem("시험 안건"))
    tab.result_table.selectRow(0)


@pytest.mark.parametrize("service", ["central", "expc", "prec"])
def test_case_scope_and_query_share_one_row(qt_app, tmp_path, service) -> None:
    tab = _tab(tmp_path, service)
    try:
        qt_app.processEvents()
        combo_mid = tab.scope_combo.geometry().center().y()
        query_mid = tab.query_input.geometry().center().y()
        assert abs(combo_mid - query_mid) <= 4
        assert tab.scope_combo.geometry().right() <= tab.query_input.geometry().left()
        if tab.agency_combo is not None:
            agency_mid = tab.agency_combo.geometry().center().y()
            assert abs(agency_mid - query_mid) <= 4
            assert tab.agency_combo.geometry().right() <= tab.scope_combo.geometry().left()
    finally:
        tab.close()
        qt_app.processEvents()


@pytest.mark.parametrize("service", ["central", "expc", "prec"])
def test_case_title_column_stretches_to_fill_table(
    qt_app, tmp_path, service
) -> None:
    tab = _tab(tmp_path, service)
    try:
        tab.resize(1200, 720)
        tab.show()
        qt_app.processEvents()
        header = tab.result_table.horizontalHeader()
        # 저장 체크 칸만 고정폭이고 나머지는 손으로 끌어 조절한다. 늘림
        # 모드는 드래그한 폭을 곧바로 되돌려 버려 쓰지 않고, 남는 폭만
        # 제목 열이 흡수한다.
        assert header.sectionResizeMode(0) == QHeaderView.ResizeMode.Fixed
        assert all(
            header.sectionResizeMode(column)
            == QHeaderView.ResizeMode.Interactive
            for column in range(1, tab.result_table.columnCount())
        )
        used = sum(
            tab.result_table.columnWidth(index)
            for index in range(tab.result_table.columnCount())
            if not tab.result_table.isColumnHidden(index)
        )
        assert used >= tab.result_table.viewport().width() - 4
    finally:
        tab.close()
        qt_app.processEvents()


@pytest.mark.parametrize("service", ["central", "expc", "prec"])
def test_case_search_starts_with_results_only(qt_app, tmp_path, service) -> None:
    tab = _tab(tmp_path, service)
    try:
        qt_app.processEvents()
        assert tab.detail_card.isHidden()
        assert tab.main_splitter.sizes()[1] == 0
        assert not tab._reading_mode
    finally:
        tab.close()
        qt_app.processEvents()


def test_single_click_does_not_open_case_detail(
    qt_app, tmp_path, monkeypatch
) -> None:
    tab = _tab(tmp_path)
    requested: list[dict[str, object]] = []
    monkeypatch.setattr(
        tab,
        "_request_detail",
        lambda row, force_api=False: requested.append(row) or True,
    )
    try:
        _select_first_row(tab, _row())
        qt_app.processEvents()
        assert requested == []
        assert tab.detail_card.isHidden()
    finally:
        tab.close()
        qt_app.processEvents()


def test_single_click_updates_saved_detail_after_split_is_open(
    qt_app, tmp_path, monkeypatch
) -> None:
    tab = _tab(tmp_path)
    requested: list[dict[str, object]] = []
    monkeypatch.setattr(tab.law_cache, "has_snapshot", lambda _row: True)
    monkeypatch.setattr(
        tab,
        "_request_detail",
        lambda row, force_api=False: requested.append(row) or True,
    )
    try:
        row = _row()
        tab._show_detail_split()
        _select_first_row(tab, row)
        qt_app.processEvents()
        assert requested == [row]
    finally:
        tab.close()
        qt_app.processEvents()


def test_double_click_opens_case_detail_in_reading_mode(
    qt_app, tmp_path, monkeypatch
) -> None:
    tab = _tab(tmp_path)
    requested: list[dict[str, object]] = []
    monkeypatch.setattr(
        tab,
        "_request_detail",
        lambda row, force_api=False: requested.append(row) or True,
    )
    try:
        row = _row()
        _select_first_row(tab, row)
        tab._open_detail_expanded()
        qt_app.processEvents()

        assert requested == [row]
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


def test_detail_has_no_corner_close_button(qt_app, tmp_path) -> None:
    tab = _tab(tmp_path)
    try:
        tab._show_detail_split()
        qt_app.processEvents()

        assert not hasattr(tab, "close_detail_button")
        assert not hasattr(tab, "detail_button")
        assert tab.ai_agent_button.text() == "AI\n에이전트"
        assert tab.expand_detail_button.isVisible()

        tab._hide_detail_split()
        qt_app.processEvents()
        assert tab.detail_card.isHidden()
        assert tab.main_splitter.sizes()[1] == 0
        assert not tab._reading_mode
    finally:
        tab.close()
        qt_app.processEvents()


def test_ai_agent_button_opens_contextual_side_panel(
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

    monkeypatch.setattr(law_search_module, "AiChatPanel", FakeAiChatPanel)
    tab = _tab(tmp_path)
    try:
        tab._show_detail_split()
        tab.detail_view.setPlainText("질의요지와 회답 본문")
        qt_app.processEvents()

        assert tab.ai_agent_button.text() == "AI\n에이전트"
        assert tab.ai_agent_button.x() > tab.expand_detail_button.x()

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
            "질의요지와 회답 본문",
            "본문 전체",
        )

        tab._set_reading_mode(True)
        qt_app.processEvents()
        assert tab.main_splitter.sizes()[0] == 0
        assert tab.main_splitter.sizes()[2] > 0

        tab._set_reading_mode(False)
        qt_app.processEvents()
        assert tab.detail_card.isHidden()
        assert tab.main_splitter.sizes()[1] == 0
        assert not tab._reading_mode
        assert not tab.ai_chat_panel.isVisible()

        tab._show_detail_split()
        qt_app.processEvents()
        tab.ai_agent_button.click()
        qt_app.processEvents()
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


def test_unavailable_case_detail_keeps_results_only(
    qt_app, tmp_path, monkeypatch
) -> None:
    tab = _tab(tmp_path)
    monkeypatch.setattr(tab, "_request_detail", lambda *_args, **_kwargs: False)
    try:
        _select_first_row(tab, _row())
        tab._open_detail_expanded()
        qt_app.processEvents()
        assert tab.detail_card.isHidden()
    finally:
        tab.close()
        qt_app.processEvents()


def test_new_search_closes_case_detail_split(
    qt_app, tmp_path, monkeypatch
) -> None:
    tab = _tab(tmp_path)
    monkeypatch.setattr(tab, "_start_worker", lambda *_args, **_kwargs: None)
    try:
        tab._show_detail_split()
        qt_app.processEvents()
        assert not tab.detail_card.isHidden()

        tab.query_input.setText("도시계획")
        tab.start_search()
        qt_app.processEvents()
        assert tab.detail_card.isHidden()
        assert tab.main_splitter.sizes()[1] == 0
    finally:
        tab.close()
        qt_app.processEvents()


def test_saved_case_opens_in_reading_mode(qt_app, tmp_path) -> None:
    tab = _tab(tmp_path, "expc")
    try:
        tab.open_cached_snapshot(
            {
                "row": _row("expc"),
                "html": "<p>저장된 법령해석례 본문</p>",
                "plain_text": "저장된 법령해석례 본문",
            }
        )
        qt_app.processEvents()
        assert not tab.detail_card.isHidden()
        assert "저장된 법령해석례" in tab.detail_view.toPlainText()
        assert tab._reading_mode
        assert tab.main_splitter.sizes()[0] == 0
    finally:
        tab.close()
        qt_app.processEvents()
