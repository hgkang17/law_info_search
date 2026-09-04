from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from ui.theme import apply_detail_font_family, register_bundled_pretendard_fonts
from utils.constants import (
    DEFAULT_DETAIL_FONT_POINT,
    DETAIL_FONT_CSS_FAMILY,
    DETAIL_FONT_FAMILY,
)
from ui.widgets import (
    DETAIL_FONT_CONTROL_WIDTH,
    DETAIL_FONT_FAMILY_WIDTH,
    DETAIL_FONT_SIZE_MAX,
    DETAIL_FONT_SIZE_MIN,
    DETAIL_FONT_SIZE_STEP,
    build_detail_header_controls,
    clamp_detail_font_size,
    load_detail_font_preferences,
    normalize_detail_font_size,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_shared_detail_header_preserves_ui_contract() -> None:
    _app()
    register_bundled_pretendard_fonts()

    controls = build_detail_header_controls(
        DEFAULT_DETAIL_FONT_POINT, DETAIL_FONT_FAMILY
    )

    assert controls.title.text() == "본문"
    assert controls.title.objectName() == "detailSectionTitle"
    assert controls.title.toolTip() == "더블클릭하면 본문 크게 보기로 전환합니다."
    assert controls.font_combo.objectName() == "detailFontCombo"
    assert controls.font_combo.currentFont().family() == DETAIL_FONT_FAMILY
    assert controls.font_combo.width() == DETAIL_FONT_FAMILY_WIDTH
    assert DETAIL_FONT_FAMILY_WIDTH >= 182
    assert controls.font_spin.objectName() == "fontSizeSpin"
    assert controls.font_spin.minimum() == DETAIL_FONT_SIZE_MIN
    assert controls.font_spin.maximum() == DETAIL_FONT_SIZE_MAX
    assert controls.font_spin.singleStep() == DETAIL_FONT_SIZE_STEP
    assert controls.font_spin.decimals() == 1
    assert controls.font_spin.suffix() == "pt"
    assert controls.font_spin.value() == pytest.approx(9.0)
    assert controls.font_spin.width() == DETAIL_FONT_CONTROL_WIDTH


def test_shared_detail_header_keeps_signal_wiring_available_to_each_tab() -> None:
    _app()
    controls = build_detail_header_controls(10.0)
    toggles: list[bool] = []
    sizes: list[float] = []
    controls.title.doubleClicked.connect(lambda: toggles.append(True))
    controls.font_spin.valueChanged.connect(sizes.append)

    controls.title.doubleClicked.emit()
    controls.font_combo.setCurrentFont(controls.font_combo.font())
    controls.font_spin.setValue(10.5)

    assert toggles == [True]
    assert controls.font_combo.currentFont().family()
    assert sizes == [10.5]


def test_long_font_name_stays_scrolled_to_its_leading_text() -> None:
    _app()
    controls = build_detail_header_controls(9.0)
    editor = controls.font_combo.lineEdit()
    assert editor is not None
    controls.font_combo.setEditText("Pretendard Variable")
    editor.setCursorPosition(len(editor.text()))

    controls.font_combo.currentFontChanged.emit(QFont("Pretendard Variable"))
    QApplication.processEvents()

    assert editor.cursorPosition() == 0


def test_legacy_saved_font_migrates_once_without_overwriting_custom_size(
    tmp_path,
) -> None:
    settings = QSettings(
        str(tmp_path / "detail-font.ini"), QSettings.Format.IniFormat
    )
    settings.setValue("law_detail_font_family", "Pretendard Variable")
    settings.setValue("law_detail_font_size", 10.0)

    size, family = load_detail_font_preferences(
        settings,
        size_key="law_detail_font_size",
        family_key="law_detail_font_family",
    )

    assert family == DETAIL_FONT_FAMILY
    assert size == pytest.approx(10.0)
    assert settings.value("law_detail_font_family") == DETAIL_FONT_FAMILY
    assert float(settings.value("law_detail_font_size")) == pytest.approx(10.0)

    # 마이그레이션 뒤 사용자가 다시 고른 값은 다음 실행에서도 보존한다.
    settings.setValue("law_detail_font_family", "Pretendard Variable")
    settings.setValue("law_detail_font_size", 11.5)
    size, family = load_detail_font_preferences(
        settings,
        size_key="law_detail_font_size",
        family_key="law_detail_font_family",
    )
    assert family == "Pretendard Variable"
    assert size == pytest.approx(11.5)


def test_new_detail_font_preferences_default_to_gulim_9pt(tmp_path) -> None:
    settings = QSettings(
        str(tmp_path / "new-detail-font.ini"), QSettings.Format.IniFormat
    )

    size, family = load_detail_font_preferences(
        settings,
        size_key="resource_detail_font_size",
        family_key="resource_detail_font_family",
    )

    assert family == DETAIL_FONT_FAMILY
    assert size == pytest.approx(9.0)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(6.0, 7.0), (11.74, 11.5), (11.76, 12.0), (19.0, 18.0)],
)
def test_detail_font_size_tokens_share_clamping_and_step(
    value: float, expected: float
) -> None:
    assert normalize_detail_font_size(value) == expected


def test_saved_detail_font_size_is_clamped_without_changing_its_precision() -> None:
    assert clamp_detail_font_size(11.7) == 11.7


def test_saved_body_fonts_are_normalized_to_the_detail_font() -> None:
    """저장해 둔 본문의 글꼴을 지금 본문 글꼴로 맞춘다.

    어떤 글꼴로 통일할지는 DETAIL_FONT_CSS_FAMILY 하나가 정한다. 맑은
    고딕으로 옮겼다가 굴림으로 되돌린 적이 있어, 특정 글꼴 이름을 테스트에
    박아 두지 않고 그 상수를 기준으로 견준다.
    """
    html = "<div style=\"font-family:'Pretendard','없는글꼴';\">본문</div>"

    normalized = apply_detail_font_family(html)

    assert f"font-family:{DETAIL_FONT_CSS_FAMILY}" in normalized
    assert "Pretendard" not in normalized
