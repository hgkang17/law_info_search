"""상단 열린 본문 띠에서 탭을 끌어내 별도 창으로 꺼내는지 검증."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget

from ui.dialogs import DetachedDocumentWindow
from ui.main_window import LawSearchWindow


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _fill_expc_document(window: LawSearchWindow) -> str:
    """법령해석례 화면에 본문 하나를 띄워 띠에 올린다."""
    tab = window.expc_tab
    tab._active_detail_row = {"id": "310123", "name": "법령해석례 사례"}
    tab.current_detail_text = "질의요지와 회답 본문이다."
    tab.detail_view.setHtml("<p>질의요지와 회답 본문이다.</p>")
    window._refresh_open_documents()
    return "expc:310123"


def test_dragging_the_strip_tab_out_detaches_that_document(qt_app) -> None:
    window = LawSearchWindow()
    try:
        token = _fill_expc_document(window)
        assert window._open_document_index_for_token(token) >= 0

        # 띠 탭바가 알리는 신호 그대로 부른다. 연결까지 함께 확인한다.
        window.open_document_tabs.detachRequested.emit(token, QPoint(300, 300))
        qt_app.processEvents()

        assert len(window._detached_document_windows) == 1
        detached = window._detached_document_windows[0]
        assert isinstance(detached, DetachedDocumentWindow)
        assert window.styleSheet() in detached.styleSheet()
        assert detached.browser.verticalScrollBar().sizeHint().width() == 12
        assert not detached.toc_panel.isVisible()
        assert "질의요지와 회답 본문이다." in detached.browser.toPlainText()
        assert "법령해석례 사례" in detached.windowTitle()

        # 꺼낸 본문은 원래 화면에서 닫혀 띠에서도 사라진다.
        assert window.expc_tab._active_detail_row is None
        assert window.expc_tab.current_detail_text == ""
        window._refresh_open_documents()
        assert window._open_document_index_for_token(token) < 0

        detached.close()
        qt_app.processEvents()
        assert window._detached_document_windows == []
    finally:
        window.close()
        qt_app.processEvents()


def test_law_document_detach_is_left_to_the_body_screen(qt_app) -> None:
    """법령 본문은 상태를 쥔 본문 화면이 꺼낸다."""
    window = LawSearchWindow()
    try:
        resource = window.resource_tab
        key = "law:009294"
        row = {
            "target": "law",
            "id": "009294",
            "name": "국토의 계획 및 이용에 관한 법률",
            "short_name": "국토계획법",
        }
        state = resource._empty_document_state()
        state.update({"row": row, "plain_text": "제1조 목적 본문"})
        resource._document_states[key] = state
        resource._active_document_key = key
        resource.current_detail_text = "제1조 목적 본문"
        resource.detail_view.setPlainText(resource.current_detail_text)
        index = resource.document_tabs.addTab("국토계획법")
        resource.document_tabs.setTabData(index, key)
        resource.document_tabs.setCurrentIndex(index)
        window._refresh_open_documents()

        calls: list[tuple[str, object]] = []
        resource._detach_document_tab = lambda k, pos: calls.append((k, pos))

        window.open_document_tabs.detachRequested.emit(
            f"resource:{key}", QPoint(120, 400)
        )

        assert calls == [(key, QPoint(120, 400))]
        # 띠가 따로 창을 만들지는 않는다.
        assert window._detached_document_windows == []
    finally:
        window.close()
        qt_app.processEvents()


def test_unknown_strip_token_is_ignored(qt_app) -> None:
    window = LawSearchWindow()
    try:
        window._detach_open_document_tab("", QPoint(0, 0))
        window._detach_open_document_tab("expc:없는본문", QPoint(0, 0))
        assert window._detached_document_windows == []
    finally:
        window.close()
        qt_app.processEvents()


def _mouse_event(bar, kind, spot: QPoint, buttons) -> QMouseEvent:
    return QMouseEvent(
        kind,
        QPointF(spot),
        QPointF(bar.mapToGlobal(spot)),
        Qt.MouseButton.LeftButton,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def _press_and_release(bar, start: QPoint, end: QPoint) -> None:
    """탭을 눌러 끌었다 놓는 몸짓을 그대로 흉내 낸다."""
    bar.mousePressEvent(
        _mouse_event(
            bar,
            QEvent.Type.MouseButtonPress,
            start,
            Qt.MouseButton.LeftButton,
        )
    )
    bar.mouseReleaseEvent(
        _mouse_event(
            bar,
            QEvent.Type.MouseButtonRelease,
            end,
            Qt.MouseButton.NoButton,
        )
    )


def test_dropping_below_the_strip_detaches_but_sideways_does_not(qt_app) -> None:
    window = LawSearchWindow()
    try:
        token = _fill_expc_document(window)
        bar = window.open_document_tabs
        spot = bar.tabRect(window._open_document_index_for_token(token)).center()

        # 좌우로 끄는 것은 순서 바꾸기다. 꺼내지 않는다.
        _press_and_release(bar, spot, QPoint(spot.x() + 200, spot.y()))
        qt_app.processEvents()
        assert window._detached_document_windows == []

        # 띠 아래로 충분히 내려놓으면 별도 창으로 나온다.
        _press_and_release(
            bar, spot, QPoint(spot.x(), bar.height() + bar.DETACH_MARGIN + 10)
        )
        qt_app.processEvents()
        assert len(window._detached_document_windows) == 1
        window._detached_document_windows[0].close()
        qt_app.processEvents()
    finally:
        window.close()
        qt_app.processEvents()


def test_detached_window_can_be_put_back_on_the_strip(qt_app) -> None:
    window = LawSearchWindow()
    try:
        token = _fill_expc_document(window)
        window.open_document_tabs.detachRequested.emit(token, QPoint(300, 300))
        qt_app.processEvents()
        detached = window._detached_document_windows[0]
        assert window._open_document_index_for_token(token) < 0

        # 제목 줄을 띠 위에 놓은 것과 같은 길로 되돌린다.
        window._reattach_detached_window(detached)
        qt_app.processEvents()

        assert window.expc_tab._active_detail_row["id"] == "310123"
        assert "질의요지와 회답 본문이다." in window.expc_tab.detail_view.toPlainText()
        window._refresh_open_documents()
        assert window._open_document_index_for_token(token) >= 0
    finally:
        window.close()
        qt_app.processEvents()


def test_law_body_goes_back_into_its_document_tab(qt_app) -> None:
    window = LawSearchWindow()
    try:
        resource = window.resource_tab
        key = "law:009294"
        row = {
            "target": "law",
            "label": "법령",
            "id": "009294",
            "name": "국토의 계획 및 이용에 관한 법률",
            "short_name": "국토계획법",
        }
        state = resource._empty_document_state()
        state.update(
            {
                "row": row,
                "plain_text": "제1조(목적) 본문이다.",
                "html": "<p>제1조(목적) 본문이다.</p>",
            }
        )
        resource._document_states[key] = state
        resource._active_document_key = key
        resource.current_detail_text = "제1조(목적) 본문이다."
        # 활성 본문은 화면에도 그려져 있다. 꺼낼 때 지금 그려 둔 문서를
        # 저장해 들고 가므로, 비워 두면 빈 창이 나온다.
        resource.detail_view.setHtml("<p>제1조(목적) 본문이다.</p>")
        index = resource.document_tabs.addTab("국토계획법")
        resource.document_tabs.setTabData(index, key)
        resource.document_tabs.setCurrentIndex(index)
        window._refresh_open_documents()

        window.open_document_tabs.detachRequested.emit(
            f"resource:{key}", QPoint(240, 320)
        )
        qt_app.processEvents()

        assert resource.document_tabs.count() == 0
        detached = window._detached_document_windows[0]
        assert detached.reattach_payload["source"] == "resource"
        original_document = detached.reattach_payload["state"]["document"]
        assert original_document is detached.browser.document()
        assert original_document is not resource.detail_view.document()
        assert "제1조(목적) 본문이다." in original_document.toPlainText()

        window._reattach_detached_window(detached)
        qt_app.processEvents()

        assert resource.document_tabs.count() == 1
        assert str(resource.document_tabs.tabData(0)) == key
        assert resource._active_document_key == key
        assert resource.detail_view.document() is original_document
        assert original_document.parent() is resource
        assert "제1조(목적) 본문이다." in resource.detail_view.toPlainText()
    finally:
        window.close()
        qt_app.processEvents()


def test_strip_is_the_drop_target_for_a_detached_window(qt_app) -> None:
    window = LawSearchWindow()
    window.show()
    qt_app.processEvents()
    try:
        bar = window.open_documents_widget
        inside = bar.mapToGlobal(QPoint(bar.width() // 2, bar.height() // 2))
        assert window._can_reattach_at(inside)
        assert bar.property("dropTarget") == "true"

        assert not window._can_reattach_at(QPoint(-5000, -5000))
        assert bar.property("dropTarget") == "false"
    finally:
        window.close()
        qt_app.processEvents()


def _move(bar, spot: QPoint) -> None:
    bar.mouseMoveEvent(
        _mouse_event(bar, QEvent.Type.MouseMove, spot, Qt.MouseButton.LeftButton)
    )


def test_a_window_preview_follows_the_cursor_while_dragging_out(qt_app) -> None:
    window = LawSearchWindow()
    window.show()
    qt_app.processEvents()
    try:
        token = _fill_expc_document(window)
        bar = window.open_document_tabs
        spot = bar.tabRect(window._open_document_index_for_token(token)).center()
        below = QPoint(spot.x(), bar.height() + bar.DETACH_MARGIN + 20)

        bar.mousePressEvent(
            _mouse_event(
                bar,
                QEvent.Type.MouseButtonPress,
                spot,
                Qt.MouseButton.LeftButton,
            )
        )
        # 띠 안에서 움직이는 동안은 순서 바꾸기라 아무것도 뜨지 않는다.
        _move(bar, QPoint(spot.x() + 30, spot.y()))
        assert bar._preview is None

        _move(bar, below)
        qt_app.processEvents()
        preview = bar._preview
        assert preview is not None
        first = preview.pos()
        _move(bar, QPoint(below.x() + 60, below.y() + 40))
        assert preview.pos() != first

        # 띠로 되돌아오면 미리보기도 사라진다.
        _move(bar, spot)
        assert bar._preview is None

        _move(bar, below)
        bar.mouseReleaseEvent(
            _mouse_event(
                bar,
                QEvent.Type.MouseButtonRelease,
                below,
                Qt.MouseButton.NoButton,
            )
        )
        qt_app.processEvents()
        # 놓은 자리는 창이 펼쳐질 시작 자리로 남는다.
        assert bar.detach_preview_rect.isValid()
        assert bar._preview is None
        assert len(window._detached_document_windows) == 1
        detached = window._detached_document_windows[0]
        assert not hasattr(detached, "reattach_button")
        assert not detached.windowFlags() & Qt.WindowType.FramelessWindowHint
        detached.close()
        qt_app.processEvents()
    finally:
        window.close()
        qt_app.processEvents()


def test_detached_window_opens_from_the_preview_rect(qt_app) -> None:
    window = LawSearchWindow()
    try:
        token = _fill_expc_document(window)
        start = QRect(400, 300, 980, 720)
        window.open_document_tabs.detach_preview_rect = start
        window.open_document_tabs.detachRequested.emit(token, QPoint(500, 380))
        qt_app.processEvents()

        detached = window._detached_document_windows[0]
        # 축소 카드가 부풀어 오르지 않고 끌던 창의 자리를 그대로 쓴다.
        assert detached._geometry_animation is None
        assert detached.geometry() == start
        detached.close()
        qt_app.processEvents()
    finally:
        window.close()
        qt_app.processEvents()


def test_preview_carries_a_picture_of_the_document(qt_app) -> None:
    window = LawSearchWindow()
    try:
        token = _fill_expc_document(window)
        title, snapshot = window._open_document_preview(token)
        assert "법령해석례 사례" in title
        # 보고 있지 않은 화면의 본문이어도 그림이 나온다.
        assert snapshot is not None and not snapshot.isNull()
    finally:
        window.close()
        qt_app.processEvents()


def test_dragging_the_window_tab_puts_it_back_without_a_button(qt_app) -> None:
    window = LawSearchWindow()
    window.show()
    qt_app.processEvents()
    try:
        token = _fill_expc_document(window)
        window.open_document_tabs.detachRequested.emit(token, QPoint(300, 300))
        qt_app.processEvents()
        detached = window._detached_document_windows[0]

        header = detached.header
        start = QPoint(40, 20)
        target = header.mapFromGlobal(window._open_documents_drop_rect().center())
        header.mousePressEvent(_mouse_event(
            header, QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton,
        ))
        _move(header, target)
        target = header.mapFromGlobal(window._open_documents_drop_rect().center())
        header.mouseReleaseEvent(_mouse_event(
            header, QEvent.Type.MouseButtonRelease, target, Qt.MouseButton.NoButton,
        ))
        qt_app.processEvents()

        window._refresh_open_documents()
        assert window._open_document_index_for_token(token) >= 0
        # 한 번 되돌린 창은 다시 되돌리지 않는다.
        assert detached.reattach_handler is None
    finally:
        window.close()
        qt_app.processEvents()


def test_detached_tab_click_does_not_reattach_and_double_click_maximizes(qt_app):
    detached = DetachedDocumentWindow("본문", "<p>내용</p>", None, qt_app.font())
    calls = []
    detached.enable_reattach({}, lambda point: True, lambda window: calls.append(window))
    detached.show()
    qt_app.processEvents()
    try:
        header = detached.header
        spot = QPoint(40, 20)
        header.mousePressEvent(_mouse_event(
            header, QEvent.Type.MouseButtonPress, spot, Qt.MouseButton.LeftButton,
        ))
        header.mouseReleaseEvent(_mouse_event(
            header, QEvent.Type.MouseButtonRelease, spot, Qt.MouseButton.NoButton,
        ))
        assert calls == []
        header.mouseDoubleClickEvent(_mouse_event(
            header, QEvent.Type.MouseButtonDblClick, spot, Qt.MouseButton.LeftButton,
        ))
        assert detached.isMaximized()
        detached.toggle_maximized()
        assert not detached.isMaximized()
        assert not detached.size_grip.isVisible()  # Windows 기본 창 테두리로 조절한다.
    finally:
        detached.close()
        qt_app.processEvents()


def test_reattached_document_is_inserted_at_the_drop_position(qt_app):
    window = LawSearchWindow()
    window.show()
    qt_app.processEvents()
    try:
        token = _fill_expc_document(window)
        window._detach_open_document_tab(token, QPoint(300, 300))
        qt_app.processEvents()
        detached = window._detached_document_windows[0]
        tab = window.prec_tab
        tab._active_detail_row = {"id": "123", "name": "판례 사례"}
        tab.current_detail_text = "판례 본문"
        tab.detail_view.setHtml("<p>판례 본문</p>")
        window._refresh_open_documents()
        qt_app.processEvents()
        bar = window.open_document_tabs
        position = bar.mapToGlobal(bar.tabRect(0).topLeft() + QPoint(2, 10))
        detached.drop_reattach(position)
        qt_app.processEvents()
        assert str(bar.tabData(0)) == token
        assert bar.count() == 2
    finally:
        for detached in list(window._detached_document_windows):
            detached.close()
        window.close()
        qt_app.processEvents()


def test_detached_windows_merge_split_and_keep_reader_instances(qt_app):
    first = DetachedDocumentWindow("첫 본문", "<p>첫 본문</p>" * 300, None, qt_app.font())
    second = DetachedDocumentWindow("다른 본문", "<p>다른 본문</p>", None, qt_app.font())
    first.move(50, 50)
    second.move(1100, 200)
    first.show()
    second.show()
    qt_app.processEvents()
    try:
        page = second.current_page()
        document = page.browser.document()
        first.scroll_to(240)
        saved_scroll = first.scroll_position()
        first_page = first.current_page()
        second.drop_reattach(first.drop_rect().center())
        qt_app.processEvents()
        assert first.document_tabs.count() == 2
        assert first.current_page() is page
        assert first.browser.document() is document
        assert second not in DetachedDocumentWindow._windows
        first.document_tabs.setCurrentIndex(0)
        assert first.current_page() is first_page
        assert first.scroll_position() == saved_scroll
        assert first.document_tabs.objectName() == "openDocumentTabs"
        first.document_tabs.moveTab(1, 0)
        first.document_tabs.setCurrentIndex(0)
        assert first.current_page() is page
        first._detach_tab(page, QPoint(2200, 900))
        qt_app.processEvents()
        split = next(w for w in DetachedDocumentWindow._windows if w is not first and w.current_page() is page)
        assert first.document_tabs.count() == 1
        assert split.browser.document() is document
        split.close()
    finally:
        first.close()
        for other in tuple(DetachedDocumentWindow._windows):
            other.close()
        qt_app.processEvents()


def test_main_tab_can_join_a_detached_window_and_return_alone(qt_app):
    main = LawSearchWindow()
    main.show()
    qt_app.processEvents()
    try:
        token = _fill_expc_document(main)
        main._detach_open_document_tab(token, QPoint(700, 500))
        qt_app.processEvents()
        group = main._detached_document_windows[0]
        group.move(800, 600)
        tab = main.prec_tab
        tab._active_detail_row = {"id": "123", "name": "판례 사례"}
        tab.current_detail_text = "판례 본문"
        tab.detail_view.setHtml("<p>판례 본문</p>")
        main._refresh_open_documents()
        main._detach_open_document_tab("prec:123", group.drop_rect().center())
        qt_app.processEvents()
        assert group.document_tabs.count() == 2
        assert "판례 본문" in group.browser.toPlainText()
        group.drop_reattach(main._open_documents_drop_rect().center())
        qt_app.processEvents()
        assert group.document_tabs.count() == 1
        assert group.isVisible()
        assert "질의요지" in group.browser.toPlainText()
        assert main._open_document_index_for_token("prec:123") >= 0
    finally:
        for other in tuple(DetachedDocumentWindow._windows):
            other.close()
        main.close()
        qt_app.processEvents()


def test_drag_preview_is_cached_until_release_without_a_fade(qt_app):
    from ui.widgets import CornerCloseTabBar

    bar = CornerCloseTabBar()
    index = bar.addTab("본문")
    bar.setTabData(index, "document")
    calls = []

    def preview(data):
        calls.append(data)
        return "본문", None

    bar.preview_provider = preview
    bar._pressed_data = "document"
    try:
        bar._show_preview(QPoint(200, 200))
        assert bar._preview._fade is None
        bar._hide_preview()
        bar._show_preview(QPoint(250, 250))
        assert calls == ["document"]
    finally:
        bar._hide_preview()
        bar.close()


def test_single_detached_tab_moves_the_window_before_mouse_release(qt_app):
    window = DetachedDocumentWindow("본문", "<p>본문</p>", None, qt_app.font())
    window.move(200, 200)
    window.show()
    qt_app.processEvents()
    try:
        bar = window.document_tabs
        spot = bar.tabRect(0).center()
        start = window.pos()
        bar.mousePressEvent(_mouse_event(bar, QEvent.Type.MouseButtonPress, spot, Qt.MouseButton.LeftButton))
        _move(bar, spot + QPoint(120, 0))
        assert window.pos() == start + QPoint(120, 0)
        assert bar._preview is None
        bar.mouseReleaseEvent(_mouse_event(bar, QEvent.Type.MouseButtonRelease, spot, Qt.MouseButton.NoButton))
        assert window.isVisible()
        assert bar.count() == 1
    finally:
        window.close()
        qt_app.processEvents()


def test_dragging_one_of_many_tabs_out_creates_a_live_window_before_release(qt_app):
    window = DetachedDocumentWindow("첫 본문", "<p>첫 본문</p>", None, qt_app.font())
    other = DetachedDocumentWindow("둘째 본문", "<p>둘째 본문</p>", None, qt_app.font())
    page = other.current_page()
    window.add_page(other._take_page(page))
    window.move(200, 200)
    window.show()
    qt_app.processEvents()
    try:
        bar = window.document_tabs
        spot = bar.tabRect(1).center()
        bar.mousePressEvent(_mouse_event(bar, QEvent.Type.MouseButtonPress, spot, Qt.MouseButton.LeftButton))
        _move(bar, spot + QPoint(30, 0))
        assert bar.count() == 2
        assert bar._moving_window is None
        _move(bar, QPoint(spot.x(), bar.height() + 50))
        moving = bar._moving_window
        assert moving is not None and moving is not window
        assert moving.isVisible()
        assert moving.current_page() is page
        assert bar.count() == 1
        old = moving.pos()
        _move(bar, QPoint(spot.x() + 70, bar.height() + 90))
        assert moving.pos() == old + QPoint(70, 40)
        bar.mouseReleaseEvent(_mouse_event(
            bar, QEvent.Type.MouseButtonRelease,
            QPoint(spot.x() + 70, bar.height() + 90), Qt.MouseButton.NoButton,
        ))
        assert moving.isVisible()
        assert QWidget.mouseGrabber() is not bar
    finally:
        for detached in tuple(DetachedDocumentWindow._windows):
            detached.close()
        qt_app.processEvents()


def test_dragging_a_single_tab_onto_another_window_joins_on_release(qt_app):
    source = DetachedDocumentWindow("첫 본문", "<p>첫 본문</p>", None, qt_app.font())
    target = DetachedDocumentWindow("둘째 본문", "<p>둘째 본문</p>", None, qt_app.font())
    source.move(100, 100)
    target.move(600, 500)
    source.show()
    target.show()
    qt_app.processEvents()
    try:
        bar = source.document_tabs
        spot = bar.tabRect(0).center()
        page = source.current_page()
        QApplication.sendEvent(bar, _mouse_event(
            bar, QEvent.Type.MouseButtonPress, spot, Qt.MouseButton.LeftButton,
        ))
        destination = target.drop_rect().center()
        QApplication.sendEvent(bar, _mouse_event(
            bar, QEvent.Type.MouseMove, bar.mapFromGlobal(destination), Qt.MouseButton.LeftButton,
        ))
        assert target.header.property("dropReady") == "true"
        assert target.document_tabs.count() == 1
        QApplication.sendEvent(bar, _mouse_event(
            bar, QEvent.Type.MouseButtonRelease, bar.mapFromGlobal(destination), Qt.MouseButton.NoButton,
        ))
        qt_app.processEvents()
        assert target.document_tabs.count() == 2
        assert target.current_page() is page
        assert source not in DetachedDocumentWindow._windows
    finally:
        for detached in tuple(DetachedDocumentWindow._windows):
            detached.close()
        qt_app.processEvents()
