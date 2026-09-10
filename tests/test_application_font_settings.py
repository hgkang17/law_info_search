"""실제 시작 경로의 글꼴 저장/복원과 테스트 설정 격리."""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

import ui.main_window as main_window
from ui.tabs.ai_chat_panel import AiChatPanel
from ui.tabs.resource_search import ResourceSearchTab
from utils.constants import DETAIL_FONT_FAMILY


@pytest.fixture
def application(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(main_window, "LAW_CACHE_DIR", tmp_path / "saved")
    monkeypatch.setattr(AiChatPanel, "_start_visible_background_checks", lambda self: None)
    monkeypatch.setattr(ResourceSearchTab, "_queue_three_stage_link_request", lambda *a: None)
    return app


def test_main_window_font_reset_survives_reopening(application, tmp_path):
    window = main_window.LawSearchWindow()
    try:
        assert Path(window.settings.fileName()).is_relative_to(tmp_path)
        tab = window.resource_tab
        tab._set_detail_font_family(QFont("Arial"))
        assert window.settings.value("resource_detail_font_family") == "Arial"
        tab.detail_font_reset.click()
        window.settings.sync()
    finally:
        window.close()
        application.processEvents()

    reopened = main_window.LawSearchWindow()
    try:
        reopened.show()
        application.processEvents()
        tab = reopened.resource_tab
        assert reopened.settings.value("resource_detail_font_family") == DETAIL_FONT_FAMILY
        assert tab.detail_font_family == DETAIL_FONT_FAMILY
        assert tab.detail_font_combo.currentFont().family() == DETAIL_FONT_FAMILY
        assert tab.detail_font_size == 9.5
    finally:
        reopened.close()
        application.processEvents()


def test_named_settings_and_fallback_stay_inside_test_directory(tmp_path):
    for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
        settings = QSettings(
            QSettings.Format.IniFormat, scope,
            "CentralLawSearch", "CentralAgencyLawInterpretation",
        )
        assert Path(settings.fileName()).is_relative_to(tmp_path)
        settings.setValue("resource_detail_font_family", "Arial")
        settings.sync()
        assert settings.status() == QSettings.Status.NoError
