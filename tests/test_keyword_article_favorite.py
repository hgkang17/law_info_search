"""지능형 검색 결과를 조문 즐겨찾기로 거는 회귀 테스트.

지능형 검색이 주는 법령ID와 여섯 자리 조문코드는 조항호목 API가 받는 값과
같은 체계다. 그래서 법령 조문은 법령검색 화면의 조문 즐겨찾기에 그대로
얹는다. 행정규칙 조문과 별표ㆍ서식은 얹을 수 없어 별을 그리지 않는다.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.ai_search import AiLawSearchTab
from ui.tabs.viewed_laws import ViewedLawsTab


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _tab(tmp_path) -> AiLawSearchTab:
    settings = QSettings(
        str(tmp_path / "keyword-fav.ini"), QSettings.Format.IniFormat
    )
    return AiLawSearchTab(
        "ai_search",
        lambda: "",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )


def test_law_article_row_is_offered_as_an_article_favorite(
    qt_app, tmp_path
) -> None:
    tab = _tab(tmp_path)
    try:
        tab.result_rows = [
            {
                "kind": "법령조문",
                "name": "국토의 계획 및 이용에 관한 법률",
                "provision": "제6조(국토의 용도 구분)",
                "source_id": "009293",
                "jo_code": "000600",
            }
        ]
        target = tab._article_favorite_target(tab.result_rows[0])

        assert target is not None
        assert target["law_id"] == "009293"
        assert target["jo"] == "000600"
        assert tab._row_supports_favorite(0) is True
    finally:
        tab.close()


@pytest.mark.parametrize(
    "row",
    [
        {
            "kind": "행정규칙조문",
            "name": "도시·군관리계획수립지침",
            "provision": "제9조",
            "source_id": "34769",
            "jo_code": "000900",
        },
        {
            "kind": "법령별표서식",
            "name": "건축법 시행령",
            "provision": "별표·서식 1",
            "source_id": "002118",
            "jo_code": "",
        },
    ],
)
def test_rows_without_an_article_target_show_no_star(
    qt_app, tmp_path, row: dict
) -> None:
    """행정규칙 조문과 별표ㆍ서식은 조문 즐겨찾기에 얹을 수 없다."""
    tab = _tab(tmp_path)
    try:
        tab.result_rows = [row]

        assert tab._article_favorite_target(row) is None
        assert tab._row_supports_favorite(0) is False
    finally:
        tab.close()


def test_favorite_screen_no_longer_has_a_keyword_column() -> None:
    """키워드검색 칸을 없애고 조문 즐겨찾기 한 곳으로 모았다."""
    names = {category for category, _label in ViewedLawsTab.FAVORITE_CATEGORIES}

    assert "keyword" not in names
    assert "article" in names
