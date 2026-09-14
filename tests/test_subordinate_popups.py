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
        assert len(popups) == 1
        assert all(p.pin_button.isChecked() for p in popups)
        assert all(option["text"] in popups[0].browser.toPlainText() for option in options)
        assert len(popups[0]._combined_sections) == 2
        # 반복 클릭해도 이미 열린 두 조문을 재사용한다.
        tab._show_inline_subordinate_menu(QUrl(tab._inline_subordinate_href(options)))
        app.processEvents()
        assert len([p for p in tab._all_reference_popups() if p.isVisible()]) == 1
    finally:
        tab.worker = None
        for popup in tab._all_reference_popups():
            popup.close()
        tab.close()
        app.processEvents()


def test_combined_articles_share_one_law_header_and_metadata(tmp_path):
    app = QApplication.instance() or QApplication([])
    tab = ResourceSearchTab(lambda: "test", RecentSearchManager(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)),
        LawDocumentCache(tmp_path / "cache"))
    popup = tab.reference_popup
    law_name = "국토의 계획 및 이용에 관한 법률 시행령"
    options = [{"text": f"{law_name} {article}"} for article in ("제19조의2", "제20조")]
    header = "".join(tab._popup_detail_header(
        law_name, [("법령ID", "009419"), ("소관부처", "국토교통부")]
    ))
    popup.begin_combined(options)
    for index, article in enumerate(("제19조의2", "제20조")):
        popup._combined_active = index
        popup.set_content(
            f"{law_name} {article}",
            header
            + '<div class="popup-section-title">조문</div>'
            + f'<div class="content"><p>{article}(주민제안) 내용</p></div>',
        )
    shown = popup.browser.toPlainText()
    assert shown.count(law_name) == 1
    assert shown.count("법령ID") == 1
    assert shown.count("소관부처") == 1
    assert shown.count("제19조의2") == 1
    assert shown.count("제20조") == 1
    assert shown.count("조문") == 0
    assert popup._source_html.count('class="popup-law-title"') == 1
    assert popup._source_html.count("<hr ") == 1
    tab.close()
    app.processEvents()


def test_combined_articles_keep_distinct_law_versions(tmp_path):
    app = QApplication.instance() or QApplication([])
    tab = ResourceSearchTab(lambda: "test", RecentSearchManager(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)),
        LawDocumentCache(tmp_path / "cache"))
    popup = tab.reference_popup
    law_name = "국토의 계획 및 이용에 관한 법률 시행령"
    popup.begin_combined([{"text": "제19조의2"}, {"text": "제20조"}])
    for index, (article, effective) in enumerate((
        ("제19조의2", "20260101"), ("제20조", "20260801")
    )):
        popup._combined_active = index
        header = "".join(tab._popup_detail_header(
            law_name, [("법령ID", "009419"), ("시행일자", effective)]
        ))
        popup.set_content(
            f"{law_name} {article}",
            header + '<div class="popup-section-title">조문</div>'
            + f'<div class="content"><p>{article} 내용</p></div>',
        )
    shown = popup.browser.toPlainText()
    assert shown.count(law_name) == 2
    assert "20260101" in shown and "20260801" in shown
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
        assert len(popups) == 1
        assert any("첫 조문 조회 실패" in p.browser.toPlainText() for p in popups)
        assert any("002000 본문" in p.browser.toPlainText() for p in popups)
        assert tab.worker is None
        popup = popups[0]
        before = popup.browser.toPlainText()
        popup.set_content_font_point(11.0)
        assert popup.browser.toPlainText() == before
        assert popup.refresh_button.isEnabled()
        tab._refresh_reference_popup(popup)
        for _ in range(10):
            app.processEvents()
        assert calls == ["001900", "002000", "001900", "002000"]
        assert popup.browser.toPlainText() == before
        assert len([p for p in tab._all_reference_popups() if p.isVisible()]) == 1
        group = popups[0]
        before = group.browser.toPlainText()
        group._close_popup()
        tab._show_inline_subordinate_menu(QUrl(tab._inline_subordinate_href(options)))
        for _ in range(3):
            app.processEvents()
        assert group.isVisible()
        assert group.browser.toPlainText() == before
        # 일반 조문을 따로 열어도 묶음 팝업의 마지막 조문을 덮어쓰지 않는다.
        tab._detail_link_clicked(QUrl(options[0]["href"]))
        assert group.browser.toPlainText() == before
        assert len([p for p in tab._all_reference_popups() if p.isVisible()]) == 2
    finally:
        for popup in tab._all_reference_popups():
            popup.close()
        tab.close()
        app.processEvents()
