"""인용 조문 즐겨찾기 검증.

조문 즐겨찾기는 따로 저장하지 않고 그 법령의 저장 파일 안에
``favorite_articles``로 얹힌다. 조문만 따로 두면 본문이 없어 열 수도,
현행 여부를 볼 수도 없기 때문이다.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from llm import extract_cited_articles
from storage.cache import LawDocumentCache
from ui.tabs.viewed_laws import ViewedLawsTab

ROW = {
    "target": "law",
    "label": "법령",
    "id": "009294",
    "name": "국토의 계획 및 이용에 관한 법률",
}


def _cache(tmp_path) -> LawDocumentCache:
    cache = LawDocumentCache(tmp_path / "saved")
    assert cache.save(ROW, {"법령": {"조문": []}})
    return cache


def test_article_favorite_is_kept_inside_the_law_record(tmp_path) -> None:
    cache = _cache(tmp_path)
    assert cache.article_favorites(ROW) == []
    assert not cache.is_article_favorite(ROW, "25")

    assert cache.set_article_favorite(ROW, "25", "국토계획법 제25조", True)

    assert cache.is_article_favorite(ROW, "25")
    assert cache.article_favorites(ROW) == [
        {
            "jo": "25",
            "hang": "",
            "ho": "",
            "mok": "",
            "label": "국토계획법 제25조",
        }
    ]
    # 조문을 걸면 그 법령도 즐겨찾기로 올라간다. 법령이 목록에 없으면
    # 그 밑에 달린 조문도 찾아갈 길이 없다.
    assert cache.is_favorite(ROW)


def test_subarticle_favorite_is_distinct_and_survives_resave(tmp_path) -> None:
    cache = _cache(tmp_path)
    assert cache.set_article_favorite(
        ROW,
        "001000",
        "국토계획법 제10조제1항제2호",
        True,
        hang="000100",
        ho="000200",
    )
    assert cache.is_article_favorite(
        ROW, "001000", hang="000100", ho="000200"
    )
    assert not cache.is_article_favorite(ROW, "001000")

    assert cache.save(ROW, {"법령": {"조문": ["갱신 본문"]}})

    assert cache.is_article_favorite(
        ROW, "001000", hang="000100", ho="000200"
    )
    assert cache.set_article_favorite(
        ROW,
        "001000",
        "국토계획법 제10조제1항제2호",
        False,
        hang="000100",
        ho="000200",
    )
    assert cache.article_favorites(ROW) == []


def test_article_favorite_can_be_removed_without_touching_the_law(
    tmp_path,
) -> None:
    cache = _cache(tmp_path)
    cache.set_article_favorite(ROW, "25", "제25조", True)
    cache.set_article_favorite(ROW, "30", "제30조", True)

    assert cache.set_article_favorite(ROW, "25", "제25조", False)

    assert [entry["jo"] for entry in cache.article_favorites(ROW)] == ["30"]
    assert cache.is_favorite(ROW)


def test_unsaved_law_cannot_hold_an_article_favorite(tmp_path) -> None:
    cache = LawDocumentCache(tmp_path / "saved")
    assert not cache.set_article_favorite(ROW, "25", "제25조", True)
    assert cache.last_error


def test_cited_articles_are_read_from_the_answer(tmp_path) -> None:
    """즐겨찾기 단추는 답에 실제로 박힌 조문 링크에만 단다."""
    text = (
        "[국토계획법 제25조](law:009294:25)와 "
        "[국토계획법 제30조](law:009294:30), "
        "[수립지침](doc:admrul:12345)을 함께 봅니다. "
        "[국토계획법 제25조](law:009294:25)는 한 번만 셉니다."
    )

    assert extract_cited_articles(text) == (
        ("009294", "25", "국토계획법 제25조"),
        ("009294", "30", "국토계획법 제30조"),
    )
    # 문서 전체를 가리키는 doc: 링크는 조문 단추 대상이 아니다.
    assert extract_cited_articles("[지침](doc:admrul:12345)") == ()


def test_article_favorite_has_own_column_and_can_be_unstarred(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    cache = _cache(tmp_path)
    assert cache.set_article_favorite(ROW, "25", "제25조", True)
    settings = QSettings(
        str(tmp_path / "favorites.ini"), QSettings.Format.IniFormat
    )
    tab = ViewedLawsTab(cache, favorites_only=True, settings=settings)
    tab.show()
    app.processEvents()

    tree = tab.favorite_trees["article"]
    assert tab.favorite_add_buttons["article"].isVisible()
    assert tree.topLevelItemCount() == 1
    item = tree.topLevelItem(0)
    assert item.data(0, tab.FAVORITE_KIND_ROLE) == "article"
    assert item.data(0, tab.FAVORITE_ARTICLE_ROLE) == "25"
    assert item.data(0, tab.FAVORITE_UNIT_ROLE)["jo"] == "25"
    assert item.parent() is None

    opened: list[dict[str, object]] = []
    tab.openRequested.connect(opened.append)
    # 한 번 누르는 것으로는 열리지 않는다 — 옆의 법령 즐겨찾기와 같다.
    tree.itemClicked.emit(item, 0)
    app.processEvents()
    assert opened == []

    tree.itemDoubleClicked.emit(item, 0)
    app.processEvents()

    assert len(opened) == 1
    assert opened[0]["favorite_article_jo"] == "25"
    assert opened[0]["favorite_article_unit"]["jo"] == "25"
    assert opened[0].get("kind") != "detail_snapshot"

    tab._remove_favorite_by_index("article", tree.indexFromItem(item))
    app.processEvents()
    assert not cache.is_article_favorite(ROW, "25")
    assert tree.topLevelItemCount() == 0
    tab.close()


def test_article_favorite_can_be_moved_into_its_own_folder(
    tmp_path, monkeypatch
) -> None:
    app = QApplication.instance() or QApplication([])
    cache = _cache(tmp_path)
    assert cache.set_article_favorite(ROW, "25", "제25조", True)
    settings = QSettings(
        str(tmp_path / "article-folders.ini"), QSettings.Format.IniFormat
    )
    tab = ViewedLawsTab(cache, favorites_only=True, settings=settings)
    tab.show()
    app.processEvents()
    monkeypatch.setattr(
        "ui.tabs.viewed_laws.QInputDialog.getText",
        lambda *_args, **_kwargs: ("검토 조문", True),
    )

    tab._create_favorite_folder("article")
    tree = tab.favorite_trees["article"]
    folder = next(
        tree.topLevelItem(index)
        for index in range(tree.topLevelItemCount())
        if tree.topLevelItem(index).data(0, tab.FAVORITE_KIND_ROLE) == "folder"
    )
    article = next(
        tree.topLevelItem(index)
        for index in range(tree.topLevelItemCount())
        if tree.topLevelItem(index).data(0, tab.FAVORITE_KIND_ROLE) == "article"
    )
    tree.takeTopLevelItem(tree.indexOfTopLevelItem(article))
    folder.addChild(article)
    tab._persist_favorite_tree("저장")
    app.processEvents()

    saved = cache.article_favorites(ROW)
    assert saved[0]["favorite_folder"] == folder.data(
        0, tab.FAVORITE_FOLDER_ID_ROLE
    )

    tab.refresh()
    app.processEvents()
    tree = tab.favorite_trees["article"]
    folder = next(
        tree.topLevelItem(index)
        for index in range(tree.topLevelItemCount())
        if tree.topLevelItem(index).data(0, tab.FAVORITE_KIND_ROLE) == "folder"
    )
    assert folder.childCount() == 1
    assert folder.child(0).data(0, tab.FAVORITE_KIND_ROLE) == "article"
    tab.close()


def test_new_article_column_is_enabled_for_old_visibility_settings(
    tmp_path,
) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(
        str(tmp_path / "old-favorites.ini"), QSettings.Format.IniFormat
    )
    settings.setValue(
        ViewedLawsTab.FAVORITE_VISIBLE_CATEGORIES_KEY,
        '["law", "annex"]',
    )
    tab = ViewedLawsTab(
        LawDocumentCache(tmp_path / "old-saved"),
        favorites_only=True,
        settings=settings,
    )
    tab.show()
    app.processEvents()

    assert tab.favorite_category_checks["article"].isChecked()
    assert tab.favorite_category_cards["article"].isVisible()
    assert int(
        settings.value(tab.FAVORITE_VISIBLE_CATEGORIES_VERSION_KEY, 0)
    ) == tab.FAVORITE_VISIBLE_CATEGORIES_VERSION
    tab.close()
