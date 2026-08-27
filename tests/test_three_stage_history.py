"""3단비교표가 저장내역에 남고 API 없이 다시 열리는지 검증."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab
from ui.tabs.viewed_laws import ViewedLawsTab

KEY = "thdcmp:009294:000200"
TITLE = "국토의 계획 및 이용에 관한 법률 제2조 3단비교"
HTML = '<table class="comparison-table"><tr><td>법률 제2조</td></tr></table>'


def _tab(tmp_path) -> ResourceSearchTab:
    QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "thd.ini"), QSettings.Format.IniFormat)
    return ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )


def _remember(tab: ResourceSearchTab) -> None:
    tab._remember_three_stage_popup(
        KEY,
        TITLE,
        HTML,
        law_name="국토의 계획 및 이용에 관한 법률",
        label="제2조(정의)",
        short_name="국토계획법",
    )


def test_comparison_is_written_to_the_saved_history(tmp_path) -> None:
    tab = _tab(tmp_path)

    _remember(tab)

    records = [
        record
        for record in tab.law_cache.list_records()
        if isinstance(record.get("row"), dict)
        and record["row"].get("target") == "three_stage"
    ]
    assert len(records) == 1
    record = records[0]
    assert record["html"] == HTML
    assert record["reference_key"] == KEY
    assert record["three_stage_request"]["label"] == "제2조(정의)"


def test_saved_comparison_reopens_without_api(tmp_path) -> None:
    tab = _tab(tmp_path)
    _remember(tab)
    record = next(
        record
        for record in tab.law_cache.list_records()
        if isinstance(record.get("row"), dict)
        and record["row"].get("target") == "three_stage"
    )
    tab.three_stage_popup.hide()

    tab.open_cached_three_stage_popup(record)

    assert tab.three_stage_popup.reference_key == KEY
    assert "법률 제2조" in tab.three_stage_popup.browser.toPlainText()
    assert "API 호출 없음" in tab.status_label.text()


def test_history_labels_the_comparison(tmp_path) -> None:
    record = {
        "kind": "detail_snapshot",
        "name": TITLE,
        "row": {"target": "three_stage", "title": TITLE},
    }

    assert ViewedLawsTab._record_type(record) == "3단비교"


def test_reopening_a_missing_body_is_ignored(tmp_path) -> None:
    tab = _tab(tmp_path)

    tab.open_cached_three_stage_popup({"row": {}, "html": ""})

    assert tab.three_stage_popup.isVisible() is False
