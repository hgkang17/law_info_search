"""다운로드 목록의 삭제 단추와 지운 파일 표시 회귀 시험."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QEnterEvent
from PySide6.QtWidgets import QApplication, QWidgetAction

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab
from ui.widgets import DownloadTrayButton


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _tab(tmp_path) -> ResourceSearchTab:
    settings = QSettings(str(tmp_path / "dl.ini"), QSettings.Format.IniFormat)
    return ResourceSearchTab(
        lambda: "",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )


def _row_widgets(menu) -> list:
    """팝업에서 파일 줄 위젯만 모은다(머리글 줄은 뺀다)."""
    return [
        action.defaultWidget()
        for action in menu.actions()
        if isinstance(action, QWidgetAction)
        and action.defaultWidget() is not None
        and action.defaultWidget().objectName() == "downloadFileRow"
    ]


def _rows(menu) -> list[tuple[str, bool, bool]]:
    """팝업의 파일 줄을 (이름, 취소선, 지울 수 있음)으로 모은다."""
    return [
        (row.label.text(), row.label.font().strikeOut(), row._deletable)
        for row in _row_widgets(menu)
    ]


def _hover(row, x_ratio: float) -> None:
    """줄의 가로 어느 지점에 커서를 올린 것처럼 만든다."""
    point = QPointF(row.width() * x_ratio, row.height() / 2)
    row.enterEvent(
        QEnterEvent(point, point, row.mapToGlobal(point.toPoint()))
    )


def test_each_row_has_a_delete_button(qt_app, tmp_path) -> None:
    tab = _tab(tmp_path)
    tray = DownloadTrayButton()
    tray.show()
    try:
        tab.set_download_list_button(tray)
        first = tmp_path / "별표 1.hwp"
        second = tmp_path / "조례.hwp"
        for path in (first, second):
            path.write_bytes(b"hwp")
            tab._register_completed_download(str(path))
        tab._show_download_popup()
        qt_app.processEvents()

        rows = _rows(tab._download_menu)
        assert [name for name, _struck, _live in rows] == ["조례.hwp", "별표 1.hwp"]
        # 아직 아무것도 지우지 않았으니 줄도 없고 지울 수도 있다.
        assert all(not struck and live for _name, struck, live in rows)

        # 휴지통은 늘 떠 있지 않다. 커서를 줄 어디에 올리든 줄 음영과
        # 함께 드러난다. 평소에는 음영도 없다.
        row = _row_widgets(tab._download_menu)[0]
        assert row.delete_button.icon().isNull()
        assert not row._hovered
        assert "background:transparent" in row.label.styleSheet()
        _hover(row, 0.3)
        assert row._hovered
        assert not row.delete_button.icon().isNull()
        assert row.delete_button.isEnabled()
        # 휴지통은 제 바탕을 따로 그리지 않는다(줄 음영 하나로 감싼다).
        assert ":hover" not in row.delete_button.styleSheet()
        # 자리는 늘 비워 두므로 그림이 들고 나도 단추 크기는 그대로다.
        assert row.delete_button.width() == row.BUTTON_SIZE
        assert row.delete_button.height() == row.BUTTON_SIZE
        assert row.delete_button.iconSize().width() == 17
        assert (
            row.layout().itemAt(1).alignment() & Qt.AlignmentFlag.AlignVCenter
        )
        row.leaveEvent(None)
        assert row.delete_button.icon().isNull()
        assert not row._hovered
        tab._download_menu.close()
    finally:
        tab.close()
        tray.deleteLater()


def test_deleting_strikes_the_name_through_and_keeps_the_row(
    qt_app, tmp_path
) -> None:
    """브라우저처럼 줄은 남기고 글자 가운데에 줄을 긋는다."""
    tab = _tab(tmp_path)
    tray = DownloadTrayButton()
    tray.show()
    try:
        tab.set_download_list_button(tray)
        target = tmp_path / "지울 별표.hwp"
        keep = tmp_path / "남길 조례.hwp"
        for path in (keep, target):
            path.write_bytes(b"hwp")
            tab._register_completed_download(str(path))
        tab._show_download_popup()
        qt_app.processEvents()

        tab._delete_downloaded_file(target)
        qt_app.processEvents()
        # 파일은 실제로 사라진다(윈도우에서는 휴지통으로 간다).
        assert not target.exists()
        assert keep.exists()

        rows = dict(
            (name, (struck, live)) for name, struck, live in _rows(tab._download_menu)
        )
        # 지운 줄은 목록에 남되 줄이 그어지고 휴지통은 더 이상 나오지 않는다.
        assert rows["지울 별표.hwp"] == (True, False)
        assert rows["남길 조례.hwp"] == (False, True)
        gone_row = next(
            row
            for row in _row_widgets(tab._download_menu)
            if row.label.text() == "지울 별표.hwp"
        )
        _hover(gone_row, 0.95)
        assert gone_row.delete_button.icon().isNull()
        tab._download_menu.close()
    finally:
        tab.close()
        tray.deleteLater()


def test_a_file_removed_outside_the_program_is_shown_struck_through(
    qt_app, tmp_path
) -> None:
    """탐색기에서 지운 파일도 지운 것으로 읽는다."""
    tab = _tab(tmp_path)
    try:
        path = tmp_path / "밖에서 지운.hwp"
        path.write_bytes(b"hwp")
        tab._register_completed_download(str(path))
        assert tab._download_is_gone(path) is False
        path.unlink()
        assert tab._download_is_gone(path) is True
    finally:
        tab.close()


def test_downloading_the_same_file_again_clears_the_struck_state(
    qt_app, tmp_path
) -> None:
    """지운 뒤 다시 받으면 줄이 사라진다."""
    tab = _tab(tmp_path)
    try:
        path = tmp_path / "다시 받을.hwp"
        path.write_bytes(b"hwp")
        tab._register_completed_download(str(path))
        tab._delete_downloaded_file(path)
        assert tab._download_is_gone(path) is True

        path.write_bytes(b"hwp")
        tab._register_completed_download(str(path))
        assert tab._download_is_gone(path) is False
        assert [item.name for item in tab._completed_downloads] == [path.name]
    finally:
        tab.close()
