"""질의회신·법령해석례·판례의 목록/본문 전환 검증."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QTableWidgetItem

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
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


def test_double_click_opens_case_detail_in_split_view(
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
        assert all(size > 0 for size in tab.main_splitter.sizes())
        assert not tab._reading_mode
    finally:
        tab.close()
        qt_app.processEvents()


def test_small_close_button_replaces_detail_lookup_button(
    qt_app, tmp_path
) -> None:
    tab = _tab(tmp_path)
    try:
        tab._show_detail_split()
        qt_app.processEvents()

        assert not hasattr(tab, "detail_button")
        assert tab.close_detail_button.text() == "×"
        assert tab.close_detail_button.width() <= 24
        assert tab.close_detail_button.height() <= 24

        tab.close_detail_button.click()
        qt_app.processEvents()

        assert tab.detail_card.isHidden()
        assert tab.main_splitter.sizes()[1] == 0
        assert not tab._reading_mode
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


def test_saved_case_opens_in_split_view(qt_app, tmp_path) -> None:
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
        assert not tab._reading_mode
    finally:
        tab.close()
        qt_app.processEvents()
