"""인증키 발급 안내 단추가 다른 위젯을 밀지 않는지 검증."""

from __future__ import annotations

import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from ui.assets import API_KEY_MANUAL_PATH, MANUAL_DIR
from ui.main_window import LawSearchWindow

SPEC = Path(__file__).resolve().parent.parent / "국가법령정보 통합검색.spec"


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def test_every_manual_and_the_images_it_uses_exist() -> None:
    """안내 문서가 가리키는 그림이 실제로 있어야 그 자리가 깨지지 않는다."""
    manuals = sorted(MANUAL_DIR.glob("*.html"))

    assert manuals, "안내 문서를 하나도 찾지 못했습니다."
    for manual in manuals:
        sources = re.findall(
            r'<img[^>]+src="([^"]+)"', manual.read_text(encoding="utf-8")
        )
        assert sources, f"{manual.name}에 그림이 하나도 없습니다."
        for source in sources:
            assert (MANUAL_DIR / source).is_file(), f"{manual.name} → {source}"


def test_every_manual_and_its_images_are_bundled_into_the_exe() -> None:
    """spec에서 빠지면 개발 중에만 보이고 exe에서는 그 자리가 깨진다.

    실제로 제미나이 안내가 이렇게 빠진 적이 있다. 검사 범위를 인증키
    안내 하나로 좁혀 두었더니 새로 늘어난 안내가 걸리지 않았다. 그래서
    폴더에 있는 안내 문서 전부를 본다.
    """
    spec = SPEC.read_text(encoding="utf-8")
    manuals = sorted(MANUAL_DIR.glob("*.html"))

    assert manuals, "안내 문서를 하나도 찾지 못했습니다."
    for manual in manuals:
        assert f'("메뉴얼/{manual.name}", "메뉴얼")' in spec, manual.name
        sources = re.findall(
            r'<img[^>]+src="([^"]+)"', manual.read_text(encoding="utf-8")
        )
        for source in sources:
            assert f'("메뉴얼/{source}", "메뉴얼")' in spec, source


def test_help_button_floats_inside_the_api_box(qt_app) -> None:
    window = LawSearchWindow()
    try:
        window.resize(1400, 900)
        window.show()
        qt_app.processEvents()

        button = window.api_manual_button
        api_compact = window._api_compact

        # 레이아웃에 들어가면 그만큼 인증키 칸이 밀린다.
        assert api_compact.layout().indexOf(button) == -1
        assert button.parent() is api_compact
        assert button.width() <= 24 and button.height() <= 24
        assert button.x() >= 0 and button.y() >= 0
        assert button.x() + button.width() <= api_compact.width()
        assert button.y() + button.height() <= api_compact.height()
        assert not button.geometry().intersects(
            window.save_api_checkbox.geometry()
        )
    finally:
        window.close()


def test_help_button_follows_the_api_box_edge_when_the_window_resizes(qt_app) -> None:
    window = LawSearchWindow()
    try:
        window.show()
        margins = []
        for width in (1400, 1000, 1600):
            window.resize(width, 900)
            qt_app.processEvents()
            button = window.api_manual_button
            api_compact = window._api_compact
            margins.append(
                api_compact.width() - (button.x() + button.width())
            )

        # 창 크기가 바뀌어도 인증키 박스 오른쪽 안쪽에 붙어 있어야 한다.
        assert len(set(margins)) == 1, margins
        assert margins[0] > 0
    finally:
        window.close()


def test_api_key_widgets_do_not_move_because_of_the_help_button(qt_app) -> None:
    window = LawSearchWindow()
    try:
        window.resize(1400, 900)
        window.show()
        qt_app.processEvents()
        before = (
            window.api_input.x(),
            window.api_reveal_button.x(),
            window.save_api_checkbox.x(),
        )

        # 단추를 숨겼다 다시 보여도 옆 위젯 자리는 그대로여야 한다.
        window.api_manual_button.hide()
        qt_app.processEvents()
        after_hidden = (
            window.api_input.x(),
            window.api_reveal_button.x(),
            window.save_api_checkbox.x(),
        )

        assert before == after_hidden
    finally:
        window.close()


def test_gemini_dialog_has_a_help_button_next_to_the_issue_button(qt_app, tmp_path) -> None:
    """제미나이 키도 발급 자리에서 바로 안내를 볼 수 있어야 한다."""
    from PySide6.QtCore import QSettings

    from ui.assets import GEMINI_KEY_MANUAL_PATH
    from ui.tabs.ai_chat_panel import AiChatPanel

    settings = QSettings(
        str(tmp_path / "panel.ini"), QSettings.Format.IniFormat
    )
    panel = AiChatPanel(settings=settings, standalone=True)
    try:
        panel.key_row_widget.show()
        qt_app.processEvents()
        button = panel.gemini_manual_button

        assert GEMINI_KEY_MANUAL_PATH.is_file()
        # 발급 바로 옆이라 키를 받으러 가기 전에 눈에 들어온다.
        assert panel.key_button.x() < button.x() < panel.refresh_button.x()
        # 전역 QPushButton 스타일에 눌려 세로로 늘어나면 안 된다.
        assert button.height() <= 26
    finally:
        panel.key_row_widget.close()
        panel.deleteLater()
