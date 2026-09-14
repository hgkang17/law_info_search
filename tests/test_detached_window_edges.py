import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton

from ui.dialogs import DetachedDocumentWindow


def test_detached_window_uses_one_tab_row_with_matching_window_controls():
    app = QApplication.instance() or QApplication([])
    window = DetachedDocumentWindow("본문", "<p>제1조 본문</p>")
    window.show()
    app.processEvents()
    try:
        flags = window.windowFlags()
        assert flags & Qt.WindowType.FramelessWindowHint
        controls = [b for b in window.header.findChildren(QPushButton)
                    if b.property("windowControl") == "true"]
        assert [b.accessibleName() for b in controls] == ["최소화", "최대화 / 복원", "닫기"]
        assert len({(b.width(), b.height()) for b in controls}) == 1
        assert len(window.resize_handles) == 8
        controls[1].click()
        app.processEvents()
        assert window.isMaximized()
        assert all(not handle.isVisible() for handle in window.resize_handles)
        controls[1].click()
        app.processEvents()
        assert not window.isMaximized()
        assert all(handle.isVisible() for handle in window.resize_handles)
    finally:
        window.close()
        app.processEvents()
