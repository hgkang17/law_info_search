"""즐겨찾기 폴더를 우클릭 메뉴에서 만드는지 검증."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from ui.tabs.viewed_laws import ViewedLawsTab


def _tab(tmp_path) -> ViewedLawsTab:
    QApplication.instance() or QApplication([])
    settings = QSettings(
        str(tmp_path / "favorites.ini"), QSettings.Format.IniFormat
    )
    tab = ViewedLawsTab(
        LawDocumentCache(tmp_path / "saved"),
        favorites_only=True,
        settings=settings,
    )
    tab.resize(1200, 700)
    tab.show()
    return tab


def _labels(menu) -> list[str]:
    return [action.text() for action in menu.actions() if action.text()]


def _name_dialog(monkeypatch, *names: str) -> None:
    values = iter(names)
    monkeypatch.setattr(
        "ui.tabs.viewed_laws.QInputDialog.getText",
        staticmethod(lambda *_args, **_kwargs: (next(values), True)),
    )


def test_empty_area_right_click_offers_a_new_folder(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    app.processEvents()

    menu = tab._build_favorite_folder_menu("law", None)

    assert menu is not None
    assert _labels(menu) == ["새 폴더"]
    tab.close()


def test_folder_right_click_offers_a_child_folder(tmp_path, monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    tree = tab.favorite_trees["law"]
    tab._activate_favorite_category("law")
    _name_dialog(monkeypatch, "상위폴더")
    tab._create_favorite_folder("law")
    app.processEvents()
    assert tree.topLevelItemCount() == 1

    menu = tab._build_favorite_folder_menu("law", tree.topLevelItem(0))

    assert menu is not None
    assert _labels(menu) == ["새 하위 폴더", "이름 변경", "삭제"]
    tab.close()


def test_new_folder_from_the_menu_lands_under_the_folder(
    tmp_path, monkeypatch
) -> None:
    """폴더 위에서 만들면 하위 폴더, 빈 자리에서 만들면 맨 위 폴더."""
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    tree = tab.favorite_trees["law"]
    _name_dialog(monkeypatch, "상위폴더", "하위폴더", "형제폴더")

    tab._build_favorite_folder_menu("law", None).actions()[0].trigger()
    app.processEvents()
    parent = tree.topLevelItem(0)

    tab._build_favorite_folder_menu("law", parent).actions()[0].trigger()
    app.processEvents()
    assert tree.topLevelItemCount() == 1
    assert parent.childCount() == 1
    assert parent.child(0).text(0) == "하위폴더"

    # 빈 자리에서 부르면 고른 폴더를 풀고 맨 위에 만든다.
    tab._build_favorite_folder_menu("law", None).actions()[0].trigger()
    app.processEvents()
    assert tree.topLevelItemCount() == 2
    assert parent.childCount() == 1
    tab.close()
