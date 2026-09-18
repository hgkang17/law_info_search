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


def test_collapsed_column_shows_named_strip_but_hidden_column_does_not(
    tmp_path,
) -> None:
    """접힌 칸만 음영 띠로 보이고, 체크 해제로 숨긴 칸은 표시하지 않는다."""
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "strip.ini"), QSettings.Format.IniFormat)
    tab = ViewedLawsTab(
        LawDocumentCache(tmp_path / "saved-strip"),
        favorites_only=True,
        settings=settings,
    )
    try:
        tab.resize(1400, 600)
        tab.show()
        app.processEvents()
        splitter = tab.favorite_splitter
        assert splitter is not None

        def strips() -> list[str]:
            app.processEvents()
            return [
                splitter.handle(index).collapsed_title()
                for index in range(1, splitter.count())
                if splitter.handle(index).collapsed_index() >= 0
            ]

        tab.favorite_category_checks["annex"].setChecked(False)
        assert strips() == []

        sizes = splitter.sizes()
        sizes[0] += sizes[1]
        sizes[1] = 0
        splitter.setSizes(sizes)
        assert strips() == ["조항호목"]
        handle = splitter.handle(1)
        assert handle.width() >= handle.STRIP_WIDTH

        assert handle.restore_collapsed()
        assert splitter.sizes()[1] > 0
        assert strips() == []
    finally:
        tab.close()


def test_two_collapsed_leading_columns_each_keep_a_strip(tmp_path) -> None:
    """맨 앞 두 칸을 함께 접어도 둘 다 음영 띠로 남는다.

    손잡이는 자기 칸 앞에 붙으므로 첫 칸에는 맡을 손잡이가 없다. 예전에는
    바로 뒤 손잡이가 자기 칸까지 접히면 자기 것만 맡아, 첫 칸이 음영 띠도
    없이 통째로 사라졌다(체크박스를 껐다 켜야만 돌아왔다).
    """
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "pair.ini"), QSettings.Format.IniFormat)
    tab = ViewedLawsTab(
        LawDocumentCache(tmp_path / "saved-pair"),
        favorites_only=True,
        settings=settings,
    )
    try:
        tab.resize(1400, 600)
        tab.show()
        app.processEvents()
        splitter = tab.favorite_splitter
        assert splitter is not None

        sizes = splitter.sizes()
        sizes[2] += sizes[0] + sizes[1]
        sizes[0] = 0
        sizes[1] = 0
        splitter.setSizes(sizes)
        app.processEvents()

        handle = splitter.handle(1)
        assert handle.collapsed_indices() == (0, 1)
        assert handle.collapsed_titles() == ["법령검색", "조항호목"]
        # 이름 둘을 나란히 적으므로 띠 하나 폭의 두 배를 받는다.
        assert handle.width() >= handle.STRIP_WIDTH * 2

        # 각 띠는 자기 칸만 펼친다. 첫 칸을 되살려도 둘째는 접힌 채 남는다.
        assert handle.restore_collapsed(0)
        app.processEvents()
        assert splitter.sizes()[0] > 0
        assert splitter.sizes()[1] == 0
        assert splitter.handle(1).collapsed_indices() == (1,)
    finally:
        tab.close()


def test_dragging_collapsed_strip_restores_column_and_clears_strip(
    tmp_path,
) -> None:
    """접힌 음영 띠를 끌면 그 칸이 열리고 띠는 사라진다.

    Qt 기본 끌기는 접힌 칸을 0으로 둔 채 옆 칸만 늘려, 띠가 열린 칸
    옆에 그대로 남았다.
    """
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "drag-strip.ini"), QSettings.Format.IniFormat)
    tab = ViewedLawsTab(
        LawDocumentCache(tmp_path / "saved-drag-strip"),
        favorites_only=True,
        settings=settings,
    )
    try:
        tab.resize(1400, 600)
        tab.show()
        app.processEvents()
        splitter = tab.favorite_splitter
        assert splitter is not None

        sizes = splitter.sizes()
        sizes[0] += sizes[3]
        sizes[3] = 0
        splitter.setSizes(sizes)
        app.processEvents()
        handle = splitter.handle(3)
        assert handle.collapsed_indices() == (3,)
        assert handle.width() >= handle.STRIP_WIDTH

        center = QPointF(handle.width() / 2, handle.height() / 2)
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            center,
            handle.mapToGlobal(center.toPoint()),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        handle.mousePressEvent(press)
        # CLICK_SLOP(3)을 넘기며 왼쪽으로 끌어 접힌 칸을 연다.
        for offset in (5, 10, 20, 40):
            pos = QPointF(center.x() - offset, center.y())
            move = QMouseEvent(
                QEvent.Type.MouseMove,
                pos,
                handle.mapToGlobal(pos.toPoint()),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            handle.mouseMoveEvent(move)
            app.processEvents()
        assert splitter.sizes()[3] > 0
        assert handle.collapsed_indices() == ()
        assert handle.width() < handle.STRIP_WIDTH
    finally:
        tab.close()


def test_multiple_collapsed_strips_stay_inside_available_width(
    tmp_path,
) -> None:
    """칸 여러 개를 접어도 음영 띠가 분할기 폭 안에 남는다.

    손잡이가 띠로 넓어지면 Qt가 분할기 위젯 자체를 키워, 오른쪽 띠가
    창 밖으로 밀려 아예 안 보였다. 바깥에서 받은 폭을 기준으로 맞춰야 한다.
    """
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "fit.ini"), QSettings.Format.IniFormat)
    tab = ViewedLawsTab(
        LawDocumentCache(tmp_path / "saved-fit"),
        favorites_only=True,
        settings=settings,
    )
    try:
        tab.resize(1000, 600)
        tab.show()
        app.processEvents()
        splitter = tab.favorite_splitter
        assert splitter is not None
        available = splitter.width()
        assert available > 0
        assert splitter._available_span == available

        sizes = splitter.sizes()
        sizes[0] += sizes[3] + sizes[4] + sizes[5]
        sizes[3] = sizes[4] = sizes[5] = 0
        splitter.setSizes(sizes)
        app.processEvents()

        assert splitter.width() == available
        rightmost = splitter.handle(splitter.count() - 1)
        assert rightmost.collapsed_indices()
        assert rightmost.x() + rightmost.width() <= available
        assert all(
            splitter.handle(index).x() + splitter.handle(index).width()
            <= available
            for index in range(1, splitter.count())
        )
        assert splitter.sizes()[3] == 0
        assert splitter.handle(3).collapsed_titles() == ["중앙부처 질의회신"]
        assert splitter.handle(3).width() >= splitter.handle(3).STRIP_WIDTH
        assert splitter.handle(4).width() >= splitter.handle(4).STRIP_WIDTH
        assert splitter.handle(5).width() >= splitter.handle(5).STRIP_WIDTH
    finally:
        tab.close()


def test_unchecking_collapsed_column_resets_thick_handle(
    tmp_path,
) -> None:
    """접힌 칸을 체크 해제한 뒤 손잡이가 24px로 남지 않는다."""
    app = QApplication.instance() or QApplication([])
    settings = QSettings(
        str(tmp_path / "thick.ini"), QSettings.Format.IniFormat
    )
    tab = ViewedLawsTab(
        LawDocumentCache(tmp_path / "saved-thick"),
        favorites_only=True,
        settings=settings,
    )
    try:
        tab.resize(1400, 600)
        tab.show()
        app.processEvents()
        splitter = tab.favorite_splitter
        assert splitter is not None

        sizes = splitter.sizes()
        sizes[0] += sizes[3]
        sizes[3] = 0
        splitter.setSizes(sizes)
        app.processEvents()
        handle = splitter.handle(3)
        assert handle.width() >= handle.STRIP_WIDTH

        tab.favorite_category_checks["central"].setChecked(False)
        app.processEvents()
        assert handle.collapsed_indices() == ()
        assert handle.width() <= splitter.handleWidth() + 1

        tab.favorite_category_checks["central"].setChecked(True)
        app.processEvents()
        # 다시 켜면 폭을 되받아 일반 칸으로 서고, 손잡이도 얇다.
        assert splitter.sizes()[3] > 0
        assert splitter.handle(3).collapsed_indices() == ()
        assert splitter.handle(3).width() <= splitter.handleWidth() + 1
    finally:
        tab.close()


def test_dragging_favorite_columns_defers_width_save(tmp_path) -> None:
    """끄는 동안에는 설정 파일에 쓰지 않고 멈춘 뒤 한 번 쓴다."""
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "drag.ini"), QSettings.Format.IniFormat)
    tab = ViewedLawsTab(
        LawDocumentCache(tmp_path / "saved-drag"),
        favorites_only=True,
        settings=settings,
    )
    try:
        tab.resize(1400, 600)
        tab.show()
        app.processEvents()
        splitter = tab.favorite_splitter
        assert splitter is not None
        start = splitter.handle(2).x()
        for offset in range(20):
            splitter.moveSplitter(start + offset, 2)
        app.processEvents()
        assert settings.value("favorite_card_widths") is None

        tab.flush_favorite_widths()
        saved = [int(value) for value in settings.value("favorite_card_widths")]
        assert saved == splitter.sizes()
    finally:
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
