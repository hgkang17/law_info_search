"""목록 검색의 검색범위 콤보(이름/본문검색) 검증."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab


def _tab(tmp_path) -> ResourceSearchTab:
    QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "res.ini"), QSettings.Format.IniFormat)
    return ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )


def _items(tab: ResourceSearchTab) -> list[tuple[str, int]]:
    combo = tab.search_scope
    return [(combo.itemText(i), combo.itemData(i)) for i in range(combo.count())]


def test_list_categories_offer_name_and_body_search(tmp_path) -> None:
    """법령ㆍ행정규칙ㆍ자치법규는 이름(1)과 본문검색(2)을 고를 수 있다."""
    tab = _tab(tmp_path)
    expected = {
        "law": [("법령명", 1), ("본문검색", 2)],
        "admrul": [("행정규칙명", 1), ("본문검색", 2)],
        "ordin": [("자치법규명", 1), ("본문검색", 2)],
    }
    for target, items in expected.items():
        assert tab.select_category(target)
        assert _items(tab) == items
        assert tab.current_search_scope() == 1


def test_annex_categories_keep_three_scopes(tmp_path) -> None:
    """별표ㆍ서식은 기존 1/2/3 구성을 그대로 쓴다."""
    tab = _tab(tmp_path)
    assert tab.select_category("licbyl")
    assert _items(tab) == [
        ("별표·서식명", 1),
        ("해당 법령명", 2),
        ("별표 본문", 3),
    ]
    assert tab.select_category("admbyl")
    assert _items(tab)[1] == ("해당 행정규칙명", 2)
    assert tab.select_category("ordinbyl")
    assert _items(tab)[1] == ("해당 자치법규명", 2)


def test_integrated_search_hides_scope_and_uses_one(tmp_path) -> None:
    """통합검색은 대상마다 search=2의 뜻이 달라 범위를 고르지 않는다."""
    tab = _tab(tmp_path)
    assert tab.select_category("__all__")
    assert _items(tab) == []
    assert tab.current_search_scope() == 1


def test_scope_choice_changes_value_and_placeholder(tmp_path) -> None:
    """본문검색을 고르면 API search 값과 입력 안내가 함께 바뀐다."""
    tab = _tab(tmp_path)
    assert tab.select_category("law")
    assert tab.query_input.placeholderText() == "검색할 법령명을 입력하세요"
    tab.search_scope.setCurrentIndex(1)
    assert tab.current_search_scope() == 2
    assert tab.query_input.placeholderText() == "법령 본문에서 찾을 단어를 입력하세요"


def test_scope_resets_when_category_has_no_such_value(tmp_path) -> None:
    """범위 3을 고른 뒤 법령으로 옮기면 지원하지 않는 값이 남지 않는다."""
    tab = _tab(tmp_path)
    assert tab.select_category("licbyl")
    tab.search_scope.setCurrentIndex(2)
    assert tab.current_search_scope() == 3
    assert tab.select_category("law")
    assert tab.current_search_scope() == 1
