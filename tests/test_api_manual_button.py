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


def test_manual_and_every_image_it_uses_exist() -> None:
    assert API_KEY_MANUAL_PATH.is_file()

    html = API_KEY_MANUAL_PATH.read_text(encoding="utf-8")
    sources = re.findall(r'<img[^>]+src="([^"]+)"', html)

    assert sources, "안내 문서에 그림이 하나도 없습니다."
    for source in sources:
        assert (MANUAL_DIR / source).is_file(), source


def test_every_manual_file_is_bundled_into_the_exe() -> None:
    """spec의 datas에서 빠지면 개발 중에만 보이고 exe에서는 사라진다."""
    spec = SPEC.read_text(encoding="utf-8")

    for path in sorted(MANUAL_DIR.iterdir()):
        assert f'("메뉴얼/{path.name}", "메뉴얼")' in spec, path.name


def test_help_button_floats_over_the_header_instead_of_taking_space(qt_app) -> None:
    window = LawSearchWindow()
    try:
        window.resize(1400, 900)
        window.show()
        qt_app.processEvents()

        button = window.api_manual_button
        header = window._header_card

        # 레이아웃에 들어가면 그만큼 인증키 칸이 밀린다.
        assert header.layout().indexOf(button) == -1
        assert button.parent() is header
        assert button.width() <= 24 and button.height() <= 24
    finally:
        window.close()


def test_help_button_follows_the_right_edge_when_the_window_resizes(qt_app) -> None:
    window = LawSearchWindow()
    try:
        window.show()
        margins = []
        for width in (1400, 1000, 1600):
            window.resize(width, 900)
            qt_app.processEvents()
            button = window.api_manual_button
            header = window._header_card
            margins.append(header.width() - (button.x() + button.width()))

        # 창 크기가 바뀌어도 오른쪽 모서리에서 같은 거리에 붙어 있어야 한다.
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
