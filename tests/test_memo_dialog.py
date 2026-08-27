from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui.dialogs import MemoNoteDialog


def test_save_keeps_existing_memo_dialog_open() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = MemoNoteDialog("본문", "기존 메모")
    dialog.show()
    app.processEvents()

    dialog.edit_button.click()
    dialog.editor.setPlainText("수정한 메모")
    dialog.save_button.click()
    app.processEvents()

    assert dialog.isVisible()
    assert dialog.editor.isReadOnly()
    assert dialog.memo_text() == "수정한 메모"
    assert dialog.excerpt_label.text() == "메모한 문구: 본문"
    assert dialog.cancel_button.text() == "닫기"
    assert dialog.delete_button.text() == "메모\n삭제"
    assert dialog.delete_button.x() < dialog.edit_button.x()
    assert dialog.delete_button.width() == 68

    dialog.close()


def test_save_emits_memo_text_before_dialog_closes() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = MemoNoteDialog("본문", "")
    saved: list[str] = []
    dialog.memo_saved.connect(saved.append)
    dialog.editor.setPlainText("새 메모")

    dialog.save_button.click()
    app.processEvents()

    assert saved == ["새 메모"]
    assert dialog.isVisible() is False or dialog.result() == 0

    dialog.close()
