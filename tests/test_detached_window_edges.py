import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from ui.dialogs import DetachedDocumentWindow


def test_all_edges_resize_and_controls_align_at_top():
    app = QApplication.instance() or QApplication([])
    window = DetachedDocumentWindow("본문", "<p>제1조 본문</p>")
    window.show()
    app.processEvents()
    try:
        for index, delta in ((0, QPoint(-20, 0)), (1, QPoint(20, 0)),
                             (2, QPoint(0, -20)), (3, QPoint(0, 20))):
            handle = window.resize_handles[index]
            assert handle.isVisible()
            before = window.size()
            start = handle.rect().center()
            QTest.mousePress(handle, Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseMove(handle, start + delta)
            QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=start + delta)
            assert window.width() > before.width() if index < 2 else window.height() > before.height()
        controls = [b for b in window.header.findChildren(QPushButton)
                    if b.property("windowControl") == "true"]
        assert len(controls) == 3
        assert all(b.y() == 0 and not b.icon().isNull() for b in controls)
        window.toggle_maximized()
        app.processEvents()
        assert all(not h.isVisible() for h in window.resize_handles)
        window.toggle_maximized()
        app.processEvents()
        assert all(h.isVisible() for h in window.resize_handles)
    finally:
        window.close()
        app.processEvents()
