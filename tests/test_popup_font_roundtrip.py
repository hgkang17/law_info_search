"""팝업/3단비교 확대ㆍ축소 뒤 기본 글꼴과 줄간격 복원."""

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QTextBlockFormat
from ui.dialogs import LawReferencePopup
from utils.constants import DETAIL_FONT_FAMILY


@pytest.mark.parametrize("wrapper", [
    '<div class="content">{body}</div>',
    '<table><tr><td>{body}</td><td>{body}</td></tr></table>',
    '<div style="line-height:8px;font-size:9.5pt">{body}</div>',
])
def test_popup_font_roundtrip_restores_layout_and_link(wrapper):
    app = QApplication.instance() or QApplication([])
    popup = LawReferencePopup(lambda url: None)
    popup.resize(700, 450)
    text = '법령 본문의 줄간격과 글자 크기를 확인합니다. ' * 40
    html = wrapper.format(body='<p>' + text + '</p><p><a href="lawref://open?name=법&amp;jo=26">제26조</a></p>')
    try:
        popup.set_content("검증", html)
        popup.show()
        app.processEvents()
        initial_text = popup.browser.toPlainText()
        initial_height = popup.browser.document().size().height()
        for point in (14, 7, 18, 9.5, 13, 9.5):
            popup.set_content_font_point(point)
            app.processEvents()
            document = popup.browser.document()
            assert document.defaultFont().pointSizeF() == point
            assert popup.font_size_label.text() == f"{point:g}pt"
            assert document.toPlainText() == initial_text
            block = document.begin()
            while block.isValid():
                if block.text().strip():
                    assert block.blockFormat().lineHeight() == 135
                    assert block.blockFormat().lineHeightType() == QTextBlockFormat.LineHeightTypes.ProportionalHeight.value
                block = block.next()
            assert document.find("제26조").charFormat().anchorHref().startswith("lawref:")
        assert popup.browser.document().size().height() == pytest.approx(initial_height, abs=0.1)
        popup.set_content_font_point(14, family="Arial")
        popup.font_reset_button.click()
        app.processEvents()
        assert popup.content_font_point == 9.5
        assert popup.content_font_family == DETAIL_FONT_FAMILY
        assert popup.browser.document().size().height() == pytest.approx(initial_height, abs=0.1)
    finally:
        popup.close()


def test_font_change_does_not_restore_previous_body_after_error():
    app = QApplication.instance() or QApplication([])
    popup = LawReferencePopup(lambda url: None)
    try:
        popup.set_content("이전", "<p>이전 본문</p>")
        popup.set_error("조회 실패")
        popup.font_larger_button.click()
        assert "이전 본문" not in popup.browser.toPlainText()
    finally:
        popup.close()


def test_popup_reset_updates_both_popups_and_saved_size(tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from storage.cache import LawDocumentCache
    from storage.recent import RecentSearchManager
    from ui.tabs.resource_search import ResourceSearchTab
    from ui.tabs.ai_chat_panel import AiChatPanel

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(AiChatPanel, "_start_visible_background_checks", lambda self: None)
    settings = QSettings(str(tmp_path / "font.ini"), QSettings.Format.IniFormat)
    tab = ResourceSearchTab(lambda: "", RecentSearchManager(settings), LawDocumentCache(tmp_path / "saved"))
    try:
        for popup in (tab.reference_popup, tab.three_stage_popup):
            popup.set_content("검증", "<p>본문</p>")
        tab.reference_popup.font_larger_button.click()
        assert tab.three_stage_popup.font_size_label.text() == "10pt"
        tab.three_stage_popup.font_reset_button.click()
        assert float(settings.value("resource_popup_font_size")) == 9.5
        for popup in (tab.reference_popup, tab.three_stage_popup):
            assert popup.content_font_point == 9.5
            assert popup.content_font_family == DETAIL_FONT_FAMILY
            assert popup.browser.document().begin().blockFormat().lineHeight() == 135
    finally:
        tab.close()
