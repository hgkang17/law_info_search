import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QByteArray, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from ui.dialogs import DetachedDocumentWindow


def test_detached_window_uses_native_frame_and_controls():
    app = QApplication.instance() or QApplication([])
    window = DetachedDocumentWindow("본문", "<p>제1조 본문</p>")
    window.show()
    app.processEvents()
    try:
        flags = window.windowFlags()
        assert not flags & Qt.WindowType.FramelessWindowHint
        assert flags & Qt.WindowType.WindowMinMaxButtonsHint
        assert flags & Qt.WindowType.WindowCloseButtonHint
        controls = [b for b in window.header.findChildren(QPushButton)
                    if b.property("windowControl") == "true"]
        assert not controls
        assert not window.resize_handles
        window.toggle_maximized()
        app.processEvents()
        assert window.isMaximized()
        window.toggle_maximized()
        app.processEvents()
        assert not window.isMaximized()
    finally:
        window.close()
        app.processEvents()


def test_native_title_drag_returns_whole_window_but_resize_does_not(monkeypatch):
    import sys
    import pytest
    if sys.platform != "win32":
        pytest.skip("Windows native title bar")
    import ctypes
    from ctypes import wintypes
    app = QApplication.instance() or QApplication([])
    window = DetachedDocumentWindow("native", "<p>body</p>")
    calls = []
    monkeypatch.setattr(window, "probe_reattach", lambda point: True)
    monkeypatch.setattr(window, "drop_reattach", lambda point, all_pages=False: calls.append(all_pages))
    message = wintypes.MSG()
    try:
        for code in (0x0214, 0x0232):
            message.message = code
            window.nativeEvent(QByteArray(b"windows_generic_MSG"), ctypes.addressof(message))
        app.processEvents()
        assert calls == []
        for code in (0x0216, 0x0232):
            message.message = code
            window.nativeEvent(QByteArray(b"windows_generic_MSG"), ctypes.addressof(message))
        app.processEvents()
        assert calls == [True]
    finally:
        window.close()
        app.processEvents()
