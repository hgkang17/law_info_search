"""대화상자와 떠 있는 조문 팝업."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QEasingCurve,
    QEvent,
    QIODevice,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QCursor, QMouseEvent, QPixmap, QTextCursor, QTextBlockFormat
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSizeGrip,
    QStyle,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QSpinBox,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui.assets import SPIN_DOWN_ICON_PATH, SPIN_UP_ICON_PATH
from ui.theme import detail_font, scale_document_font_sizes
from ui.widgets import (
    DETAIL_FONT_SIZE_STEP,
    DetailSearchBar,
    CornerCloseTabBar,
    DeferredWrapTextBrowser,
    tab_preview_snapshot,
    PopupDragBar,
    PopupResizeHandle,
    apply_close_icon,
    favorite_icon,
    normalize_detail_font_size,
)
from utils.constants import DEFAULT_POPUP_FONT_POINT, DETAIL_FONT_FAMILY
from utils.formatting import BODY_LINE_HEIGHT
from utils.legal_body import repair_enumerated_reference_links
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


# 꺼낸 창은 본 창의 자식이 아니라 스타일시트를 물려받지 못한다. 창이
# 본문 화면과 같은 결로 보이도록 최소한의 규칙을 직접 건다.
_DETACHED_WINDOW_STYLE = """
QWidget#detachedDocumentWindow {
    background: #f5f6f8;
    border: 1px solid #91a0b5;
}
QWidget#detachedDocumentPage { background: #ffffff; border: none; }
QStackedWidget#detachedDocumentStack { background: transparent; border: none; }
QFrame#detachedDocumentHeader {
    background: #f5f6f8;
    border: none;
}
QFrame#detachedDocumentHeader[dropReady="true"] {
    background: #dceafb;
}
QLabel#detachedDocumentTitle {
    background: transparent;
    color: #34465a;
    font-size: 10pt;
    font-weight: 500;
    padding: 8px 16px;
}
QPushButton[windowControl="true"] {
    background: transparent; border: none; color: #40546a;
    font-size: 12pt; padding: 0;
}
QPushButton[windowControl="true"]:hover { background: #e7e9ed; }
QTextBrowser#detachedDocumentBrowser {
    background: #ffffff;
    border: none;
    padding: 8px;
}
"""


class ReattachDragBar(QFrame):
    """꺼낸 창의 제목 줄. 끌어서 옮기고, 띠 위에 놓으면 되돌아간다.

    창틀 대신 이 줄을 쥐고 끄는 이유는 놓는 순간을 알아야 하기 때문이다.
    운영체제가 그리는 창틀을 끌 때는 어디에서 손을 뗐는지 알 수 없어
    "열린 본문 띠 위에 떨어뜨리면 다시 넣기"를 만들 수 없다.
    """

    def __init__(self, window: DetachedDocumentWindow) -> None:
        super().__init__(window)
        self.window_ref = window
        self.setObjectName("detachedDocumentHeader")
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setToolTip(
            "이 줄을 끌어 창을 옮깁니다. 본 창의 '열린 본문' 띠 위에 "
            "놓으면 이 창의 모든 탭이 원래 자리로 돌아갑니다."
        )
        self._drag_offset: QPoint | None = None
        self._press_position: QPoint | None = None
        self._drag_started = False

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt 규약)
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_position = event.globalPosition().toPoint()
            self._drag_started = False
            self._drag_offset = (
                event.globalPosition().toPoint()
                - self.window_ref.frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt 규약)
        if (
            self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            point = event.globalPosition().toPoint()
            if not self._drag_started:
                if (point - self._press_position).manhattanLength() < QApplication.startDragDistance():
                    return
                self._drag_started = True
                if self.window_ref.isMaximized():
                    self.window_ref.showNormal()
                    self._drag_offset = QPoint(self.window_ref.width() // 2, 20)
            self.window_ref.move(point - self._drag_offset)
            self.window_ref.probe_reattach(point)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt 규약)
        dragging = self._drag_started
        self._drag_started = False
        self._drag_offset = None
        if dragging and event.button() == Qt.MouseButton.LeftButton:
            self.window_ref.drop_reattach(event.globalPosition().toPoint(), all_pages=True)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = None
            self._drag_started = False
            self.window_ref.toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class DetachedDocumentPage(QWidget):
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
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("detachedDocumentPage")
        self.setWindowTitle(title)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(980, 720)
        self.setMinimumSize(420, 280)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)

        # 본문을 어디로 되돌릴지 아는 쪽(본 창)이 채워 넣는다.
        self.reattach_payload: dict[str, object] = {}
        self.reattach_probe = None
        self.reattach_handler = None
        self._geometry_animation: QPropertyAnimation | None = None
        self._drop_ready = False
        self.reattach_position: QPoint | None = None

        self.header = ReattachDragBar(self)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(8, 6, 0, 0)
        header_layout.setSpacing(0)
        self.header.setFixedHeight(44)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("detachedDocumentTitle")
        self.title_label.setMaximumWidth(420)
        self.title_label.setMinimumWidth(160)
        self.title_label.setToolTip(title)
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        header_layout.addWidget(self.title_label)
        header_layout.addStretch(1)
        for text, tip, callback in (
            ("−", "최소화", self.showMinimized),
            ("□", "최대화 / 복원", self.toggle_maximized),
            ("×", "닫기", self.close),
        ):
            button = QPushButton(text, self.header)
            button.setProperty("windowControl", "true")
            button.setFixedSize(44, 38)
            button.setToolTip(tip)
            button.setAccessibleName(tip)
            button.clicked.connect(callback)
            if text == "×":
                button.setObjectName("detachedWindowClose")
            header_layout.addWidget(button)
        layout.addWidget(self.header)
        # 독립 창으로 유지하되 본체의 스크롤바·목차 스타일을 그대로 쓴다.
        self.setStyleSheet(
            (parent.styleSheet() if parent is not None else "")
            + _DETACHED_WINDOW_STYLE
        )

        self.reader_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.reader_splitter.setChildrenCollapsible(False)
        self.reader_splitter.setHandleWidth(5)
        self.toc_panel = QWidget()
        self.toc_panel.setObjectName("articleTocPanel")
        toc_layout = QVBoxLayout(self.toc_panel)
        toc_layout.setContentsMargins(10, 10, 4, 8)
        toc_layout.setSpacing(6)
        toc_layout.addWidget(QLabel("조문목차"))
        self.toc_search_input = QLineEdit()
        self.toc_search_input.setObjectName("tocSearchInput")
        self.toc_search_input.setPlaceholderText("목차 검색")
        self.toc_search_input.setClearButtonEnabled(True)
        toc_layout.addWidget(self.toc_search_input)
        self.toc_tree = QTreeWidget()
        self.toc_tree.setObjectName("articleToc")
        self.toc_tree.setHeaderHidden(True)
        self.toc_tree.setIndentation(12)
        self.toc_tree.setMinimumWidth(160)
        self.toc_tree.setWordWrap(True)
        toc_layout.addWidget(self.toc_tree, 1)
        self.reader_splitter.addWidget(self.toc_panel)
        self.toc_panel.hide()
        self.toc_tree.itemClicked.connect(self._toc_item_clicked)
        self.toc_tree.itemActivated.connect(self._toc_item_clicked)
        self.toc_search_input.textChanged.connect(self._filter_toc)

        self.browser = DeferredWrapTextBrowser()
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
        self.reader_splitter.addWidget(self.browser)
        self.reader_splitter.setStretchFactor(0, 0)
        self.reader_splitter.setStretchFactor(1, 1)
        layout.addWidget(self.reader_splitter, 1)
        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 0, 0)
        grip_row.addStretch(1)
        self.size_grip = QSizeGrip(self)
        self.size_grip.setFixedSize(16, 16)
        grip_row.addWidget(self.size_grip)
        layout.addLayout(grip_row)

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

    def toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def attach_toc(self, entries, *, scroll: int = 0) -> None:
        """꺼낸 문서 자신의 편·장·절·조문·별표 목차를 전달받는다."""
        self.toc_tree.clear()
        parents = {}
        for depth, label, anchor in entries:
            parents = {level: item for level, item in parents.items() if level < depth}
            parent = parents[max(parents)] if parents else self.toc_tree
            item = QTreeWidgetItem(parent, [str(label)])
            item.setData(0, Qt.ItemDataRole.UserRole, str(anchor))
            item.setToolTip(0, str(label))
            if depth < 4:
                parents[depth] = item
        self.toc_tree.expandAll()
        self.toc_panel.setVisible(bool(entries))
        if entries:
            self.reader_splitter.setSizes([240, 740])
            QTimer.singleShot(0, self, lambda: self.toc_tree.verticalScrollBar().setValue(scroll))

    def _toc_item_clicked(self, item, _column=0) -> None:
        anchor = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        if anchor:
            self.browser.scrollToAnchor(anchor)

    def _filter_toc(self, query: str) -> None:
        query = query.strip().casefold()

        def visit(item):
            children = [visit(item.child(i)) for i in range(item.childCount())]
            visible = not query or query in item.text(0).casefold() or any(children)
            item.setHidden(not visible)
            if query and any(children):
                item.setExpanded(True)
            return visible

        for index in range(self.toc_tree.topLevelItemCount()):
            visit(self.toc_tree.topLevelItem(index))

    def scroll_to(self, position: int) -> None:
        scroll_bar = self.browser.verticalScrollBar()
        scroll_bar.setValue(max(0, min(int(position), scroll_bar.maximum())))

    def scroll_position(self) -> int:
        return int(self.browser.verticalScrollBar().value())

    # ---- 다시 넣기 ---------------------------------------------------
    def enable_reattach(self, payload, probe, handler) -> None:
        """이 창을 어디로 되돌릴지 본 창이 알려 준다.

        ``probe(전역좌표)``는 지금 놓으면 되돌아갈 자리인지 알려 주고,
        ``handler(창)``이 실제로 본문을 제자리에 돌려놓는다.
        """
        self.reattach_payload = dict(payload or {})
        self.reattach_probe = probe
        self.reattach_handler = handler

    def probe_reattach(self, global_point: QPoint) -> bool:
        """끌고 가는 동안 되돌아갈 자리인지 제목 줄 색으로 알려 준다."""
        ready = False
        if self.reattach_probe is not None:
            try:
                ready = bool(self.reattach_probe(global_point))
            except Exception:  # noqa: BLE001 - 끌기를 막지 않는다.
                ready = False
        self._set_drop_ready(ready)
        return ready

    def _set_drop_ready(self, ready: bool) -> None:
        if ready == self._drop_ready:
            return
        self._drop_ready = ready
        self.header.setProperty("dropReady", "true" if ready else "false")
        self.header.style().unpolish(self.header)
        self.header.style().polish(self.header)

    def drop_reattach(self, global_point: QPoint) -> None:
        """제목 줄을 놓았다. 띠 위였으면 본문을 제자리로 돌려보낸다."""
        ready = self.probe_reattach(global_point)
        # 놓았으니 강조는 거둔다. 본 창 쪽 띠 강조도 함께 꺼진다.
        if self.reattach_probe is not None:
            try:
                self.reattach_probe(QPoint(-1, -1))
            except Exception:  # noqa: BLE001 - 끌기를 막지 않는다.
                pass
        self._set_drop_ready(False)
        if ready:
            self.reattach_position = QPoint(global_point)
            self._reattach_now()

    def _reattach_now(self) -> None:
        if self.reattach_handler is None:
            return
        handler = self.reattach_handler
        state = self.reattach_payload.get("state")
        if isinstance(state, dict):
            state["toc_scroll"] = self.toc_tree.verticalScrollBar().value()
        # 두 번 불리지 않게 먼저 끊는다. 본문이 두 군데 열릴 수 있다.
        self.reattach_handler = None
        handler(self)

    # ---- 열리고 닫히는 모습 ------------------------------------------
    def animate_open_from(self, rect: QRect) -> None:
        """끌던 창과 같은 자리에서 본문을 표시한다."""
        if rect is not None and rect.isValid():
            self.setGeometry(rect)
        self.show()

    def animate_close_to(self, rect: QRect) -> None:
        """복원된 탭이 즉시 이어 보이도록 분리 창을 닫는다."""
        self.close()

    def _animate_geometry(self, start: QRect, end: QRect) -> QPropertyAnimation:
        animation = QPropertyAnimation(self, QByteArray(b"geometry"), self)
        animation.setDuration(170)
        animation.setStartValue(QRect(start))
        animation.setEndValue(QRect(end))
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.start(QPropertyAnimation.DeletionPolicy.KeepWhenStopped)
        self._geometry_animation = animation
        return animation

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


class DetachedDocumentTabBar(CornerCloseTabBar):
    """탭 정렬과 실제 창 끌기를 구분한다. 마지막 탭은 곧 창 손잡이다."""

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self._press_global = None
        self._press_page = None
        self._moving_window = None
        self._window_drag = False
        self._window_offset = QPoint()
        self._moved = False

    def mousePressEvent(self, event):  # noqa: N802
        self._press_global = None
        self._moving_window = None
        self._moved = False
        spot = event.position().toPoint()
        if event.button() != Qt.MouseButton.LeftButton or self.close_spot_at(spot) >= 0:
            super().mousePressEvent(event)
            return
        self._press_global = event.globalPosition().toPoint()
        index = self.tabAt(spot)
        self._press_page = self.tabData(index) if index >= 0 else None
        self._window_drag = self.count() == 1 or index < 0
        self._window_offset = self._press_global - self.owner.pos()
        if self._window_drag:
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._press_global is None or not event.buttons() & Qt.MouseButton.LeftButton:
            super().mouseMoveEvent(event)
            return
        point = event.globalPosition().toPoint()
        if not self._moved:
            if (point - self._press_global).manhattanLength() < QApplication.startDragDistance():
                event.accept()
                return
            self._moved = True
        if self._moving_window is None:
            if self._window_drag:
                self._moving_window = self.owner
            elif not self.rect().adjusted(-12, -12, 12, 12).contains(event.position().toPoint()):
                # Qt의 정렬 드래그만 먼저 끝낸다. 공용 release의 detach 신호는
                # 호출하지 않아 놓기 전에 복귀/이중 분리가 일어나지 않게 한다.
                release = QMouseEvent(
                    QEvent.Type.MouseButtonRelease, event.position(), event.globalPosition(),
                    Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, event.modifiers(),
                )
                QTabBar.mouseReleaseEvent(self, release)
                self._pressed_data = None
                self._hide_preview()
                pages = [p for p in self.owner.ordered_pages() if p in self._selected_tab_data]
                if self._press_page not in pages:
                    pages = [self._press_page]
                self._moving_window = self.owner.split_pages(pages, point)
                self._window_offset = QPoint(self._moving_window.width() // 2, 20)
                # 새 창이 떠도 현재 누름을 시작한 탭바가 놓기까지 받는다.
                self.grabMouse()
            else:
                super().mouseMoveEvent(event)
                return
        window = self._moving_window
        if window.isMaximized():
            window.showNormal()
            self._window_offset = QPoint(window.width() // 2, 20)
        window.move(point - self._window_offset)
        window.probe_reattach(point)
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        moving = self._moving_window
        window_drag = self._window_drag and self._press_global is not None
        self._press_global = None
        self._moving_window = None
        self._press_page = None
        self._window_drag = False
        if moving is not None:
            if QWidget.mouseGrabber() is self:
                self.releaseMouse()
            event.accept()
            moving.drop_reattach(event.globalPosition().toPoint(), all_pages=window_drag or len(moving._pages) > 1)
            return
        if window_drag:
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.count() == 1:
            self._press_global = None
            self.owner.toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class DetachedDocumentWindow(QWidget):
    """독립된 본문 페이지를 탭으로 소유하는 창. 이동 시 페이지를 재생성하지 않는다."""

    _windows = set()

    def __init__(self, title="", html="", link_handler=None, font=None, parent=None, *, page=None, tab_title=None):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("detachedDocumentWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(980, 720)
        self.setMinimumSize(420, 280)
        self.owner = parent
        self.setStyleSheet((parent.styleSheet() if parent is not None else "") + _DETACHED_WINDOW_STYLE)
        self._pages = []
        self._last_page = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)
        self.header = ReattachDragBar(self)
        self.header.setFixedHeight(44)
        row = QHBoxLayout(self.header)
        row.setContentsMargins(8, 0, 0, 0)
        row.setSpacing(0)
        self.document_tabs = DetachedDocumentTabBar(self)
        self.document_tabs.setObjectName("openDocumentTabs")
        self.document_tabs.setDrawBase(False)
        self.document_tabs.setExpanding(False)
        self.document_tabs.setMovable(True)
        self.document_tabs.setTabsClosable(False)
        self.document_tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.document_tabs.currentChanged.connect(self._select_page)
        self.document_tabs.tabCloseRequested.connect(self._close_tab)
        self.document_tabs.detachRequested.connect(self._detach_tab)
        self.document_tabs.preview_provider = lambda page: (page.windowTitle(), tab_preview_snapshot(page.reader_splitter))
        self.document_tabs.drop_probe = lambda point: self.probe_reattach(point)
        row.addWidget(self.document_tabs, 1)
        for icon, tip, callback in (
            (QStyle.StandardPixmap.SP_TitleBarMinButton, "최소화", self.showMinimized),
            (QStyle.StandardPixmap.SP_TitleBarMaxButton, "최대화 / 복원", self.toggle_maximized),
            (QStyle.StandardPixmap.SP_TitleBarCloseButton, "닫기", self.close),
        ):
            button = QPushButton(self.header)
            button.setIcon(self.style().standardIcon(icon))
            button.setIconSize(QSize(12, 12))
            button.setProperty("windowControl", "true")
            button.setFixedSize(46, 30)
            button.setToolTip(tip)
            button.setAccessibleName(tip)
            button.clicked.connect(callback)
            if tip == "최대화 / 복원":
                self.maximize_button = button
            row.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.header)
        self.stack = QStackedWidget()
        self.stack.setObjectName("detachedDocumentStack")
        # 탭 바탕색이 본문 사방으로 이어지는 여유 공간.
        self.stack.setContentsMargins(10, 8, 10, 10)
        layout.addWidget(self.stack, 1)
        self.size_grip = QSizeGrip(self)
        self.size_grip.setFixedSize(10, 10)
        self.size_grip.hide()
        if page is None:
            page = DetachedDocumentPage(title, html, link_handler, font or self.font(), parent=parent)
        if tab_title:
            page.detached_tab_title = tab_title
        self.add_page(page)
        self.resize_handles = []
        for edges, cursor in (
            (Qt.Edge.LeftEdge, Qt.CursorShape.SizeHorCursor),
            (Qt.Edge.RightEdge, Qt.CursorShape.SizeHorCursor),
            (Qt.Edge.TopEdge, Qt.CursorShape.SizeVerCursor),
            (Qt.Edge.BottomEdge, Qt.CursorShape.SizeVerCursor),
            (Qt.Edge.LeftEdge | Qt.Edge.TopEdge, Qt.CursorShape.SizeFDiagCursor),
            (Qt.Edge.RightEdge | Qt.Edge.TopEdge, Qt.CursorShape.SizeBDiagCursor),
            (Qt.Edge.LeftEdge | Qt.Edge.BottomEdge, Qt.CursorShape.SizeBDiagCursor),
            (Qt.Edge.RightEdge | Qt.Edge.BottomEdge, Qt.CursorShape.SizeFDiagCursor),
        ):
            handle = PopupResizeHandle(self, edges, cursor, enabled=lambda: not self.isMaximized())
            handle.setToolTip("끌어서 창 크기를 조절합니다.")
            self.resize_handles.append(handle)
        self._layout_resize_handles()
        self._windows.add(self)

    def _layout_resize_handles(self):
        w, h, m = self.width(), self.height(), 6
        if "size_grip" in self.__dict__:
            self.size_grip.move(w - 12, h - 12)
        rects = ((0,m,m,h-2*m), (w-m,m,m,h-2*m), (m,0,w-2*m,m),
                 (m,h-m,w-2*m,m), (0,0,m,m), (w-m,0,m,m),
                 (0,h-m,m,m), (w-m,h-m,m,m))
        for handle, rect in zip(self.__dict__.get("resize_handles", []), rects):
            handle.setGeometry(*rect)
            handle.setVisible(not self.isMaximized())
            handle.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_resize_handles()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._layout_resize_handles()
            icon = (QStyle.StandardPixmap.SP_TitleBarNormalButton if self.isMaximized()
                    else QStyle.StandardPixmap.SP_TitleBarMaxButton)
            self.maximize_button.setIcon(self.style().standardIcon(icon))

    def current_page(self):
        return self.stack.currentWidget() if self._pages else self._last_page

    def closeEvent(self, event):  # noqa: N802
        from ui.detached_reader import retain_busy_page
        for page in self._pages:
            retain_busy_page(page)
        self._windows.discard(self)
        super().closeEvent(event)

    def __getattr__(self, name):
        # 기존 호출부의 본문 조작 API는 현재 페이지로 전달한다.
        if name.startswith("__") or "stack" not in self.__dict__:
            raise AttributeError(name)
        page = self.current_page()
        if page is None:
            raise AttributeError(name)
        reader = getattr(page, "source_reader", None)
        reader_names = {"_favorite_buttons": "_article_favorite_buttons",
                        "_favorite_state": "_article_is_favorite",
                        "_three_stage_buttons": "_three_stage_buttons",
                        "_article_anchor_positions": "_three_stage_anchor_positions"}
        if reader is not None and name in reader_names and hasattr(reader, reader_names[name]):
            return getattr(reader, reader_names[name])
        return getattr(page, name)

    @property
    def reattach_handler(self):
        return self.current_page().reattach_handler

    @reattach_handler.setter
    def reattach_handler(self, handler):
        self.current_page().reattach_handler = handler

    @property
    def reattach_position(self):
        return self.current_page().reattach_position

    @reattach_position.setter
    def reattach_position(self, position):
        self.current_page().reattach_position = position

    def add_page(self, page, position=None):
        page.hide()
        page.setParent(self.stack, Qt.WindowType.Widget)
        page.setMinimumSize(0, 0)
        page.header.hide()
        page.size_grip.hide()
        page.layout().setContentsMargins(0, 0, 0, 0)
        self._pages.append(page)
        self.stack.addWidget(page)
        index = self.document_tabs.count()
        if position is not None:
            x = self.document_tabs.mapFromGlobal(position).x()
            index = next((i for i in range(index) if x < self.document_tabs.tabRect(i).center().x()), index)
        self.document_tabs.blockSignals(True)
        self.document_tabs.insertTab(index, getattr(page, "detached_tab_title", page.windowTitle()))
        self.document_tabs.setTabData(index, page)
        self.document_tabs.setTabToolTip(index, page.windowTitle())
        self.document_tabs.setCurrentIndex(index)
        self.document_tabs.blockSignals(False)
        self._select_page(index)

    def _select_page(self, index):
        if index >= 0:
            page = self.document_tabs.tabData(index)
            if page is not None:
                self.stack.setCurrentWidget(page)
                self.setWindowTitle(page.windowTitle())

    def _take_page(self, page):
        index = next(i for i in range(self.document_tabs.count()) if self.document_tabs.tabData(i) is page)
        self._last_page = page
        self.document_tabs.removeTab(index)
        self.stack.removeWidget(page)
        self._pages.remove(page)
        page.hide()
        page.setParent(None)
        if not self._pages:
            self.close()
        return page

    def _close_tab(self, index):
        from ui.detached_reader import retain_busy_page
        page = self.document_tabs.tabData(index)
        self._take_page(page)
        if not retain_busy_page(page):
            page.deleteLater()

    def toggle_maximized(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def drop_rect(self):
        if not self.isVisible() or self.isMinimized():
            return QRect()
        return QRect(self.document_tabs.mapToGlobal(QPoint()), self.document_tabs.size()).adjusted(-8, -16, 8, 16)

    def highlight_drop(self, active):
        value = "true" if active else "false"
        if self.header.property("dropReady") != value:
            self.header.setProperty("dropReady", value)
            self.header.style().unpolish(self.header)
            self.header.style().polish(self.header)

    @classmethod
    def target_at(cls, point, exclude=None):
        target = None
        for window in tuple(cls._windows):
            inside = window is not exclude and window.drop_rect().contains(point)
            window.highlight_drop(inside)
            if inside:
                target = window
        return target

    def probe_reattach(self, point):
        target = self.target_at(point, self)
        probe = self.current_page().reattach_probe
        main_ready = bool(probe(point)) if probe else False
        return target is not None or main_ready

    def ordered_pages(self):
        return [self.document_tabs.tabData(i) for i in range(self.document_tabs.count())]

    def reattach_all(self):
        for page in self.ordered_pages():
            self.document_tabs.setCurrentIndex(self.ordered_pages().index(page))
            page.reattach_position = None
            self._reattach_now()

    @classmethod
    def detach_group(cls, keys, callback, point):
        target = cls.target_at(point)
        for key in keys:
            before = set(cls._windows)
            destination = target.document_tabs.mapToGlobal(QPoint(target.document_tabs.width() - 1, 20)) if target else point
            callback(key, destination)
            if target is None:
                target = next((w for w in cls._windows - before if w.isVisible()), None)

    def drop_reattach(self, point, all_pages=False):
        target = self.target_at(point, self)
        if target is not None:
            pages = self.ordered_pages() if all_pages else [self.current_page()]
            x = target.document_tabs.mapFromGlobal(point).x()
            insertion = next((i for i in range(target.document_tabs.count())
                              if x < target.document_tabs.tabRect(i).center().x()), target.document_tabs.count())
            for offset, page in enumerate(pages):
                target.add_page(self._take_page(page))
                target.document_tabs.moveTab(target.document_tabs.count() - 1, insertion + offset)
            target.raise_()
            target.activateWindow()
        elif self.current_page().reattach_probe and self.current_page().reattach_probe(point):
            pages = self.ordered_pages() if all_pages else [self.current_page()]
            for page in pages:
                self.document_tabs.setCurrentIndex(self.ordered_pages().index(page))
                self.reattach_position = QPoint(point)
                self._reattach_now()
                rect_for = getattr(self.owner, "_open_document_tab_rect", None)
                if rect_for is not None:
                    rect = rect_for(str(page.reattach_payload.get("token") or ""))
                    if rect.isValid():
                        point = rect.topRight() + QPoint(1, rect.height() // 2)
        self.target_at(QPoint(-100000, -100000))
        page = self.current_page()
        if page and page.reattach_probe:
            page.reattach_probe(QPoint(-100000, -100000))

    def _reattach_now(self):
        page = self.current_page()
        handler = page.reattach_handler
        if handler:
            state = page.reattach_payload.get("state")
            if isinstance(state, dict):
                state["toc_scroll"] = page.toc_tree.verticalScrollBar().value()
            page.reattach_handler = None
            handler(self)

    def _detach_tab(self, page, point):
        self.document_tabs.setCurrentIndex(next(i for i in range(self.document_tabs.count()) if self.document_tabs.tabData(i) is page))
        if self.probe_reattach(point):
            self.drop_reattach(point)
            return
        if len(self._pages) == 1:
            self.move(point - QPoint(self.width() // 2, 20))
            return
        self.split_page(page, point)

    def split_page(self, page, point):
        """페이지를 새 창으로 옮기고 진행 중인 마우스 끌기에 넘긴다."""
        moved = self._take_page(page)
        window = DetachedDocumentWindow(parent=self.owner, page=moved)
        register = getattr(self.owner, "register_detached_window", None)
        if register:
            register(window, moved.reattach_payload)
        window.move(point - QPoint(window.width() // 2, 20))
        window.show()
        return window

    def split_pages(self, pages, point):
        if len(pages) == len(self._pages):
            return self
        window = self.split_page(pages[0], point)
        for page in pages[1:]:
            window.add_page(self._take_page(page))
        return window

    def animate_open_from(self, rect):
        if rect is not None and rect.isValid():
            self.setGeometry(rect)
        self.show()

    def animate_close_to(self, rect):
        self._close_tab(self.document_tabs.currentIndex())

    def finish_detach(self, point):
        if point is not None and self.target_at(point, self) is not None:
            self.drop_reattach(point)


class LawReferencePopup(QFrame):
    """법령 인용 링크의 조항목 API 결과를 표시하는 고정 가능 팝업."""

    refreshRequested = Signal(object)
    favoriteRequested = Signal(object)
    fontSizeChanged = Signal(float)
    fontResetRequested = Signal()

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
        self._source_html = ""
        self._content_generation = 0
        self._restoring_scroll = False
        self.setMinimumSize(560, 220)
        self.resize(640, 320)

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
        self.font_smaller_button = QPushButton("가−")
        self.font_smaller_button.setObjectName("referencePopupFontSmaller")
        self.font_smaller_button.setFixedSize(36, 30)
        self.font_smaller_button.setToolTip("팝업 글자를 작게 합니다.")
        self.font_larger_button = QPushButton("가+")
        self.font_larger_button.setObjectName("referencePopupFontLarger")
        self.font_larger_button.setFixedSize(36, 30)
        self.font_larger_button.setToolTip("팝업 글자를 크게 합니다.")
        self.font_reset_button = QPushButton("기본값")
        self.font_reset_button.setObjectName("referencePopupFontReset")
        self.font_reset_button.setFixedSize(48, 30)
        self.font_reset_button.setToolTip("굴림 9.5pt와 기본 줄간격으로 되돌립니다.")
        self.font_size_label = QLabel("9.5pt")
        self.font_size_label.setObjectName("referencePopupFontSize")
        self.font_size_label.setMinimumWidth(42)
        self.font_size_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
        header.addWidget(self.font_reset_button)
        header.addWidget(self.font_smaller_button)
        header.addWidget(self.font_size_label)
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
            self.font_reset_button,
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
        self.font_reset_button.clicked.connect(self._reset_content_font)
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
        family_changed = bool(family and family != self.content_font_family)
        self.content_font_point = point
        if family:
            self.content_font_family = family
        font = detail_font(point, self.content_font_family or None)
        self.browser.setFont(font)
        self.browser.document().setDefaultFont(font)
        self.font_size_label.setText(f"{point:g}pt")
        self.font_size_label.setToolTip(
            f"현재 글꼴: {self.content_font_family or DETAIL_FONT_FAMILY} · 기본값: 굴림 9.5pt"
        )
        if self._source_html and (changed or family_changed):
            bar = self.browser.verticalScrollBar()
            ratio = bar.value() / bar.maximum() if bar.maximum() else 0.0
            self._render_content()
            bar.setValue(round(bar.maximum() * ratio))
        if notify and changed:
            self.fontSizeChanged.emit(point)

    def _reset_content_font(self) -> None:
        self.set_content_font_point(DEFAULT_POPUP_FONT_POINT, family=DETAIL_FONT_FAMILY)
        # 값이 이미 기본값이어도 구버전 문서의 줄간격을 다시 맞춘다.
        if self._source_html:
            self._render_content()
        self.fontResetRequested.emit()

    def _render_content(self) -> None:
        """항상 원본 HTML에서 다시 그려 확대/축소 서식이 누적되지 않게 한다."""
        font = detail_font(self.content_font_point, self.content_font_family or None)
        self.browser.document().setDefaultFont(font)
        self.browser.setHtml(scale_document_font_sizes(
            self._source_html, DEFAULT_POPUP_FONT_POINT, self.content_font_point,
            self.content_font_family or DETAIL_FONT_FAMILY,
        ))
        document = self.browser.document()
        repair_enumerated_reference_links(document)
        # Qt는 body/div의 줄간격을 표 안의 문단에 항상 상속하지 않는다.
        # 구버전 HTML의 고정 높이도 글자 크기에 비례하는 간격으로 복구한다.
        block = document.begin()
        while block.isValid():
            if block.text().replace("\ufffc", "").strip():
                cursor = QTextCursor(block)
                format_ = block.blockFormat()
                format_.setLineHeight(
                    float(BODY_LINE_HEIGHT) * 100,
                    QTextBlockFormat.LineHeightTypes.ProportionalHeight.value,
                )
                cursor.setBlockFormat(format_)
            block = block.next()

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
        if getattr(self, "_combined_sections", None) is not None:
            self._set_combined_section(title, f"<p>{escape(message)}</p>")
            self.refresh_button.setEnabled(False)
            return
        self._content_generation += 1
        self._source_html = ""
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
        if getattr(self, "_combined_sections", None) is not None and not getattr(self, "_rendering_combined", False):
            self._set_combined_section(title, html)
            return
        self.title_label.setText(title)
        self.refresh_button.setEnabled(bool(self.reference_request))
        self._refresh_favorite_button()
        self._content_generation += 1
        generation = self._content_generation
        self._restoring_scroll = True
        self._source_html = html
        self._render_content()
        QTimer.singleShot(
            0,
            lambda: self._restore_content_scroll(
                generation, scroll_position, scroll_anchor
            ),
        )

    def begin_combined(self, options):
        self._combined_options = options
        self._combined_sections = [(str(option["text"]), "<p>불러오는 중…</p>") for option in options]
        self._combined_active = 0
        self.pin_button.setChecked(True)

    def _set_combined_section(self, title, html):
        self._combined_sections[self._combined_active] = (title, html)
        parts = []
        for heading, body in self._combined_sections:
            parts.append(f'<h3>{escape(heading)}</h3>{body}<hr>')
        position = self.browser.verticalScrollBar().value()
        self._rendering_combined = True
        try:
            self.set_content("연결 조문", "".join(parts), scroll_position=position)
            self.refresh_button.setEnabled(False)
        finally:
            self._rendering_combined = False

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
        if getattr(self, "_combined_sections", None) is not None:
            self._set_combined_section(self._combined_sections[self._combined_active][0],
                                       f'<p style="color:#a12b2b">{escape(message)}</p>')
            return
        self._source_html = ""
        self._content_generation += 1
        self._restoring_scroll = False
        self.refresh_button.setEnabled(bool(self.reference_request))
        self._refresh_favorite_button()
        self.browser.setHtml(
            '<div style="font-family:Malgun Gothic; color:#a12b2b; '
            f'padding:18px;">{escape(message)}</div>'
        )

    def _refresh_favorite_button(self) -> None:
        if getattr(self, "_combined_sections", None) is not None:
            self.favorite_button.setEnabled(False)
            return
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
