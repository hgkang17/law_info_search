import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ui.widgets import CornerCloseTabBar
from ui.dialogs import DetachedDocumentWindow
from ui.main_window import LawSearchWindow


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_shift_select_drag_emits_ordered_group(app):
    bar = CornerCloseTabBar()
    for name in ("a", "b", "c"):
        i = bar.addTab(name * 10)
        bar.setTabData(i, name)
    bar.show()
    app.processEvents()
    groups = []
    bar.detachGroupRequested.connect(lambda keys, point: groups.append(keys))
    QTest.mouseClick(bar, Qt.LeftButton, pos=bar.tabRect(0).center())
    QTest.mouseClick(bar, Qt.LeftButton, Qt.ShiftModifier, bar.tabRect(2).center())
    assert bar._selected_tab_data == ["a", "b", "c"]
    QTest.mousePress(bar, Qt.LeftButton, pos=bar.tabRect(1).center())
    QTest.mouseRelease(bar, Qt.LeftButton, pos=QPoint(20, bar.height() + 80))
    assert groups == [["a", "b", "c"]]
    bar.close()


def test_group_detach_and_restore_all_sources(app):
    main = LawSearchWindow()
    main.show()
    app.processEvents()
    try:
        for name in ("expc", "central"):
            reader = getattr(main, name + "_tab")
            reader._active_detail_row = {"id": "123", "name": name}
            reader.current_detail_text = name
            reader.detail_view.setHtml("<p>" + name + "</p>")
        main._refresh_open_documents()
        main.open_document_tabs.detachGroupRequested.emit(["expc:123", "central:123"], QPoint(-1500, -1500))
        app.processEvents()
        windows = [w for w in main._detached_document_windows if w.isVisible()]
        assert len(windows) == 1
        detached = windows[0]
        assert [p.reattach_payload["source"] for p in detached.ordered_pages()] == ["expc", "central"]
        assert "reattach_all_button" not in detached.__dict__
        point = main._open_documents_drop_rect().center()
        assert main._can_reattach_at(point)
        detached.drop_reattach(point, all_pages=True)
        assert main.expc_tab.current_detail_text == "expc"
        assert main.central_tab.current_detail_text == "central"
        assert not detached._pages
    finally:
        for w in list(DetachedDocumentWindow._windows):
            w.close()
        main.close()
        app.processEvents()


def test_whole_window_drop_preserves_all_pages_and_order(app):
    source = DetachedDocumentWindow("a", "<p>a</p>")
    second = DetachedDocumentWindow("b", "<p>b</p>")
    target = DetachedDocumentWindow("c", "<p>c</p>")
    source.add_page(second._take_page(second.current_page()))
    source.show()
    target.move(1100, 100)
    target.show()
    app.processEvents()
    try:
        point = target.document_tabs.mapToGlobal(target.document_tabs.tabRect(0).topLeft() + QPoint(1, 10))
        source.drop_reattach(point, all_pages=True)
        assert [p.windowTitle() for p in target.ordered_pages()] == ["a", "b", "c"]
        assert not source._pages
    finally:
        source.close()
        target.close()
        app.processEvents()


def test_split_selected_pages_keeps_remaining_page(app):
    source = DetachedDocumentWindow("a", "a")
    for name in ("b", "c"):
        extra = DetachedDocumentWindow(name, name)
        source.add_page(extra._take_page(extra.current_page()))
    source.show()
    app.processEvents()
    moved = source.split_pages(source.ordered_pages()[:2], QPoint(1300, 200))
    try:
        assert [p.windowTitle() for p in moved.ordered_pages()] == ["a", "b"]
        assert [p.windowTitle() for p in source.ordered_pages()] == ["c"]
    finally:
        source.close()
        moved.close()
        app.processEvents()
