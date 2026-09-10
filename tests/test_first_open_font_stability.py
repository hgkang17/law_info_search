"""글꼴 목록 갱신을 사용자 선택으로 저장하지 않는다."""

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab
from ui.tabs.ai_search import AiLawSearchTab
from ui.tabs.law_search import LawSearchTab
from ui.tabs.ai_chat_panel import AiChatPanel
from ui.theme import register_bundled_pretendard_fonts
from utils.constants import DETAIL_FONT_FAMILY


@pytest.fixture(params=['resource', 'ai_search', 'ai_related', 'central', 'expc', 'prec'])
def tab(tmp_path, request, monkeypatch):
    app = QApplication.instance() or QApplication([])
    register_bundled_pretendard_fonts()
    settings = QSettings(str(tmp_path / 'font.ini'), QSettings.Format.IniFormat)
    monkeypatch.setattr(ResourceSearchTab, '_queue_three_stage_link_request', lambda *a: None)
    monkeypatch.setattr(AiChatPanel, '_start_visible_background_checks', lambda self: None)
    args = (lambda: '', RecentSearchManager(settings), LawDocumentCache(tmp_path / 'saved'))
    if request.param == 'resource':
        widget = ResourceSearchTab(*args)
    elif request.param.startswith('ai_'):
        widget = AiLawSearchTab(request.param, *args)
    else:
        widget = LawSearchTab(request.param, *args)
    yield widget
    widget.close()
    app.processEvents()


def test_font_database_refresh_does_not_change_default(tab):
    QApplication.instance().fontDatabaseChanged.emit()
    QApplication.processEvents()
    assert tab.detail_font_family == DETAIL_FONT_FAMILY
    prefix = getattr(tab, 'service', 'resource')
    assert tab.recent_search_manager.settings.value(f'{prefix}_detail_font_family') == DETAIL_FONT_FAMILY


def test_programmatic_font_selection_does_not_persist_as_user_choice(tab):
    tab.detail_font_combo.setCurrentFont(QFont('Arial'))
    QApplication.processEvents()
    assert tab.detail_font_family == DETAIL_FONT_FAMILY
    assert tab.detail_font_size == 9.5


def test_actual_user_font_selection_is_applied(tab):
    tab.detail_font_combo.setCurrentFont(QFont('Arial'))
    tab.detail_font_combo.activated.emit(tab.detail_font_combo.currentIndex())
    assert tab.detail_font_family == tab.detail_font_combo.currentFont().family()


def test_keyboard_font_choice_still_applies_and_persists(tab):
    QTest.keyClick(tab.detail_font_combo, Qt.Key.Key_Down)
    selected = tab.detail_font_combo.currentFont().family()
    assert selected != DETAIL_FONT_FAMILY
    assert tab.detail_font_family == selected
    prefix = getattr(tab, 'service', 'resource')
    assert tab.recent_search_manager.settings.value(f'{prefix}_detail_font_family') == selected


def test_first_body_and_next_body_use_default_font_even_with_source_styles(tab):
    for family in ('Arial', 'GulimChe'):
        tab._replace_detail_content(
            html=f'<p style="font-family:{family};font-size:10pt">새 본문 ABC 123</p>'
        )
        QApplication.processEvents()
        document = tab.detail_view.document()
        cursor = document.find('새 본문')
        assert not cursor.isNull()
        assert document.defaultFont().family() == DETAIL_FONT_FAMILY
        assert document.defaultFont().pointSizeF() == 9.5
        assert cursor.charFormat().fontFamilies()[0] == DETAIL_FONT_FAMILY
        assert cursor.charFormat().fontPointSize() == 9.5


@pytest.mark.parametrize('tab', ['resource'], indirect=True)
def test_new_law_then_new_article_keep_default_font(tab):
    row = {'target': 'law', 'id': 'font-test', 'name': '시험법', 'label': '법령'}
    payload = {'법령': {
        '기본정보': {'법령명_한글': '시험법', '법령ID': 'font-test'},
        '조문': {'조문단위': [{'조문번호': '1', '조문내용': '제1조(목적) 새 본문을 확인한다.'}]},
    }}
    tab.pending_row = row
    tab._show_detail(payload, save_cache=False)
    first_document = tab.detail_view.document()
    tab._show_favorite_article_payload({'row': row}, {'jo': '000100'}, payload, '시험 응답')
    QApplication.processEvents()
    assert tab.detail_view.document() is not first_document
    for document in (first_document, tab.detail_view.document()):
        cursor = document.find('새 본문')
        assert not cursor.isNull()
        assert document.defaultFont().family() == DETAIL_FONT_FAMILY
        assert document.defaultFont().pointSizeF() == 9.5
        assert cursor.charFormat().fontFamilies()[0] == DETAIL_FONT_FAMILY
        assert (cursor.charFormat().fontPointSize() or document.defaultFont().pointSizeF()) == 9.5
