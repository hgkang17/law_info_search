"""창 폭에 따라 주 내비게이션이 안전하게 전환되는지 검증."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QLabel, QApplication

from ui.main_window import LawSearchWindow
from ui.theme import WORKBENCH_COLORS


def _relative_luminance(color: str) -> float:
    channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        channel / 12.92
        if channel <= 0.04045
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def test_footer_muted_text_meets_normal_text_contrast() -> None:
    foreground = _relative_luminance(WORKBENCH_COLORS["muted"])
    background = _relative_luminance(WORKBENCH_COLORS["canvas"])
    contrast = (max(foreground, background) + 0.05) / (
        min(foreground, background) + 0.05
    )

    assert contrast >= 4.5


def test_half_screen_uses_compact_navigation(monkeypatch) -> None:
    # 이 단위 테스트가 글꼴을 전역 등록하면 뒤의 파서 테스트가 실제 앱과
    # 무관한 QFontMetrics 실행 순서 영향을 받는다.
    monkeypatch.setattr(
        "ui.main_window.register_bundled_pretendard_fonts", lambda: False
    )
    application = QApplication.instance() or QApplication([])
    assert application is not None
    window = LawSearchWindow()
    try:
        window.resize(900, 700)
        window._update_adaptive_navigation()

        assert not window.compact_navigation.isHidden()
        assert window.navigation_card.isHidden()
        assert window.minimumWidth() == 900
        assert window.resource_tab._compact_reader
        assert not window.resource_tab.compact_format_button.isHidden()
        assert window.resource_tab.color_tools.isHidden()

        law_index = window.compact_navigation.findData(1)
        window.compact_navigation.setCurrentIndex(law_index)
        window._compact_navigation_changed(law_index)
        assert window.navigation.currentRow() == 1

        window.resize(1200, 700)
        window._update_adaptive_navigation()
        assert window.compact_navigation.isHidden()
        assert not window.navigation_card.isHidden()
        assert not window.resource_tab._compact_reader
        assert window.resource_tab.compact_format_button.isHidden()
        assert not window.resource_tab.color_tools.isHidden()
    finally:
        window.close()


def test_gray_workbench_navigation_is_flat_and_compact(monkeypatch) -> None:
    monkeypatch.setattr(
        "ui.main_window.register_bundled_pretendard_fonts", lambda: False
    )
    application = QApplication.instance() or QApplication([])
    assert application is not None
    window = LawSearchWindow()
    try:
        window.resize(1200, 700)
        window._update_adaptive_navigation()

        assert window.navigation_card.width() == 168
        assert window.favorite_navigation_button.text() == "즐겨찾기"
        assert window.favorite_navigation_button.height() <= 44
        assert window.ai_review_button.text() == "AI 에이전트"
        assert window.viewed_laws_button.text() == "저장내역"
        assert window.navigation.item(1).text() == "법령 검색"
        # 머리글에는 로고만 둔다. 프로그램 이름은 창 제목 표시줄에 있다.
        assert window.header_card.findChild(QLabel, "appNameLabel") is None

        style = window.styleSheet()
        assert "background: #fafafa" in style
        assert "background: #202124" in style
        assert "border-bottom: 2px solid #2563eb" in style
    finally:
        window.close()
