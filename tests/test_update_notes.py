"""업데이트 직후 누적 변경 내역 대화상자 검증."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from ui.update_notes import UpdateNotesDialog, display_version, load_update_notes


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def test_bundled_notes_start_with_the_next_release() -> None:
    notes = load_update_notes()

    assert notes.startswith("# 업데이트 내역")
    assert "## 1.4.4" in notes
    assert "조문 즐겨찾기 이름" in notes
    assert "전체 끄기" in notes
    assert "국토계획법 제26조" in notes
    assert "업데이트 직후 첫 실행" in notes


def test_version_prefix_is_removed_for_display() -> None:
    assert display_version("v1.4.4") == "1.4.4"
    assert display_version("1.4.5") == "1.4.5"


def test_update_notes_dialog_shows_accumulated_notes(
    qt_app, tmp_path: Path
) -> None:
    notes_path = tmp_path / "notes.md"
    notes_path.write_text(
        "# 업데이트 내역\n\n## 1.4.5\n\n- 새 수정\n\n"
        "## 1.4.4\n\n- 이전 수정\n",
        encoding="utf-8",
    )
    dialog = UpdateNotesDialog("v1.4.5", notes_path=notes_path)
    try:
        dialog.show()
        qt_app.processEvents()

        text = dialog.notes_view.toPlainText()
        assert dialog.windowTitle() == "1.4.5 업데이트 완료"
        assert dialog.isModal()
        assert text.index("1.4.5") < text.index("1.4.4")
        assert "새 수정" in text
        assert "이전 수정" in text
        confirm = dialog.findChild(QDialogButtonBox).button(
            QDialogButtonBox.StandardButton.Ok
        )
        assert confirm.text() == "확인"
    finally:
        dialog.close()


def test_missing_notes_file_has_a_version_fallback(qt_app, tmp_path: Path) -> None:
    dialog = UpdateNotesDialog(
        "1.4.4", notes_path=tmp_path / "missing.md"
    )
    try:
        assert "1.4.4" in dialog.notes_view.toPlainText()
        assert "업데이트가 완료되었습니다" in dialog.notes_view.toPlainText()
    finally:
        dialog.close()


def test_release_build_includes_update_notes() -> None:
    spec = Path("국가법령정보 통합검색.spec").read_text(encoding="utf-8")

    assert '("업데이트내역.md", ".")' in spec
