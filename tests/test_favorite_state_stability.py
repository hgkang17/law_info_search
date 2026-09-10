"""본문 저장 알림과 프로젝트 이동 뒤에도 사용자가 정한 배치를 유지한다."""

from PySide6.QtCore import QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from ui.tabs.viewed_laws import ViewedLawsTab


def _tab(tmp_path):
    QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    cache = LawDocumentCache(tmp_path / "saved")
    return ViewedLawsTab(cache, favorites_only=True, settings=settings)


def _favorite(tab, name, item_id):
    row = {"target": "law", "id": item_id, "name": name}
    tab.law_cache.save(row, {"법령": {"기본정보": {"법령명_한글": name}}})
    tab.law_cache.set_favorite(row, True)
    return row


def _names(tree):
    return [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]


def test_project_wheel_does_not_change_favorite_destination(tmp_path):
    tab = _tab(tmp_path)
    tab._create_favorite_project()
    selected = tab.active_favorite_project
    wheel = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(), QPoint(0, 120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(tab.project_tabs, wheel)
    assert tab.active_favorite_project == selected
    assert tab.law_cache.active_favorite_project == selected
    tab.close()


def test_history_view_does_not_reset_shared_project(tmp_path):
    tab = _tab(tmp_path)
    tab._create_favorite_project()
    selected = tab.active_favorite_project
    history = ViewedLawsTab(tab.law_cache)
    assert tab.law_cache.active_favorite_project == selected
    history.close()
    tab.close()


def test_mixed_folder_and_document_order_survives_refresh_and_reload(tmp_path, monkeypatch):
    tab = _tab(tmp_path)
    _favorite(tab, "법령 A", "A")
    monkeypatch.setattr("ui.tabs.viewed_laws.QInputDialog.getText", lambda *a, **k: ("폴더", True))
    tab._create_favorite_folder("law")
    tree = tab.favorite_trees["law"]
    # 재구성 과정에서 폴더를 앞에 모으지 않아야 한다.
    folder_index = next(i for i in range(tree.topLevelItemCount()) if tree.topLevelItem(i).text(0) == "폴더")
    folder = tree.takeTopLevelItem(folder_index)
    tree.addTopLevelItem(folder)
    tab._persist_favorite_tree("저장")
    tab.law_cache.changed.emit()
    assert _names(tree) == ["법령 A", "폴더"]
    reopened = ViewedLawsTab(tab.law_cache, favorites_only=True, settings=tab.settings)
    assert _names(reopened.favorite_trees["law"]) == ["법령 A", "폴더"]
    reopened.close()
    tab.close()


def test_articles_from_different_laws_keep_user_order(tmp_path):
    tab = _tab(tmp_path)
    for item_id in ("A", "B"):
        row = _favorite(tab, "법령 " + item_id, item_id)
        tab.law_cache.set_article_favorite(row, "000100", "제1조", True)
    tree = tab.favorite_trees["article"]
    initial = _names(tree)
    tree.insertTopLevelItem(0, tree.takeTopLevelItem(1))
    expected = list(reversed(initial))
    tab._persist_favorite_tree("저장")
    tab.law_cache.changed.emit()
    assert _names(tree) == expected
    tab.close()


def test_body_save_before_drag_timer_keeps_pending_order(tmp_path):
    tab = _tab(tmp_path)
    _favorite(tab, "법령 A", "A")
    _favorite(tab, "법령 B", "B")
    tree = tab.favorite_trees["law"]
    initial = _names(tree)
    tree.insertTopLevelItem(0, tree.takeTopLevelItem(1))
    tab._schedule_favorite_tree_persist()
    tab.law_cache.changed.emit()
    assert _names(tree) == list(reversed(initial))
    QApplication.processEvents()
    tab.refresh()
    assert _names(tree) == list(reversed(initial))
    tab.close()
