from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget

from molit_cgm_expc_qt import DeferredWrapTextBrowser, MemoMarkerBar


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_memo_marker_bar_keeps_its_width_before_first_memo() -> None:
    app = _application()
    host = QWidget()
    layout = QHBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    browser = DeferredWrapTextBrowser()
    marker = MemoMarkerBar(browser)
    layout.addWidget(browser, 1)
    layout.addWidget(marker)
    host.resize(700, 400)
    host.show()
    app.processEvents()

    width_without_memo = browser.viewport().width()
    assert marker.isVisible()
    assert marker.width() == MemoMarkerBar.NORMAL_WIDTH

    marker.set_memos(
        [{"start": 0, "end": 1, "excerpt": "본문", "text": "메모"}]
    )
    app.processEvents()

    assert marker.isVisible()
    assert browser.viewport().width() == width_without_memo
    host.close()


def test_internal_layout_resize_does_not_enable_deferred_wrapping() -> None:
    app = _application()
    host = QWidget()
    browser = DeferredWrapTextBrowser(host)
    host.resize(800, 500)
    browser.setGeometry(0, 0, 760, 460)
    browser.setPlainText("긴 본문 " * 1000)
    host.show()
    browser.show()
    app.processEvents()
    browser._last_top_level_size = host.size()

    browser.resize(620, 460)
    app.processEvents()

    assert not browser._wrap_deferred
    assert browser.lineWrapMode() == browser.LineWrapMode.WidgetWidth
    assert browser.horizontalScrollBar().maximum() == 0
    host.close()


def test_top_level_resize_defers_wrap_without_showing_horizontal_bar() -> None:
    app = _application()
    host = QWidget()
    layout = QHBoxLayout(host)
    browser = DeferredWrapTextBrowser()
    layout.addWidget(browser)
    browser.setPlainText("긴 본문 " * 1000)
    host.resize(800, 500)
    host.show()
    app.processEvents()
    browser._last_top_level_size = host.size()

    host.resize(720, 500)
    app.processEvents()

    assert browser._wrap_deferred
    assert (
        browser.horizontalScrollBarPolicy()
        == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    browser._finish_deferred_wrap()
    assert browser.lineWrapMode() == browser.LineWrapMode.WidgetWidth
    assert (
        browser.horizontalScrollBarPolicy()
        == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    )
    host.close()
