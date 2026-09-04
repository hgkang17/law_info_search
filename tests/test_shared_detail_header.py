from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from ui.theme import apply_detail_font_family
from ui.widgets import (
    DETAIL_FONT_CONTROL_WIDTH,
    DETAIL_FONT_FAMILY_WIDTH,
    DETAIL_FONT_SIZE_MAX,
    DETAIL_FONT_SIZE_MIN,
    DETAIL_FONT_SIZE_STEP,
    build_detail_header_controls,
    clamp_detail_font_size,
    normalize_detail_font_size,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_shared_detail_header_preserves_ui_contract() -> None:
    _app()

    controls = build_detail_header_controls(11.5)

    assert controls.title.text() == "본문"
    assert controls.title.objectName() == "detailSectionTitle"
    assert controls.title.toolTip() == "더블클릭하면 본문 크게 보기로 전환합니다."
    assert controls.font_combo.objectName() == "detailFontCombo"
    assert controls.font_combo.currentFont().family()
    assert controls.font_combo.width() == DETAIL_FONT_FAMILY_WIDTH
    assert controls.font_spin.objectName() == "fontSizeSpin"
    assert controls.font_spin.minimum() == DETAIL_FONT_SIZE_MIN
    assert controls.font_spin.maximum() == DETAIL_FONT_SIZE_MAX
    assert controls.font_spin.singleStep() == DETAIL_FONT_SIZE_STEP
    assert controls.font_spin.decimals() == 1
    assert controls.font_spin.suffix() == "pt"
    assert controls.font_spin.value() == pytest.approx(11.5)
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


def test_legacy_saved_body_fonts_are_normalized_to_malgun_gothic() -> None:
    html = '<div style="font-family:\'Gulim\',\'굴림\';">본문</div>'

    normalized = apply_detail_font_family(html)

    assert "font-family:'Malgun Gothic'" in normalized
    assert "font-family:'Gulim'" not in normalized
