"""대화상자와 떠 있는 조문 팝업."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, QRect, QSize, Signal, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from ui.theme import detail_font
from ui.widgets import (
    PopupDragBar,
    PopupResizeHandle,
    apply_close_icon,
    favorite_icon,
)
from workers.download_worker import PdfDownloadWorker
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtWidgets import QApplication
from html import escape


def _position_dialog_beside(dialog: QDialog, anchor_rect: QRect) -> None:
    """앵커(오른쪽 띠지 표식) 옆, 화면 오른쪽에 붙여서 팝업을 띄운다."""
    width = dialog.width()
    height = dialog.height()
    x = anchor_rect.right() + 8
    y = anchor_rect.center().y() - height // 2
    screen = QApplication.screenAt(anchor_rect.center()) or QApplication.primaryScreen()
    if screen is not None:
        available = screen.availableGeometry()
        if x + width > available.right():
            x = anchor_rect.left() - width - 8
        x = max(available.left(), min(x, available.right() - width))
        y = max(available.top(), min(y, available.bottom() - height))
    dialog.move(x, y)


class PdfPreviewDialog(QDialog):
    """별표·서식 PDF를 다운로드 없이 앱 안에서 바로 보여주는 미리보기 창."""

    def __init__(self, url: str, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title or "PDF 미리보기")
        self.resize(760, 900)
        self._buffer: QBuffer | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.status_label = QLabel("PDF를 불러오는 중...")
        self.status_label.setObjectName("mutedText")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setContentsMargins(16, 40, 16, 40)
        layout.addWidget(self.status_label)

        self.document = QPdfDocument(self)
        self.pdf_view = QPdfView(self)
        self.pdf_view.setDocument(self.document)
        self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.pdf_view.hide()
        layout.addWidget(self.pdf_view, 1)

        self.worker = PdfDownloadWorker(url, self)
        self.worker.succeeded.connect(self._on_downloaded)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def _on_downloaded(self, data: bytes) -> None:
        self._buffer = QBuffer(self)
        self._buffer.setData(data)
        self._buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        status = self.document.load(self._buffer)
        if status != QPdfDocument.Error.None_:
            self.status_label.setText(f"PDF를 여는 데 실패했습니다: {status}")
            return
        self.status_label.hide()
        self.pdf_view.show()

    def _on_failed(self, message: str) -> None:
        self.status_label.setText(f"PDF 다운로드에 실패했습니다: {message}")


class InlinePdfPreviewPanel(QFrame):
    """본문 영역 안에서 높이를 제한해 보여 주는 PDF 미리보기."""

    closeRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("inlinePdfPreviewPanel")
        self.setMinimumHeight(340)
        self.setMaximumHeight(560)
        self._buffer: QBuffer | None = None
        self._expanded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        toolbar = QFrame()
        toolbar.setObjectName("inlinePdfToolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(12, 7, 8, 7)
        toolbar_layout.setSpacing(6)
        self.title_label = QLabel("별표·서식 미리보기")
        self.title_label.setObjectName("inlinePdfTitle")
        self.page_label = QLabel("")
        self.page_label.setObjectName("inlinePdfPageCount")
        self.previous_button = QPushButton("‹")
        self.previous_button.setObjectName("inlinePdfToolButton")
        self.previous_button.setFixedSize(28, 28)
        self.page_spin = QSpinBox()
        self.page_spin.setObjectName("inlinePdfPageSpin")
        self.page_spin.setRange(1, 1)
        self.page_spin.setFixedWidth(54)
        self.next_button = QPushButton("›")
        self.next_button.setObjectName("inlinePdfToolButton")
        self.next_button.setFixedSize(28, 28)
        self.zoom_spin = QSpinBox()
        self.zoom_spin.setObjectName("inlinePdfZoom")
        self.zoom_spin.setRange(40, 220)
        self.zoom_spin.setSingleStep(10)
        self.zoom_spin.setSuffix("%")
        self.zoom_spin.setValue(100)
        self.zoom_spin.setFixedWidth(76)
        self.expand_button = QPushButton("크게")
        self.expand_button.setObjectName("inlinePdfToolButton")
        self.expand_button.setFixedHeight(28)
        self.close_button = QPushButton("접기")
        self.close_button.setObjectName("inlinePdfClose")
        self.close_button.setFixedHeight(28)
        toolbar_layout.addWidget(self.title_label, 1)
        toolbar_layout.addWidget(self.page_label)
        toolbar_layout.addWidget(self.previous_button)
        toolbar_layout.addWidget(self.page_spin)
        toolbar_layout.addWidget(self.next_button)
        toolbar_layout.addWidget(self.zoom_spin)
        toolbar_layout.addWidget(self.expand_button)
        toolbar_layout.addWidget(self.close_button)
        layout.addWidget(toolbar)

        self.status_label = QLabel("PDF를 불러오는 중입니다…")
        self.status_label.setObjectName("inlinePdfStatus")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label, 1)

        self.document = QPdfDocument(self)
        self.document.statusChanged.connect(self._document_status_changed)
        self.pdf_view = QPdfView(self)
        self.pdf_view.setObjectName("inlinePdfView")
        self.pdf_view.setDocument(self.document)
        self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.pdf_view.setZoomFactor(1.0)
        self.pdf_view.hide()
        layout.addWidget(self.pdf_view, 1)

        self.zoom_spin.valueChanged.connect(
            lambda value: self.pdf_view.setZoomFactor(value / 100.0)
        )
        self.previous_button.clicked.connect(lambda: self._move_page(-1))
        self.next_button.clicked.connect(lambda: self._move_page(1))
        self.page_spin.valueChanged.connect(self._jump_to_page)
        self.pdf_view.pageNavigator().currentPageChanged.connect(
            self._current_page_changed
        )
        self.expand_button.clicked.connect(self._toggle_expanded)
        self.close_button.clicked.connect(self.closeRequested)
        self.setStyleSheet(
            "QFrame#inlinePdfPreviewPanel { background:#f1f1f1; "
            "border:1px solid #c9ccd1; }"
            "QFrame#inlinePdfToolbar { background:#34363a; border:none; }"
            "QLabel#inlinePdfTitle, QLabel#inlinePdfPageCount { color:#f5f5f5; "
            "border:none; font-weight:500; }"
            "QSpinBox#inlinePdfZoom { min-height:26px; max-height:26px; "
            "background:#fff; border:1px solid #777b82; border-radius:3px; }"
            "QPushButton#inlinePdfClose { color:#f5f5f5; background:#4a4d52; "
            "border:1px solid #656970; border-radius:3px; padding:3px 9px; }"
            "QPushButton#inlinePdfToolButton { color:#f5f5f5; "
            "background:transparent; border:1px solid #656970; "
            "border-radius:3px; padding:2px 7px; }"
            "QPushButton#inlinePdfClose:hover, QPushButton#inlinePdfToolButton:hover "
            "{ background:#5a5e64; }"
            "QSpinBox#inlinePdfPageSpin { min-height:26px; max-height:26px; "
            "background:#fff; border:1px solid #777b82; border-radius:3px; }"
            "QLabel#inlinePdfStatus { color:#59616c; border:none; }"
        )
        self.hide()

    def show_loading(self, title: str) -> None:
        self.title_label.setText(title or "별표·서식 미리보기")
        self.page_label.clear()
        self.page_spin.setRange(1, 1)
        self.document.close()
        self.pdf_view.hide()
        self.status_label.setText("PDF를 불러오는 중입니다…")
        self.status_label.show()
        self.show()

    def show_pdf(self, data: bytes, title: str = "") -> None:
        if title:
            self.title_label.setText(title)
        self._buffer = QBuffer(self)
        self._buffer.setData(bytes(data))
        self._buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        error = self.document.load(self._buffer)
        if error != QPdfDocument.Error.None_:
            self.show_error(f"PDF를 여는 데 실패했습니다: {error}")

    def show_error(self, message: str) -> None:
        self.pdf_view.hide()
        self.page_label.clear()
        self.status_label.setText(message)
        self.status_label.show()
        self.show()

    def _document_status_changed(self, status: QPdfDocument.Status) -> None:
        if status == QPdfDocument.Status.Ready:
            total = self.document.pageCount()
            self.page_label.setText(f"/ {total}" if total else "")
            self.page_spin.blockSignals(True)
            self.page_spin.setRange(1, max(1, total))
            self.page_spin.setValue(1)
            self.page_spin.blockSignals(False)
            self.status_label.hide()
            self.pdf_view.show()
        elif status == QPdfDocument.Status.Error:
            self.show_error(
                f"PDF를 여는 데 실패했습니다: {self.document.error()}"
            )

    def _move_page(self, delta: int) -> None:
        self.page_spin.setValue(self.page_spin.value() + int(delta))

    def _jump_to_page(self, page: int) -> None:
        self.pdf_view.pageNavigator().jump(
            max(0, int(page) - 1), QPointF(0, 0), self.pdf_view.zoomFactor()
        )

    def _current_page_changed(self, page: int) -> None:
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(max(1, int(page) + 1))
        self.page_spin.blockSignals(False)

    def _toggle_expanded(self) -> None:
        self._expanded = not self._expanded
        if self._expanded:
            parent_height = self.parentWidget().height() if self.parentWidget() else 700
            self.setMaximumHeight(16_777_215)
            self.setMinimumHeight(max(500, parent_height - 24))
            self.expand_button.setText("축소")
        else:
            self.setMinimumHeight(340)
            self.setMaximumHeight(560)
            self.expand_button.setText("크게")


class PdfPreviewPopup(QFrame):
    """Resizable, non-modal PDF preview tool window."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("pdfPreviewPopup")
        self.setMinimumSize(420, 320)
        self.resize(760, 900)
        self._buffer: QBuffer | None = None
        self._url = ""
        self.worker: PdfDownloadWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 10)
        layout.setSpacing(6)

        self.arrow_drag_bar = PopupDragBar(self)
        self.arrow_drag_bar.setFixedHeight(22)
        arrow_row = QHBoxLayout(self.arrow_drag_bar)
        arrow_row.setContentsMargins(0, 0, 0, 0)
        arrow_row.addSpacing(44)
        arrow = QLabel("▲")
        arrow.setObjectName("referencePopupArrow")
        arrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        arrow_row.addWidget(arrow)
        arrow_row.addStretch()
        layout.addWidget(self.arrow_drag_bar)

        self.drag_bar = PopupDragBar(self)
        self.drag_bar.setFixedHeight(38)
        header = QHBoxLayout(self.drag_bar)
        header.setContentsMargins(4, 0, 2, 0)
        self.title_label = QLabel("PDF 미리보기")
        self.title_label.setObjectName("referencePopupTitle")
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.zoom_spin = QSpinBox()
        self.zoom_spin.setRange(20, 300)
        self.zoom_spin.setSingleStep(5)
        self.zoom_spin.setSuffix("%")
        self.zoom_spin.setValue(100)
        self.zoom_spin.setFixedWidth(76)
        self.pin_button = QPushButton("고정됨")
        self.pin_button.setObjectName("referencePopupPin")
        self.pin_button.setCheckable(True)
        self.pin_button.setChecked(True)
        self.pin_button.setFixedSize(58, 30)
        self.close_button = QPushButton()
        self.close_button.setObjectName("referencePopupClose")
        apply_close_icon(self.close_button)
        self.close_button.setFixedSize(30, 30)
        header.addWidget(self.title_label, 1)
        header.addWidget(self.zoom_spin)
        header.addWidget(self.pin_button)
        header.addWidget(self.close_button)
        layout.addWidget(self.drag_bar)

        self.status_label = QLabel("PDF를 불러오는 중...")
        self.status_label.setObjectName("mutedText")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        self.document = QPdfDocument(self)
        self.document.statusChanged.connect(self._on_document_status_changed)
        self.pdf_view = QPdfView(self)
        self.pdf_view.setDocument(self.document)
        self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.pdf_view.installEventFilter(self)
        self.pdf_view.viewport().installEventFilter(self)
        self.pdf_view.hide()
        layout.addWidget(self.pdf_view, 1)

        self.zoom_spin.valueChanged.connect(
            lambda value: self.pdf_view.setZoomFactor(value / 100.0)
        )
        self.pin_button.toggled.connect(self._pin_toggled)
        self.close_button.clicked.connect(self.hide)
        self._create_resize_handles()
        self._pin_toggled(True)
        self.setStyleSheet(
            "QFrame#pdfPreviewPopup { background:#fff; border:2px solid #1670b8; border-radius:10px; }"
            "QFrame#pdfPreviewPopup QLabel { border:none; }"
        )

    def current_url(self) -> str:
        """지금 이 창이 보여 주고 있는 PDF 주소."""
        return self._url

    def show_pdf(self, url: str, title: str = "PDF 미리보기", global_position=None) -> None:
        self.title_label.setText(title or "PDF 미리보기")
        position = global_position or QCursor.pos()
        screen = QApplication.screenAt(position) or QApplication.primaryScreen()
        if screen is not None and (not self.isVisible() or not self.pin_button.isChecked()):
            area = screen.availableGeometry()
            self.move(
                max(area.left(), min(position.x() - 54, area.right() - self.width())),
                max(area.top(), min(position.y() + 6, area.bottom() - self.height())),
            )
        self.show()
        self.raise_()
        self.activateWindow()
        if url == self._url and (self.worker is not None or self.document.pageCount() > 0):
            return
        self._url = url
        self.document.close()
        self.pdf_view.hide()
        self.status_label.setText("PDF를 불러오는 중...")
        self.status_label.show()
        worker = PdfDownloadWorker(url, self)
        self.worker = worker
        worker.succeeded.connect(self._on_downloaded)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_downloaded(self, data: bytes) -> None:
        if self.sender() is not self.worker:
            return
        self._buffer = QBuffer(self)
        self._buffer.setData(data)
        self._buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self.document.load(self._buffer)
        self.worker = None

    def _on_document_status_changed(self, status: QPdfDocument.Status) -> None:
        if status == QPdfDocument.Status.Ready:
            self.status_label.hide()
            self.pdf_view.show()
        elif status == QPdfDocument.Status.Error:
            self.pdf_view.hide()
            self.status_label.setText(
                f"PDF를 여는 데 실패했습니다: {self.document.error()}"
            )
            self.status_label.show()

    def _on_failed(self, message: str) -> None:
        if self.sender() is not self.worker:
            return
        self.status_label.setText(f"PDF 다운로드에 실패했습니다: {message}")
        self.worker = None

    def _pin_toggled(self, checked: bool) -> None:
        self.pin_button.setText("고정됨" if checked else "고정")
        for handle in getattr(self, "resize_handles", []):
            handle.setVisible(checked)

    def _adjust_zoom(self, step: int) -> None:
        self.zoom_spin.setValue(self.zoom_spin.value() + step)

    def eventFilter(self, watched, event) -> bool:
        if (
            watched in (self.pdf_view, self.pdf_view.viewport())
            and event.type() == QEvent.Type.Wheel
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            delta = event.angleDelta().y()
            if delta:
                self._adjust_zoom(5 if delta > 0 else -5)
            return True
        return super().eventFilter(watched, event)

    def _create_resize_handles(self) -> None:
        specs = (
            (Qt.Edge.LeftEdge, Qt.CursorShape.SizeHorCursor),
            (Qt.Edge.RightEdge, Qt.CursorShape.SizeHorCursor),
            (Qt.Edge.TopEdge, Qt.CursorShape.SizeVerCursor),
            (Qt.Edge.BottomEdge, Qt.CursorShape.SizeVerCursor),
            (Qt.Edge.LeftEdge | Qt.Edge.TopEdge, Qt.CursorShape.SizeFDiagCursor),
            (Qt.Edge.RightEdge | Qt.Edge.TopEdge, Qt.CursorShape.SizeBDiagCursor),
            (Qt.Edge.LeftEdge | Qt.Edge.BottomEdge, Qt.CursorShape.SizeBDiagCursor),
            (Qt.Edge.RightEdge | Qt.Edge.BottomEdge, Qt.CursorShape.SizeFDiagCursor),
        )
        self.resize_handles = [PopupResizeHandle(self, edges, cursor) for edges, cursor in specs]
        self._position_resize_handles()

    def _position_resize_handles(self) -> None:
        width, height, edge, corner = self.width(), self.height(), 7, 13
        geometries = (
            (0, corner, edge, max(0, height - corner * 2)),
            (width - edge, corner, edge, max(0, height - corner * 2)),
            (corner, 0, max(0, width - corner * 2), edge),
            (corner, height - edge, max(0, width - corner * 2), edge),
            (0, 0, corner, corner),
            (width - corner, 0, corner, corner),
            (0, height - corner, corner, corner),
            (width - corner, height - corner, corner, corner),
        )
        for handle, geometry in zip(self.resize_handles, geometries):
            handle.setGeometry(*geometry)
            handle.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_resize_handles()


class MemoNoteDialog(QDialog):
    """노란 메모지 형태의 본문 메모 작성창.

    이미 저장된 메모를 다시 열면 바로 편집 상태(커서 활성화)로 뜨지
    않고 읽기 전용으로 보여주며, "수정"을 눌러야 편집할 수 있다. 새
    메모를 작성할 때만 처음부터 바로 입력할 수 있게 둔다."""

    memo_saved = Signal(str)

    def __init__(
        self, excerpt: str, initial_text: str = "", parent=None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("memoNoteDialog")
        self.setWindowTitle("본문 메모")
        self.resize(430, 300)
        self.deleted = False
        self._saved = False
        self._saved_text = initial_text.strip()
        self._has_existing_memo = bool(initial_text)
        self._editing = not self._has_existing_memo

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        title = QLabel("메모")
        title.setObjectName("memoNoteTitle")
        self.editor = QPlainTextEdit()
        self.editor.setObjectName("memoNoteEditor")
        self.editor.setPlaceholderText("이 문구에 남길 메모를 입력하세요.")
        self.editor.setPlainText(initial_text)
        normalized_excerpt = " ".join(excerpt.split())
        displayed_excerpt = (
            f"{normalized_excerpt[:120]}…"
            if len(normalized_excerpt) > 120
            else normalized_excerpt
        )
        self.excerpt_label = QLabel(
            f"메모한 문구: {displayed_excerpt or '(문구 없음)'}"
        )
        self.excerpt_label.setObjectName("memoExcerptLabel")
        self.excerpt_label.setWordWrap(True)
        self.excerpt_label.setToolTip(normalized_excerpt)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)
        self.delete_button = QPushButton("메모\n삭제")
        self.delete_button.setFixedWidth(68)
        self.delete_button.setObjectName("memoDeleteButton")
        self.delete_button.clicked.connect(self._delete_memo)
        self.edit_button = QPushButton("메모 수정")
        self.edit_button.setObjectName("memoEditButton")
        self.edit_button.clicked.connect(self._enter_edit_mode)
        self.save_button = QPushButton("메모 저장")
        self.save_button.setObjectName("memoSaveButton")
        self.save_button.clicked.connect(self._save_memo)
        self.cancel_button = QPushButton("취소")
        self.cancel_button.setObjectName("memoCancelButton")
        self.cancel_button.clicked.connect(self.reject)

        button_row.addWidget(self.delete_button)
        button_row.addStretch(1)
        button_row.addWidget(self.edit_button)
        button_row.addWidget(self.save_button)
        button_row.addWidget(self.cancel_button)

        layout.addWidget(title)
        layout.addWidget(self.excerpt_label)
        layout.addWidget(self.editor, 1)
        layout.addLayout(button_row)
        self.setStyleSheet(
            "QDialog#memoNoteDialog { background:#fff3a6; }"
            "QLabel#memoNoteTitle { background:transparent; color:#6b5200; "
            "font-size:15pt; font-weight:700; }"
            "QPlainTextEdit#memoNoteEditor { background:#fffbd8; color:#3f3520; "
            "border:1px solid #d8bd4a; border-radius:6px; padding:9px; "
            "selection-background-color:#e5bd35; }"
            "QPlainTextEdit#memoNoteEditor[readOnly=\"true\"] { "
            "background:#fff7dc; }"
            "QLabel#memoExcerptLabel { background:#fff8c9; color:#665c42; "
            "border:1px solid #dfcc72; border-radius:5px; padding:6px 8px; "
            "font-size:9pt; }"
            "QPushButton#memoSaveButton { background:#d39b13; color:white; "
            "border:1px solid #b47e08; }"
            "QPushButton#memoEditButton { background:#fff0b8; color:#6b5200; "
            "border:1px solid #d8bd4a; }"
            "QPushButton#memoDeleteButton { background:#fff7d1; color:#a12b2b; "
            "border:1px solid #dfb7a7; }"
            "QPushButton#memoCancelButton { background:#fffbe5; color:#665c42; "
            "border:1px solid #d8c982; }"
        )
        self._apply_mode()

    def _apply_mode(self) -> None:
        self.editor.setReadOnly(not self._editing)
        self.edit_button.setVisible(
            self._has_existing_memo and not self._editing
        )
        self.delete_button.setVisible(
            self._has_existing_memo and not self._editing
        )
        self.save_button.setVisible(self._editing)
        self.cancel_button.setText("취소" if self._editing else "닫기")
        if self._editing:
            self.editor.setFocus()
            self.editor.selectAll()

    def _enter_edit_mode(self) -> None:
        self._editing = True
        self._apply_mode()

    def _save_memo(self) -> None:
        self._saved_text = self.editor.toPlainText().strip()
        self._saved = True
        self._has_existing_memo = bool(self._saved_text)
        self._editing = False
        self._apply_mode()
        self.memo_saved.emit(self._saved_text)

    def _delete_memo(self) -> None:
        self.deleted = True
        self.accept()

    def reject(self) -> None:
        # 저장 버튼은 창을 닫지 않는다. 이후 닫기/X를 누르면 마지막으로
        # 저장한 값만 호출자에게 전달하고 저장하지 않은 편집 내용은 버린다.
        if self._saved:
            self.accept()
            return
        super().reject()

    def memo_text(self) -> str:
        if self.deleted:
            return ""
        if self._saved:
            return self._saved_text
        return self.editor.toPlainText().strip()


class LawReferencePopup(QFrame):
    """법령 인용 링크의 조항목 API 결과를 표시하는 고정 가능 팝업."""

    refreshRequested = Signal(object)
    favoriteRequested = Signal(object)

    def __init__(self, link_handler, parent=None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint,
        )
        self.setObjectName("lawReferencePopup")
        self.reference_key = ""
        self.reference_request: dict[str, str] = {}
        self.favorite_checker = None
        self.hover_guard = None
        self._content_generation = 0
        self._restoring_scroll = False
        self.setMinimumSize(320, 220)
        self.resize(440, 300)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 10)
        layout.setSpacing(6)

        self.arrow_drag_bar = PopupDragBar(self)
        arrow_row = QHBoxLayout(self.arrow_drag_bar)
        arrow_row.setContentsMargins(0, 0, 0, 0)
        arrow_row.addSpacing(44)
        arrow = QLabel("▲")
        arrow.setObjectName("referencePopupArrow")
        arrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        arrow_row.addWidget(arrow)
        arrow_row.addStretch()
        layout.addWidget(self.arrow_drag_bar)

        self.drag_bar = PopupDragBar(self)
        header = QHBoxLayout(self.drag_bar)
        header.setContentsMargins(4, 0, 2, 0)
        self.title_label = QLabel("인용 조문")
        self.title_label.setObjectName("referencePopupTitle")
        self.title_label.setWordWrap(True)
        self.title_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self.pin_button = QPushButton("고정")
        self.pin_button.setObjectName("referencePopupPin")
        self.pin_button.setCheckable(True)
        self.pin_button.setFixedSize(58, 30)
        self.pin_button.setToolTip(
            "팝업을 고정하면 이동하거나 크기를 조절할 수 있습니다."
        )
        self.refresh_button = QPushButton("API갱신")
        self.refresh_button.setObjectName("referencePopupRefresh")
        self.refresh_button.setFixedSize(66, 30)
        self.refresh_button.setToolTip(
            "저장된 조문을 사용하지 않고 같은 조문을 API에서 다시 불러옵니다."
        )
        self.refresh_button.setEnabled(False)
        self.favorite_button = QPushButton()
        self.favorite_button.setObjectName("referencePopupFavorite")
        self.favorite_button.setIconSize(QSize(16, 16))
        self.favorite_button.setFixedSize(34, 30)
        self.favorite_button.setEnabled(False)
        self.favorite_button.setToolTip("이 조항호목을 즐겨찾기에 추가합니다.")
        self.close_button = QPushButton()
        self.close_button.setObjectName("referencePopupClose")
        apply_close_icon(self.close_button)
        self.close_button.setFixedSize(30, 30)
        header.addWidget(self.title_label, 1)
        header.addWidget(self.favorite_button)
        header.addWidget(self.refresh_button)
        header.addWidget(self.pin_button)
        header.addWidget(self.close_button)
        # 레이아웃에 넣으면서 버튼의 부모가 이동 영역으로 바뀐 뒤에
        # 지정해야 십자 이동 커서를 상속하지 않는다.
        for button in (
            self.favorite_button,
            self.refresh_button,
            self.pin_button,
            self.close_button,
        ):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.drag_bar)

        self.browser = QTextBrowser()
        self.browser.setObjectName("referencePopupBrowser")
        browser_font = detail_font()
        self.browser.setFont(browser_font)
        self.browser.document().setDefaultFont(browser_font)
        self.browser.setOpenExternalLinks(False)
        self.browser.setOpenLinks(False)
        self.browser.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self.browser.anchorClicked.connect(link_handler)
        layout.addWidget(self.browser, 1)

        self.dismiss_timer = QTimer(self)
        self.dismiss_timer.setSingleShot(True)
        self.dismiss_timer.timeout.connect(self._hide_if_unpinned)
        self.pin_button.toggled.connect(self._pin_toggled)
        self.refresh_button.clicked.connect(
            lambda: self.refreshRequested.emit(self)
        )
        self.favorite_button.clicked.connect(
            lambda: self.favoriteRequested.emit(self)
        )
        self.close_button.clicked.connect(self._close_popup)
        self._create_resize_handles()

    def _create_resize_handles(self) -> None:
        handle_specs = (
            (Qt.Edge.LeftEdge, Qt.CursorShape.SizeHorCursor),
            (Qt.Edge.RightEdge, Qt.CursorShape.SizeHorCursor),
            (Qt.Edge.TopEdge, Qt.CursorShape.SizeVerCursor),
            (Qt.Edge.BottomEdge, Qt.CursorShape.SizeVerCursor),
            (
                Qt.Edge.LeftEdge | Qt.Edge.TopEdge,
                Qt.CursorShape.SizeFDiagCursor,
            ),
            (
                Qt.Edge.RightEdge | Qt.Edge.TopEdge,
                Qt.CursorShape.SizeBDiagCursor,
            ),
            (
                Qt.Edge.LeftEdge | Qt.Edge.BottomEdge,
                Qt.CursorShape.SizeBDiagCursor,
            ),
            (
                Qt.Edge.RightEdge | Qt.Edge.BottomEdge,
                Qt.CursorShape.SizeFDiagCursor,
            ),
        )
        self.resize_handles = [
            PopupResizeHandle(self, edges, cursor)
            for edges, cursor in handle_specs
        ]
        # 기존 내부 참조와의 호환을 위해 우하단 핸들을 같은 이름으로 유지.
        self.size_grip = self.resize_handles[-1]
        self._position_resize_handles()

    def _position_resize_handles(self) -> None:
        if not hasattr(self, "resize_handles"):
            return
        width = self.width()
        height = self.height()
        edge = 7
        corner = 13
        geometries = (
            (0, corner, edge, max(0, height - corner * 2)),
            (width - edge, corner, edge, max(0, height - corner * 2)),
            (corner, 0, max(0, width - corner * 2), edge),
            (corner, height - edge, max(0, width - corner * 2), edge),
            (0, 0, corner, corner),
            (width - corner, 0, corner, corner),
            (0, height - corner, corner, corner),
            (width - corner, height - corner, corner, corner),
        )
        for handle, geometry in zip(self.resize_handles, geometries):
            handle.setGeometry(*geometry)
            handle.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_resize_handles()

    def show_loading(
        self,
        title: str,
        global_position,
        message: str = "조항목 API에서 불러오는 중입니다…",
    ) -> None:
        self.set_loading(title, message)
        self.show_at(global_position)
        if not self.pin_button.isChecked():
            self.dismiss_timer.start(1500)

    def set_loading(self, title: str, message: str) -> None:
        """Show loading content without changing the popup position."""
        self._content_generation += 1
        self._restoring_scroll = False
        self.refresh_button.setEnabled(False)
        self._refresh_favorite_button()
        self.title_label.setText(title)
        self.browser.setHtml(
            '<div style="font-family:Malgun Gothic; color:#526176; '
            f'padding:18px;">{escape(message)}</div>'
        )

    def show_at(self, global_position) -> None:
        self.arrow_drag_bar.show()
        if not self.pin_button.isChecked() or not self.isVisible():
            screen = (
                QApplication.screenAt(global_position)
                or QApplication.primaryScreen()
            )
            available = screen.availableGeometry()
            x = max(
                available.left(),
                min(global_position.x() - 54, available.right() - self.width()),
            )
            y = max(
                available.top(),
                min(global_position.y() + 6, available.bottom() - self.height()),
            )
            self.move(x, y)
        self.show()
        self.raise_()

    def show_content_at(
        self,
        title: str,
        html: str,
        global_position,
        *,
        scroll_position: int = 0,
        scroll_anchor: str = "",
    ) -> None:
        self.set_content(
            title,
            html,
            scroll_position=scroll_position,
            scroll_anchor=scroll_anchor,
        )
        self.show_at(global_position)
        if not self.pin_button.isChecked():
            self.dismiss_timer.start(1500)

    def show_content_above(
        self,
        title: str,
        html: str,
        anchor_rect: QRect,
        *,
        scroll_position: int = 0,
    ) -> None:
        """하단 기록 탭에서 다시 열 때: 화살표 없이 그 탭 바로 위에 붙여서 표시."""
        self.set_content(title, html, scroll_position=scroll_position)
        self.arrow_drag_bar.hide()
        screen = (
            QApplication.screenAt(anchor_rect.center())
            or QApplication.primaryScreen()
        )
        available = screen.availableGeometry()
        x = max(
            available.left(),
            min(anchor_rect.left(), available.right() - self.width()),
        )
        y = max(available.top(), anchor_rect.top() - self.height())
        self.move(x, y)
        self.show()
        self.raise_()
        if not self.pin_button.isChecked():
            self.dismiss_timer.start(1500)

    def set_content(
        self,
        title: str,
        html: str,
        *,
        scroll_position: int = 0,
        scroll_anchor: str = "",
    ) -> None:
        self.title_label.setText(title)
        self.refresh_button.setEnabled(bool(self.reference_request))
        self._refresh_favorite_button()
        self._content_generation += 1
        generation = self._content_generation
        self._restoring_scroll = True
        self.browser.setHtml(html)
        QTimer.singleShot(
            0,
            lambda: self._restore_content_scroll(
                generation, scroll_position, scroll_anchor
            ),
        )

    def _restore_content_scroll(
        self, generation: int, position: int, anchor: str = ""
    ) -> None:
        if generation != self._content_generation:
            return
        scroll_bar = self.browser.verticalScrollBar()
        # 저장해 둔 위치가 있으면 그것이 우선이다. 처음 여는 화면에서만
        # 닻으로 이동해, 다시 열 때 보던 자리를 잃지 않는다.
        if anchor and not position:
            self.browser.scrollToAnchor(anchor)
        else:
            scroll_bar.setValue(
                max(0, min(int(position), scroll_bar.maximum()))
            )
        self._restoring_scroll = False

    def set_error(self, message: str) -> None:
        self._content_generation += 1
        self._restoring_scroll = False
        self.refresh_button.setEnabled(bool(self.reference_request))
        self._refresh_favorite_button()
        self.browser.setHtml(
            '<div style="font-family:Malgun Gothic; color:#a12b2b; '
            f'padding:18px;">{escape(message)}</div>'
        )

    def _refresh_favorite_button(self) -> None:
        request = self.reference_request
        available = bool(request.get("law_id") and request.get("jo"))
        favorite = False
        if available and self.favorite_checker is not None:
            try:
                favorite = bool(self.favorite_checker(request))
            except Exception:  # noqa: BLE001 - 별표 확인 실패는 팝업을 막지 않는다.
                favorite = False
        self.favorite_button.setEnabled(available)
        self.favorite_button.setText("")
        self.favorite_button.setIcon(
            favorite_icon(
                favorite,
                "#c88700" if favorite else "#aeb4bc",
            )
        )
        self.favorite_button.setProperty("favorite", favorite)
        self.favorite_button.setToolTip(
            "이 조항호목을 즐겨찾기에서 해제합니다."
            if favorite
            else "이 조항호목을 즐겨찾기에 추가합니다."
        )
        self.favorite_button.style().unpolish(self.favorite_button)
        self.favorite_button.style().polish(self.favorite_button)

    def set_favorite_pending(self) -> None:
        """본문 저장을 기다리는 동안 클릭이 접수됐음을 표시한다."""
        self.favorite_button.setEnabled(False)
        self.favorite_button.setText("…")
        self.favorite_button.setToolTip(
            "진행 중인 조회가 끝나면 이 조항호목을 즐겨찾기에 추가합니다."
        )

    def enterEvent(self, event) -> None:
        self.dismiss_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if not self.pin_button.isChecked():
            self.dismiss_timer.start(300)
        super().leaveEvent(event)

    def _pin_toggled(self, checked: bool) -> None:
        self.pin_button.setText("고정됨" if checked else "고정")
        self.pin_button.setToolTip(
            "고정을 풀면 팝업 바깥으로 마우스를 옮길 때 사라집니다."
            if checked
            else "팝업을 고정하면 이동하거나 크기를 조절할 수 있습니다."
        )
        # 제목줄은 고정 여부와 관계없이 실제로 끌어 옮길 수 있다.
        # 십자 화살표도 항상 유지해 이 동작을 바로 알 수 있게 한다.
        self.drag_bar.setCursor(Qt.CursorShape.SizeAllCursor)
        self.arrow_drag_bar.setCursor(Qt.CursorShape.SizeAllCursor)
        for handle in self.resize_handles:
            handle.setVisible(checked)
            if checked:
                handle.raise_()
        if checked:
            self.dismiss_timer.stop()
        elif not self.underMouse():
            self.dismiss_timer.start(300)

    def _hide_if_unpinned(self) -> None:
        if self.pin_button.isChecked() or self.underMouse():
            return
        keep = self.frameGeometry().adjusted(-16, -48, 16, 12)
        try:
            source_is_hovered = bool(self.hover_guard and self.hover_guard())
        except (RuntimeError, TypeError):
            source_is_hovered = False
        if source_is_hovered or keep.contains(QCursor.pos()):
            self.dismiss_timer.start(250)
            return
        self.hide()

    def _close_popup(self) -> None:
        self.pin_button.setChecked(False)
        self.hide()
