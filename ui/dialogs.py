"""대화상자와 떠 있는 조문 팝업."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import (
    QBuffer,
    QEvent,
    QIODevice,
    QPointF,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QCursor, QPixmap, QTextCursor
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ui.assets import SPIN_DOWN_ICON_PATH, SPIN_UP_ICON_PATH
from ui.theme import detail_font
from ui.widgets import (
    DETAIL_FONT_SIZE_STEP,
    DetailSearchBar,
    PopupDragBar,
    PopupResizeHandle,
    apply_close_icon,
    favorite_icon,
    normalize_detail_font_size,
)
from utils.constants import DEFAULT_POPUP_FONT_POINT
from workers.download_worker import PdfDownloadWorker


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
    """본문 영역 안에서 PDF 또는 변환 이미지를 보여 주는 미리보기."""

    closeRequested = Signal()

    # 도구줄에 서는 칸ㆍ단추의 공통 높이. 본문 글자 크기 조절칸(28px)의
    # 절반에 가깝게 두어 검은 띠가 종이를 덜 가리게 한다.
    TOOL_HEIGHT = 22

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("inlinePdfPreviewPanel")
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        self.setFixedHeight(340)
        self._buffer: QBuffer | None = None
        self._expanded = False
        self._mode = "pdf"
        self._image_pages: list[QPixmap] = []
        self._image_labels: list[QLabel] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        toolbar = QFrame()
        toolbar.setObjectName("inlinePdfToolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        # 도구줄은 얇게. 원문을 보는 자리가 본체이므로 검은 띠가 두꺼우면
        # 그만큼 종이가 가려진다.
        toolbar_layout.setContentsMargins(10, 3, 6, 3)
        toolbar_layout.setSpacing(5)
        # 제목은 두지 않는다. 바로 위 별표 목록 줄에 같은 제목이 이미
        # 있고, 도구줄 폭을 다 차지해 흰 상자처럼 보였다.
        self._title = ""
        self.page_spin = QSpinBox()
        self.page_spin.setObjectName("inlinePdfPageSpin")
        self.page_spin.setRange(1, 1)
        # 숫자만 있으면 무슨 값인지 알기 어렵다. 쪽수라는 것을 붙여 둔다.
        self.page_spin.setSuffix("p")
        self.page_spin.setFixedSize(58, self.TOOL_HEIGHT)
        self.zoom_spin = QSpinBox()
        self.zoom_spin.setObjectName("inlinePdfZoom")
        self.zoom_spin.setRange(40, 220)
        self.zoom_spin.setSingleStep(10)
        self.zoom_spin.setSuffix("%")
        self.zoom_spin.setValue(100)
        self.zoom_spin.setFixedSize(72, self.TOOL_HEIGHT)
        self.expand_button = QPushButton("크게")
        self.expand_button.setObjectName("inlinePdfToolButton")
        self.expand_button.setFixedHeight(self.TOOL_HEIGHT)
        self.close_button = QPushButton("접기")
        self.close_button.setObjectName("inlinePdfClose")
        self.close_button.setFixedHeight(self.TOOL_HEIGHT)
        # 쪽 이동은 스핀 상자의 위아래 화살표만으로 한다. ‹ › 단추는
        # 같은 일을 두 번 두는 것이라 뺐다.
        toolbar_layout.addStretch(1)
        toolbar_layout.addWidget(self.page_spin)
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
        self.pdf_view.installEventFilter(self)
        self.pdf_view.viewport().installEventFilter(self)
        self.pdf_view.hide()
        layout.addWidget(self.pdf_view, 1)

        self.image_scroll = QScrollArea(self)
        self.image_scroll.setObjectName("inlineAnnexImageScroll")
        self.image_scroll.setWidgetResizable(True)
        self.image_scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.image_container = QWidget()
        self.image_layout = QVBoxLayout(self.image_container)
        self.image_layout.setContentsMargins(8, 8, 8, 8)
        self.image_layout.setSpacing(10)
        self.image_layout.addStretch(1)
        self.image_scroll.setWidget(self.image_container)
        self.image_scroll.hide()
        layout.addWidget(self.image_scroll, 1)

        self.zoom_spin.valueChanged.connect(self._set_zoom)
        self.page_spin.valueChanged.connect(self._jump_to_page)
        self.pdf_view.pageNavigator().currentPageChanged.connect(
            self._current_page_changed
        )
        self.expand_button.clicked.connect(self._toggle_expanded)
        self.close_button.clicked.connect(self.closeRequested)
        # 숫자칸의 위아래 화살표는 본문 글자 크기 조절칸과 같은 모양으로
        # 둔다. 같은 일을 하는 칸이 화면마다 다르게 생기지 않게 한다.
        height = self.TOOL_HEIGHT
        # 1px 테두리 안쪽 높이(20px)를 정확히 반으로 나눈다. 기존 10px
        # 버튼 두 개에 각 경계선까지 더해져 화살표 영역이 상자 밖으로 샜다.
        arrow_height = max(8, (height - 4) // 2)
        self.setStyleSheet(
            "QFrame#inlinePdfPreviewPanel { background:#f1f1f1; "
            "border:1px solid #c9ccd1; }"
            "QFrame#inlinePdfToolbar { background:#34363a; border:none; }"
            "QPushButton#inlinePdfClose { color:#f5f5f5; background:#4a4d52; "
            f"border:1px solid #656970; border-radius:3px; padding:0 9px; "
            f"min-height:{height}px; max-height:{height}px; }}"
            "QPushButton#inlinePdfToolButton { color:#f5f5f5; "
            "background:transparent; border:1px solid #656970; "
            f"border-radius:3px; padding:0 7px; "
            f"min-height:{height}px; max-height:{height}px; }}"
            "QPushButton#inlinePdfClose:hover, QPushButton#inlinePdfToolButton:hover "
            "{ background:#5a5e64; }"
            "QSpinBox#inlinePdfPageSpin, QSpinBox#inlinePdfZoom { "
            "background:#fff; border:1px solid #777b82; border-radius:3px; "
            "padding:0 17px 0 5px; font-size:8pt; }"
            "QSpinBox#inlinePdfPageSpin::up-button, "
            "QSpinBox#inlinePdfZoom::up-button { "
            "subcontrol-origin:padding; subcontrol-position:top right; "
            f"width:15px; height:{arrow_height}px; background:#f4f7fa; "
            "border-left:1px solid #cfd8e3; border-bottom:1px solid #dbe3eb; "
            "border-top-right-radius:2px; }"
            "QSpinBox#inlinePdfPageSpin::down-button, "
            "QSpinBox#inlinePdfZoom::down-button { "
            "subcontrol-origin:padding; subcontrol-position:bottom right; "
            f"width:15px; height:{arrow_height}px; background:#f4f7fa; "
            "border-left:1px solid #cfd8e3; border-top:1px solid #dbe3eb; "
            "border-bottom-right-radius:2px; }"
            "QSpinBox#inlinePdfPageSpin::up-button:hover, "
            "QSpinBox#inlinePdfZoom::up-button:hover, "
            "QSpinBox#inlinePdfPageSpin::down-button:hover, "
            "QSpinBox#inlinePdfZoom::down-button:hover { background:#e8f1fb; }"
            "QSpinBox#inlinePdfPageSpin::up-arrow, "
            "QSpinBox#inlinePdfZoom::up-arrow { "
            f'image:url("{SPIN_UP_ICON_PATH.as_posix()}"); '
            "width:8px; height:5px; }"
            "QSpinBox#inlinePdfPageSpin::down-arrow, "
            "QSpinBox#inlinePdfZoom::down-arrow { "
            f'image:url("{SPIN_DOWN_ICON_PATH.as_posix()}"); '
            "width:8px; height:5px; }"
            "QSpinBox#inlinePdfPageSpin QLineEdit, "
            "QSpinBox#inlinePdfZoom QLineEdit { min-height:0; border:none; "
            "background:transparent; padding:0; }"
            "QLabel#inlinePdfStatus { color:#59616c; border:none; }"
        )
        self.hide()

    def current_title(self) -> str:
        """지금 보여 주는 별표 제목. 화면에는 그리지 않고 기록만 한다."""
        return self._title

    def show_loading(self, title: str) -> None:
        self._title = title or "별표·서식 미리보기"
        self.page_spin.setRange(1, 1)
        self.document.close()
        self.pdf_view.hide()
        self.image_scroll.hide()
        self.status_label.setText("원문 미리보기를 불러오는 중입니다…")
        self.status_label.show()
        # 위치는 본문 쪽 `_place_inline_annex_preview`가 잡은 뒤에만
        # 보이게 한다. 여기서 show()하면 뷰포트 전체를 덮는다.

    def show_pdf(self, data: bytes, title: str = "") -> None:
        self._mode = "pdf"
        self.image_scroll.hide()
        if title:
            self._title = title
        self._buffer = QBuffer(self)
        self._buffer.setData(bytes(data))
        self._buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        error = self.document.load(self._buffer)
        # load()가 비동기로 끝나 None을 주는 경우가 있다. 그때를 실패로
        # 보면 "PDF를 여는 데 실패했습니다: None"이 뜨고, 실제 결과는
        # statusChanged가 나중에 알려 준다.
        if error is not None and error != QPdfDocument.Error.None_:
            self.show_error(f"PDF를 여는 데 실패했습니다: {error}")

    def show_error(self, message: str) -> None:
        self.pdf_view.hide()
        self.image_scroll.hide()
        self.status_label.setText(message)
        self.status_label.show()

    def _document_status_changed(self, status: QPdfDocument.Status) -> None:
        if status == QPdfDocument.Status.Ready:
            total = self.document.pageCount()
            self.page_spin.blockSignals(True)
            self.page_spin.setRange(1, max(1, total))
            self.page_spin.setValue(1)
            self.page_spin.blockSignals(False)
            self.page_spin.setToolTip(
                f"보고 있는 쪽 (전체 {total}쪽)" if total else "보고 있는 쪽"
            )
            self.status_label.hide()
            self.pdf_view.show()
        elif status == QPdfDocument.Status.Error:
            self.show_error(
                f"PDF를 여는 데 실패했습니다: {self.document.error()}"
            )

    def show_images(
        self, pages: list[bytes], title: str = "", *, total: int = 0
    ) -> None:
        """법제처 문서뷰어가 변환한 자치법규 별표 쪽을 표시한다."""
        if title:
            self._title = title
        self._mode = "images"
        self.document.close()
        self.pdf_view.hide()
        for label in self._image_labels:
            self.image_layout.removeWidget(label)
            label.deleteLater()
        self._image_labels.clear()
        self._image_pages.clear()
        for data in pages:
            pixmap = QPixmap()
            if not pixmap.loadFromData(bytes(data)):
                continue
            label = QLabel()
            label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            label.setObjectName("inlineAnnexImagePage")
            self.image_layout.insertWidget(self.image_layout.count() - 1, label)
            self._image_pages.append(pixmap)
            self._image_labels.append(label)
        if not self._image_pages:
            self.show_error("자치법규 별표 이미지를 열지 못했습니다.")
            return
        loaded = len(self._image_pages)
        self.page_spin.blockSignals(True)
        self.page_spin.setRange(1, loaded)
        self.page_spin.setValue(1)
        self.page_spin.blockSignals(False)
        whole = max(loaded, int(total or 0))
        self.page_spin.setToolTip(
            f"보고 있는 쪽 (전체 {whole}쪽)"
            + (f" · 앞 {loaded}쪽 표시" if whole > loaded else "")
        )
        # 크기를 먼저 재면 아직 감춰져 있는 스크롤 칸의 기본 폭(100px)에
        # 맞춰 그림이 아주 작게 들어간다. 예전에는 확대ㆍ축소를 한 번
        # 눌러야 제 크기가 됐다. 보이게 한 뒤에 재고, 배치가 끝난 다음
        # 한 번 더 맞춘다.
        self.status_label.hide()
        self.image_scroll.show()
        self._refresh_image_sizes()
        QTimer.singleShot(0, self._refresh_image_sizes)

    def _set_zoom(self, value: int) -> None:
        if self._mode == "images":
            self._refresh_image_sizes()
        else:
            self.pdf_view.setZoomFactor(value / 100.0)

    def _refresh_image_sizes(self) -> None:
        if not self._image_pages:
            return
        available = max(80, self.image_scroll.viewport().width() - 20)
        zoom = self.zoom_spin.value() / 100.0
        for pixmap, label in zip(self._image_pages, self._image_labels):
            fit = min(1.0, available / max(1, pixmap.width()))
            width = max(1, int(pixmap.width() * fit * zoom))
            label.setPixmap(
                pixmap.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
            )

    def _jump_to_page(self, page: int) -> None:
        if self._mode == "images":
            index = max(0, min(len(self._image_labels) - 1, int(page) - 1))
            if self._image_labels:
                self.image_scroll.ensureWidgetVisible(
                    self._image_labels[index], 0, 0
                )
            return
        self.pdf_view.pageNavigator().jump(
            max(0, int(page) - 1), QPointF(0, 0), self.pdf_view.zoomFactor()
        )

    def _current_page_changed(self, page: int) -> None:
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(max(1, int(page) + 1))
        self.page_spin.blockSignals(False)

    def eventFilter(self, watched, event) -> bool:
        if (
            watched in (self.pdf_view, self.pdf_view.viewport())
            and event.type() == QEvent.Type.Wheel
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            delta = event.angleDelta().y()
            if delta:
                self.zoom_spin.setValue(
                    self.zoom_spin.value() + (10 if delta > 0 else -10)
                )
            return True
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._mode == "images":
            self._refresh_image_sizes()

    def _toggle_expanded(self) -> None:
        # 부모는 본문 뷰포트다. 예전처럼 parent.height()-24를 쓰면
        # 미리보기가 문서 전체를 덮고, 자리 표시 높이도 같이 커져
        # 본문을 밀어 낸다. 크게 보기는 기본 높이의 정확히 두 배다.
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        """미리보기 높이를 기본 또는 크게 상태로 명시해서 맞춘다."""
        self._expanded = bool(expanded)
        self.setFixedHeight(680 if self._expanded else 340)
        self.expand_button.setText("축소" if self._expanded else "크게")


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

        # 자치법규 별표처럼 PDF가 없는 자료는 법제처 뷰어가 변환한 쪽
        # 그림으로 온다. 같은 창에서 그대로 보여 준다.
        self._mode = "pdf"
        self._image_pages: list[QPixmap] = []
        self._image_labels: list[QLabel] = []
        self.image_scroll = QScrollArea(self)
        self.image_scroll.setWidgetResizable(True)
        self.image_scroll.setFrameShape(QFrame.Shape.NoFrame)
        image_holder = QWidget()
        self.image_layout = QVBoxLayout(image_holder)
        self.image_layout.setContentsMargins(0, 0, 0, 0)
        self.image_layout.setSpacing(8)
        self.image_layout.addStretch(1)
        self.image_scroll.setWidget(image_holder)
        self.image_scroll.hide()
        layout.addWidget(self.image_scroll, 1)

        self.zoom_spin.valueChanged.connect(self._zoom_changed)
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

    def _zoom_changed(self, value: int) -> None:
        if self._mode == "images":
            self._refresh_image_sizes()
        else:
            self.pdf_view.setZoomFactor(value / 100.0)

    def _refresh_image_sizes(self) -> None:
        if not self._image_pages:
            return
        available = max(80, self.image_scroll.viewport().width() - 20)
        zoom = self.zoom_spin.value() / 100.0
        for pixmap, label in zip(self._image_pages, self._image_labels):
            fit = min(1.0, available / max(1, pixmap.width()))
            width = max(1, int(pixmap.width() * fit * zoom))
            label.setPixmap(
                pixmap.scaledToWidth(
                    width, Qt.TransformationMode.SmoothTransformation
                )
            )

    def place_at(self, global_position=None) -> None:
        """창을 커서 옆에 세운다(고정해 둔 창은 자리를 지킨다)."""
        position = global_position or QCursor.pos()
        screen = QApplication.screenAt(position) or QApplication.primaryScreen()
        if screen is not None and (
            not self.isVisible() or not self.pin_button.isChecked()
        ):
            area = screen.availableGeometry()
            self.move(
                max(
                    area.left(),
                    min(position.x() - 54, area.right() - self.width()),
                ),
                max(
                    area.top(),
                    min(position.y() + 6, area.bottom() - self.height()),
                ),
            )
        self.show()
        self.raise_()
        self.activateWindow()

    def show_loading(self, title: str, global_position=None) -> None:
        """받는 동안 빈 창을 먼저 띄운다."""
        self.title_label.setText(title or "별표 미리보기")
        self._mode = "loading"
        self.pdf_view.hide()
        self.image_scroll.hide()
        self.status_label.setText("별표를 불러오는 중...")
        self.status_label.show()
        self.place_at(global_position)

    def show_images(
        self,
        pages: list[bytes],
        title: str = "별표 미리보기",
        *,
        total: int = 0,
        global_position=None,
        url: str = "",
    ) -> None:
        """법제처 뷰어가 변환한 쪽 그림을 보여 준다."""
        self.title_label.setText(title or "별표 미리보기")
        self._url = url
        self._mode = "images"
        self.document.close()
        self.pdf_view.hide()
        for label in self._image_labels:
            self.image_layout.removeWidget(label)
            label.deleteLater()
        self._image_labels.clear()
        self._image_pages.clear()
        for data in pages:
            pixmap = QPixmap()
            if not pixmap.loadFromData(bytes(data)):
                continue
            label = QLabel()
            label.setAlignment(
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
            )
            self.image_layout.insertWidget(
                self.image_layout.count() - 1, label
            )
            self._image_pages.append(pixmap)
            self._image_labels.append(label)
        if not self._image_pages:
            self.show_message("별표 그림을 열지 못했습니다.")
            return
        whole = max(len(self._image_pages), int(total or 0))
        if whole > len(self._image_pages):
            self.title_label.setText(
                f"{title} · 앞 {len(self._image_pages)}쪽 (전체 {whole}쪽)"
            )
        self.status_label.hide()
        self.image_scroll.show()
        self._refresh_image_sizes()
        QTimer.singleShot(0, self._refresh_image_sizes)
        self.place_at(global_position)

    def show_message(self, message: str) -> None:
        self.pdf_view.hide()
        self.image_scroll.hide()
        self.status_label.setText(message)
        self.status_label.show()

    def show_pdf(self, url: str, title: str = "PDF 미리보기", global_position=None) -> None:
        self._mode = "pdf"
        self.image_scroll.hide()
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

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 규약)
        super().resizeEvent(event)
        if self._mode == "images":
            self._refresh_image_sizes()

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


class DetachedDocumentWindow(QWidget):
    """열린 본문 탭을 창 밖으로 꺼내 따로 띄우는 크게 보기 창.

    본문 화면과 같은 HTML을 그대로 보여 주고, 인용 링크는 원래 화면이
    처리하도록 넘긴다. 창 안에서도 Ctrl+F로 찾을 수 있다.
    """

    def __init__(
        self,
        title: str,
        html: str,
        link_handler,
        font,
        parent=None,
    ) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.setObjectName("detachedDocumentWindow")
        self.setWindowTitle(title)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(980, 720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(6)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("detachedDocumentTitle")
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        self.browser = QTextBrowser()
        self.browser.setObjectName("detachedDocumentBrowser")
        self.browser.setFont(font)
        self.browser.document().setDefaultFont(font)
        self.browser.setOpenExternalLinks(False)
        self.browser.setOpenLinks(False)
        self.browser.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        if link_handler is not None:
            self.browser.anchorClicked.connect(link_handler)
        self.browser.setHtml(html)
        layout.addWidget(self.browser, 1)

        # 본문 화면과 같은 찾기 창을 이 창에도 붙인다.
        self.search_bar = DetailSearchBar(self.browser, self)

        # 본문 화면처럼 조문 왼쪽에 즐겨찾기 별, 오른쪽에 3단비교 단추를
        # 얹는다. attach_article_controls를 부르기 전에는 비어 있다.
        self._article_entries: list[dict[str, object]] = []
        self._article_anchor_positions: dict[str, int] = {}
        self._favorite_buttons: list[QPushButton] = []
        self._three_stage_buttons: list[QPushButton] = []
        self._favorite_state = None
        self._favorite_icon_for = None
        self._star_size = 18
        self._three_stage_width = 44
        self._article_layout_pending = False
        self.browser.verticalScrollBar().valueChanged.connect(
            lambda _value=0: self._schedule_article_layout()
        )

    def scroll_to(self, position: int) -> None:
        scroll_bar = self.browser.verticalScrollBar()
        scroll_bar.setValue(max(0, min(int(position), scroll_bar.maximum())))

    # ---- 조문 별표ㆍ3단비교 단추 -------------------------------------
    def attach_article_controls(
        self,
        articles: list[dict[str, object]],
        *,
        favorite_clicked,
        three_stage_clicked,
        favorite_state,
        favorite_icon_for,
        star_size: int,
        three_stage_width: int,
    ) -> None:
        """본문 화면과 같은 조문 별표ㆍ3단비교 단추를 이 창에도 얹는다.

        `articles`는 본문 화면이 쓰는 것과 같은 모양이다(anchor·label·jo·
        law_id·law_name·comparison_available). 누르면 본체 화면의 처리를
        그대로 부르므로 즐겨찾기와 3단비교 팝업은 한 곳에서만 관리된다.
        """
        self._clear_article_controls()
        self._article_entries = [
            dict(article)
            for article in articles
            if isinstance(article, dict) and article.get("anchor")
        ]
        self._favorite_state = favorite_state
        self._favorite_icon_for = favorite_icon_for
        self._star_size = int(star_size)
        self._three_stage_width = int(three_stage_width)
        if not self._article_entries:
            return

        # 3단 단추가 본문 글자와 겹치지 않게 오른쪽에 자리를 낸다.
        root_frame = self.browser.document().rootFrame()
        frame_format = root_frame.frameFormat()
        frame_format.setRightMargin(float(self._three_stage_width + 24))
        root_frame.setFrameFormat(frame_format)

        self._article_anchor_positions = self._find_anchor_positions(
            {str(article["anchor"]) for article in self._article_entries}
        )
        viewport = self.browser.viewport()
        for article in self._article_entries:
            star = QPushButton(viewport)
            star.setObjectName("articleFavoriteButton")
            star.setFixedSize(self._star_size, self._star_size)
            star.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            star.setCursor(Qt.CursorShape.PointingHandCursor)
            star.setIconSize(QSize(16, 16))
            star.clicked.connect(
                lambda _checked=False, item=dict(article): favorite_clicked(
                    item
                )
            )
            star.hide()
            self._favorite_buttons.append(star)

            button = QPushButton("3단", viewport)
            button.setObjectName("threeStageArticleButton")
            button.setFixedSize(self._three_stage_width, 24)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(
                f"{article.get('label') or '이 조문'}의 법률·시행령·"
                "시행규칙을 3단으로 비교합니다."
            )
            button.clicked.connect(
                lambda _checked=False, item=dict(article): (
                    three_stage_clicked(item)
                )
            )
            button.hide()
            self._three_stage_buttons.append(button)
        self.refresh_article_favorites()
        self._schedule_article_layout()

    def refresh_article_favorites(self) -> None:
        """별표 색과 안내를 지금 즐겨찾기 상태에 맞춘다."""
        if self._favorite_state is None or self._favorite_icon_for is None:
            return
        star_size = self._star_size
        for article, button in zip(
            self._article_entries, self._favorite_buttons
        ):
            favorite = bool(self._favorite_state(article))
            button.setIcon(self._favorite_icon_for(favorite))
            label = str(article.get("label") or "이 조문")
            button.setToolTip(
                f"{label} 즐겨찾기를 "
                + ("해제합니다." if favorite else "추가합니다.")
            )
            button.setAccessibleName(button.toolTip())
            button.setStyleSheet(
                "QPushButton#articleFavoriteButton {"
                f"color: {'#e2a400' if favorite else '#aeb9c5'};"
                "border:none; background:transparent; padding:0;"
                f"font-size:13px; min-width:{star_size}px; "
                f"max-width:{star_size}px;"
                f"min-height:{star_size}px; max-height:{star_size}px;}}"
                "QPushButton#articleFavoriteButton:hover {color:#e2a400;}"
            )

    def _clear_article_controls(self) -> None:
        for button in (*self._favorite_buttons, *self._three_stage_buttons):
            button.setParent(None)
            button.deleteLater()
        self._favorite_buttons = []
        self._three_stage_buttons = []
        self._article_entries = []
        self._article_anchor_positions = {}

    def _find_anchor_positions(self, anchors: set[str]) -> dict[str, int]:
        """문서 안에서 조문 앵커가 놓인 글자 위치를 찾는다."""
        positions: dict[str, int] = {}
        remaining = set(anchors)
        block = self.browser.document().begin()
        while block.isValid() and remaining:
            iterator = block.begin()
            while not iterator.atEnd() and remaining:
                fragment = iterator.fragment()
                if fragment.isValid():
                    for anchor in set(
                        fragment.charFormat().anchorNames()
                    ).intersection(remaining):
                        positions[anchor] = fragment.position()
                        remaining.discard(anchor)
                iterator += 1
            block = block.next()
        return positions

    def _schedule_article_layout(self) -> None:
        if self._article_layout_pending or not self._article_entries:
            return
        self._article_layout_pending = True
        QTimer.singleShot(0, self._position_article_controls)

    def _position_article_controls(self) -> None:
        self._article_layout_pending = False
        viewport = self.browser.viewport()
        for article, star, button in zip(
            self._article_entries,
            self._favorite_buttons,
            self._three_stage_buttons,
        ):
            position = self._article_anchor_positions.get(
                str(article.get("anchor") or "")
            )
            if position is None:
                star.hide()
                button.hide()
                continue
            cursor = QTextCursor(self.browser.document())
            cursor.setPosition(position)
            rect = self.browser.cursorRect(cursor)
            visible = 0 <= rect.bottom() and rect.top() <= viewport.height()
            if not visible:
                star.hide()
                button.hide()
                continue
            star_y = rect.top() + (rect.height() - star.height()) // 2
            star.move(max(1, rect.left() - star.width() - 6), star_y)
            star.show()
            star.raise_()
            # 비교 자료가 있다고 확인된 조문에만 3단 단추를 보인다.
            if article.get("comparison_available") is not True:
                button.hide()
                continue
            button.move(
                max(1, viewport.width() - button.width() - 6),
                rect.top() + (rect.height() - button.height()) // 2,
            )
            button.show()
            button.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 이름)
        super().resizeEvent(event)
        self._schedule_article_layout()


class LawReferencePopup(QFrame):
    """법령 인용 링크의 조항목 API 결과를 표시하는 고정 가능 팝업."""

    refreshRequested = Signal(object)
    favoriteRequested = Signal(object)
    fontSizeChanged = Signal(float)

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
        self.content_font_point = float(DEFAULT_POPUP_FONT_POINT)
        # 본문에서 고른 글꼴을 팝업도 따라간다. 비워 두면 기본 굴림.
        self.content_font_family = ""
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
        self.font_smaller_button = QPushButton("가－")
        self.font_smaller_button.setObjectName("referencePopupFontSmaller")
        self.font_smaller_button.setFixedSize(30, 30)
        self.font_smaller_button.setToolTip("팝업 글자를 작게 합니다.")
        self.font_larger_button = QPushButton("가＋")
        self.font_larger_button.setObjectName("referencePopupFontLarger")
        self.font_larger_button.setFixedSize(30, 30)
        self.font_larger_button.setToolTip("팝업 글자를 크게 합니다.")
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
        header.addWidget(self.font_smaller_button)
        header.addWidget(self.font_larger_button)
        header.addWidget(self.favorite_button)
        header.addWidget(self.refresh_button)
        header.addWidget(self.pin_button)
        header.addWidget(self.close_button)
        # 레이아웃에 넣으면서 버튼의 부모가 이동 영역으로 바뀐 뒤에
        # 지정해야 십자 이동 커서를 상속하지 않는다.
        for button in (
            self.font_smaller_button,
            self.font_larger_button,
            self.favorite_button,
            self.refresh_button,
            self.pin_button,
            self.close_button,
        ):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.drag_bar)

        self.browser = QTextBrowser()
        self.browser.setObjectName("referencePopupBrowser")
        # 팝업 본문은 크기를 pt로만 정하고 HTML 쪽은 배수(em)로 적는다.
        # 그래야 가+ㆍ가- 로 크기를 바꿀 때 제목ㆍ본문이 같은 비율로
        # 따라 커지고, 줄 간격도 배수라 저절로 벌어진다.
        browser_font = detail_font(self.content_font_point)
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
        self.font_smaller_button.clicked.connect(
            lambda: self._step_content_font(-1)
        )
        self.font_larger_button.clicked.connect(
            lambda: self._step_content_font(1)
        )
        self._create_resize_handles()

    def _step_content_font(self, direction: int) -> None:
        step = float(DETAIL_FONT_SIZE_STEP) * (1 if direction > 0 else -1)
        self.set_content_font_point(
            self.content_font_point + step, notify=True
        )

    def set_content_font_point(
        self, point: float, *, family: str = "", notify: bool = False
    ) -> None:
        """팝업 본문 글꼴과 크기를 바꾼다. 줄 간격은 배수라 따라온다.

        글꼴 이름을 주면 그것도 함께 맞춘다. 본문에서 고른 글꼴을 팝업이
        따라가지 않으면 링크를 눌러 뜬 조문만 다른 글씨로 보인다.
        """
        point = normalize_detail_font_size(point)
        changed = abs(point - self.content_font_point) >= 0.01
        self.content_font_point = point
        if family:
            self.content_font_family = family
        font = detail_font(point, self.content_font_family or None)
        self.browser.setFont(font)
        self.browser.document().setDefaultFont(font)
        if notify and changed:
            self.fontSizeChanged.emit(point)

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
