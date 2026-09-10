"""AI 패널 열기ㆍ닫기ㆍ연속 너비 조절은 같은 상단 글자를 유지한다."""

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QPoint, QSettings, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs import resource_search


class _Panel(QWidget):
    closeRequested = Signal()

    def __init__(self, _settings, parent=None):
        super().__init__(parent)
        self.input_edit = QLineEdit(self)


def test_ai_panel_toggle_and_drag_keep_the_top_visible_character(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(resource_search, 'AiChatPanel', _Panel)
    tab = resource_search.ResourceSearchTab(
        lambda: '',
        RecentSearchManager(QSettings(str(tmp_path / 'panel.ini'), QSettings.Format.IniFormat)),
        LawDocumentCache(tmp_path / 'saved'),
    )
    try:
        tab.resize(1400, 750)
        tab.show()
        tab._set_reading_mode(True)
        tab._hide_ai_chat()
        browser = tab.detail_view
        browser.setPlainText(''.join(f'{i}번째 법령 조문 안에서 읽고 있는 긴 본문입니다. ' for i in range(1200)))
        QTest.qWait(browser.WRAP_SETTLE_MS + 80)
        browser.verticalScrollBar().setValue(browser.verticalScrollBar().maximum() // 2)

        def assert_kept(action):
            for y in range(browser.viewport().height()):
                cursor = browser.cursorForPosition(QPoint(2, y))
                if browser.cursorRect(cursor).top() >= 0:
                    break
            before = browser.cursorRect(cursor).top()
            action()
            QTest.qWait(browser.WRAP_SETTLE_MS + 80)
            assert abs(browser.cursorRect(cursor).top() - before) <= 2

        assert_kept(tab._show_ai_chat)
        assert tab.ai_chat_panel.isVisible()

        def drag():
            total = sum(tab.main_splitter.sizes())
            for chat_width in (400, 550, 350, 650):
                tab.main_splitter.setSizes([0, total - chat_width, chat_width])
                app.processEvents()

        assert_kept(drag)
        assert_kept(tab._hide_ai_chat)
        assert not tab.ai_chat_panel.isVisible()

        # 직전 줄의 글자는 이미 위로 잘리고 아래 여백만 남은 경우에도,
        # 실제 읽을 수 있는 첫 줄을 기준으로 고정한다.
        browser.setPlainText('\n'.join(
            f'{i}번째 조문: ' + '긴 본문이 이어집니다. ' * 30
            for i in range(100)
        ))
        QTest.qWait(browser.WRAP_SETTLE_MS + 80)
        first_line = browser.document().find('40번째 조문')
        first_line.clearSelection()
        first_line.movePosition(first_line.MoveOperation.StartOfBlock)
        scroll = browser.verticalScrollBar()
        scroll.setValue(scroll.value() + browser.cursorRect(first_line).top() - 4)
        before = browser.cursorRect(first_line).top()
        assert before == 4
        tab._show_ai_chat()
        QTest.qWait(browser.WRAP_SETTLE_MS + 80)
        assert abs(browser.cursorRect(first_line).top() - before) <= 2
    finally:
        tab.close()
        app.processEvents()
