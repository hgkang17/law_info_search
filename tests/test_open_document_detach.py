"""상단 열린 본문 띠에서 탭을 끌어내 별도 창으로 꺼내는지 검증."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
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
