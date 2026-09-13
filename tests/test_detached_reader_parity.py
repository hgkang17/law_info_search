import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QSettings, Qt, QUrl
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.dialogs import MemoNoteDialog
from ui.main_window import LawSearchWindow
from ui.tabs.resource_search import ResourceSearchTab
from ui.widgets import DeferredWrapTextBrowser
from shiboken6 import isValid


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("target,name", [
    ("law", "시험법"), ("admrul", "시험 행정규칙"),
    ("admrul", "도시관리계획 수립지침"), ("ordin", "시험시 조례"),
])
def test_resource_detached_reader_keeps_tools_keys_colors_and_memos(app, tmp_path, target, name):
    cache = LawDocumentCache(tmp_path / "cache")
    source = ResourceSearchTab(lambda: "", RecentSearchManager(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)), cache)
    row = dict(target=target, id="123", name=name, label=name)
    html = '<p>선택할 본문</p>' + '<p>긴 본문 내용</p>' * 150
    cache.save_snapshot(row, html=html, plain_text="선택할 본문")
    source._open_document_tab(row, defer_restore=True)
    source._commit_detail([html], ["선택할 본문"])
    source.resize(1100, 700)
    source.show()
    app.processEvents()
    key = source._active_document_key
    document = source.detail_view.document()
    source._detach_document_tab(key, QPoint(-1000, -1000))
    window = source._detached_document_windows[0]
    window.move(100, 100)
    app.processEvents()
    try:
        reader = window.current_page().source_reader
        assert isinstance(reader.detail_view, DeferredWrapTextBrowser)
        assert reader.detail_view.document() is document
        assert reader.detail_view is not source.detail_view
        for widget in (reader.detail_font_reset, reader.detail_font_combo,
                       reader.detail_font_spin, reader.color_tools,
                       reader.color_reset_tools, reader.memo_button):
            assert widget.isVisible()
        bar = reader.detail_view.verticalScrollBar()
        assert bar.maximum() > 0
        QTest.keyClick(reader.detail_view, Qt.Key.Key_End)
        assert bar.value() == bar.maximum()
        QTest.keyClick(reader.detail_view, Qt.Key.Key_Home)
        assert bar.value() == 0
        reader.detail_font_spin.setValue(10.0)
        assert reader.detail_view.document().defaultFont().pointSizeF() == 10.0
        cursor = reader.detail_view.document().find("선택할 본문")
        reader.detail_view.setTextCursor(cursor)
        reader._apply_palette_color("#ef4444", background=False)
        assert cursor.charFormat().foreground().color().name() == "#ef4444"
        reader.memo_button.click()
        dialog = reader.findChild(MemoNoteDialog)
        assert dialog is not None
        dialog.editor.setPlainText("분리 창 메모")
        dialog.save_button.click()
        assert reader._visible_memos[0]["text"] == "분리 창 메모"
        assert cache.load_for_row(row)["memos"][0]["text"] == "분리 창 메모"
        from ui.detached_reader import sync_reader_state
        sync_reader_state(window.current_page())
        state = window.reattach_payload["state"]
        assert state["memos"][0]["text"] == "분리 창 메모"
        assert source.reattach_document(window.reattach_payload)
        assert "선택할 본문" in source.detail_view.toPlainText()
        assert source._document_states[key]["memos"][0]["text"] == "분리 창 메모"
    finally:
        window.close()
        source.close()
        app.processEvents()


@pytest.mark.parametrize("attribute,source_name", [
    ("central_tab", "central"), ("expc_tab", "expc"),
    ("prec_tab", "prec"), ("ai_search_tab", "ai_search"),
    ("ai_related_tab", "ai_related"),
])
def test_other_document_types_use_their_original_reader(app, tmp_path, attribute, source_name):
    main = LawSearchWindow()
    source = getattr(main, attribute)
    source.law_cache = LawDocumentCache(tmp_path / "cache")
    row = dict(target=source_name, id="123", name="시험 문서", label="시험")
    source.law_cache.save_snapshot(row, html='<p>본문</p>' * 180, plain_text="본문")
    source.restore_open_document(row, html='<p>본문</p>' * 180, text="본문", scroll=0)
    main._refresh_open_documents()
    token = next(str(main.open_document_tabs.tabData(i)) for i in range(main.open_document_tabs.count())
                 if str(main.open_document_tabs.tabData(i)).startswith(source_name + ":"))
    main._detach_open_document_tab(token, QPoint(-1000, -1000))
    window = main._detached_document_windows[0]
    window.move(100, 100)
    app.processEvents()
    try:
        reader = window.current_page().source_reader
        assert type(reader) is type(source)
        assert reader.service == source.service
        assert reader.memo_button.isVisible()
        assert reader.detail_font_combo.isVisible()
        QTest.keyClick(reader.detail_view, Qt.Key.Key_End)
        assert reader.detail_view.verticalScrollBar().value() > 0
        reader.detail_font_spin.setValue(10.5)
        cursor = reader.detail_view.document().find("본문")
        reader.detail_view.setTextCursor(cursor)
        reader._apply_palette_color("#ef4444", background=False)
        reader.memo_button.click()
        dialog = reader.findChild(MemoNoteDialog)
        assert dialog is not None
        dialog.editor.setPlainText("유형별 메모")
        dialog.save_button.click()
        main._reattach_detached_window(window)
        app.processEvents()
        assert "본문" in source.detail_view.toPlainText()
        assert source.detail_font_spin.value() == 10.5
        assert source.detail_view.document().defaultFont().pointSizeF() == 10.5
        assert source._visible_memos[0]["text"] == "유형별 메모"
        assert source.detail_view.document().find("본문").charFormat().foreground().color().name() == "#ef4444"
        source.detail_view.setTextCursor(source.detail_view.document().find("본문"))
        source._reset_selected_colors()
        assert source.detail_view.document().find("본문").charFormat().foreground().color().name() != "#ef4444"
    finally:
        if isValid(window):
            window.close()
        main.close()
        app.processEvents()


@pytest.mark.parametrize("target", ["law", "admrul", "ordin"])
def test_annex_expands_inside_detached_reader(app, tmp_path, monkeypatch, target):
    cache = LawDocumentCache(tmp_path / "cache")
    source = ResourceSearchTab(lambda: "", RecentSearchManager(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)), cache)
    row = dict(target=target, id="123", name="시험 본문", label="시험")
    source._open_document_tab(row, defer_restore=True)
    entries = [dict(label="별표 1", title="허용 기준", pdf_url="https://www.law.go.kr/LSW/flDownload.do?flSeq=1")]
    source._annex_section_entries = entries
    parts = ['<p>본문</p>']
    source._append_law_annex_section(parts, [], entries)
    source._commit_detail(parts, ["본문"])
    source._detach_document_tab(source._active_document_key, QPoint(-1000, -1000))
    window = source._detached_document_windows[0]
    window.move(100, 100)
    app.processEvents()
    reader = window.current_page().source_reader
    downloads = []
    monkeypatch.setattr(reader, "_start_annex_download", lambda key, entry: downloads.append((key, entry)))
    try:
        reader.detail_view.anchorClicked.emit(QUrl("annex:0"))
        app.processEvents()
        assert len(downloads) == 1
        assert reader._annex_previews
        assert not source._annex_previews
        panel = next(iter(reader._annex_preview_panels.values()))
        assert panel.parent() is reader.detail_view.viewport()
        assert panel.isVisible()
        reader.detail_view.anchorClicked.emit(QUrl("annex:0"))
        app.processEvents()
        assert not reader._annex_previews
        assert not panel.isVisible()
    finally:
        window.close()
        source.close()
        app.processEvents()


def test_family_selection_adds_a_tab_to_the_same_detached_window(app, tmp_path, monkeypatch):
    monkeypatch.setattr(ResourceSearchTab, "_queue_three_stage_link_request", lambda *args: None)
    cache = LawDocumentCache(tmp_path / "cache")
    source = ResourceSearchTab(lambda: "", RecentSearchManager(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)), cache)
    keys = []
    for number, name in enumerate(("시험법", "시험법 시행령"), 1):
        row = dict(target="law", id=str(number), name=name, label="법령")
        payload = {"법령": {"기본정보": {"법령명_한글": name, "법령ID": str(number)},
                             "조문": {"조문단위": [{"조문번호": "1", "조문내용": "제1조(목적) 본문"}]}}}
        cache.save(row, payload)
        source.open_cached_law(dict(row=row, payload=payload))
        keys.append(source._active_document_key)
    source._detach_document_tab(keys[0], QPoint(-1000, -1000))
    window = source._detached_document_windows[0]
    window.move(100, 100)
    app.processEvents()
    try:
        tree = window.current_page().source_reader.family_law_tree
        assert tree.isVisible()
        tree.itemDoubleClicked.emit(tree.topLevelItem(1), 0)
        app.processEvents()
        assert window.document_tabs.count() == 2
        assert window.current_page().reattach_payload["row"]["name"] == "시험법 시행령"
        assert {p.reattach_payload["row"]["name"] for p in window._pages} == {"시험법", "시험법 시행령"}
        for page in window.ordered_pages():
            family = page.source_reader.family_law_tree
            active = page.reattach_payload["row"]["name"]
            for i in range(family.topLevelItemCount()):
                item = family.topLevelItem(i)
                assert (item.background(0).color().name() == "#dcecf9") == (
                    item.data(0, Qt.ItemDataRole.UserRole) == active)
            assert not family.selectedItems()
    finally:
        window.close()
        source.close()
        app.processEvents()


def test_closing_a_detached_window_keeps_its_running_download_alive(app):
    from PySide6.QtCore import QThread
    from ui.dialogs import DetachedDocumentWindow
    from ui.detached_reader import _retired_pages

    class Download(QThread):
        def run(self):
            self.msleep(80)

    window = DetachedDocumentWindow("다운로드", "<p>본문</p>")
    page = window.current_page()
    worker = Download(page)
    window.show()
    worker.start()
    window.close()
    app.processEvents()
    assert page in _retired_pages
    assert isValid(page)
    QTest.qWait(150)
    app.processEvents()
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert page not in _retired_pages
    assert not isValid(page)
