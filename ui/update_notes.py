"""업데이트 직후 첫 실행에 표시하는 누적 변경 내역 대화상자."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ui.assets import UPDATE_NOTES_PATH


def display_version(value: str) -> str:
    """업데이트 도우미가 넘긴 ``v1.4.4``를 화면용 ``1.4.4``로 바꾼다."""
    version = str(value or "").strip()
    if version[:1].casefold() == "v":
        version = version[1:]
    return version or "새 버전"


def load_update_notes(path: Path = UPDATE_NOTES_PATH) -> str:
    """EXE에 포함된 누적 업데이트 내역을 읽는다."""
    try:
        notes = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return notes


class UpdateNotesDialog(QDialog):
    """최신 항목부터 이전 항목까지 한 창에서 보여 주는 업데이트 완료창."""

    def __init__(
        self,
        updated_version: str,
        parent: QWidget | None = None,
        *,
        notes_path: Path = UPDATE_NOTES_PATH,
    ) -> None:
        super().__init__(parent)
        version = display_version(updated_version)
        self.setObjectName("updateNotesDialog")
        self.setWindowTitle(f"{version} 업데이트 완료")
        self.setModal(True)
        self.resize(650, 540)
        self.setMinimumSize(520, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)

        heading = QLabel(f"{version} 버전으로 업데이트했습니다.", self)
        heading.setObjectName("updateNotesHeading")
        heading.setTextFormat(Qt.TextFormat.PlainText)
        heading.setStyleSheet(
            "font-size:18px; font-weight:700; color:#173b63;"
        )
        layout.addWidget(heading)

        description = QLabel(
            "이번 버전과 이전 업데이트에서 달라진 내용을 최신순으로 보여드립니다.",
            self,
        )
        description.setObjectName("updateNotesDescription")
        description.setWordWrap(True)
        description.setTextFormat(Qt.TextFormat.PlainText)
        description.setStyleSheet("color:#5a6b80;")
        layout.addWidget(description)

        self.notes_view = QTextBrowser(self)
        self.notes_view.setObjectName("updateNotesView")
        self.notes_view.setAccessibleName("누적 업데이트 내역")
        self.notes_view.setOpenExternalLinks(False)
        self.notes_view.setStyleSheet(
            "QTextBrowser {"
            " background:#ffffff; color:#172033;"
            " border:1px solid #cfdcea; border-radius:10px;"
            " padding:14px;"
            "}"
        )
        notes = load_update_notes(notes_path)
        self.notes_view.setMarkdown(
            notes
            or f"## {version}\n\n- 업데이트가 완료되었습니다."
        )
        self.notes_view.moveCursor(QTextCursor.MoveOperation.Start)
        layout.addWidget(self.notes_view, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok, self)
        buttons.setObjectName("updateNotesButtons")
        confirm = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if confirm is not None:
            confirm.setText("확인")
            confirm.setDefault(True)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


def show_update_notes_dialog(
    updated_version: str, parent: QWidget | None = None
) -> int:
    """업데이트 완료 대화상자를 모달로 표시한다."""
    return UpdateNotesDialog(updated_version, parent).exec()
