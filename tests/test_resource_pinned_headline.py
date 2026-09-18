"""행정규칙ㆍ자치법규도 법령처럼 붙박이 제목 줄을 두는지 확인한다.

이 줄이 없으면 그 위에 얹히는 'API 갱신'과 한글 다운로드 단추까지 함께
숨는다. 예전에는 법령에만 줄이 떠서 두 단추를 아예 쓸 수 없었다.
"""

from __future__ import annotations

import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab


ADMRUL_ROW = {
    "target": "admrul",
    "label": "행정규칙",
    "id": "2100000282348",
    "name": "도시·군관리계획수립지침",
    "organization": "국토교통부",
    "date": "20260708",
    "number": "1967",
    "effective": "20260708",
    "raw": {
        "소관부처명": "국토교통부",
        "행정규칙종류": "훈령",
        "제개정구분명": "타법개정",
    },
}

ORDIN_ROW = {
    "target": "ordin",
    "label": "자치법규",
    "id": "2113131",
    "name": "이천시 도시계획 조례",
    "organization": "경기도 이천시",
    "date": "2026.02.27",
    "number": "2341",
    "effective": "2026.02.27",
    "raw": {
        "지자체기관명": "경기도 이천시",
        "자치법규종류": "조례",
        "제개정구분명": "일부개정",
    },
}


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _tab(tmp_path) -> ResourceSearchTab:
    settings = QSettings(
        str(tmp_path / "headline.ini"), QSettings.Format.IniFormat
    )
    return ResourceSearchTab(
        lambda: "",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )


def test_subtitle_follows_the_official_site_wording() -> None:
    assert ResourceSearchTab._resource_headline_subtitle(ADMRUL_ROW) == (
        "[시행 2026. 7. 8.] [국토교통부훈령 제1967호, 2026. 7. 8., 타법개정]"
    )
    assert ResourceSearchTab._resource_headline_subtitle(ORDIN_ROW) == (
        "[시행 2026. 2. 27.] [경기도 이천시조례 제2341호, 2026. 2. 27., 일부개정]"
    )
    # 법령ㆍ별표는 각자의 길로 만든다. 여기서는 빈 줄을 준다.
    assert ResourceSearchTab._resource_headline_subtitle({"target": "law"}) == ""
    assert ResourceSearchTab._resource_headline_subtitle(None) == ""


@pytest.mark.parametrize("row", [ADMRUL_ROW, ORDIN_ROW])
def test_pinned_bar_carries_the_title_and_both_buttons(qt_app, tmp_path, row) -> None:
    tab = _tab(tmp_path)
    try:
        tab.pending_row = dict(row)
        tab._open_document_tab(dict(row))
        tab._set_pinned_headline(str(row["name"]), "", "")
        qt_app.processEvents()

        assert not tab.pinned_headline_bar.isHidden()
        shown = re.sub(r"<[^>]+>", " ", tab.pinned_headline.text())
        shown = " ".join(shown.replace("&nbsp;", " ").split())
        assert str(row["name"]) in shown
        assert ResourceSearchTab._resource_headline_subtitle(row) in shown
        # 사이트 저장 창이 있는 문서라 한글 다운로드 단추도 함께 선다.
        assert not tab.hwp_export_button.isHidden()
    finally:
        tab.close()


def test_annex_document_keeps_no_pinned_bar(qt_app, tmp_path) -> None:
    """별표ㆍ서식은 사이트 저장 창도 API 재조회도 없어 줄을 두지 않는다."""
    tab = _tab(tmp_path)
    try:
        row = {
            "target": "licbyl",
            "label": "별표·서식",
            "id": "1",
            "name": "[별표 1] 시험 기준",
        }
        tab.pending_row = dict(row)
        tab._open_document_tab(dict(row))
        tab._set_pinned_headline(str(row["name"]), "", "")
        qt_app.processEvents()
        assert tab.pinned_headline_bar.isHidden()
    finally:
        tab.close()
