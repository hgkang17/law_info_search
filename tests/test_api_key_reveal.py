"""API 인증키 입력칸의 표시·숨기기 토글 검증."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QLineEdit

from ui.main_window import LawSearchWindow


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def test_api_key_is_masked_until_reveal_is_pressed(qt_app) -> None:
    window = LawSearchWindow()
    try:
        window.api_input.setText("HGKANG17")

        # 화면 공유·어깨너머 노출을 막으려고 기본은 가린 상태다.
        assert window.api_input.echoMode() == QLineEdit.EchoMode.Password
        assert window.api_reveal_button.text() == "표시"

        window.api_reveal_button.setChecked(True)
        assert window.api_input.echoMode() == QLineEdit.EchoMode.Normal
        assert window.api_reveal_button.text() == "숨김"

        window.api_reveal_button.setChecked(False)
        assert window.api_input.echoMode() == QLineEdit.EchoMode.Password
        assert window.api_reveal_button.text() == "표시"

        # 가리는 것은 화면 표시일 뿐이라 값 자체는 그대로 남는다.
        assert window.api_input.text() == "HGKANG17"
    finally:
        window.close()
