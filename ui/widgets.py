"""여러 화면이 함께 쓰는 위젯."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
import re
from PySide6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QRect,
    QSize,
    Qt,
    QTimer,
    QSettings,
    Signal,
    QRegularExpression,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QKeySequence,
    QPainter,
    QPen,
    QShortcut,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextOption,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QSplitter,
    QTableWidget,
    QTabBar,
    QTextBrowser,
    QTextEdit,
    QTreeWidget,
    QWidget,
)
from PySide6.QtCore import QPointF
from PySide6.QtGui import QPalette, QTextLayout
from PySide6.QtWidgets import QApplication, QButtonGroup, QToolTip
from storage.recent import RecentSearchManager
from utils.formatting import hwp_friendly_clipboard_html
from utils.parsing import whitespace_flexible_pattern


def restore_text_view_scroll(
    view: QTextBrowser, vertical_position: int, horizontal_position: int
) -> None:
    """Restore a text view's scroll position without a torn repaint.

    포커스가 검색창→본문으로 넘어갈 때, 포커스 링/스타일 재적용으로
    스크롤 범위가 다시 계산되는 타이밍이 한 번의 다음 틱으로는 부족해
    스크롤이 조금씩 밀리는 경우가 있어 같은 목표 위치로 몇 차례 더
    되돌린다. 다만 그 사이 화면 갱신을 열어두면, 옛 위치 화면이 미처
    다 지워지기 전에 다음 위치가 겹쳐 그려져 글자가 깨진 것처럼 보이는
    "티어링" 현상이 생겼다. 복원이 끝날 때까지 화면 갱신을 잠가서
    중간 상태가 아예 그려지지 않게 한다."""
    view.setUpdatesEnabled(False)

    def restore(*, last: bool = False) -> None:
        vertical_bar = view.verticalScrollBar()
        horizontal_bar = view.horizontalScrollBar()
        vertical_bar.setValue(min(vertical_position, vertical_bar.maximum()))
        horizontal_bar.setValue(min(horizontal_position, horizontal_bar.maximum()))
        if last:
            view.setUpdatesEnabled(True)
            view.viewport().update()

    restore()
    QTimer.singleShot(0, restore)
    QTimer.singleShot(0, lambda: QTimer.singleShot(0, restore))
    QTimer.singleShot(50, lambda: restore(last=True))


def clear_search_term_backgrounds(
    browser: QTextBrowser, terms: tuple[str, ...]
) -> None:
    """검색어 자동 강조(#ffe58f)만 지우고 사용자가 칠한 다른 색은 유지."""
    if not terms:
        return
    document = browser.document()
    for term in terms:
        cursor = QTextCursor(document)
        while True:
            cursor = document.find(term, cursor)
            if cursor.isNull():
                break
            background = cursor.charFormat().background()
            if (
                background.style() != Qt.BrushStyle.NoBrush
                and background.color().name().casefold() == "#ffe58f"
            ):
                clear_format = QTextCharFormat()
                clear_format.setBackground(QBrush(Qt.BrushStyle.NoBrush))
                foreground = cursor.charFormat().foreground()
                if (
                    foreground.style() != Qt.BrushStyle.NoBrush
                    and foreground.color().name().casefold() == "#172033"
                ):
                    # 이전 검색 강조 HTML은 검은 전경색도 함께 넣었다.
                    # Qt는 mergeCharFormat의 clearForeground()를 상속색 복원으로
                    # 처리하지 않으므로 같은 문단의 인접 글자색을 직접 가져온다.
                    replacement = None
                    for position in (
                        cursor.selectionEnd(),
                        cursor.selectionStart() - 1,
                    ):
                        if position < cursor.block().position() or position >= (
                            cursor.block().position() + cursor.block().length() - 1
                        ):
                            continue
                        neighbor = QTextCursor(document)
                        neighbor.setPosition(position)
                        neighbor.setPosition(
                            position + 1, QTextCursor.MoveMode.KeepAnchor
                        )
                        neighbor_background = neighbor.charFormat().background()
                        neighbor_foreground = neighbor.charFormat().foreground()
                        if (
                            neighbor_background.color().name().casefold()
                            != "#ffe58f"
                            and neighbor_foreground.style()
                            != Qt.BrushStyle.NoBrush
                        ):
                            replacement = neighbor_foreground
                            break
                    if replacement is not None:
                        clear_format.setForeground(replacement)
                cursor.mergeCharFormat(clear_format)
            next_position = cursor.selectionEnd()
            cursor = QTextCursor(document)
            cursor.setPosition(next_position)
    browser.viewport().update()


def replace_search_term_backgrounds(
    browser: QTextBrowser, terms: tuple[str, ...]
) -> None:
    """저장 본문의 과거 검색 음영을 모두 지우고 현재 검색어만 칠한다."""
    document = browser.document()
    ranges: list[tuple[int, int, QTextCharFormat]] = []
    block = document.begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid():
                background = fragment.charFormat().background()
                if (
                    background.style() != Qt.BrushStyle.NoBrush
                    and background.color().name().casefold() == "#ffe58f"
                ):
                    ranges.append(
                        (
                            fragment.position(),
                            fragment.position() + fragment.length(),
                            QTextCharFormat(fragment.charFormat()),
                        )
                    )
            iterator += 1
        block = block.next()

    for start, end, original_format in ranges:
        cursor = QTextCursor(document)
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        # 빈 포맷을 병합하면 Qt가 복합 구간의 공통 글자 속성을 택하면서
        # 제목 볼드·링크·메모 밑줄이 사라질 수 있다. 원래 fragment의
        # 서식을 복제하고 자동 검색 배경만 걷어낸 뒤 그대로 되돌린다.
        clear_format = QTextCharFormat(original_format)
        clear_format.setBackground(QBrush(Qt.BrushStyle.NoBrush))
        foreground = original_format.foreground()
        if (
            foreground.style() != Qt.BrushStyle.NoBrush
            and foreground.color().name().casefold() == "#172033"
        ):
            if original_format.isAnchor():
                clear_format.setForeground(QColor("#006dcc"))
            else:
                for position in (end, start - 1):
                    if position < cursor.block().position() or position >= (
                        cursor.block().position() + cursor.block().length() - 1
                    ):
                        continue
                    neighbor = QTextCursor(document)
                    neighbor.setPosition(position)
                    neighbor.setPosition(
                        position + 1, QTextCursor.MoveMode.KeepAnchor
                    )
                    neighbor_format = neighbor.charFormat()
                    neighbor_foreground = neighbor_format.foreground()
                    if (
                        neighbor_foreground.style() != Qt.BrushStyle.NoBrush
                        and neighbor_foreground.color().name().casefold()
                        != "#172033"
                    ):
                        clear_format.setForeground(neighbor_foreground)
                        break
        cursor.setCharFormat(clear_format)

    highlight_format = QTextCharFormat()
    highlight_format.setBackground(QColor("#ffe58f"))
    for term in terms:
        pattern = whitespace_flexible_pattern(term)
        if not pattern:
            continue
        cursor = QTextCursor(document)
        while True:
            cursor = document.find(
                QRegularExpression(
                    pattern,
                    QRegularExpression.PatternOption.CaseInsensitiveOption,
                ),
                cursor,
            )
            if cursor.isNull():
                break
            cursor.mergeCharFormat(highlight_format)
            next_position = cursor.selectionEnd()
            cursor = QTextCursor(document)
            cursor.setPosition(next_position)
    browser.viewport().update()


def resize_adaptive_result_rows(table: QTableWidget) -> None:
    """지정 열이 실제 두 줄로 감싸질 때만 해당 결과 행을 높임."""
    wrap_columns = tuple(getattr(table, "_adaptive_wrap_columns", ()))
    single_height = max(26, table.fontMetrics().height() + 8)
    double_height = max(single_height, table.fontMetrics().lineSpacing() * 2 + 8)
    updates_were_enabled = table.updatesEnabled()
    table.setUpdatesEnabled(False)
    try:
        for row in range(table.rowCount()):
            needs_two_lines = False
            for column in wrap_columns:
                if table.isColumnHidden(column):
                    continue
                item = table.item(row, column)
                if item is None or not item.text():
                    continue
                available_width = max(20, table.columnWidth(column) - 12)
                layout = QTextLayout(item.text(), table.font())
                text_option = QTextOption()
                text_option.setWrapMode(
                    QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere
                )
                layout.setTextOption(text_option)
                layout.beginLayout()
                first_line = layout.createLine()
                if first_line.isValid():
                    first_line.setLineWidth(available_width)
                second_line = layout.createLine()
                if second_line.isValid():
                    needs_two_lines = True
                layout.endLayout()
                if needs_two_lines:
                    break
            target_height = double_height if needs_two_lines else single_height
            if table.rowHeight(row) != target_height:
                table.setRowHeight(row, target_height)
    finally:
        table.setUpdatesEnabled(updates_were_enabled)


@contextmanager
def batch_table_updates(table: QTableWidget):
    """대량 셀 교체 중 신호ㆍ페인트ㆍ열 자동 폭 계산을 미룬다."""
    signals_were_blocked = table.blockSignals(True)
    updates_were_enabled = table.updatesEnabled()
    header = table.horizontalHeader()
    resize_modes = tuple(
        header.sectionResizeMode(column) for column in range(table.columnCount())
    )
    table.setUpdatesEnabled(False)
    header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
    try:
        yield
    finally:
        for column, resize_mode in enumerate(resize_modes):
            header.setSectionResizeMode(column, resize_mode)
        table.blockSignals(signals_were_blocked)
        table.setUpdatesEnabled(updates_were_enabled)


def configure_adaptive_result_rows(
    table: QTableWidget,
    wrap_columns: tuple[int, ...],
    minimum_height: int = 26,
) -> None:
    """한 줄 결과는 촘촘하게, 명칭·조문 줄바꿈만 두 줄 높이로 확장."""
    table._adaptive_wrap_columns = tuple(wrap_columns)
    table.setWordWrap(True)
    vertical_header = table.verticalHeader()
    vertical_header.setMinimumSectionSize(minimum_height)
    vertical_header.setDefaultSectionSize(minimum_height)
    vertical_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
    table.horizontalHeader().sectionResized.connect(
        lambda _index, _old, _new, result_table=table: QTimer.singleShot(
            0,
            lambda: resize_adaptive_result_rows(result_table),
        )
    )


def configure_horizontal_splitter(splitter: QSplitter) -> None:
    """분할선에서 좌우 드래그 커서와 사용 안내를 명확히 표시."""
    splitter.setHandleWidth(10)
    handle = splitter.handle(1)
    if handle is None:
        return
    handle.setCursor(Qt.CursorShape.SplitHCursor)
    handle.setToolTip("좌우로 드래그하여 영역 너비를 조절합니다.")


def build_dismissible_banner(
    text: str, settings: QSettings, key: str
) -> QWidget:
    """닫을 수 있는 상단 안내 배너를 만든다.

    한 번 닫으면 설정에 기억해 다음 실행에도 다시 뜨지 않는다. 매번
    반복 사용하는 실무자에게는 학습이 끝난 뒤에도 영구히 화면을
    차지하던 안내문을 스스로 치울 수 있게 한다.
    """
    row = QWidget()
    row.setObjectName("dismissibleBanner")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)

    label = QLabel(text)
    label.setObjectName("mutedText")
    label.setWordWrap(True)
    label.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextSelectableByMouse
        | Qt.TextInteractionFlag.TextSelectableByKeyboard
    )
    label.setCursor(Qt.CursorShape.IBeamCursor)

    close_button = QPushButton("✕")
    close_button.setObjectName("bannerDismissButton")
    close_button.setFixedSize(24, 24)
    close_button.setToolTip("이 안내를 닫습니다. 다음 실행에도 숨겨집니다.")
    close_button.setAccessibleName("안내 닫기")

    layout.addWidget(label, 1)
    layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignTop)

    def _dismiss(_checked: bool = False) -> None:
        settings.setValue(key, True)
        row.setVisible(False)

    close_button.clicked.connect(_dismiss)
    if bool(settings.value(key, False, type=bool)):
        row.setVisible(False)
    return row


def build_restore_view_button(owner) -> QPushButton:
    """크게 보기에서 원래 화면으로 돌아가는 왼쪽 ◀ 버튼."""
    button = QPushButton()
    button.setObjectName("restoreViewButton")
    button.setFixedSize(30, 30)
    button.setIcon(
        button.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack)
    )
    button.setToolTip("원래 화면으로 돌아가기")
    button.setShortcut(QKeySequence("Alt+Left"))
    button.clicked.connect(owner._exit_reading_mode)
    button.hide()
    return button


def build_count_badge(text: str = "0건") -> QLabel:
    """검색 결과 건수 표시. 화면마다 크기가 달라지지 않게 한곳에서 만든다."""
    badge = QLabel(text)
    badge.setObjectName("countBadge")
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return badge


DETAIL_FONT_SIZE_MIN = 7.0
DETAIL_FONT_SIZE_MAX = 18.0
DETAIL_FONT_SIZE_STEP = 0.5
DETAIL_FONT_LABEL_WIDTH = 24
DETAIL_FONT_CONTROL_WIDTH = 80


def clamp_detail_font_size(value: float) -> float:
    """저장값을 공용 본문 글자 크기 범위 안으로 제한한다."""
    return max(DETAIL_FONT_SIZE_MIN, min(DETAIL_FONT_SIZE_MAX, float(value)))


def normalize_detail_font_size(value: float) -> float:
    """본문 글자 크기를 공용 증감 단위에 맞춘 뒤 범위 안으로 제한한다."""
    snapped = round(float(value) / DETAIL_FONT_SIZE_STEP) * DETAIL_FONT_SIZE_STEP
    return clamp_detail_font_size(snapped)


@dataclass(frozen=True, slots=True)
class DetailHeaderControls:
    """본문 머리글에서 함께 쓰는 제목과 글자 크기 조절 묶음."""

    title: DoubleClickLabel
    font_label: QLabel
    font_spin: QDoubleSpinBox


def build_detail_header_controls(font_size: float) -> DetailHeaderControls:
    """검색 화면마다 같은 규격으로 쓰는 본문 머리글 조절부를 만든다."""
    title = DoubleClickLabel("본문")
    title.setObjectName("detailSectionTitle")
    title.setToolTip("더블클릭하면 본문 크게 보기로 전환합니다.")

    font_label = QLabel("글자")
    font_label.setObjectName("fontSizeLabel")
    font_label.setFixedWidth(DETAIL_FONT_LABEL_WIDTH)

    font_spin = QDoubleSpinBox()
    font_spin.setObjectName("fontSizeSpin")
    font_spin.setToolTip(
        "본문 글자 크기 · 위아래 버튼으로 0.5pt씩 조절"
    )
    font_spin.setRange(DETAIL_FONT_SIZE_MIN, DETAIL_FONT_SIZE_MAX)
    font_spin.setDecimals(1)
    font_spin.setSingleStep(DETAIL_FONT_SIZE_STEP)
    font_spin.setSuffix("pt")
    font_spin.setValue(font_size)
    font_spin.setFixedWidth(DETAIL_FONT_CONTROL_WIDTH)

    return DetailHeaderControls(title, font_label, font_spin)


@dataclass(frozen=True, slots=True)
class SearchResultHead:
    layout: QHBoxLayout
    count: QLabel
    shade_reset: QPushButton
    refresh: QPushButton


def build_search_result_head(
    *,
    on_clear_highlight: Callable[..., object],
    on_refresh_api: Callable[..., object],
    refresh_tooltip: str,
) -> SearchResultHead:
    """검색 결과 제목·건수·음영초기화·API갱신 한 줄."""
    layout = QHBoxLayout()
    title = QLabel("검색 결과")
    title.setObjectName("sectionTitle")
    count = build_count_badge()
    shade_reset = QPushButton("음영초기화")
    shade_reset.setObjectName("searchShadeResetButton")
    shade_reset.setEnabled(False)
    shade_reset.clicked.connect(on_clear_highlight)
    refresh = QPushButton("API갱신")
    refresh.setObjectName("searchShadeResetButton")
    refresh.setToolTip(refresh_tooltip)
    refresh.clicked.connect(on_refresh_api)
    layout.addWidget(title)
    layout.addWidget(count)
    layout.addWidget(shade_reset)
    layout.addStretch()
    layout.addWidget(refresh)
    layout.setAlignment(count, Qt.AlignmentFlag.AlignVCenter)
    layout.setAlignment(refresh, Qt.AlignmentFlag.AlignBottom)
    return SearchResultHead(layout, count, shade_reset, refresh)


def prompt_oc_api_key(owner) -> None:
    """법제처 인증키가 없을 때 설정 창을 연다."""
    window = owner.window() if hasattr(owner, "window") else owner
    opener = getattr(window, "open_oc_api_settings", None)
    if callable(opener):
        opener()


def close_hovered_reference_popup(owner) -> bool:
    """마우스가 올라와 있는 조항호목·3단비교 팝업을 닫는다.

    고정된 팝업도 함께 닫는다. 닫을 팝업이 없으면 False를 돌려준다.
    """
    popups: list = []
    getter = getattr(owner, "_all_reference_popups", None)
    if callable(getter):
        popups.extend(getter())
    three_stage = getattr(owner, "three_stage_popup", None)
    if three_stage is not None:
        popups.append(three_stage)
    cursor_position = QCursor.pos()
    # 겹쳐 있으면 가장 위에 뜬 팝업부터 닫는다.
    for popup in reversed(popups):
        try:
            if popup.isVisible() and popup.frameGeometry().contains(
                cursor_position
            ):
                popup._close_popup()
                return True
        except RuntimeError:
            continue
    return False


class ResultHeaderView(QHeaderView):
    """결과표 제목 행의 열 구분선을 그린다."""

    def paintSection(self, painter, rect, logical_index) -> None:
        super().paintSection(painter, rect, logical_index)
        if logical_index < self.count() - 1:
            painter.save()
            painter.setPen(QColor("#c7d2dc"))
            painter.drawLine(rect.topRight(), rect.bottomRight())
            painter.restore()


class PairedCategoryBar(QWidget):
    """QTabBar 대신, 짝이 되는 두 버튼(예: 법령·별표·서식)을 실제 테두리 프레임 안에 넣어
    하나의 세트로 보여주는 상단 카테고리 바. QTabBar의 최소 API(addTab/tabData/
    currentIndex/currentChanged 등)를 흉내내 기존 연동 코드를 그대로 사용할 수 있게 함."""

    currentChanged = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._row_layout = QHBoxLayout(self)
        self._row_layout.setContentsMargins(0, 0, 0, 0)
        self._row_layout.setSpacing(8)
        self._buttons: list[QPushButton] = []
        self._tab_data: list[object] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.idClicked.connect(self._set_current)
        self._current_index = -1

    def _make_button(self, text: str, object_name: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(object_name)
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedHeight(self.FRAME_HEIGHT - 8)
        index = len(self._buttons)
        self._buttons.append(button)
        self._tab_data.append(None)
        self._group.addButton(button, index)
        return button

    FRAME_HEIGHT = 44

    def addTab(self, text: str) -> int:
        # 통합검색도 옆 카테고리 묶음과 같은 캡슐형 외곽을 쓴다.
        # 안쪽 버튼은 별도 테두리 없이 배경으로만 선택 상태를 표시한다.
        frame = QFrame()
        frame.setObjectName("resourceSubTabSingleFrame")
        frame.setFixedHeight(self.FRAME_HEIGHT)
        frame_layout = QHBoxLayout(frame)
        frame_layout.setContentsMargins(4, 4, 4, 4)
        button = self._make_button(text, "resourceSubTabSingle")
        frame_layout.addWidget(button)
        self._row_layout.addWidget(frame)
        return len(self._buttons) - 1

    def add_pair(self, first_text: str, second_text: str) -> tuple[int, int]:
        frame = QFrame()
        frame.setObjectName("resourceSubTabFrame")
        frame.setFixedHeight(self.FRAME_HEIGHT)
        frame_layout = QHBoxLayout(frame)
        frame_layout.setContentsMargins(4, 4, 4, 4)
        frame_layout.setSpacing(2)
        first = self._make_button(first_text, "resourceSubTabPaired")
        second = self._make_button(second_text, "resourceSubTabPaired")
        frame_layout.addWidget(first)
        frame_layout.addWidget(second)
        self._row_layout.addWidget(frame)
        return len(self._buttons) - 2, len(self._buttons) - 1

    def add_stretch(self) -> None:
        self._row_layout.addStretch(1)

    def setTabData(self, index: int, data: object) -> None:
        if 0 <= index < len(self._tab_data):
            self._tab_data[index] = data

    def tabData(self, index: int) -> object:
        if 0 <= index < len(self._tab_data):
            return self._tab_data[index]
        return None

    def count(self) -> int:
        return len(self._buttons)

    def currentIndex(self) -> int:
        return self._current_index

    def setCurrentIndex(self, index: int) -> None:
        if not (0 <= index < len(self._buttons)):
            return
        self._buttons[index].setChecked(True)
        self._set_current(index)

    def _set_current(self, index: int) -> None:
        if index == self._current_index:
            return
        self._current_index = index
        self.currentChanged.emit(index)


class StatusLine:
    """화면 하나가 쓰는 상태 문구 자리. 실제 표시는 공용 하단바가 한다.

    화면마다 상태줄을 따로 두면 창 아래에 그 줄과 별개로 프로그램 정보
    단추 줄이 하나 더 생겨 여백이 두 배가 된다. 그래서 실물 상태줄은 창에
    하나만 두고, 각 화면은 이 자리를 자기 것처럼 쓴다. 문구는 화면별로
    보관하다가 그 화면이 앞에 나올 때 하단바에 올린다. 뒤에서 끝난 검색이
    지금 보는 화면의 문구를 덮어쓰지 않는다.

    화면 코드가 쓰던 QLabel API(setText/text/setToolTip/setVisible)를 그대로
    받아 주므로 호출부는 손대지 않는다.
    """

    def __init__(self, bar: "SharedStatusBar") -> None:
        self._bar = bar
        self._text = ""
        self._tooltip = ""
        self._visible = True
        self._opacity = 0.0

    # --- QLabel 대체 ------------------------------------------------
    def setText(self, text: str) -> None:
        self._text = str(text)
        self._bar.refresh(self)

    def text(self) -> str:
        return self._text

    def setToolTip(self, text: str) -> None:
        self._tooltip = str(text)
        self._bar.refresh(self)

    def toolTip(self) -> str:
        return self._tooltip

    def setVisible(self, visible: bool) -> None:
        self._visible = bool(visible)
        self._bar.refresh(self)

    def isVisible(self) -> bool:
        return self._visible

    def isHidden(self) -> bool:
        return not self._visible

    def setObjectName(self, name: str) -> None:
        """공용 하단바가 자기 이름을 쓰므로 받기만 한다."""

    # --- 진행 표시 --------------------------------------------------
    def setOpacity(self, opacity: float) -> None:
        self._opacity = float(opacity)
        self._bar.refresh(self)

    def opacity(self) -> float:
        return self._opacity


class SharedStatusBar(QFrame):
    """창 아래에 하나만 두는 상태줄. 오른쪽에 프로그램 정보 단추가 함께 선다."""

    HEIGHT = 26

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("sharedStatusBar")
        self.setFixedHeight(self.HEIGHT)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.label = QLabel("")
        self.label.setObjectName("mutedText")
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedSize(120, 8)
        self.progress.setTextVisible(False)
        # 껐다 켜면 상태줄 폭이 바뀌어 그 위 본문까지 흔들린다. 자리는 늘
        # 차지하되 투명도만 조절한다.
        self._opacity = QGraphicsOpacityEffect(self.progress)
        self._opacity.setOpacity(0.0)
        self.progress.setGraphicsEffect(self._opacity)
        layout.addWidget(self.label, 1)
        layout.addWidget(self.progress)
        self._trailing = QHBoxLayout()
        self._trailing.setContentsMargins(0, 0, 0, 0)
        self._trailing.setSpacing(10)
        layout.addLayout(self._trailing)
        self._active: StatusLine | None = None
        self._owners: dict[QWidget, StatusLine] = {}

    def add_trailing_widget(self, widget: QWidget) -> None:
        """상태 문구와 같은 줄, 오른쪽 끝에 세울 위젯(업데이트ㆍ정보 단추)."""
        self._trailing.addWidget(widget)

    def line_for(self, owner: QWidget) -> StatusLine:
        """화면 하나가 쓸 자리를 내주고, 그 화면이 보일 때 앞으로 올린다."""
        line = StatusLine(self)
        owner.installEventFilter(self)
        self._owners[owner] = line
        if self._active is None:
            self.set_active(line)
        return line

    def set_active(self, line: StatusLine) -> None:
        self._active = line
        self.refresh(line)

    def refresh(self, line: StatusLine) -> None:
        """지금 앞에 나온 화면의 문구만 실제 상태줄에 옮긴다."""
        if line is not self._active:
            return
        self.label.setText(line.text())
        self.label.setToolTip(line.toolTip())
        self.label.setVisible(line.isVisible())
        self.progress.setVisible(line.isVisible())
        self._opacity.setOpacity(line.opacity())

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.Show:
            line = self._owners.get(watched)
            if line is not None:
                self.set_active(line)
        return super().eventFilter(watched, event)


class SegmentedModeSwitch(QFrame):
    """검색줄 안에서 모드를 고르는 작은 캡슐형 스위치.

    카테고리 바의 짝 캡슐과 같은 모양이되, 검색어 칸ㆍ콤보와 한 줄에 서도록
    높이를 낮춘 것이다. 고른 값은 ``changed``로 알린다.
    """

    changed = Signal(str)

    # 검색줄의 콤보ㆍ입력칸과 같은 높이. 버튼 자체 높이는 스타일시트가
    # 정한다. 파이썬에서 setFixedHeight로 잡으면 스타일시트의 여백 규칙과
    # 부딪혀 버튼이 캡슐 밖으로 밀려 나온다.
    HEIGHT = 40

    def __init__(self, items: tuple[tuple[str, str], ...], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("modeSwitchFrame")
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self._values: list[str] = []
        self._buttons: list[QPushButton] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for label, value in items:
            button = QPushButton(label, self)
            button.setObjectName("modeSwitchButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self._group.addButton(button, len(self._buttons))
            self._values.append(value)
            self._buttons.append(button)
            layout.addWidget(button)
        if self._buttons:
            self._buttons[0].setChecked(True)
        self._group.idClicked.connect(self._clicked)

    def _clicked(self, index: int) -> None:
        if 0 <= index < len(self._values):
            self.changed.emit(self._values[index])

    def current_value(self) -> str:
        for index, button in enumerate(self._buttons):
            if button.isChecked():
                return self._values[index]
        return ""

    def set_current_value(self, value: str) -> None:
        """신호를 내지 않고 표시 상태만 맞춘다."""
        if value not in self._values:
            return
        self._buttons[self._values.index(value)].setChecked(True)


class GroupedNavigationList(QListWidget):
    """좌측 대표 메뉴용 세로 내비게이션 목록."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._group_ranges: list[tuple[int, int]] = []

    def set_group_range(self, start_row: int, end_row: int) -> None:
        self.set_group_ranges([(start_row, end_row)])

    def set_group_ranges(self, ranges: list[tuple[int, int]]) -> None:
        self._group_ranges = [
            (min(start, end), max(start, end)) for start, end in ranges
        ]
        self.viewport().update()

    def _section_rects(self) -> list[QRect]:
        """단독 메뉴와 연관 검색군의 카드 외곽 영역을 반환."""
        rectangles: list[QRect] = []
        for group_start_row, group_end_row in self._group_ranges:
            group_rectangle = QRect()
            for row in range(group_start_row, group_end_row + 1):
                item = self.item(row)
                if item is None or item.isHidden():
                    continue
                item_rectangle = self.visualItemRect(item)
                if not item_rectangle.isValid():
                    continue
                group_rectangle = (
                    QRect(item_rectangle)
                    if group_rectangle.isNull()
                    else group_rectangle.united(item_rectangle)
                )
            if not group_rectangle.isNull():
                rectangles.append(group_rectangle.adjusted(1, 0, -1, 0))
        return rectangles

    def paintEvent(self, event) -> None:
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor("#41627f"))
        painter.setBrush(QColor("#173956"))
        for rectangle in self._section_rects():
            painter.drawRoundedRect(rectangle, 8, 8)
        painter.end()
        super().paintEvent(event)


class CenteredCheckDelegate(QStyledItemDelegate):
    """저장 체크의 포커스 사각형을 없애고 셀 가운데에 표시."""

    def paint(self, painter, option, index) -> None:
        clean_option = QStyleOptionViewItem(option)
        clean_option.state &= ~QStyle.StateFlag.State_HasFocus
        check_state = index.data(Qt.ItemDataRole.CheckStateRole)
        if check_state is None:
            super().paint(painter, clean_option, index)
            return

        self.initStyleOption(clean_option, index)
        clean_option.state &= ~QStyle.StateFlag.State_HasFocus
        style = option.widget.style() if option.widget else QApplication.style()
        indicator_rect = style.subElementRect(
            QStyle.SubElement.SE_ItemViewItemCheckIndicator,
            clean_option,
            option.widget,
        )
        centered_x = option.rect.x() + (
            option.rect.width() - indicator_rect.width()
        ) // 2
        clean_option.rect.translate(centered_x - indicator_rect.x(), 0)
        painter.save()
        painter.setClipRect(option.rect)
        super().paint(painter, clean_option, index)
        painter.restore()

    def editorEvent(self, event, model, option, index) -> bool:
        # 체크박스를 셀 가운데 그리기 때문에, 기본 클릭 판정 영역(왼쪽 정렬 기준)이
        # 눈에 보이는 위치와 어긋나 클릭이 씹히는 문제가 있었음. 셀 전체를 클릭
        # 가능 영역으로 취급해 토글되게 함.
        if (
            event.type() == QEvent.Type.MouseButtonRelease
            and index.data(Qt.ItemDataRole.CheckStateRole) is not None
            and bool(index.flags() & Qt.ItemFlag.ItemIsEnabled)
            and bool(index.flags() & Qt.ItemFlag.ItemIsUserCheckable)
        ):
            current = Qt.CheckState(
                int(index.data(Qt.ItemDataRole.CheckStateRole))
            )
            new_state = (
                Qt.CheckState.Unchecked
                if current == Qt.CheckState.Checked
                else Qt.CheckState.Checked
            )
            model.setData(
                index, new_state.value, Qt.ItemDataRole.CheckStateRole
            )
            return True
        return super().editorEvent(event, model, option, index)


class StableHorizontalTableWidget(QTableWidget):
    """행 선택(클릭·키보드·코드 호출)으로 가로 스크롤이 자동 이동하지 않도록 위치를 보존."""

    def scrollTo(self, index, hint=QAbstractItemView.ScrollHint.EnsureVisible) -> None:
        scroll_bar = self.horizontalScrollBar()
        previous_value = scroll_bar.value()
        super().scrollTo(index, hint)
        scroll_bar.setValue(previous_value)


class DeferredWrapTextBrowser(QTextBrowser):
    """실제 최상위 창 크기 조절 중에만 줄바꿈을 잠시 미룬다."""

    WRAP_SETTLE_MS = 140

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._wrap_deferred = False
        self._restoring_wrap = False
        self._resize_scroll_ratio = 0.0
        self._resize_anchor_position = -1
        self._resize_anchor_viewport_y = 0
        self._last_top_level_size = QSize()
        self._deferred_horizontal_policy = (
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._wrap_timer = QTimer(self)
        self._wrap_timer.setSingleShot(True)
        self._wrap_timer.timeout.connect(self._finish_deferred_wrap)

    def createMimeDataFromSelection(self):
        # 드래그 복사ㆍCtrl+Cㆍ우클릭 복사가 모두 이 경로를 지나므로,
        # 여기서 한 번만 한글용 표기로 바꿔 두면 붙여넣기 경로 전체가
        # 함께 고쳐진다. 화면에 그려지는 HTML은 건드리지 않는다.
        mime = super().createMimeDataFromSelection()
        if mime is not None and mime.hasHtml():
            mime.setHtml(hwp_friendly_clipboard_html(mime.html()))
        return mime

    def viewportEvent(self, event) -> bool:
        if event.type() == QEvent.Type.Resize and hasattr(self, "_wrap_timer"):
            top_level_size = self.window().size()
            top_level_resized = (
                self._last_top_level_size.isValid()
                and top_level_size != self._last_top_level_size
            )
            self._last_top_level_size = QSize(top_level_size)
            if (
                not self._restoring_wrap
                and self.document().characterCount() > 1
                and (top_level_resized or self._wrap_deferred)
            ):
                if not self._wrap_deferred:
                    scroll_bar = self.verticalScrollBar()
                    self._resize_scroll_ratio = (
                        scroll_bar.value() / scroll_bar.maximum()
                        if scroll_bar.maximum() > 0
                        else 0.0
                    )
                    anchor_cursor = self.cursorForPosition(QPoint(2, 2))
                    self._resize_anchor_position = anchor_cursor.position()
                    self._resize_anchor_viewport_y = self.cursorRect(
                        anchor_cursor
                    ).top()
                    old_width = max(80, event.oldSize().width())
                    self._wrap_deferred = True
                    # 이전의 넓은 폭을 잠시 유지하는 동안 Qt가 가로
                    # 스크롤바를 만들면 그 자체로 viewport가 다시 줄어든다.
                    # 지연 구간에는 숨기고 최종 줄바꿈 뒤 원래 정책을 복원한다.
                    self._deferred_horizontal_policy = (
                        self.horizontalScrollBarPolicy()
                    )
                    self.setHorizontalScrollBarPolicy(
                        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
                    )
                    self.setLineWrapMode(
                        QTextEdit.LineWrapMode.FixedPixelWidth
                    )
                    self.setLineWrapColumnOrWidth(old_width)
                self._wrap_timer.start(self.WRAP_SETTLE_MS)
        return super().viewportEvent(event)

    def _finish_deferred_wrap(self) -> None:
        if not self._wrap_deferred:
            return
        self._restoring_wrap = True
        self._wrap_deferred = False
        try:
            self.setUpdatesEnabled(False)
            self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
            self.setHorizontalScrollBarPolicy(
                self._deferred_horizontal_policy
            )
        finally:
            self.setUpdatesEnabled(True)
            self._restoring_wrap = False
        # 수신 객체를 함께 넘겨, 창을 닫은 뒤 남은 다음 틱 콜백이 파괴된
        # QTextBrowser를 다시 만지지 않게 한다.
        QTimer.singleShot(0, self, self._restore_resize_scroll)
        self.viewport().update()

    def _restore_resize_scroll(self) -> None:
        scroll_bar = self.verticalScrollBar()
        if 0 <= self._resize_anchor_position < self.document().characterCount():
            # 새 폭으로 문서 배치가 끝난 뒤, 크기 변경 전에 화면 첫 줄에
            # 있던 문자가 같은 세로 위치에 오도록 스크롤한다.
            self.document().size()
            anchor_cursor = QTextCursor(self.document())
            anchor_cursor.setPosition(self._resize_anchor_position)
            anchor_y = self.cursorRect(anchor_cursor).top()
            scroll_bar.setValue(
                scroll_bar.value()
                + anchor_y
                - self._resize_anchor_viewport_y
            )
            self._resize_anchor_position = -1
            return
        scroll_bar.setValue(round(self._resize_scroll_ratio * scroll_bar.maximum()))


class SearchHighlightDelegate(QStyledItemDelegate):
    """두 줄 안건명에서 검색어와 일치한 부분만 음영으로 강조."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._terms: tuple[str, ...] = ()
        self._pattern: re.Pattern[str] | None = None

    def set_terms(self, terms: tuple[str, ...]) -> None:
        self._terms = terms
        self._pattern = (
            re.compile(
                "|".join(
                    pattern
                    for term in terms
                    if (pattern := whitespace_flexible_pattern(term))
                ),
                re.IGNORECASE,
            )
            if terms
            else None
        )

    def sizeHint(self, option, index):
        """한 줄은 낮게 유지하고 긴 제목만 최대 두 줄 높이로 확장."""
        styled_option = QStyleOptionViewItem(option)
        self.initStyleOption(styled_option, index)
        table = styled_option.widget
        available_width = max(
            20,
            (
                table.columnWidth(index.column())
                if isinstance(table, QTableWidget)
                else max(20, option.rect.width())
            )
            - 12,
        )
        layout = QTextLayout(styled_option.text, styled_option.font)
        text_option = QTextOption()
        text_option.setWrapMode(
            QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere
        )
        layout.setTextOption(text_option)
        line_height = 0.0
        layout.beginLayout()
        for _unused in range(2):
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(available_width)
            line_height += line.height()
        layout.endLayout()
        size = super().sizeHint(option, index)
        size.setHeight(max(26, round(line_height + 6)))
        return size

    def paint(self, painter, option, index) -> None:
        styled_option = QStyleOptionViewItem(option)
        self.initStyleOption(styled_option, index)
        text = styled_option.text
        styled_option.text = ""
        style = (
            styled_option.widget.style()
            if styled_option.widget is not None
            else QApplication.style()
        )
        style.drawControl(
            QStyle.ControlElement.CE_ItemViewItem,
            styled_option,
            painter,
            styled_option.widget,
        )

        text_rect = option.rect.adjusted(6, 3, -6, -3)
        layout = QTextLayout(text, styled_option.font)
        text_option = QTextOption()
        text_option.setWrapMode(
            QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere
        )
        layout.setTextOption(text_option)

        if self._pattern is not None:
            ranges = []
            for match in self._pattern.finditer(text):
                char_format = QTextCharFormat()
                char_format.setBackground(QColor("#ffe58f"))
                char_format.setForeground(QColor("#172033"))
                format_range = QTextLayout.FormatRange()
                format_range.start = match.start()
                format_range.length = match.end() - match.start()
                format_range.format = char_format
                ranges.append(format_range)
            layout.setFormats(ranges)

        layout.beginLayout()
        line_height = 0.0
        for _ in range(2):
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(max(0, text_rect.width()))
            line.setPosition(QPointF(0, line_height))
            line_height += line.height()
        layout.endLayout()

        painter.save()
        painter.setClipRect(text_rect)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.setPen(option.palette.highlightedText().color())
        else:
            painter.setPen(option.palette.text().color())
        top = text_rect.top() + max(0.0, (text_rect.height() - line_height) / 2)
        layout.draw(painter, QPointF(text_rect.left(), top))
        painter.restore()


class FavoriteTitleDelegate(SearchHighlightDelegate):
    """제목 왼쪽 또는 전용 열에 즐겨찾기 별을 그리고 클릭하면 토글."""

    STAR_WIDTH = 22

    def __init__(
        self,
        toggle_callback,
        is_favorite_callback,
        parent=None,
        *,
        star_only: bool = False,
    ) -> None:
        super().__init__(parent)
        self._toggle_callback = toggle_callback
        self._is_favorite_callback = is_favorite_callback
        self._star_only = star_only

    def _star_rect(self, option: QStyleOptionViewItem) -> QRect:
        if self._star_only:
            return QRect(option.rect)
        return QRect(
            option.rect.left(),
            option.rect.top(),
            self.STAR_WIDTH,
            option.rect.height(),
        )

    def paint(self, painter, option, index) -> None:
        is_favorite = bool(self._is_favorite_callback(index.row()))
        star_rect = self._star_rect(option)
        if self._star_only:
            QStyledItemDelegate.paint(self, painter, option, index)
        painter.save()
        painter.setPen(QColor("#e2a400" if is_favorite else "#c3ccd6"))
        font = QFont(painter.font())
        font.setPointSizeF(font.pointSizeF() + 1.5)
        painter.setFont(font)
        painter.drawText(
            star_rect, Qt.AlignmentFlag.AlignCenter, "★" if is_favorite else "☆"
        )
        painter.restore()
        if self._star_only:
            return
        shifted_option = QStyleOptionViewItem(option)
        shifted_option.rect = QRect(option.rect)
        shifted_option.rect.setLeft(option.rect.left() + self.STAR_WIDTH)
        super().paint(painter, shifted_option, index)

    def editorEvent(self, event, model, option, index) -> bool:
        if event.type() == QEvent.Type.MouseButtonRelease:
            star_rect = self._star_rect(option)
            if star_rect.contains(event.position().toPoint()):
                self._toggle_callback(index.row())
                return True
        return False
class FavoriteTreeItemDelegate(QStyledItemDelegate):
    """Paint selection inside the item's own rect, excluding tree branches.

    즐겨찾기 항목(record) 오른쪽 끝에 해제(×) 버튼을 그려서, 우클릭 메뉴나
    Delete 키를 몰라도 바로 눈에 보이는 방식으로 즐겨찾기를 해제할 수
    있게 한다."""

    REMOVE_BUTTON_WIDTH = 22
    _KIND_ROLE = int(Qt.ItemDataRole.UserRole) + 1

    def _is_record(self, index) -> bool:
        return index.data(self._KIND_ROLE) in ("record", "article")

    def _remove_rect(self, option) -> QRect:
        return QRect(
            option.rect.left(),
            option.rect.top(),
            self.REMOVE_BUTTON_WIDTH,
            option.rect.height(),
        )

    def paint(self, painter, option, index) -> None:
        styled_option = QStyleOptionViewItem(option)
        is_record = self._is_record(index)
        if is_record:
            styled_option.rect = styled_option.rect.adjusted(
                self.REMOVE_BUTTON_WIDTH, 0, 0, 0
            )
        selected = bool(
            styled_option.state & QStyle.StateFlag.State_Selected
        )
        if selected:
            depth = 0
            parent_index = index.parent()
            while parent_index.isValid():
                depth += 1
                parent_index = parent_index.parent()
            tree = self.parent()
            indentation = (
                tree.indentation()
                if isinstance(tree, QTreeWidget)
                else 0
            )
            # 별표 자리를 위해 줄인 styled_option.rect가 아니라 원래
            # option.rect 기준으로 그려서, 선택 음영이 별표까지 포함해
            # 줄 전체를 덮도록 한다(안 그러면 별표만 음영 밖으로
            # 빠져나와 보인다).
            selection_rect = option.rect.adjusted(
                indentation * depth + 1, 1, -1, -1
            )
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#dcecf9"))
            painter.drawRoundedRect(selection_rect, 5, 5)
            painter.restore()
            styled_option.state &= ~QStyle.StateFlag.State_Selected
            styled_option.state &= ~QStyle.StateFlag.State_MouseOver
            styled_option.state &= ~QStyle.StateFlag.State_HasFocus
            styled_option.palette.setColor(
                QPalette.ColorRole.Text, QColor("#1768aa")
            )
            styled_option.palette.setColor(
                QPalette.ColorRole.HighlightedText, QColor("#1768aa")
            )
        super().paint(painter, styled_option, index)

        if is_record:
            remove_rect = self._remove_rect(option)
            hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            font = QFont(painter.font())
            font.setPointSizeF(font.pointSizeF() + 1.0)
            painter.setFont(font)
            # 즐겨찾기 표시와 같은 별(★)을 그대로 눌러서 해제하는
            # 기존 방식을 그대로 따른다. 눌러서 해제된다는 걸 알 수
            # 있도록 마우스를 올리면 색이 진해진다.
            painter.setPen(QColor("#c88700" if hovered else "#e2a400"))
            painter.drawText(remove_rect, Qt.AlignmentFlag.AlignCenter, "★")
            painter.restore()

    def editorEvent(self, event, model, option, index) -> bool:
        if (
            self._is_record(index)
            and event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
            and self._remove_rect(option).contains(
                event.position().toPoint()
            )
        ):
            tree = self.parent()
            if isinstance(tree, FavoriteCategoryTree):
                tree.removeRequested.emit(index)
            return True
        return super().editorEvent(event, model, option, index)



class FavoriteCategoryTree(QTreeWidget):
    """즐겨찾기 고정 구분 카드 안에서만 이동하는 폴더 트리."""

    categoryActivated = Signal(str)
    removeRequested = Signal(object)

    def __init__(self, category: str, parent=None) -> None:
        super().__init__(parent)
        self.category = category
        self.setItemDelegate(FavoriteTreeItemDelegate(self))
        self.setMouseTracking(True)

    def focusInEvent(self, event) -> None:
        self.categoryActivated.emit(self.category)
        super().focusInEvent(event)

    def mousePressEvent(self, event) -> None:
        self.categoryActivated.emit(self.category)
        position = event.position().toPoint()
        item = self.itemAt(position)
        if (
            item is not None
            and item.data(0, Qt.ItemDataRole.UserRole)
            and position.x() < self.visualItemRect(item).left()
        ):
            event.accept()
            return
        super().mousePressEvent(event)


class DetailSearchBar(QWidget):
    """QTextBrowser 본문 안의 일치 항목을 강조하고 이전·다음으로 이동."""

    def __init__(self, browser: QTextBrowser, parent=None) -> None:
        super().__init__(parent)
        self.browser = browser
        self.matches: list[QTextCursor] = []
        self.base_selections: list[QTextEdit.ExtraSelection] = []
        self.current_index = -1
        self._document_change_suspended = False
        self.setObjectName("detailSearchBar")

        layout = QHBoxLayout(self)
        # 본문 카드 경계에 라벨이 바로 붙지 않도록
        # 검색줄에만 작은 왼쪽 여백을 둔다.
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(6)

        label = QLabel("본문 검색")
        label.setObjectName("detailSearchLabel")
        self.query_input = QLineEdit()
        self.query_input.setObjectName("detailSearchInput")
        self.query_input.setProperty("findActive", False)
        self.query_input.setPlaceholderText("본문에서 찾을 단어")
        self.query_input.setClearButtonEnabled(True)
        self.query_input.installEventFilter(self)
        self.whole_word_checkbox = QCheckBox("전체 단어 일치")
        self.whole_word_checkbox.setObjectName("detailSearchWholeWord")
        self.whole_word_checkbox.setToolTip(
            "검색어가 다른 글자에 포함되지 않은 경우만 찾습니다."
        )
        self.count_label = QLabel("0/0")
        self.count_label.setObjectName("detailSearchCount")
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.count_label.setFixedWidth(54)
        self.previous_button = QPushButton("이전")
        self.previous_button.setObjectName("detailSearchButton")
        self.previous_button.setFixedWidth(54)
        self.next_button = QPushButton("다음")
        self.next_button.setObjectName("detailSearchButton")
        self.next_button.setFixedWidth(54)

        layout.addWidget(label)
        layout.addWidget(self.query_input, 1)
        layout.addWidget(self.whole_word_checkbox)
        layout.addWidget(self.count_label)
        layout.addWidget(self.previous_button)
        layout.addWidget(self.next_button)

        self.query_input.textChanged.connect(lambda _text: self.refresh())
        self.whole_word_checkbox.toggled.connect(lambda _checked: self.refresh())
        self.query_input.returnPressed.connect(lambda: self.move(1))
        self.previous_button.clicked.connect(lambda: self.move(-1))
        self.next_button.clicked.connect(lambda: self.move(1))
        self.browser.document().contentsChanged.connect(self.refresh)
        self._connected_document = self.browser.document()
        self.find_shortcut = QShortcut(
            QKeySequence(QKeySequence.StandardKey.Find), self.browser
        )
        self.find_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self.find_shortcut.activated.connect(self.focus_query)
        self._update_controls()

    def bind_document(self, document) -> None:
        """본문 뷰가 보관 중인 다른 QTextDocument로 전환될 때 재연결."""
        if document is self._connected_document:
            return
        try:
            self._connected_document.contentsChanged.disconnect(self.refresh)
        except (RuntimeError, TypeError):
            pass
        self._connected_document = document
        document.contentsChanged.connect(self.refresh)
        self.matches = []
        self.base_selections = []
        self.current_index = -1
        self._update_controls()

    def focus_query(self) -> None:
        vertical_position = self.browser.verticalScrollBar().value()
        horizontal_position = self.browser.horizontalScrollBar().value()
        selected_query = re.sub(
            r"\s+", " ", self.browser.textCursor().selectedText()
        ).strip()
        if selected_query:
            self.query_input.setText(selected_query)
        self._set_query_highlight(True)
        self.query_input.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.query_input.selectAll()
        self._restore_scroll_if_changed(vertical_position, horizontal_position)

    def _restore_scroll_if_changed(
        self, vertical_position: int, horizontal_position: int
    ) -> None:
        """검색창 포커스 이동만으로 바뀐 스크롤을 재렌더 없이 복원."""
        vertical_bar = self.browser.verticalScrollBar()
        horizontal_bar = self.browser.horizontalScrollBar()
        if vertical_bar.value() != vertical_position:
            vertical_bar.setValue(min(vertical_position, vertical_bar.maximum()))
        if horizontal_bar.value() != horizontal_position:
            horizontal_bar.setValue(
                min(horizontal_position, horizontal_bar.maximum())
            )

    def _set_query_highlight(self, highlighted: bool) -> None:
        if bool(self.query_input.property("findActive")) == highlighted:
            return
        self.query_input.setProperty("findActive", highlighted)
        self.query_input.style().unpolish(self.query_input)
        self.query_input.style().polish(self.query_input)
        self.query_input.update()

    def cancel_search(self) -> None:
        """Esc: 검색어와 강조를 지우고 보던 위치 그대로 본문으로 돌아간다."""
        vertical_position = self.browser.verticalScrollBar().value()
        horizontal_position = self.browser.horizontalScrollBar().value()
        self.query_input.clear()
        self._set_query_highlight(False)
        self.browser.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._restore_scroll_if_changed(vertical_position, horizontal_position)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.query_input:
            # 탭에 걸린 Esc 단축키가 먼저 키를 채가지 않도록 가로챈다.
            if (
                event.type() == QEvent.Type.ShortcutOverride
                and event.key() == Qt.Key.Key_Escape
            ):
                event.accept()
                return True
            if (
                event.type() == QEvent.Type.KeyPress
                and event.key() == Qt.Key.Key_Escape
            ):
                self.cancel_search()
                return True
            if event.type() == QEvent.Type.FocusIn:
                self._set_query_highlight(True)
            elif event.type() == QEvent.Type.FocusOut:
                vertical_position = self.browser.verticalScrollBar().value()
                horizontal_position = self.browser.horizontalScrollBar().value()
                self._set_query_highlight(False)
                # 검색칸에서 본문으로 포커스가 넘어갈 때 QTextBrowser가
                # 저장된 검색 커서를 화면에 넣더라도, 포커스를 잃기 직전의
                # 사용자가 보고 있던 위치로 되돌린다.
                self._restore_scroll_if_changed(
                    vertical_position, horizontal_position
                )
        return super().eventFilter(watched, event)

    def refresh(self) -> None:
        if self._document_change_suspended:
            return
        query = self.query_input.text()
        self.matches = []
        self.current_index = -1
        if query:
            document = self.browser.document()
            cursor = QTextCursor(document)
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            find_flags = (
                QTextDocument.FindFlag.FindWholeWords
                if self.whole_word_checkbox.isChecked()
                else QTextDocument.FindFlag(0)
            )
            while True:
                found = document.find(query, cursor, find_flags)
                if found.isNull():
                    break
                self.matches.append(QTextCursor(found))
                cursor = QTextCursor(found)
                cursor.setPosition(found.selectionEnd())
            if self.matches:
                self.current_index = 0
        self._apply_highlights()

    def move(self, direction: int) -> None:
        if not self.matches:
            self._update_controls()
            return
        self.current_index = (self.current_index + direction) % len(self.matches)
        self._apply_highlights()

    def _apply_highlights(self, *, navigate: bool = True) -> None:
        selections = list(self.base_selections)
        for index, cursor in enumerate(self.matches):
            selection = QTextEdit.ExtraSelection()
            selection.cursor = QTextCursor(cursor)
            selection.format.setBackground(
                QColor("#ff9800" if index == self.current_index else "#ffeb3b")
            )
            selection.format.setForeground(QColor("#172033"))
            selections.append(selection)
        self.browser.setExtraSelections(selections)

        if navigate and 0 <= self.current_index < len(self.matches):
            navigation_cursor = QTextCursor(self.matches[self.current_index])
            navigation_cursor.setPosition(navigation_cursor.selectionStart())
            self.browser.setTextCursor(navigation_cursor)
            self.browser.ensureCursorVisible()
        self._update_controls()

    def set_base_selections(
        self, selections: list[QTextEdit.ExtraSelection]
    ) -> None:
        """본문 검색과 함께 유지할 화면용 기본 강조 영역을 지정."""
        self.base_selections = list(selections)
        self._apply_highlights(navigate=False)

    def _update_controls(self) -> None:
        total = len(self.matches)
        current = self.current_index + 1 if total else 0
        self.count_label.setText(f"{current}/{total}")
        self.previous_button.setEnabled(total > 0)
        self.next_button.setEnabled(total > 0)

    def begin_document_change(self) -> None:
        self._document_change_suspended = True
        self.matches = []
        self.base_selections = []
        self.current_index = -1
        self.browser.setExtraSelections([])
        self._update_controls()

    def end_document_change(self) -> None:
        self._document_change_suspended = False
        self.refresh()


class RecentSearchBar(QWidget):
    """최근 검색어를 한 줄에 최대 10개까지 표시하고 다시 입력하거나 초기화함."""

    QUERY_BUTTON_MAX_WIDTH = 104

    def __init__(
        self,
        query_input: QLineEdit,
        manager: RecentSearchManager,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.query_input = query_input
        self.manager = manager
        self.setObjectName("recentSearchBar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(5)
        label = QLabel("최근 검색어")
        label.setObjectName("recentSearchLabel")
        self.clear_button = QPushButton("초기화")
        self.clear_button.setObjectName("recentSearchClearButton")
        self.clear_button.setToolTip("저장된 최근 검색어를 모두 삭제합니다.")
        self.clear_button.clicked.connect(self.manager.clear)
        layout.addWidget(label)
        self.items_layout = QHBoxLayout()
        self.items_layout.setContentsMargins(0, 0, 0, 0)
        self.items_layout.setSpacing(3)
        layout.addLayout(self.items_layout, 1)
        layout.addWidget(self.clear_button)

        manager.changed.connect(self.refresh)
        self._query_buttons: list[tuple[QPushButton, str]] = []
        self._last_elide_widths: tuple[int, ...] = ()
        self._wrap_timer = QTimer(self)
        self._wrap_timer.setSingleShot(True)
        self._wrap_timer.timeout.connect(self._apply_query_eliding)
        self.refresh(manager.items)

    def refresh(self, items: object = None) -> None:
        values = [str(value) for value in (
            items if items is not None else self.manager.items
        )]
        if values == [query for _button, query in self._query_buttons]:
            self.clear_button.setEnabled(bool(values))
            self._schedule_query_eliding_if_needed()
            return

        while self.items_layout.count():
            layout_item = self.items_layout.takeAt(0)
            widget = layout_item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        self.clear_button.setEnabled(bool(values))
        self._query_buttons = []
        self._last_elide_widths = ()
        if not values:
            empty = QLabel("없음")
            empty.setObjectName("recentSearchEmpty")
            self.items_layout.addWidget(empty)
            self.items_layout.addStretch()
            return

        for query in values:
            query = str(query)
            button = QPushButton(" ".join(query.split()))
            button.setObjectName("recentSearchButton")
            button.setMinimumWidth(0)
            button.setMaximumWidth(self.QUERY_BUTTON_MAX_WIDTH)
            button.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
            )
            button.setToolTip(query)
            button.clicked.connect(
                lambda _checked=False, value=query: self._select(value)
            )
            self.items_layout.addWidget(button, 1)
            self._query_buttons.append((button, query))
        # 검색어가 적을 때 칩이 남은 한 줄 전체를 늘려 쓰지 않게 한다.
        # 폭이 부족하면 앞의 stretch factor에 따라 모든 칩이 함께 줄어든다.
        self.items_layout.addStretch(1)
        self._schedule_query_eliding()

    def _schedule_query_eliding(self, delay: int = 0) -> None:
        self._wrap_timer.start(max(0, delay))

    def _schedule_query_eliding_if_needed(self, delay: int = 0) -> None:
        widths = tuple(button.width() for button, _query in self._query_buttons)
        if widths != self._last_elide_widths:
            self._schedule_query_eliding(delay)
        else:
            self._wrap_timer.stop()

    def _apply_query_eliding(self) -> None:
        if not self.isVisible():
            return
        widths = tuple(button.width() for button, _query in self._query_buttons)
        if widths == self._last_elide_widths:
            return
        for button, query in self._query_buttons:
            width = button.width()
            if width < 16:
                continue
            elided = button.fontMetrics().elidedText(
                " ".join(query.split()),
                Qt.TextElideMode.ElideRight,
                max(1, width - 8),
            )
            if button.text() != elided:
                button.setText(elided)
        self._last_elide_widths = widths

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._query_buttons:
            self._schedule_query_eliding_if_needed(30)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._query_buttons:
            # 같은 폭의 화면으로 돌아온 경우 문구를 다시 설정하지 않는다.
            # 탭 전환 때 최근 검색어가 잠깐 원문으로 돌아갔다가 줄바꿈되는
            # 것처럼 보이던 깜빡임을 막는다.
            self._schedule_query_eliding_if_needed(50)

    def _select(self, query: str) -> None:
        self.query_input.setText(query)
        self.query_input.setFocus()
        # 최근 검색어를 누르면 검색창만 채우지 말고 바로 검색까지
        # 실행한다(검색 버튼과 동일하게 연결된 Enter 신호를 그대로
        # 재사용).
        self.query_input.returnPressed.emit()


class DoubleClickLabel(QLabel):
    """왼쪽 버튼 더블클릭을 신호로 제공하는 제목 라벨."""

    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.doubleClicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class MemoMarkerBar(QWidget):
    """본문 오른쪽에 메모 위치를 노란 띠지로 표시하고 클릭 이동."""

    NORMAL_WIDTH = 11
    NAV_BUTTON_HEIGHT = 10
    MARKER_HEIGHT = 6
    MARKER_GAP = 2
    EDGE_MARGIN = 2
    NAV_FONT_PIXEL_SIZE = 7
    TOOLTIP_DELAY_MS = 500

    activated = Signal(int)

    def __init__(self, browser: QTextBrowser, parent=None) -> None:
        super().__init__(parent)
        self.browser = browser
        self._memos: list[dict[str, object]] = []
        self._hovered_index = -1
        self._pressed_index = -1
        self._active_index = -1
        self._hovered_navigation = 0
        self._pressed_navigation = 0
        self.setObjectName("memoMarkerBar")
        self.setFixedWidth(self.NORMAL_WIDTH)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(
            "노란 띠지에 마우스를 올린 뒤 클릭하면 메모 위치로 이동합니다."
        )
        self.browser.document().contentsChanged.connect(self.update)
        self._connected_document = self.browser.document()
        self._tooltip_timer = QTimer(self)
        self._tooltip_timer.setSingleShot(True)
        self._tooltip_timer.timeout.connect(self._show_hover_tooltip)

    def bind_document(self, document) -> None:
        if document is self._connected_document:
            return
        try:
            self._connected_document.contentsChanged.disconnect(self.update)
        except (RuntimeError, TypeError):
            pass
        self._connected_document = document
        document.contentsChanged.connect(self.update)
        self.update()

    def set_memos(self, memos: list[dict[str, object]]) -> None:
        self._memos = [dict(memo) for memo in memos if memo.get("text")]
        self._active_index = -1
        self._hovered_index = -1
        self._pressed_index = -1
        self._hovered_navigation = 0
        self._pressed_navigation = 0
        # 메모가 처음 생길 때 띠지를 show()하면 본문 폭이 14px 줄어들어
        # 전체 문서가 다시 줄바꿈된다. 메모 유무와 관계없이 고정 폭을
        # 항상 차지하고, 표식만 그리거나 지운다.
        self.setVisible(True)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor
            if self._memos
            else Qt.CursorShape.ArrowCursor
        )
        self.update()

    def refresh_after_layout_change(self) -> None:
        """크게보기처럼 부모 레이아웃이 바뀐 뒤 띠지 표시를 다시 확정."""
        self.setVisible(True)
        self.raise_()
        self.updateGeometry()
        self.update()

    def _marker_rects(self) -> list[QRect]:
        if not self._memos:
            return []
        document_end = max(1, self.browser.document().characterCount() - 1)
        marker_height = self.MARKER_HEIGHT
        gap = self.MARKER_GAP
        top = self.NAV_BUTTON_HEIGHT + self.EDGE_MARGIN
        bottom = max(
            top,
            self.height()
            - self.NAV_BUTTON_HEIGHT
            - marker_height
            - self.EDGE_MARGIN,
        )
        span = max(1, bottom - top)
        ordered: list[tuple[int, int]] = []
        for index, memo in enumerate(self._memos):
            position = max(
                0, min(int(memo.get("start") or 0), document_end)
            )
            ordered.append(
                (top + round(position / document_end * span), index)
            )
        ordered.sort(key=lambda item: (item[0], item[1]))

        spacing = marker_height + gap
        placed: list[list[int]] = []
        previous_y = top - spacing
        for desired_y, index in ordered:
            y = max(desired_y, previous_y + spacing)
            placed.append([y, index])
            previous_y = y
        if placed and placed[-1][0] > bottom:
            placed[-1][0] = bottom
            for position in range(len(placed) - 2, -1, -1):
                placed[position][0] = min(
                    placed[position][0], placed[position + 1][0] - spacing
                )
        if placed and placed[0][0] < top:
            # 표시 수가 높이보다 많을 때도 전체 범위에 고르게 분산한다.
            step = span / max(1, len(placed) - 1)
            for position, item in enumerate(placed):
                item[0] = top + round(position * step)

        marker_width = max(6, self.width() - 4)
        rectangles = [QRect() for _memo in self._memos]
        for y, index in placed:
            rectangles[index] = QRect(2, y, marker_width, marker_height)
        return rectangles

    def _navigation_rect(self, step: int) -> QRect:
        if step < 0:
            return QRect(1, 1, self.width() - 2, self.NAV_BUTTON_HEIGHT)
        return QRect(
            1,
            self.height() - self.NAV_BUTTON_HEIGHT - 1,
            self.width() - 2,
            self.NAV_BUTTON_HEIGHT,
        )

    def _navigation_step_at(self, position: QPointF) -> int:
        point = position.toPoint()
        if self._navigation_rect(-1).contains(point):
            return -1
        if self._navigation_rect(1).contains(point):
            return 1
        return 0

    def _move_active_memo(self, step: int) -> None:
        if not self._memos or step not in (-1, 1):
            return
        ordered = sorted(
            range(len(self._memos)),
            key=lambda index: (
                int(self._memos[index].get("start") or 0),
                index,
            ),
        )
        if self._active_index in ordered:
            position = ordered.index(self._active_index)
            next_position = (position + step) % len(ordered)
        else:
            cursor_position = self.browser.textCursor().position()
            if step > 0:
                next_position = next(
                    (
                        position
                        for position, index in enumerate(ordered)
                        if int(self._memos[index].get("start") or 0)
                        >= cursor_position
                    ),
                    0,
                )
            else:
                next_position = next(
                    (
                        position
                        for position in range(len(ordered) - 1, -1, -1)
                        if int(self._memos[ordered[position]].get("start") or 0)
                        <= cursor_position
                    ),
                    len(ordered) - 1,
                )
        self._active_index = ordered[next_position]
        self._jump_to_memo(self._active_index)
        self.update()

    def _marker_rect(self, memo: dict[str, object], index: int) -> QRect:
        rectangles = self._marker_rects()
        if 0 <= index < len(rectangles):
            return rectangles[index]
        return QRect()

    def marker_global_rect(self, index: int) -> QRect:
        rectangles = self._marker_rects()
        if not (0 <= index < len(rectangles)):
            return QRect(self.mapToGlobal(QPoint(0, 0)), self.size())
        local_rect = rectangles[index]
        return QRect(self.mapToGlobal(local_rect.topLeft()), local_rect.size())

    def _marker_index_at(self, position: QPointF) -> int:
        rectangles = self._marker_rects()
        if not rectangles:
            return -1
        for index, rectangle in enumerate(rectangles):
            if rectangle.contains(position.toPoint()):
                return index
        return -1

    def _memo_tooltip(self, index: int) -> str:
        if not (0 <= index < len(self._memos)):
            return ""
        memo = self._memos[index]
        excerpt = str(memo.get("excerpt") or "").strip()
        text = str(memo.get("text") or "").strip()
        if excerpt:
            return f"선택 문구: {excerpt[:80]}\n메모: {text}"
        return f"메모: {text}"

    def _jump_to_memo(self, index: int) -> None:
        if not (0 <= index < len(self._memos)):
            return
        memo = self._memos[index]
        document_end = max(0, self.browser.document().characterCount() - 1)
        start = max(0, min(int(memo.get("start") or 0), document_end))
        end = max(start, min(int(memo.get("end") or start), document_end))
        cursor = QTextCursor(self.browser.document())
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        palette = self.browser.palette()
        for color_group in (
            QPalette.ColorGroup.Active,
            QPalette.ColorGroup.Inactive,
        ):
            palette.setColor(
                color_group,
                QPalette.ColorRole.Highlight,
                QColor("#e58f00"),
            )
            palette.setColor(
                color_group,
                QPalette.ColorRole.HighlightedText,
                QColor("#ffffff"),
            )
        self.browser.setPalette(palette)
        self.browser.setTextCursor(cursor)
        self.browser.ensureCursorVisible()
        # ensureCursorVisible()은 선택 범위가 보이기만 하면 멈추므로 메모가
        # 화면 중간이나 아래에 남을 수 있다. 선택 시작점의 현재 뷰포트
        # 좌표만큼 스크롤을 더 이동해 메모 첫 줄을 본문 최상단에 맞춘다.
        start_cursor = QTextCursor(self.browser.document())
        start_cursor.setPosition(start)
        start_y = self.browser.cursorRect(start_cursor).top()
        scroll_bar = self.browser.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.value() + start_y)
        self.browser.setToolTip(f"메모: {memo.get('text', '')}")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#fffefa"))
        painter.setPen(QColor("#f0ead6"))
        painter.drawLine(0, 0, 0, self.height())
        navigation_font = painter.font()
        navigation_font.setPixelSize(self.NAV_FONT_PIXEL_SIZE)
        painter.setFont(navigation_font)
        for step, text in ((-1, "▲"), (1, "▼")):
            rectangle = self._navigation_rect(step)
            active = step in (self._hovered_navigation, self._pressed_navigation)
            painter.setPen(
                QColor("#a47a1b")
                if self._memos
                else QColor("#c8bea4")
            )
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if active and self._memos:
                painter.setPen(QColor("#7f5b0b"))
            painter.drawText(rectangle, Qt.AlignmentFlag.AlignCenter, text)
        rectangles = self._marker_rects()
        for index, rectangle in enumerate(rectangles):
            drawn_rectangle = QRect(rectangle)
            if index == self._pressed_index:
                drawn_rectangle.adjust(1, 1, -1, -1)
                fill_color = QColor("#b96f00")
                border_color = QColor("#8f5200")
            elif index == self._active_index:
                fill_color = QColor("#e58f00")
                border_color = QColor("#a85f00")
            elif index == self._hovered_index:
                fill_color = QColor("#ffda55")
                border_color = QColor("#c88700")
            else:
                fill_color = QColor("#f1bf2f")
                border_color = QColor("#d49d13")
            painter.setPen(border_color)
            painter.setBrush(fill_color)
            painter.drawRoundedRect(drawn_rectangle, 1, 1)
        painter.end()

    def leaveEvent(self, event) -> None:
        self._hovered_index = -1
        self._pressed_index = -1
        self._hovered_navigation = 0
        self._pressed_navigation = 0
        self._tooltip_timer.stop()
        QToolTip.hideText()
        self.setToolTip(
            "노란 띠지에 마우스를 올린 뒤 클릭하면 메모 위치로 이동합니다."
        )
        self.update()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event) -> None:
        navigation = self._navigation_step_at(event.position())
        hovered_index = self._marker_index_at(event.position())
        self.setCursor(
            Qt.CursorShape.PointingHandCursor
            if self._memos and (hovered_index >= 0 or navigation)
            else Qt.CursorShape.ArrowCursor
        )
        if (
            hovered_index != self._hovered_index
            or navigation != self._hovered_navigation
        ):
            self._hovered_index = hovered_index
            self._hovered_navigation = navigation
            self._tooltip_timer.stop()
            QToolTip.hideText()
            if hovered_index >= 0:
                self._tooltip_timer.start(self.TOOLTIP_DELAY_MS)
            elif navigation:
                self.setToolTip(
                    "이전 메모로 이동" if navigation < 0 else "다음 메모로 이동"
                )
            else:
                self.setToolTip(
                    "노란 띠지에 마우스를 올린 뒤 클릭하면 메모 위치로 이동합니다."
                )
            self.update()
        super().mouseMoveEvent(event)

    def _show_hover_tooltip(self) -> None:
        if self._hovered_index < 0:
            return
        text = self._memo_tooltip(self._hovered_index)
        if text:
            QToolTip.showText(QCursor.pos(), text, self)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self._memos:
            super().mousePressEvent(event)
            return
        self._pressed_navigation = self._navigation_step_at(event.position())
        if self._pressed_navigation:
            self.update()
            event.accept()
            return
        self._pressed_index = self._marker_index_at(event.position())
        if self._pressed_index < 0:
            super().mousePressEvent(event)
            return
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self._memos:
            super().mouseReleaseEvent(event)
            return
        released_navigation = self._navigation_step_at(event.position())
        if (
            self._pressed_navigation
            and released_navigation == self._pressed_navigation
        ):
            self._move_active_memo(released_navigation)
            self._pressed_navigation = 0
            self.update()
            event.accept()
            return
        self._pressed_navigation = 0
        released_index = self._marker_index_at(event.position())
        if released_index == self._pressed_index and released_index >= 0:
            self._active_index = released_index
            self._jump_to_memo(released_index)
            self.activated.emit(released_index)
        self._pressed_index = -1
        self.update()
        event.accept()


class FlowLayout(QLayout):
    """폭이 모자라면 다음 줄로 넘기는 배치. 하단 기록 칩을 여러 줄로 놓는다."""

    def __init__(self, parent=None, margin: int = 0, spacing: int = 4) -> None:
        super().__init__(parent)
        self._items: list = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._arrange(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(
            margins.left() + margins.right(),
            margins.top() + margins.bottom(),
        )

    def _arrange(self, rect: QRect, *, test_only: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        x = area.x()
        y = area.y()
        line_height = 0
        spacing = self.spacing()
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + spacing
            if next_x - spacing > area.right() and line_height > 0:
                x = area.x()
                y = y + line_height + spacing
                next_x = x + hint.width() + spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()


class ReferenceHistoryChip(QFrame):
    """하단 기록바의 항목 하나. 전체 이름을 줄이지 않고 그대로 보여 준다."""

    activated = Signal(object)
    close_requested = Signal(object)
    drag_moved = Signal(object, QPoint)
    drag_finished = Signal(object)

    DRAG_THRESHOLD = 6

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("referenceChip")
        self.setProperty("chipSelected", False)
        self._press_position: QPoint | None = None
        self._dragging = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 0, 3, 0)
        layout.setSpacing(5)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.text_label = QLabel(text)
        self.text_label.setObjectName("referenceChipText")
        self.text_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self.close_button = QPushButton("×")
        self.close_button.setObjectName("referenceChipClose")
        self.close_button.setFixedSize(24, 24)
        self.close_button.setFlat(True)
        self.close_button.setAccessibleName(f"{text} 참조 제거")
        self.close_button.setToolTip(f"{text} 참조 제거")
        self.close_button.setCursor(Qt.CursorShape.ArrowCursor)
        self.close_button.clicked.connect(
            lambda: self.close_requested.emit(self)
        )
        layout.addWidget(self.text_label)
        layout.addWidget(self.close_button)
        self.setFixedHeight(30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_text(self, text: str) -> None:
        self.text_label.setText(text)
        self.close_button.setAccessibleName(f"{text} 참조 제거")
        self.close_button.setToolTip(f"{text} 참조 제거")
        self.updateGeometry()

    def text(self) -> str:
        return self.text_label.text()

    def press_offset(self) -> QPoint:
        """칩 안에서 마우스로 잡은 지점. 끌 때 그 위치를 유지한다."""
        if self._press_position is not None:
            return self._press_position
        return QPoint(self.width() // 2, self.height() // 2)

    def set_dragging(self, dragging: bool) -> None:
        if bool(self.property("chipDragging")) == bool(dragging):
            return
        self.setProperty("chipDragging", bool(dragging))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def set_selected(self, selected: bool) -> None:
        if bool(self.property("chipSelected")) == bool(selected):
            return
        self.setProperty("chipSelected", bool(selected))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_position = event.position().toPoint()
            self._dragging = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._press_position is None:
            super().mouseMoveEvent(event)
            return
        moved = (event.position().toPoint() - self._press_position).manhattanLength()
        if not self._dragging and moved < self.DRAG_THRESHOLD:
            return
        if not self._dragging:
            self._dragging = True
            # 끄는 도중 칩이 재배치되어도 이벤트가 끊기지 않도록 붙잡는다.
            self.grabMouse()
        self.drag_moved.emit(self, event.globalPosition().toPoint())
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._press_position is not None and event.button() == (
            Qt.MouseButton.LeftButton
        ):
            was_dragging = self._dragging
            self._press_position = None
            self._dragging = False
            if was_dragging:
                self.releaseMouse()
                self.drag_finished.emit(self)
            else:
                self.activated.emit(self)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ReferenceHistoryBar(QScrollArea):
    """조회한 조문·3단비교 기록을 한 줄로 보여 주는 하단 바.

    상단 ``열린 본문`` 탭과 같은 조작감으로 맞춰 한 줄만 쓴다. 항목이
    넘치면 줄을 늘리는 대신 휠로 좌우로 밀어 본다. 높이가 늘 같아
    항목이 늘어도 본문 크기가 흔들리지 않는다.
    """

    ROW_HEIGHT = 24
    ROW_SPACING = 4
    CHIP_HEIGHT = 30
    # 휠 한 칸(120)에 옮길 거리. 칩 하나가 대략 이 정도 폭이다.
    WHEEL_STEP = 60

    tabBarClicked = Signal(int)
    tabCloseRequested = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("referenceHistoryBar")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        # 스크롤바를 띄우면 그만큼 칩이 가려진다. 상단 탭처럼 막대 없이
        # 휠로만 옮긴다.
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        container = QWidget()
        container.setObjectName("referenceHistoryContent")
        self._row = QHBoxLayout(container)
        self._row.setContentsMargins(2, 2, 2, 2)
        self._row.setSpacing(self.ROW_SPACING)
        # 칩이 몇 개 없을 때 남는 자리를 칩이 나눠 갖지 않도록 끝을 민다.
        self._row.addStretch(1)
        self.setWidget(container)
        self._container = container
        self._chips: list[ReferenceHistoryChip] = []
        self._data: list[str] = []
        self._current_index = -1
        self._dragging_chip: ReferenceHistoryChip | None = None
        self.setFixedHeight(self.CHIP_HEIGHT + 8)
        self.setToolTip(
            "클릭하면 그 조문으로 이동하고, 끌어서 순서를 바꿀 수 있습니다. "
            "항목이 많으면 휠로 좌우로 넘깁니다."
        )

    # --- QTabBar와 같은 이름의 조작부 -------------------------------
    def count(self) -> int:
        return len(self._chips)

    def addTab(self, text: str) -> int:
        chip = ReferenceHistoryChip(text, self._container)
        chip.activated.connect(self._chip_activated)
        chip.close_requested.connect(self._chip_close_requested)
        chip.drag_moved.connect(self._chip_drag_moved)
        chip.drag_finished.connect(self._chip_drag_finished)
        self._chips.append(chip)
        self._data.append("")
        # 마지막 자리(끝을 미는 여백) 앞에 넣는다.
        self._row.insertWidget(self._row.count() - 1, chip)
        chip.show()
        self._refresh_layout()
        return len(self._chips) - 1

    def removeTab(self, index: int) -> None:
        if not 0 <= index < len(self._chips):
            return
        chip = self._chips.pop(index)
        self._data.pop(index)
        self._row.removeWidget(chip)
        chip.setParent(None)
        chip.deleteLater()
        if self._current_index >= len(self._chips):
            self._current_index = len(self._chips) - 1
        self._refresh_layout()

    def moveTab(self, source: int, target: int) -> None:
        if not (
            0 <= source < len(self._chips) and 0 <= target < len(self._chips)
        ) or source == target:
            return
        chip = self._chips.pop(source)
        data = self._data.pop(source)
        self._chips.insert(target, chip)
        self._data.insert(target, data)
        if self._current_index == source:
            self._current_index = target
        self._rebuild_row()

    def tabText(self, index: int) -> str:
        if 0 <= index < len(self._chips):
            return self._chips[index].text()
        return ""

    def setTabData(self, index: int, value: object) -> None:
        if 0 <= index < len(self._data):
            self._data[index] = str(value or "")

    def tabData(self, index: int) -> str:
        if 0 <= index < len(self._data):
            return self._data[index]
        return ""

    def setTabToolTip(self, index: int, text: str) -> None:
        if 0 <= index < len(self._chips):
            self._chips[index].setToolTip(text)

    def currentIndex(self) -> int:
        return self._current_index

    def setCurrentIndex(self, index: int) -> None:
        self._current_index = index
        for position, chip in enumerate(self._chips):
            chip.set_selected(position == index)
        # 한 줄이라 고른 칩이 화면 밖에 있을 수 있다. 끄는 중에는 칩이
        # 마우스를 따라가는 중이라 건드리지 않는다.
        if self._dragging_chip is None:
            self.ensure_visible(index)

    # --- 내부 동작 --------------------------------------------------
    def _chip_activated(self, chip: ReferenceHistoryChip) -> None:
        if chip in self._chips:
            self.tabBarClicked.emit(self._chips.index(chip))

    def _chip_close_requested(self, chip: ReferenceHistoryChip) -> None:
        if chip in self._chips:
            self.tabCloseRequested.emit(self._chips.index(chip))

    def _chip_drag_moved(
        self, chip: ReferenceHistoryChip, global_position: QPoint
    ) -> None:
        """끄는 동안 커서가 놓인 자리로 칩 순서를 바로 바꾼다."""
        if chip not in self._chips:
            return
        source = self._chips.index(chip)
        local = self._container.mapFromGlobal(global_position)
        target = source
        for position, other in enumerate(self._chips):
            if other is chip:
                continue
            geometry = other.geometry()
            if geometry.contains(local):
                target = position
                break
        else:
            # 칩 사이 빈 곳으로 끌면 같은 줄에서 가장 가까운 자리로 보낸다.
            for position, other in enumerate(self._chips):
                if other is chip:
                    continue
                geometry = other.geometry()
                if (
                    abs(geometry.center().y() - local.y()) <= self.ROW_HEIGHT
                    and local.x() < geometry.center().x()
                ):
                    target = position
                    break
        if target != source:
            self.moveTab(source, target)
        # 끄는 칩은 상단 탭처럼 마우스를 따라오게 해서 이동 중임을 보여 준다.
        self._dragging_chip = chip
        chip.set_dragging(True)
        chip.raise_()
        self._move_dragging_chip(local)

    def _move_dragging_chip(self, local_position: QPoint) -> None:
        chip = self._dragging_chip
        if chip is None:
            return
        grab = chip.press_offset()
        area = self._container.rect()
        x = max(
            0,
            min(local_position.x() - grab.x(), max(0, area.width() - chip.width())),
        )
        y = max(
            0,
            min(local_position.y() - grab.y(), max(0, area.height() - chip.height())),
        )
        chip.move(QPoint(x, y))

    def _chip_drag_finished(self, chip: ReferenceHistoryChip) -> None:
        chip.set_dragging(False)
        self._dragging_chip = None
        self._rebuild_row()

    def _rebuild_row(self) -> None:
        while self._row.count():
            self._row.takeAt(0)
        for chip in self._chips:
            self._row.addWidget(chip)
        self._row.addStretch(1)
        self._row.activate()
        self._refresh_layout()
        if self._dragging_chip is not None:
            self._dragging_chip.raise_()

    def _refresh_layout(self) -> None:
        self.setCurrentIndex(self._current_index)

    def wheelEvent(self, event) -> None:
        """세로 휠도 좌우 이동으로 쓴다. 한 줄이라 위아래로 갈 곳이 없다."""
        angle = event.angleDelta()
        delta = angle.y() or angle.x()
        if delta:
            scroll_bar = self.horizontalScrollBar()
            scroll_bar.setValue(
                scroll_bar.value() - round(delta / 120 * self.WHEEL_STEP)
            )
            event.accept()
            return
        super().wheelEvent(event)

    def ensure_visible(self, index: int) -> None:
        """고른 칩이 화면 밖에 있으면 보이는 자리까지 끌어온다."""
        if 0 <= index < len(self._chips):
            chip = self._chips[index]
            self.ensureWidgetVisible(chip, self.ROW_SPACING, 0)


class PopupDragBar(QWidget):
    """조문 팝업을 마우스로 이동하는 제목 영역 (고정 여부와 무관하게 끌 수 있음)."""

    def __init__(self, popup: QWidget) -> None:
        super().__init__(popup)
        self.popup = popup
        self.drag_offset = None
        self.setObjectName("referencePopupDragBar")
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setToolTip("이 제목줄을 끌면 팝업을 옮길 수 있습니다.")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_offset = (
                event.globalPosition().toPoint()
                - self.popup.frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (
            self.drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.popup.move(
                event.globalPosition().toPoint() - self.drag_offset
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self.drag_offset = None
        super().mouseReleaseEvent(event)


class PopupResizeHandle(QWidget):
    """고정된 프레임리스 팝업의 한 변 또는 모서리 크기 조절 영역."""

    def __init__(
        self,
        popup: QWidget,
        edges,
        cursor: Qt.CursorShape,
    ) -> None:
        super().__init__(popup)
        self.popup = popup
        self.edges = edges
        self._press_global = None
        self._press_geometry = None
        self.setCursor(cursor)
        self.setToolTip("끌어서 팝업 크기를 조절합니다.")
        self.setStyleSheet("background: transparent; border: none;")
        self.hide()

    def mousePressEvent(self, event) -> None:
        pin_button = getattr(self.popup, "pin_button", None)
        if (
            event.button() != Qt.MouseButton.LeftButton
            or pin_button is None
            or not pin_button.isChecked()
        ):
            super().mousePressEvent(event)
            return

        window_handle = self.popup.windowHandle()
        if window_handle is not None and window_handle.startSystemResize(
            self.edges
        ):
            event.accept()
            return

        # 일부 플랫폼이 시스템 크기 조절을 지원하지 않을 때의 대체 동작.
        self._press_global = event.globalPosition().toPoint()
        self._press_geometry = self.popup.geometry()
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if (
            self._press_global is None
            or self._press_geometry is None
            or not event.buttons() & Qt.MouseButton.LeftButton
        ):
            super().mouseMoveEvent(event)
            return

        delta = event.globalPosition().toPoint() - self._press_global
        geometry = self._press_geometry.adjusted(0, 0, 0, 0)
        minimum_width = self.popup.minimumWidth()
        minimum_height = self.popup.minimumHeight()
        if self.edges & Qt.Edge.LeftEdge:
            geometry.setLeft(
                min(
                    self._press_geometry.left() + delta.x(),
                    self._press_geometry.right() - minimum_width + 1,
                )
            )
        if self.edges & Qt.Edge.RightEdge:
            geometry.setRight(
                max(
                    self._press_geometry.right() + delta.x(),
                    self._press_geometry.left() + minimum_width - 1,
                )
            )
        if self.edges & Qt.Edge.TopEdge:
            geometry.setTop(
                min(
                    self._press_geometry.top() + delta.y(),
                    self._press_geometry.bottom() - minimum_height + 1,
                )
            )
        if self.edges & Qt.Edge.BottomEdge:
            geometry.setBottom(
                max(
                    self._press_geometry.bottom() + delta.y(),
                    self._press_geometry.top() + minimum_height - 1,
                )
            )
        self.popup.setGeometry(geometry)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._press_global = None
        self._press_geometry = None
        super().mouseReleaseEvent(event)


class CornerCloseTabBar(QTabBar):
    """닫기 × 를 탭 오른쪽 위 모서리에 겹쳐 그리는 탭 줄.

    setTabButton으로 단추를 달면 그 단추가 탭 안에서 자리를 차지해 제목이
    한쪽으로 밀린다. 여기서는 자리를 내주지 않고 모서리에 직접 그린다.
    제목은 탭 한가운데 그대로 남는다.

    어느 탭에 × 를 그릴지는 화면 쪽이 정한다. closable_check에 탭 번호를
    받아 참ㆍ거짓을 돌려주는 함수를 걸어 두면 된다. 걸지 않으면 모든 탭에
    그린다.
    """

    # 글리프 반팔 길이와 모서리에서 띄우는 거리, 그리고 누르기 판정 크기.
    ARM = 3.0
    # 탭 테두리에 닿을 듯 붙으면 겹쳐 보인다. 한 칸 안쪽으로 들인다.
    INSET = 10
    HIT = 15

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.closable_check = None
        self._hover_index = -1
        self.setMouseTracking(True)

    # --- 자리 계산 -------------------------------------------------
    def _is_closable(self, index: int) -> bool:
        if not 0 <= index < self.count():
            return False
        if self.closable_check is None:
            return True
        try:
            return bool(self.closable_check(index))
        except Exception:  # noqa: BLE001 - 그리기가 화면을 막으면 안 된다.
            return False

    def _close_center(self, index: int) -> QPoint:
        rect = self.tabRect(index)
        return QPoint(rect.right() - self.INSET, rect.top() + self.INSET)

    def close_spot_at(self, point: QPoint) -> int:
        """그 자리가 어느 탭의 닫기 × 인지. 아니면 -1."""
        index = self.tabAt(point)
        if index < 0 or not self._is_closable(index):
            return -1
        center = self._close_center(index)
        half = self.HIT // 2
        inside = (
            abs(point.x() - center.x()) <= half
            and abs(point.y() - center.y()) <= half
        )
        return index if inside else -1

    # --- 그리기 ----------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 규약)
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for index in range(self.count()):
            if not self._is_closable(index):
                continue
            center = self._close_center(index)
            pen = QPen(
                QColor("#ff9d92" if index == self._hover_index else "#a3b6c8")
            )
            pen.setWidthF(1.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            arm = self.ARM
            painter.drawLine(
                QPointF(center.x() - arm, center.y() - arm),
                QPointF(center.x() + arm, center.y() + arm),
            )
            painter.drawLine(
                QPointF(center.x() + arm, center.y() - arm),
                QPointF(center.x() - arm, center.y() + arm),
            )

    # --- 조작 ------------------------------------------------------
    def _set_hover(self, index: int) -> None:
        if index != self._hover_index:
            self._hover_index = index
            self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt 규약)
        self._set_hover(self.close_spot_at(event.position().toPoint()))
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt 규약)
        self._set_hover(-1)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt 규약)
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.close_spot_at(event.position().toPoint())
            if index >= 0:
                # 여기서 멈춘다. 그냥 두면 탭이 선택되며 그 본문이 열린다.
                event.accept()
                self.tabCloseRequested.emit(index)
                return
        super().mousePressEvent(event)


class TabClickActivator(QObject):
    """탭을 눌렀다 뗄 때만 열리게 한다.

    QTabBar는 누르는 순간 현재 탭을 바꾼다. 그래서 순서를 바꾸려고 탭을
    끌기 시작하면 손을 떼기도 전에 그 본문이 열려 버렸다. 여기서는 누른
    자리와 뗀 자리가 같은 탭이고 그동안 거의 움직이지 않았을 때만
    activated를 보낸다. 끌기로 끝났으면 settled를 보내, 화면 쪽이
    강조 표시를 원래대로 돌릴 수 있게 한다.
    """

    activated = Signal(int)
    settled = Signal()

    def __init__(self, tab_bar: QTabBar) -> None:
        super().__init__(tab_bar)
        self._tab_bar = tab_bar
        self._pressed_index = -1
        self._pressed_at = QPoint()
        tab_bar.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 (Qt 규약)
        if watched is not self._tab_bar:
            return super().eventFilter(watched, event)
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress:
            spot = event.position().toPoint()
            closing = getattr(self._tab_bar, "close_spot_at", None)
            if event.button() != Qt.MouseButton.LeftButton:
                self._pressed_index = -1
            elif closing is not None and closing(spot) >= 0:
                # 모서리의 닫기 × 를 누른 것이다. 열기로 치면 닫으면서
                # 그 본문이 한 번 열렸다가 사라진다.
                self._pressed_index = -1
            else:
                self._pressed_index = self._tab_bar.tabAt(spot)
                self._pressed_at = spot
        elif kind == QEvent.Type.MouseButtonRelease:
            index = self._pressed_index
            self._pressed_index = -1
            if index >= 0 and event.button() == Qt.MouseButton.LeftButton:
                spot = event.position().toPoint()
                moved = (spot - self._pressed_at).manhattanLength()
                if (
                    self._tab_bar.tabAt(spot) == index
                    and moved <= QApplication.startDragDistance()
                ):
                    self.activated.emit(index)
                else:
                    self.settled.emit()
        return super().eventFilter(watched, event)


class TabStripScrollArea(QScrollArea):
    """탭이 가로로 넘칠 때 휠과 가운데 버튼 끌기로 밀어 보는 띠.

    QTabBar 자체 스크롤 버튼은 한 번에 한 칸씩만 움직여 탭이 많아지면
    원하는 탭까지 여러 번 눌러야 한다. 탭 줄을 스크롤 영역에 넣고
    휠을 가로 이동에, 가운데 버튼 끌기를 손으로 미는 동작에 연결한다.
    """

    def __init__(self, content: QWidget, parent=None) -> None:
        super().__init__(parent)
        self._content = content
        self.setWidget(content)
        self.setWidgetResizable(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        # 막대를 감춰 탭 줄 높이를 그대로 두고, 휠ㆍ끌기로만 움직인다.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.viewport().setAutoFillBackground(False)
        content.setAutoFillBackground(False)
        # 탭 줄이 마우스 이벤트를 먼저 받으므로 거기에도 걸어 둔다.
        content.installEventFilter(self)
        self._pan_start_x: int | None = None
        self._pan_start_value = 0
        self.refresh()

    def refresh(self) -> None:
        """탭이 늘거나 줄면 안쪽 폭과 띠 높이를 다시 맞춘다."""
        hint = self._content.sizeHint()
        height = max(hint.height(), self._content.minimumSizeHint().height())
        width = max(hint.width(), self.viewport().width())
        self._content.resize(width, height)
        # setFixedHeight는 다시 resizeEvent를 일으킨다. 높이가 실제로
        # 달라질 때만 걸어야 크기 재계산이 되풀이되지 않는다.
        if self.height() != height:
            self.setFixedHeight(height)
        # 막대를 감춰 두면 Qt가 범위를 갱신하지 않는 경우가 있어 직접
        # 잡아 준다. 값이 같으면 Qt가 계산한 것을 그대로 두는 셈이다.
        visible = self.viewport().width()
        bar = self.horizontalScrollBar()
        bar.setRange(0, max(0, width - visible))
        bar.setPageStep(visible)
        bar.setSingleStep(40)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.refresh()

    def _scroll_by(self, steps: int) -> None:
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - steps)

    def eventFilter(self, watched, event) -> bool:
        if watched is self._content:
            if event.type() == QEvent.Type.Wheel:
                self.wheelEvent(event)
                return event.isAccepted()
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.MiddleButton:
                    self._begin_pan(event)
                    return True
            elif event.type() == QEvent.Type.MouseMove:
                if self._pan_start_x is not None:
                    self._continue_pan(event)
                    return True
            elif event.type() == QEvent.Type.MouseButtonRelease:
                if self._pan_start_x is not None:
                    self._end_pan()
                    return True
        return super().eventFilter(watched, event)

    def _begin_pan(self, event) -> None:
        self._pan_start_x = int(event.globalPosition().x())
        self._pan_start_value = self.horizontalScrollBar().value()
        self._content.setCursor(Qt.CursorShape.SizeHorCursor)

    def _continue_pan(self, event) -> None:
        if self._pan_start_x is None:
            return
        moved = int(event.globalPosition().x()) - self._pan_start_x
        self.horizontalScrollBar().setValue(self._pan_start_value - moved)

    def _end_pan(self) -> None:
        self._pan_start_x = None
        self._content.unsetCursor()

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y() or event.angleDelta().x()
        if delta:
            self._scroll_by(delta)
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._begin_pan(event)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._pan_start_x is not None:
            self._continue_pan(event)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._pan_start_x is not None:
            self._end_pan()
            return
        super().mouseReleaseEvent(event)

    def ensure_visible(self, rect: QRect) -> None:
        """선택한 탭이 띠 밖에 있으면 보이는 자리까지 민다."""
        bar = self.horizontalScrollBar()
        left = rect.left() - bar.value()
        right = rect.right() - bar.value()
        if left < 0:
            bar.setValue(bar.value() + left)
        elif right > self.viewport().width():
            bar.setValue(bar.value() + right - self.viewport().width())
