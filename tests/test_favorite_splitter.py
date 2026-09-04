from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QFrame

from storage.cache import LawDocumentCache
from ui.tabs.viewed_laws import ViewedLawsTab


def test_favorite_columns_have_no_minimum_width_and_can_collapse(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "favorites.ini"), QSettings.Format.IniFormat)
    tab = ViewedLawsTab(
        LawDocumentCache(tmp_path / "saved"),
        favorites_only=True,
        settings=settings,
    )
    tab.resize(1200, 700)
    tab.show()
    app.processEvents()

    splitter = tab.favorite_splitter
    assert splitter is not None
    assert splitter.childrenCollapsible()
    assert all(splitter.widget(index).minimumWidth() == 0 for index in range(splitter.count()))
    assert all(tree.rootIsDecorated() for tree in tab.favorite_trees.values())
    assert all(tree.expandsOnDoubleClick() for tree in tab.favorite_trees.values())
    assert set(tab.favorite_category_checks) == {
        category for category, _label in tab.FAVORITE_CATEGORIES
    }
    assert all(
        checkbox.isChecked()
        for checkbox in tab.favorite_category_checks.values()
    )

    tab.favorite_category_checks["annex"].setChecked(False)
    app.processEvents()
    assert tab.favorite_category_cards["annex"].isHidden()
    assert tab.favorite_category_cards["law"].isVisible()
    assert "annex" not in str(
        settings.value(tab.FAVORITE_VISIBLE_CATEGORIES_KEY, "")
    )

    tab.favorite_category_checks["annex"].setChecked(True)
    app.processEvents()
    assert tab.favorite_category_cards["annex"].isVisible()

    sizes = [0] + [200] * (splitter.count() - 1)
    settings.setValue("favorite_card_widths", sizes)
    tab._restore_favorite_widths()
    app.processEvents()
    assert splitter.sizes()[0] == 0

    tab.close()


def test_favorite_checked_cards_are_restored(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(
        str(tmp_path / "favorite-visible.ini"), QSettings.Format.IniFormat
    )
    cache = LawDocumentCache(tmp_path / "saved-visible")
    first = ViewedLawsTab(cache, favorites_only=True, settings=settings)
    first.favorite_category_checks["central"].setChecked(False)
    first.close()

    restored = ViewedLawsTab(cache, favorites_only=True, settings=settings)
    restored.show()
    app.processEvents()
    assert restored.favorite_category_checks["central"].isChecked() is False
    assert restored.favorite_category_cards["central"].isHidden()
    assert restored.favorite_category_checks["law"].isChecked() is True
    assert restored.favorite_category_cards["law"].isVisible()
    restored.close()


def test_favorites_page_has_no_empty_heading_card(tmp_path) -> None:
    """즐겨찾기 화면은 공통 목록 위에 빈 흰 카드를 두지 않는다."""
    app = QApplication.instance() or QApplication([])
    settings = QSettings(
        str(tmp_path / "favorite-heading.ini"), QSettings.Format.IniFormat
    )
    favorites = ViewedLawsTab(
        LawDocumentCache(tmp_path / "saved-heading"),
        favorites_only=True,
        settings=settings,
    )
    saved = ViewedLawsTab(
        LawDocumentCache(tmp_path / "saved-history"),
        favorites_only=False,
        settings=settings,
    )
    try:
        favorites.show()
        saved.show()
        app.processEvents()

        heading_cards = [
            child
            for child in favorites.findChildren(QFrame)
            if child.objectName() == "card"
            and child.parent() is favorites
        ]
        assert heading_cards == []
        assert favorites.project_tabs is not None
        # 제목 카드가 없어도 왼쪽과 같은 12px 위 여백은 둔다.
        assert 10 <= favorites.project_tabs.y() <= 16
        assert favorites.search_input.isHidden()
        assert favorites.folder_button.isHidden()
        assert favorites.clear_cache_button.isHidden()
        assert favorites.union_check is not None
        assert favorites.union_check.text() == "즐겨찾기 모아보기"
        assert favorites.union_check.objectName() == "favoriteCategoryCheck"
        assert not favorites.union_check.isChecked()
        assert saved.folder_button.size() == saved.clear_cache_button.size()
        assert saved.folder_button.width() == saved.clear_cache_button.width()
        assert saved.folder_button.height() == saved.clear_cache_button.height()
        assert favorites.favorite_category_titles["law"].text() == "법령검색"
        assert "건" not in favorites.favorite_category_titles["law"].text()
        assert set(favorites.union_trees) == {
            category for category, _label in favorites.FAVORITE_CATEGORIES
        }

        saved_heading = [
            child
            for child in saved.findChildren(QFrame)
            if child.objectName() == "card" and child.parent() is saved
        ]
        assert saved_heading
        assert saved_heading[0].isVisible()
    finally:
        favorites.close()
        saved.close()


def test_union_favorites_start_unchecked_even_if_saved_on(tmp_path) -> None:
    """프로그램을 켜면 즐겨찾기 모아보기는 항상 꺼져 있다."""
    app = QApplication.instance() or QApplication([])
    settings = QSettings(
        str(tmp_path / "union-start.ini"), QSettings.Format.IniFormat
    )
    settings.setValue(ViewedLawsTab.FAVORITE_UNION_VIEW_KEY, True)
    settings.sync()
    tab = ViewedLawsTab(
        LawDocumentCache(tmp_path / "saved"),
        favorites_only=True,
        settings=settings,
    )
    try:
        tab.show()
        app.processEvents()
        assert tab.union_check is not None
        assert not tab.union_check.isChecked()
        assert tab.union_panel is not None
        assert tab.union_panel.isHidden()
    finally:
        tab.close()
