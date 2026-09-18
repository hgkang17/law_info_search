"""행정규칙ㆍ자치법규 조문 즐겨찾기가 그 문서로 열리는지 확인한다.

예전에는 조문 별을 걸 때 종류를 늘 ``law``로 적었다. 그래서 자치법규
조문 즐겨찾기를 누르면 법령 조문 API를 자치법규 ID로 부르다 빈손으로
돌아왔고, 화면에는 직전에 보던 문서(예: 행정규칙)가 그대로 남아
"눌러도 계속 다른 법령이 열린다"로 보였다.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab


ORDIN_ROW = {
    "target": "ordin",
    "label": "자치법규",
    "id": "2113131",
    "name": "이천시 도시계획 조례",
    "organization": "경기도 이천시",
    "date": "20260227",
    "number": "2341",
    "effective": "20260227",
    "raw": {"지자체기관명": "경기도 이천시", "자치법규종류": "조례"},
}


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _tab(tmp_path) -> ResourceSearchTab:
    settings = QSettings(
        str(tmp_path / "artfav.ini"), QSettings.Format.IniFormat
    )
    return ResourceSearchTab(
        lambda: "",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )


def test_article_favorite_keeps_the_open_document_kind(qt_app, tmp_path) -> None:
    """자치법규 본문에서 건 조문 별은 자치법규로 저장된다."""
    tab = _tab(tmp_path)
    try:
        tab.pending_row = dict(ORDIN_ROW)
        tab._open_document_tab(dict(ORDIN_ROW))
        assert tab._article_favorite_target("2113131") == "ordin"
        # 다른 ID에는 지금 문서의 종류를 함부로 물려주지 않는다.
        assert tab._article_favorite_target("009294") == "law"

        tab.add_article_favorite_by_id("2113131", "000100", "제1조(목적)", "이천시 도시계획 조례")
        saved = tab.law_cache.article_favorites(dict(ORDIN_ROW))
        assert [entry["jo"] for entry in saved] == ["000100"]
    finally:
        tab.close()


def test_old_law_labelled_note_is_repaired_from_the_saved_document(
    qt_app, tmp_path
) -> None:
    """이미 ``law``로 저장된 옛 쪽지는 같은 ID의 저장본을 보고 되돌린다."""
    tab = _tab(tmp_path)
    try:
        # 자치법규 본문을 저장해 둔 상태를 만든다.
        tab.law_cache.save_snapshot(
            dict(ORDIN_ROW),
            html="<p>이천시 도시계획 조례</p>",
            plain_text="이천시 도시계획 조례",
            extra={},
        )
        broken = {
            "target": "law",
            "label": "법령",
            "id": "2113131",
            "name": "이천시 도시계획 조례",
        }
        repaired = tab._repair_article_favorite_row(broken)
        assert repaired["target"] == "ordin"
        assert repaired["id"] == "2113131"

        # 저장본이 없는 ID는 건드리지 않는다(진짜 법령일 수 있다).
        untouched = dict(broken, id="009294")
        assert tab._repair_article_favorite_row(untouched)["target"] == "law"
    finally:
        tab.close()


def test_article_favourite_note_alone_is_not_taken_for_a_document(
    qt_app, tmp_path
) -> None:
    """조문 즐겨찾기 쪽지 자신은 '법령 저장본'으로 세지 않는다.

    세어 버리면 종류가 잘못 적힌 그 쪽지가 곧 근거가 되어 영영 못 고친다.
    """
    tab = _tab(tmp_path)
    try:
        note_row = {
            "target": "law",
            "label": "법령",
            "id": "2113131",
            "name": "이천시 도시계획 조례",
        }
        tab.law_cache.set_article_favorite(
            dict(note_row), "000100", "제1조(목적)", True
        )
        assert tab._has_document_record(note_row) is False
    finally:
        tab.close()
