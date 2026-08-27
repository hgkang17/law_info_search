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


def test_runtime_manual_files_are_bundled_into_the_exe() -> None:
    """HTML 안내와 그 그림이 빠지면 개발 중에만 보이고 exe에서는 사라진다."""
    spec = SPEC.read_text(encoding="utf-8")
    html = API_KEY_MANUAL_PATH.read_text(encoding="utf-8")
    sources = re.findall(r'<img[^>]+src="([^"]+)"', html)
    runtime_files = [
        API_KEY_MANUAL_PATH,
        *(MANUAL_DIR / name for name in sources),
    ]

    for path in runtime_files:
        assert f'("메뉴얼/{path.name}", "메뉴얼")' in spec, path.name


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
