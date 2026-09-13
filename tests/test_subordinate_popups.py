import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QUrl
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab
import ui.tabs.resource_search as resource_module


def test_multiple_delegations_open_all_cached_articles(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    tab = ResourceSearchTab(lambda: "test", RecentSearchManager(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)),
        LawDocumentCache(tmp_path / "cache"))
    monkeypatch.setattr(tab, "_remember_reference_popup", lambda *a, **k: "")
    options = [{"text": f"대통령령 제{jo}조", "href":
                f"lawref://open?name=테스트시행령&id=123&jo={jo}"} for jo in (19, 20)]
    for option in options:
        key = tab._reference_key_from_url(QUrl(option["href"]))
        tab._reference_popup_states[key] = {
            "title": option["text"], "html": f'<p>{option["text"]} 내용</p>'}
    try:
        # 다른 조회가 진행 중이면 pending 문맥을 건드리지 않고 기다린다.
        tab.worker = SimpleNamespace(isRunning=lambda: True)
        tab._show_inline_subordinate_menu(QUrl(tab._inline_subordinate_href(options)))
        assert len(tab._subordinate_popup_queue) == 2
        assert not any(p.isVisible() for p in tab._all_reference_popups())
        tab.worker = None
        tab._open_next_subordinate_popup()
        app.processEvents()
        popups = [p for p in tab._all_reference_popups() if p.isVisible()]
        assert len(popups) == 2
        assert all(p.pin_button.isChecked() for p in popups)
        assert {p.browser.toPlainText() for p in popups} == {
            "대통령령 제19조 내용", "대통령령 제20조 내용"}
        assert popups[0].pos() != popups[1].pos()
        # 반복 클릭해도 이미 열린 두 조문을 재사용한다.
        tab._show_inline_subordinate_menu(QUrl(tab._inline_subordinate_href(options)))
        app.processEvents()
        assert len([p for p in tab._all_reference_popups() if p.isVisible()]) == 2
    finally:
        tab.worker = None
        for popup in tab._all_reference_popups():
            popup.close()
        tab.close()
        app.processEvents()


def test_uncached_delegations_continue_after_first_request_fails(tmp_path, monkeypatch):
    from PySide6.QtCore import QObject, Signal, QTimer

    app = QApplication.instance() or QApplication([])
    calls = []

    class Worker(QObject):
        succeeded = Signal(str, object)
        failed = Signal(str, str)
        finished = Signal()

        def __init__(self, operation, **kwargs):
            super().__init__(kwargs["parent"])
            self.operation = operation
            self.jo = kwargs["jo"]
            self.running = False

        def isRunning(self):
            return self.running

        def start(self):
            self.running = True
            calls.append(self.jo)
            QTimer.singleShot(0, self.complete)

        def complete(self):
            if self.jo == "001900":
                self.failed.emit(self.operation, "첫 조문 조회 실패")
            else:
                self.succeeded.emit(self.operation, self.jo)
            self.running = False
            self.finished.emit()

    tab = ResourceSearchTab(lambda: "test", RecentSearchManager(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)),
        LawDocumentCache(tmp_path / "cache"))
    monkeypatch.setattr(resource_module, "ResourceApiWorker", Worker)
    monkeypatch.setattr(tab, "_load_reference_cache", lambda key: None)
    monkeypatch.setattr(tab, "_show_law_reference_detail", lambda jo:
                        tab._pending_reference_popup.set_content(jo, f"<p>{jo} 본문</p>"))
    options = [{"text": f"제{jo}조", "href":
                f"lawref://open?name=테스트시행령&id=123&jo={jo}"} for jo in (19, 20)]
    try:
        tab._show_inline_subordinate_menu(QUrl(tab._inline_subordinate_href(options)))
        assert calls == ["001900"]
        for _ in range(10):
            app.processEvents()
        assert calls == ["001900", "002000"]
        popups = [p for p in tab._all_reference_popups() if p.isVisible()]
        assert len(popups) == 2
        assert any("첫 조문 조회 실패" in p.browser.toPlainText() for p in popups)
        assert any("002000 본문" in p.browser.toPlainText() for p in popups)
        assert tab.worker is None
    finally:
        for popup in tab._all_reference_popups():
            popup.close()
        tab.close()
        app.processEvents()
