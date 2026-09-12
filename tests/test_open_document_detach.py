"""상단 열린 본문 띠에서 탭을 끌어내 별도 창으로 꺼내는지 검증."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

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

        window._reattach_detached_window(detached)
        qt_app.processEvents()

        assert resource.document_tabs.count() == 1
        assert str(resource.document_tabs.tabData(0)) == key
        assert resource._active_document_key == key
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
        assert detached.reattach_button.isVisibleTo(detached)
        detached.close()
        qt_app.processEvents()
    finally:
        window.close()
        qt_app.processEvents()


def test_detached_window_opens_from_the_preview_rect(qt_app) -> None:
    window = LawSearchWindow()
    try:
        token = _fill_expc_document(window)
        start = QRect(400, 300, 240, 160)
        window.open_document_tabs.detach_preview_rect = start
        window.open_document_tabs.detachRequested.emit(token, QPoint(500, 380))
        qt_app.processEvents()

        detached = window._detached_document_windows[0]
        # 끌던 그림 자리에서 시작해 제 크기로 펼쳐진다.
        assert detached._geometry_animation is not None
        assert detached._geometry_animation.startValue() == start
        assert detached._geometry_animation.endValue().width() == 980
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


def test_the_button_on_the_window_also_puts_it_back(qt_app) -> None:
    window = LawSearchWindow()
    try:
        token = _fill_expc_document(window)
        window.open_document_tabs.detachRequested.emit(token, QPoint(300, 300))
        qt_app.processEvents()
        detached = window._detached_document_windows[0]

        detached.reattach_button.click()
        qt_app.processEvents()

        window._refresh_open_documents()
        assert window._open_document_index_for_token(token) >= 0
        # 한 번 되돌린 창은 다시 되돌리지 않는다.
        assert detached.reattach_handler is None
    finally:
        window.close()
        qt_app.processEvents()
