"""업데이트 안내 대화상자의 단추 이름과 폭 회귀 검증."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from ui.main_window import LawSearchWindow


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _build_box(parent) -> tuple[QMessageBox, object]:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle("새 업데이트")
    box.setText("새 버전 9.9.9를 사용할 수 있습니다.\n현재 버전: 1.0.0")
    box.setInformativeText(
        "지금 업데이트하면 파일을 안전하게 확인한 뒤 프로그램을 다시 시작합니다."
    )
    box.setDetailedText("바뀐 점\n- 무언가를 고쳤습니다")
    confirm = box.addButton("확인", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(confirm)
    return box, confirm


def test_detail_button_is_korean_and_no_label_is_clipped(qt_app) -> None:
    window = LawSearchWindow()
    box, _confirm = _build_box(window)
    try:
        LawSearchWindow._localize_message_box(box)
        box.show()
        qt_app.processEvents()

        labels = {button.text() for button in box.buttons()}
        # Qt가 붙이는 "Show Details..."는 번역 파일이 없으면 영어로 남는다.
        assert labels == {"확인", "취소", "자세히"}

        for button in box.buttons():
            assert button.width() >= button.sizeHint().width(), button.text()
    finally:
        box.close()
        window.close()


def test_localizing_twice_does_not_rename_real_buttons(qt_app) -> None:
    window = LawSearchWindow()
    box, confirm = _build_box(window)
    try:
        LawSearchWindow._localize_message_box(box)
        LawSearchWindow._localize_message_box(box)
        box.show()
        qt_app.processEvents()

        # 확인ㆍ취소는 우리가 만든 단추라 역할이 달라 건드리지 않는다.
        assert confirm.text() == "확인"
        assert {button.text() for button in box.buttons()} == {
            "확인",
            "취소",
            "자세히",
        }
    finally:
        box.close()
        window.close()
