from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

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
