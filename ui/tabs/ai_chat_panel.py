"""본문 옆에 붙는 AI 대화 패널.

크게 보기로 법령을 읽다가 바로 옆에서 되물을 수 있게, 본문을 가리지 않는
좁은 폭으로 붙인다. 검토는 한 번 묻고 끝나지 않으므로 주고받은 말이
쌓이는 대화 형태로 둔다.
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
import threading
import time
from html import escape, unescape
from urllib.parse import quote

from PySide6.QtCore import (
    QEvent,
    QObject,
    QPointF,
    QRectF,
    QSettings,
    QSize,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QInputDialog,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyleOptionButton,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from llm import (
    PROVIDERS,
    ChatSession,
    ClaudeCodeProvider,
    CodexAppServerProvider,
    GeminiProvider,
    LlmError,
    LlmProvider,
    Progress,
    extract_cited_articles,
)
from ui.assets import GEMINI_KEY_MANUAL_PATH
from llm.document_labels import lookup_cached_document_label
from llm.inquiries import is_inquiry_target, split_doc_reference
from llm.ai_cli_setup import (
    CLAUDE_CLI,
    CODEX_CLI,
    AiCliCancelled,
    AiCliSetupError,
    AiCliSpec,
    cli_login_status,
    cli_version,
    ensure_cli,
    launch_cli_login,
)
from llm.verify_citations import (
    collect_citations,
    display_citation_label,
    verification_html,
)
from models.law import RESOURCE_CATEGORIES
from utils.annex_notation import annex_related_law_name
from utils.constants import FONT_FAMILY
from utils.formatting import law_reference_html_text
from utils.parsing import normalize_article_jo
from utils.patterns import KOREAN_ITEM_MARKERS, LAW_UNIT_REFERENCE_PATTERN


class ChatInput(QPlainTextEdit):
    """Enter로 보내고 Shift+Enter로 줄을 바꾸는 입력칸.

    대화창에서는 한 줄짜리 질문이 대부분이라 Enter가 보내기여야 손이
    멈추지 않는다. 여러 줄이 필요할 때만 Shift를 짚는다.
    """

    sendRequested = Signal()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.sendRequested.emit()
            return
        super().keyPressEvent(event)


class ShimmerLabel(QLabel):
    """글자 위로 밝은 띠가 흘러 지나가는 라벨.

    법령을 여러 번 찾는 질문은 답이 나오기까지 몇 분이 걸린다. 글자가
    가만히 있으면 멎은 것인지 아직 도는 것인지 알 수 없어서, 빛이 계속
    흐르는 것으로 "살아 있다"는 것을 보인다.

    QSS로는 글자에 그라데이션을 넣을 수 없어 직접 그린다.
    """

    # 40ms(초당 25번)면 흐름이 매끄러우면서도 그리는 비용이 눈에 띄지 않는다.
    _INTERVAL_MS = 40
    # 띠 하나가 왼쪽 끝에서 오른쪽 끝까지 지나가는 데 걸리는 시간.
    _CYCLE_MS = 1800
    # 밝은 띠의 폭. 글자 전체 너비에 대한 비율이다.
    _BAND = 0.22

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)
        self._base_color = QColor("#8a97a6")
        self._highlight_color = QColor("#1768aa")

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start(self._INTERVAL_MS)

    def stop(self) -> None:
        """빛을 멈추고 잔잔한 회색으로 되돌린다."""
        self._timer.stop()
        self._phase = 0.0
        self.update()

    def _advance(self) -> None:
        self._phase = (self._phase + self._INTERVAL_MS / self._CYCLE_MS) % 1.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 규약)
        text = self.text()
        if not text:
            return
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(self._pen())
        painter.drawText(
            self.rect(),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            text,
        )

    def _pen(self) -> QPen:
        if not self._timer.isActive():
            return QPen(self._base_color)
        gradient = QLinearGradient(0.0, 0.0, float(max(1, self.width())), 0.0)
        # 띠가 화면 밖에서 들어와 밖으로 빠져나가게 앞뒤로 여유를 준다.
        center = self._phase * (1.0 + 2 * self._BAND) - self._BAND
        gradient.setColorAt(0.0, self._base_color)
        gradient.setColorAt(1.0, self._base_color)
        for offset, color in (
            (center - self._BAND, self._base_color),
            (center, self._highlight_color),
            (center + self._BAND, self._base_color),
        ):
            if 0.0 <= offset <= 1.0:
                gradient.setColorAt(offset, color)
        return QPen(QBrush(gradient), 1)


class ChatWorker(QObject):
    """한 마디를 보내고 답을 받아 오는 일을 별도 스레드에서 한다.

    신호에는 어느 제공자의 답인지를 함께 싣는다. 예전에는 화면 쪽에서
    functools.partial로 이름을 묶어 연결했는데, partial은 받는 QObject가
    없어서 PySide6가 직접 연결로 잇는다. 그러면 말풍선을 만들고 타이머를
    멈추는 일이 전부 이 작업 스레드에서 돌아 프로그램이 죽었다
    ("Cannot create children for a parent that is in a different thread",
    "Thread tried to wait on itself"). 이름을 인자로 넘기면 화면 쪽
    메서드에 그대로 이을 수 있고, 그러면 Qt가 메인 스레드로 넘겨 준다.
    """

    # 앞의 str은 모두 제공자 이름이다.
    chunk = Signal(str, str)
    # 답변 본문이 아니라 "지금 무엇을 하는 중인지". 도구를 여러 번 오가는
    # 질문은 답이 나오기까지 몇 분이 걸려서, 그동안 진행을 보여 줘야 한다.
    progress = Signal(str, str, str)
    failed = Signal(str, str)
    finished = Signal(str)

    def __init__(
        self, session: ChatSession, message: str, provider_name: str = ""
    ) -> None:
        super().__init__()
        self._session = session
        self._message = message
        self._name = provider_name
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True
        self._session.cancel()

    def run(self) -> None:
        try:
            for piece in self._session.send(self._message):
                if self._stopped:
                    break
                if isinstance(piece, Progress):
                    self.progress.emit(self._name, piece.text, piece.kind)
                else:
                    self.chunk.emit(self._name, piece)
        except LlmError as error:
            if not self._stopped:
                self.failed.emit(self._name, str(error))
        except Exception as error:
            if not self._stopped:
                self.failed.emit(self._name, f"예상하지 못한 오류: {error}")
        finally:
            self.finished.emit(self._name)


CLI_SPECS = {
    ClaudeCodeProvider: CLAUDE_CLI,
    CodexAppServerProvider: CODEX_CLI,
}

# 제공자 탭 오른쪽에 놓이는 단추·배지의 공통 높이. 전역 QPushButton은
# 38px라서 그대로 두면 CLI 탭에서만 헤더가 높아져 화면이 밀린다.
_HEADER_CONTROL_HEIGHT = 29
# 본문 옆 패널의 AI 선택 목록. 글자 폭 + 화살표·패딩만 남긴다.
_PROVIDER_COMBO_WIDTH_MARGIN = 32
# API 키 상태 단추. 가장 긴 문구에 맞추되 좌우 빈칸은 최소만 둔다.
_API_SETTINGS_BUTTON_WIDTH_MARGIN = 8

# 질문과 답에 같이 쓰는 글자 크기. 9pt는 법령 본문을 오래 읽기에 작다.
_CHAT_FONT_POINT = 10.5

# AI Studio의 사용량·한도 화면. project 값은 계정마다 다르므로, 다른
# 프로젝트를 쓰게 되면 이 주소만 바꾸면 된다(빼도 최근 프로젝트로 열린다).
GEMINI_USAGE_URL = (
    "https://aistudio.google.com/rate-limit"
    "?timeRange=last-28-days&project=gen-lang-client-0575025548"
)

# 화면에 보일 제공자 이름. 제공자 클래스의 name은 저장 키(ai/provider,
# ai/chat_history/…)로 쓰이므로 건드리지 않고, 보이는 글자만 여기서 정한다.
PROVIDER_TAB_LABELS = {
    GeminiProvider: "Gemini",
    ClaudeCodeProvider: "Claude",
    CodexAppServerProvider: "Codex",
}
_PROVIDER_LABEL_BY_NAME = {
    provider_class.name: label
    for provider_class, label in PROVIDER_TAB_LABELS.items()
}
_PROVIDER_BY_NAME = {provider_class.name: provider_class for provider_class in PROVIDERS}


def _provider_label(name: str) -> str:
    return _PROVIDER_LABEL_BY_NAME.get(name, name)


def _label_width(widget, labels, margin: int = 32) -> int:
    """글자가 바뀌어도 흔들리지 않도록 가장 긴 문구에 맞춘 너비를 준다.

    margin은 글자 양옆에 둘 여백이다. 단추는 안쪽 여백이 넓어 기본값을
    쓰고, 배지처럼 좁은 것은 그만큼 줄여 부른다.
    """
    metrics = widget.fontMetrics()
    return max(metrics.horizontalAdvance(label) for label in labels) + margin


class ElidedLabel(QLabel):
    """폭이 모자라면 뒤를 "…"로 줄여 쓰는 라벨.

    채팅 목록은 좁고 제목은 질문 첫 줄이라 길다. QLabel은 넘치는 글자를
    그냥 잘라 버려서 무슨 대화인지도, 잘렸다는 사실도 안 보인다.
    """

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self._full_text = text
        self.setText(text)

    def setFullText(self, text: str) -> None:  # noqa: N802 (Qt 규약)
        self._full_text = text
        self._apply_elide()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 규약)
        super().resizeEvent(event)
        self._apply_elide()

    def _apply_elide(self) -> None:
        width = max(0, self.width())
        if not width:
            return
        super().setText(
            self.fontMetrics().elidedText(
                self._full_text, Qt.TextElideMode.ElideRight, width
            )
        )


class HistoryMenuButton(QPushButton):
    """글꼴 상태와 무관하게 처음부터 보이는 작은 점 세 개 단추."""

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 규약)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = ""
        painter = QPainter(self)
        self.style().drawControl(
            QStyle.ControlElement.CE_PushButton, option, painter, self
        )
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = QColor("#14496f" if self.underMouse() else "#8c96a3")
        if not self.isEnabled():
            color.setAlpha(110)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        center_x = self.rect().center().x()
        center_y = self.rect().center().y()
        radius = 1.15
        spacing = 4.0
        for offset in (-spacing, 0.0, spacing):
            painter.drawEllipse(
                QPointF(center_x + offset, center_y), radius, radius
            )


class ChatListButton(QPushButton):
    """채팅 목록을 여는 말풍선 단추.

    이모지 글리프(💬)는 24px 안에 들어가면 자간과 획이 뭉개져 계단처럼
    보인다. 환경마다 어떤 글꼴이 잡히는지도 달라 모양이 제각각이었다.
    그래서 정원 하나와 삐죽 나온 꼬리만 직접 그린다. 어느 배율에서도
    매끈하고, 작은 크기에서도 안쪽 점이 뭉개지지 않는다.
    """

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 규약)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = ""
        painter = QPainter(self)
        self.style().drawControl(
            QStyle.ControlElement.CE_PushButton, option, painter, self
        )
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # 클릭 영역은 넉넉하게 유지하되, 안쪽 표식은 그 절반 정도만 쓴다.
        side = min(self.width(), self.height()) * 0.51
        if side <= 0:
            return
        left = (self.width() - side) / 2.0 + 0.5
        top = (self.height() - side) / 2.0 - 0.5
        body = QRectF(left, top, side, side)

        active = bool(self.property("historyVisible"))
        edge = QColor("#8fb4ce" if active or self.underMouse() else "#cfdcea")
        fill = QColor("#f7fafd")

        # 왼쪽 아래 45도 방향의 짧은 꼬리. 끝을 멀리 빼지 않아
        # 지나치게 뾰족한 느낌을 줄인다.
        tail = QPainterPath()
        tail.moveTo(body.left() + side * 0.22, body.bottom() - side * 0.18)
        tail.lineTo(body.left() - side * 0.10, body.bottom() + side * 0.10)
        tail.lineTo(body.left() + side * 0.36, body.bottom() - side * 0.02)
        tail.closeSubpath()

        shape = QPainterPath()
        shape.addEllipse(body)
        shape = shape.united(tail)
        painter.setPen(QPen(edge, max(0.7, side * 0.07)))
        painter.setBrush(fill)
        painter.drawPath(shape)


class ModelMenuButton(QPushButton):
    """모델명 뒤의 V를 글자 기준선이 아니라 버튼 정중앙에 그린다."""

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 규약)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        label = option.text
        option.text = ""

        painter = QPainter(self)
        self.style().drawControl(
            QStyle.ControlElement.CE_PushButton, option, painter, self
        )
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        metrics = self.fontMetrics()
        available = max(0, self.width() - 26)
        shown = metrics.elidedText(
            label, Qt.TextElideMode.ElideRight, available
        )
        color = QColor("#173b63" if self.isEnabled() else "#9aa5b2")
        painter.setPen(color)
        painter.setFont(self.font())
        painter.drawText(
            QRectF(7, 0, available, self.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            shown,
        )

        text_width = metrics.horizontalAdvance(shown)
        center_x = min(self.width() - 8.0, 7.0 + text_width + 8.0)
        center_y = self.rect().center().y()
        painter.setPen(QPen(color, 1.1))
        painter.drawLine(
            QPointF(center_x - 3.0, center_y - 1.5),
            QPointF(center_x, center_y + 1.5),
        )
        painter.drawLine(
            QPointF(center_x, center_y + 1.5),
            QPointF(center_x + 3.0, center_y - 1.5),
        )


class PlusButton(QPushButton):
    """새 채팅(+) 단추. 글리프 대신 선 두 개를 한가운데에 직접 긋는다.

    글꼴의 "+"는 수학 기호라 글자 기준선 위쪽 수학축에 놓인다. 그래서
    단추 안에서 세로로 조금 떠 보이고, 글꼴에 따라 좌우도 어긋난다.
    여기서는 단추 네모의 정중앙을 잡아 가로·세로 선을 긋는다.
    """

    _ARM_RATIO = 0.30
    _COLOR = "#1768aa"
    _DISABLED_COLOR = "#9aa8b5"

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 규약)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        # 바탕과 테두리는 QSS 그대로 쓰고 글자만 우리가 대신 그린다.
        option.text = ""
        painter = QPainter(self)
        self.style().drawControl(
            QStyle.ControlElement.CE_PushButton, option, painter, self
        )
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())
        center = rect.center()
        arm = min(rect.width(), rect.height()) * self._ARM_RATIO
        pen = QPen(
            QColor(self._COLOR if self.isEnabled() else self._DISABLED_COLOR)
        )
        pen.setWidthF(1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(
            QPointF(center.x() - arm, center.y()),
            QPointF(center.x() + arm, center.y()),
        )
        painter.drawLine(
            QPointF(center.x(), center.y() - arm),
            QPointF(center.x(), center.y() + arm),
        )


class SendButton(QPushButton):
    """보내기(↑)·중지(■) 단추. 글리프 대신 도형을 직접 그린다.

    글꼴의 "↑"는 막대가 길고 글자 기준선에 맞춰 그려져 단추 안에서
    아래로 처져 보인다. 여기서는 화살촉과 막대 비율을 정해 놓고 단추
    한가운데에 그린다. 글자(text)는 그대로 두어 상태를 읽는 쪽이
    바뀌지 않게 하고, 그리기만 우리가 맡는다.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._stopping = False

    def set_stopping(self, stopping: bool) -> None:
        if stopping != self._stopping:
            self._stopping = stopping
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 규약)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        # 배경과 테두리는 QSS 그대로 쓰고 글자만 우리가 대신 그린다.
        option.text = ""
        painter = QPainter(self)
        self.style().drawControl(
            QStyle.ControlElement.CE_PushButton, option, painter, self
        )
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()
        size = float(min(rect.width(), rect.height()))
        center_x = rect.x() + rect.width() / 2.0
        center_y = rect.y() + rect.height() / 2.0
        color = QColor("#ffffff")
        if self._stopping:
            side = size * 0.32
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(
                QRectF(
                    center_x - side / 2.0, center_y - side / 2.0, side, side
                ),
                2.0,
                2.0,
            )
            return
        # 화살표 전체 높이의 40%가 화살촉이다. 막대만 길면 가늘어 보인다.
        height = size * 0.34
        head_height = height * 0.42
        head_width = size * 0.24
        top = center_y - height / 2.0
        bottom = center_y + height / 2.0
        pen = QPen(color)
        pen.setWidthF(max(1.8, size * 0.07))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(QPointF(center_x, bottom), QPointF(center_x, top))
        painter.drawLine(
            QPointF(center_x - head_width / 2.0, top + head_height),
            QPointF(center_x, top),
        )
        painter.drawLine(
            QPointF(center_x + head_width / 2.0, top + head_height),
            QPointF(center_x, top),
        )


class AiConnectionWorker(QObject):
    """선택한 AI CLI 확인과 npm 설치를 화면 밖 스레드에서 처리한다."""

    progress = Signal(str)
    succeeded = Signal(str, str, bool, object, str)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, spec: AiCliSpec) -> None:
        super().__init__()
        self._spec = spec
        self._cancelled = threading.Event()

    def stop(self) -> None:
        self._cancelled.set()

    def run(self) -> None:
        try:
            version, installed = ensure_cli(
                self._spec,
                self.progress.emit,
                self._cancelled.is_set,
            )
            self.progress.emit(f"{self._spec.label} 로그인 여부를 확인하는 중…")
            logged_in, login_detail = cli_login_status(
                self._spec, self._cancelled.is_set
            )
            if self._cancelled.is_set():
                return
            if logged_in is False:
                self.progress.emit(
                    f"{self._spec.label} 로그인 브라우저를 여는 중…"
                )
                launch_cli_login(self._spec)
                login_detail = (
                    "로그인 브라우저를 열었습니다. 인증을 마친 뒤 "
                    "[확인]을 다시 눌러 주세요."
                )
            self.succeeded.emit(
                self._spec.label,
                version,
                installed,
                logged_in,
                login_detail,
            )
        except AiCliCancelled:
            pass
        except AiCliSetupError as error:
            self.failed.emit(str(error))
        except Exception as error:  # noqa: BLE001 - 작업 스레드 오류를 화면에 전달
            self.failed.emit(f"AI 연결 준비 중 예상하지 못한 오류: {error}")
        finally:
            self.finished.emit()


class AiCliCheckWorker(QObject):
    """켤 때 CLI 상태를 조용히 확인한다. 없는 것을 깔지는 않는다.

    설치까지 하는 ensure_cli를 여기서 부르면 켜자마자 시키지도 않은 npm
    설치가 몇 분씩 돌 수 있다. 그래서 이 확인은 "이미 깔려 있는가,
    로그인돼 있는가"만 본다. 없을 때 깔아 주는 것은 [확인] 단추의 몫이다.
    """

    # 라벨, 버전(없으면 빈 글자), 로그인 여부(True/False/None), 설명
    checked = Signal(str, str, object, str)
    finished = Signal()

    def __init__(self, specs: tuple[AiCliSpec, ...]) -> None:
        super().__init__()
        self._specs = specs
        self._cancelled = threading.Event()

    def stop(self) -> None:
        self._cancelled.set()

    def run(self) -> None:
        try:
            for spec in self._specs:
                if self._cancelled.is_set():
                    break
                version = cli_version(spec, self._cancelled.is_set)
                if version is None:
                    self.checked.emit(spec.label, "", False, "")
                    continue
                logged_in, detail = cli_login_status(
                    spec, self._cancelled.is_set
                )
                self.checked.emit(spec.label, version, logged_in, detail)
        except AiCliCancelled:
            pass
        except Exception as error:  # noqa: BLE001 - 확인 실패로 화면이 죽으면 안 된다
            self.checked.emit("", "", None, str(error))
        finally:
            self.finished.emit()


class CliStatusCoordinator(QObject):
    """앱 안의 모든 AI 패널이 CLI 상태 확인 한 번을 함께 사용한다."""

    checked = Signal(str, str, object, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._results: list[tuple[str, str, object, str]] = []
        self._thread: QThread | None = None
        self._worker: AiCliCheckWorker | None = None

    def request(self) -> None:
        if self._results:
            for result in self._results:
                QTimer.singleShot(
                    0,
                    lambda values=result: self.checked.emit(*values),
                )
            return
        if self._thread is not None:
            return

        worker = AiCliCheckWorker(tuple(CLI_SPECS.values()))
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.checked.connect(self._remember_result)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._finished)
        self._worker = worker
        self._thread = thread
        thread.start()

    def _remember_result(
        self, label: str, version: str, logged_in: object, detail: str
    ) -> None:
        result = (label, version, logged_in, detail)
        self._results.append(result)
        self.checked.emit(*result)

    def _finished(self) -> None:
        self._worker = None
        self._thread = None

    def shutdown(self) -> None:
        worker = self._worker
        thread = self._thread
        if worker is not None:
            worker.stop()
        if thread is not None:
            thread.quit()
            thread.wait(5000)
        self._worker = None
        self._thread = None


class ModelCatalogWorker(QObject):
    """API 키 검증과 모델 목록 조회를 GUI 밖에서 수행한다."""

    succeeded = Signal(str, object)
    failed = Signal(str, str)
    finished = Signal()

    def __init__(self, request_key: str, provider_class, api_key: str) -> None:
        super().__init__()
        self._request_key = request_key
        self._provider_class = provider_class
        self._api_key = api_key

    def run(self) -> None:
        try:
            provider = self._provider_class(self._api_key)
            models = provider.fetch_validated_models()
            self.succeeded.emit(self._request_key, tuple(models))
        except LlmError as error:
            self.failed.emit(self._request_key, str(error))
        except Exception as error:  # noqa: BLE001 - 네트워크 작업 오류를 화면에 전달
            self.failed.emit(
                self._request_key,
                f"모델 목록을 확인하지 못했습니다: {error}",
            )
        finally:
            self._api_key = ""
            self.finished.emit()


class ModelCatalogCoordinator(QObject):
    """같은 제공자·API 키의 모델 조회를 여러 패널이 한 번만 공유한다."""

    resolved = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cache: dict[str, tuple] = {}
        self._threads: dict[str, QThread] = {}
        self._workers: dict[str, ModelCatalogWorker] = {}

    @staticmethod
    def request_key(provider_class, api_key: str) -> str:
        digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
        return f"{provider_class.name}:{digest}"

    def request(self, provider_class, api_key: str) -> str:
        request_key = self.request_key(provider_class, api_key)
        cached = self._cache.get(request_key)
        if cached is not None:
            QTimer.singleShot(
                0,
                self,
                lambda key=request_key, models=cached: (
                    self.resolved.emit(key, models)
                ),
            )
            return request_key
        if request_key in self._threads:
            return request_key

        worker = ModelCatalogWorker(request_key, provider_class, api_key)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._model_catalog_resolved)
        worker.failed.connect(self.failed.emit)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda key=request_key: self._model_catalog_finished(key)
        )
        self._workers[request_key] = worker
        self._threads[request_key] = thread
        thread.start()
        return request_key

    def _model_catalog_resolved(self, request_key: str, models: object) -> None:
        normalized = tuple(models) if isinstance(models, (list, tuple)) else ()
        self._cache[request_key] = normalized
        self.resolved.emit(request_key, normalized)

    def _model_catalog_finished(self, request_key: str) -> None:
        self._workers.pop(request_key, None)
        self._threads.pop(request_key, None)

    def shutdown(self) -> None:
        """종료 시 제한시간 안에서 진행 중인 네트워크 작업을 정리한다."""
        threads = tuple(self._threads.values())
        for thread in threads:
            thread.quit()
        for thread in threads:
            thread.wait(22_000)
        self._workers.clear()
        self._threads.clear()


_MODEL_CATALOG_COORDINATOR: ModelCatalogCoordinator | None = None
_CLI_STATUS_COORDINATOR: CliStatusCoordinator | None = None
_AI_SHUTDOWN_BOUND = False


def _bind_background_shutdown(application: QApplication | None) -> None:
    global _AI_SHUTDOWN_BOUND
    if application is None or _AI_SHUTDOWN_BOUND:
        return
    application.aboutToQuit.connect(shutdown_ai_background_services)
    application.lastWindowClosed.connect(shutdown_ai_background_services)
    _AI_SHUTDOWN_BOUND = True


def cli_status_coordinator() -> CliStatusCoordinator:
    global _CLI_STATUS_COORDINATOR
    if _CLI_STATUS_COORDINATOR is None:
        application = QApplication.instance()
        _CLI_STATUS_COORDINATOR = CliStatusCoordinator(application)
        _bind_background_shutdown(application)
    return _CLI_STATUS_COORDINATOR


def model_catalog_coordinator() -> ModelCatalogCoordinator:
    global _MODEL_CATALOG_COORDINATOR
    if _MODEL_CATALOG_COORDINATOR is None:
        application = QApplication.instance()
        _MODEL_CATALOG_COORDINATOR = ModelCatalogCoordinator(application)
        _bind_background_shutdown(application)
    return _MODEL_CATALOG_COORDINATOR


def shutdown_ai_background_services() -> None:
    """창 종료 전에 앱 공용 AI 백그라운드 작업을 정리한다."""
    if _CLI_STATUS_COORDINATOR is not None:
        _CLI_STATUS_COORDINATOR.shutdown()
    if _MODEL_CATALOG_COORDINATOR is not None:
        _MODEL_CATALOG_COORDINATOR.shutdown()


class AiChatPanel(QFrame):
    """AI와 대화하는 패널.

    본문 옆에 좁게 붙을 수도 있고(standalone=False), 왼쪽 메뉴의 "AI 검토"
    탭 전체를 채울 수도 있다(standalone=True). 두 자리가 같은 클래스를
    쓰는 이유는 개념이 하나이기 때문이다 — 둘 다 열어 둔 본문이 있으면
    그것부터 근거로 삼고, 없거나 다른 법령이 필요하면 검색 도구로 직접
    찾는다. 차이는 본문을 자동으로 물어다 주는 화면 옆에 붙어 있느냐
    뿐이다.
    """

    chatHistoryCleared = Signal(str)
    chatHistoryChanged = Signal(str, str)

    closeRequested = Signal()

    def __init__(
        self,
        settings: QSettings | None = None,
        *,
        standalone: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("aiChatPanel")
        self.standalone = standalone
        if not standalone:
            # 본문 옆 분할 패널은 내부 단추·콤보의 sizeHint를 최소 폭으로
            # 삼지 않는다. 그래야 손잡이로 300px 아래도 연속해서 줄일 수
            # 있고, 최소 폭에 닿자마자 0폭으로 튀지 않는다.
            self.setMinimumWidth(0)
            self.setSizePolicy(
                QSizePolicy.Policy.Ignored,
                QSizePolicy.Policy.Preferred,
            )
        # 이 패널이 붙는 화면은 설정을 들고 있지 않다. QSettings는 같은
        # 이름이면 같은 저장소를 가리키므로 직접 열어도 창 쪽과 같은 곳을
        # 읽고 쓴다.
        self.settings = settings or QSettings(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            "CentralLawSearch",
            "CentralAgencyLawInterpretation",
        )
        self._connection_thread: QThread | None = None
        self._connection_worker: AiConnectionWorker | None = None
        self._cli_status_coordinator = cli_status_coordinator()
        self._cli_status_requested = False
        self._model_catalog_request_key = ""
        self._model_catalog_reload_pending = False
        self._model_catalog = model_catalog_coordinator()
        self._session: ChatSession | None = None
        self._active_provider_name = ""
        self._provider_chat_states: dict[str, dict[str, object]] = {}
        self._chat_histories: dict[str, list[dict[str, object]]] = {}
        self._active_chat_ids: dict[str, str] = {}
        # CLI 확인 결과. 한 번 "설치됨 + 로그인됨"까지 확인했으면 그것을
        # 기억해 두었다가 다음에 켤 때 바로 연결됨으로 보여 준다. 켤
        # 때마다 [확인]을 눌러야 하는 것은, 달라진 것이 없는데도 매번
        # 같은 일을 시키는 셈이다.
        self._cli_statuses: dict[str, tuple[str, str]] = {}
        self._cli_tooltips: dict[str, str] = {}
        # 제공자 이름 -> 그 AI의 상태줄 문구. 하단 상태바는 하나지만
        # 내용은 AI마다 다르다. 예전에는 문구까지 하나를 같이 써서,
        # Gemini에서 난 오류가 Codex 탭 밑에 그대로 남아 있었다.
        self._status_texts: dict[str, str] = {}
        self._validated_api_key = ""
        self._context = ""
        self._context_label = ""
        # 본문을 가져오는 함수. 창 쪽에서 넣어 준다. 없어도 도구가 있으면
        # 대화는 된다.
        self.context_source = None
        # 국가법령정보 OC 인증키를 돌려주는 함수. 창 쪽에서 넣어 준다.
        # 값이 있어야 검색 도구가 켜진다.
        self.oc_provider = None
        # (category, item_id, name)을 받아 그 법령을 즐겨찾기에 거는 함수.
        # 창 쪽(ResourceSearchTab.add_favorite_by_id)에서 넣어 준다. 없으면
        # 즐겨찾기 단추를 만들지 않는다.
        self.favorite_handler = None
        # (category, item_id)를 받아 이미 즐겨찾기에 있는지 돌려주는 함수.
        # 없으면 단추는 늘 "추가"로 뜬다.
        self.favorite_checker = None
        # (law_id, jo, label, name)을 받아 조문 하나를 즐겨찾기에 거는
        # 함수와, 이미 걸렸는지 돌려주는 함수. 창 쪽에서 넣어 준다.
        self.article_favorite_handler = None
        self.article_favorite_checker = None
        # 법령 조문·행정규칙 링크는 본문 화면의 팝업으로 넘긴다.
        # 창 쪽(ResourceSearchTab.open_reference_link)을 넣어 준다.
        self.reference_handler = None
        # 화면의 저장내역. 있으면 도구가 저장된 본문을 먼저 읽고,
        # 없을 때만 본문 API를 받아 여기에 저장한다.
        self.document_cache = None
        # 화면에 보이는 제공자가 지금 답하는 중인가. 답은 제공자마다
        # 따로 돌 수 있으므로 "아무거나 도는 중"과는 다르다.
        self._streaming = False
        # 제공자 이름 -> 그 제공자의 답 하나. 각 답은 자기 작업 스레드와
        # 살아 있는 대화 목록, 진행 문구, 거쳐 온 도구를 따로 들고 있다.
        # 그래서 Gemini에게 묻고 답을 기다리는 동안 Claude에게도 물을 수
        # 있고, 탭을 옮겨도 각자 하던 일을 계속한다.
        self._streams: dict[str, dict[str, object]] = {}
        # 법령 id -> 이름. 진행줄에 "제25조"만 뜨면 어느 법인지 알 수 없어
        # 저장된 본문에서 이름을 찾아 두고 다시 읽지 않는다.
        self._document_names: dict[str, str] = {}
        self._current_status: ShimmerLabel | None = None
        self._current_tool_log: QLabel | None = None
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._refresh_status_line)
        # 주고받은 말. [역할, 내용] 짝이며, 도구 기록은 세 번째에
        # {"tools": [...]}로 붙는다. 흘러오는 답은 마지막 항목의 글을 늘린다.
        self._messages: list[list] = []
        # 질문 띠지는 최신 질문 말풍선이 화면 위로 완전히 밀려났을 때만
        # 보인다. 그 위치를 매번 찾지 않도록 마지막 말풍선을 잡아 둔다.
        self._latest_user_bubble: QWidget | None = None
        # 진짜 채팅처럼 한 글자씩 나오게 하는 타이머. 네트워크로 온 만큼을
        # 별도 속도로 풀어 보여 준다.
        self._revealed_chars = 0
        self._reveal_timer = QTimer(self)
        self._reveal_timer.timeout.connect(self._reveal_tick)

        self._build_ui()
        self._cli_status_coordinator.checked.connect(self._auto_check_result)
        self._model_catalog.resolved.connect(self._model_catalog_resolved)
        self._model_catalog.failed.connect(self._model_catalog_failed)
        self._restore_settings()
        # CLI 확인은 패널이 실제로 처음 보일 때 시작한다. 생성만 된 숨은
        # 패널까지 외부 프로세스를 깨우면 앱 시작과 테스트 종료가 느려진다.

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._start_visible_background_checks()

    def _start_visible_background_checks(self) -> None:
        """처음 화면에 들어왔을 때 필요한 비동기 확인만 시작한다."""
        if not self._cli_status_requested:
            self._cli_status_requested = True
            self._auto_check_cli()
        if self._model_catalog_reload_pending:
            self._model_catalog_reload_pending = False
            self._reload_models()

    # ------------------------------------------------------------------ 화면
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(8)

        if not self.standalone:
            # 탭 전체를 채울 때는 왼쪽 메뉴에 이미 "AI 검토"가 적혀 있고
            # 닫을 대상도 없다. 좁은 사이드 패널일 때만 제목과 닫기를 둔다.
            header = QHBoxLayout()
            header.setSpacing(6)
            title = QLabel("AI 에이전트", self)
            title.setObjectName("aiChatTitle")
            self.close_button = QPushButton("×", self)
            self.close_button.setObjectName("aiChatClose")
            self.close_button.setFixedSize(24, 24)
            self.close_button.setToolTip("대화 패널 닫기")
            self.close_button.clicked.connect(self.closeRequested.emit)
            self.history_toggle_button = ChatListButton()
            self.history_toggle_button.setObjectName("aiChatHistoryToggle")
            # 정원으로 그리므로 가로세로를 같게 둔다.
            self.history_toggle_button.setFixedSize(28, 28)
            self.history_toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.history_toggle_button.setToolTip("채팅 목록 보기")
            self.history_toggle_button.setAccessibleName("채팅 목록")
            self.history_toggle_button.clicked.connect(
                self._toggle_embedded_chat_history
            )
            header.addWidget(title)
            header.addStretch(1)
            # 채팅 목록이 이 줄의 주 동작이므로 맨 오른쪽 끝에 둔다.
            header.addWidget(self.close_button)
            header.addSpacing(2)
            header.addWidget(self.history_toggle_button)
            header.setContentsMargins(0, 0, 0, 0)
            layout.addLayout(header)

        self.provider_tabs = QTabBar()
        self.provider_tabs.setObjectName("aiProviderTabs")
        self.provider_tabs.setDrawBase(False)
        self.provider_tabs.setExpanding(False)
        self.provider_tabs.setToolTip("AI별 채팅과 저장된 대화를 따로 관리합니다.")

        tab_order = (GeminiProvider, ClaudeCodeProvider, CodexAppServerProvider)
        tab_labels = PROVIDER_TAB_LABELS
        self.provider_combo = QComboBox()
        self.provider_combo.setObjectName("aiProviderCombo")
        self.provider_combo.setToolTip("쓸 AI를 고릅니다.")
        for provider_class in PROVIDERS:
            self.provider_combo.addItem(
                tab_labels.get(provider_class, provider_class.name),
                provider_class,
            )
        for provider_class in tab_order:
            if self.provider_combo.findData(provider_class) >= 0:
                index = self.provider_tabs.addTab(tab_labels[provider_class])
                self.provider_tabs.setTabData(index, provider_class)
        self.provider_tabs.currentChanged.connect(self._provider_tab_changed)
        self.provider_combo.currentIndexChanged.connect(self._provider_changed)
        # 본문 옆에 붙는 좁은 패널에서는 탭 세 개가 다 안 들어가 좌우
        # 화살표가 생기고 글자도 잘린다. 그 자리에서는 목록에서 고른다.
        if self.standalone:
            self.provider_combo.hide()
        else:
            self.provider_tabs.hide()
            self.provider_combo.setFixedHeight(_HEADER_CONTROL_HEIGHT)
            # 제공자 이름 길이에 따라 콤보 폭이 바뀌면 오른쪽 상태 영역과
            # 아래 대화 영역이 함께 흔들린다. 가장 긴 이름에 맞추되
            # 예전 178px처럼 빈칸을 크게 두지 않는다.
            self.provider_combo.setFixedWidth(
                _label_width(
                    self.provider_combo,
                    tuple(PROVIDER_TAB_LABELS.values()),
                    margin=_PROVIDER_COMBO_WIDTH_MARGIN,
                )
            )

        self.model_combo = QComboBox()
        self.model_combo.setObjectName("aiChatModelCombo")
        self.model_combo.setToolTip("쓸 모델")
        self.model_combo.setMinimumWidth(170)
        self.model_combo.setMaximumWidth(260)
        self.model_combo.currentIndexChanged.connect(self._model_changed)
        # 실제 선택값과 기존 저장 로직은 콤보박스가 맡되 화면에는 가벼운
        # 텍스트형 단추만 보인다. 눌렀을 때만 설명이 긴 메뉴를 펼친다.
        self.model_combo.hide()
        self.model_menu_button = ModelMenuButton("모델 선택", self)
        self.model_menu_button.setObjectName("aiChatModelMenuButton")
        self.model_menu_button.setToolTip("모델 선택")
        self.model_menu_button.setMinimumWidth(0)
        self.model_menu_button.setMaximumWidth(250)
        self.model_menu_button.setFixedHeight(26)
        self.model_menu_button.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self.model_menu_button.clicked.connect(self._open_model_menu)

        # Gemini 키는 평소 화면에서 감추고 상단의 API 설정 팝업에서만
        # 입력한다. 긴 비밀키가 채팅창 폭을 계속 차지하지 않게 한다.
        self.key_row_widget = QDialog(self)
        self.key_row_widget.setObjectName("geminiApiDialog")
        self.key_row_widget.setWindowTitle("Gemini API 설정")
        self.key_row_widget.setModal(True)
        self.key_row_widget.resize(560, 340)
        self.key_row_widget.hide()
        key_dialog_layout = QVBoxLayout(self.key_row_widget)
        key_dialog_layout.setContentsMargins(16, 16, 16, 16)
        key_dialog_layout.setSpacing(10)
        key_description = QLabel(
            "Google AI Studio에서 발급한 Gemini API 키를 입력합니다.",
            self.key_row_widget,
        )
        key_dialog_layout.addWidget(key_description)
        # 모델별 한도는 모델 고르는 칸에 이름과 함께 적어 두었다.
        # 여기서 또 늘어놓으면 같은 말을 두 군데서 관리하게 된다.
        quota_notice = QLabel(
            "API 발급 시 비용이 없으며, 제한된 토큰량으로 무료 사용할 수 "
            "있습니다. 모델별 요청 한도는 아래 모델 고르는 칸에 이름과 "
            "함께 적어 두었습니다.\n\n"
            "한도는 모델·프로젝트·결제 등급에 따라 다르고 구글이 수시로 "
            "바꿉니다. 실제로 쓴 양은 [내 사용량 확인]에서 볼 수 있습니다.",
            self.key_row_widget,
        )
        quota_notice.setObjectName("geminiQuotaNotice")
        quota_notice.setWordWrap(True)
        key_dialog_layout.addWidget(quota_notice)
        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("Gemini API 키")
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setClearButtonEnabled(True)
        self.key_input.textChanged.connect(self._save_key)
        key_dialog_layout.addWidget(self.key_input)
        self.key_button = QPushButton("발급")
        self.key_button.setMinimumWidth(50)
        self.key_button.setToolTip("Gemini API 키 발급 페이지를 엽니다.")
        self.key_button.clicked.connect(self._open_key_page)
        # 발급 옆에 붙는 작은 물음표. 어디서 어떻게 받는지 그림으로 보여
        # 준다. 전역 QPushButton의 min-height가 이겨서 세로로 늘어나므로
        # 이 단추에만 크기를 못 박는다.
        self.gemini_manual_button = QPushButton("?")
        self.gemini_manual_button.setObjectName("geminiManualButton")
        self.gemini_manual_button.setFixedSize(28, 28)
        self.gemini_manual_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.gemini_manual_button.setToolTip("Gemini API 키 발급 방법 보기")
        self.gemini_manual_button.setAccessibleName("Gemini API 키 발급 도움말")
        self.gemini_manual_button.setStyleSheet(
            "QPushButton#geminiManualButton {"
            " min-width: 28px; max-width: 28px;"
            " min-height: 28px; max-height: 28px;"
            " padding: 0; border-radius: 14px;"
            " border: 1px solid #aec4d7; background: #eef3f7;"
            " color: #17324b; font-weight: 700; }"
            "QPushButton#geminiManualButton:hover {"
            " background: #17607f; border-color: #17607f; color: white; }"
        )
        self.gemini_manual_button.clicked.connect(self._open_gemini_manual)
        # 다른 화면의 "API갱신"과 같은 말을 쓴다. 키가 있으면 열 때
        # 자동으로 한 번 받아 오므로, 이 단추는 그 뒤에 모델이 새로
        # 나왔을 때만 다시 누르면 되는 보조 수단이다.
        self.refresh_button = QPushButton("갱신")
        self.refresh_button.setMinimumWidth(50)
        self.refresh_button.setToolTip(
            "쓸 수 있는 모델을 다시 받아 옵니다. 키가 있으면 열 때\n"
            "자동으로 한 번 받아 오고, 그 뒤로 바뀌었을 때만 누르면 됩니다."
        )
        self.refresh_button.clicked.connect(self._reload_models)
        usage_button = QPushButton("내 사용량 확인")
        usage_button.setToolTip(
            "AI Studio에서 이 계정이 실제로 쓴 양과 남은 한도를 봅니다."
        )
        usage_button.clicked.connect(self._open_gemini_usage_page)
        key_close_button = QPushButton("저장하고 닫기")
        key_close_button.clicked.connect(self._save_and_close_api_settings)
        key_actions = QHBoxLayout()
        key_actions.addWidget(self.key_button)
        key_actions.addWidget(self.gemini_manual_button)
        key_actions.addWidget(self.refresh_button)
        key_actions.addWidget(usage_button)
        key_actions.addStretch(1)
        key_actions.addWidget(key_close_button)
        key_dialog_layout.addLayout(key_actions)
        self.key_dialog_status = QLabel("")
        self.key_dialog_status.setObjectName("geminiApiDialogStatus")
        self.key_dialog_status.setWordWrap(True)
        key_dialog_layout.addWidget(self.key_dialog_status)

        self.api_settings_button = QPushButton("Gemini API 설정", self)
        self.api_settings_button.setObjectName("geminiApiSettingsButton")
        # 이 단추도 상태에 따라 글자가 바뀐다. 가장 긴 문구에 맞추되
        # CLI 연결 줄 폭까지 따라가지 않는다. 본문 안 패널에서는 그 폭이
        # 글자보다 훨씬 넓어 빈칸만 커 보였다.
        self.api_settings_button.setFixedWidth(
            _label_width(
                self.api_settings_button,
                (
                    "Gemini API 설정 필요",
                    "Gemini API 키 확인 필요",
                    "Gemini API 키 확인됨",
                ),
                margin=_API_SETTINGS_BUTTON_WIDTH_MARGIN,
            )
        )
        self.api_settings_button.clicked.connect(self._open_api_settings)
        # 이쪽은 반대다. 키만 받으면 무료 한도로 쓸 수 있다는 것을
        # 알아야 셋 중 무엇으로 시작할지 고를 수 있다.
        self.free_hint = QLabel("무료 사용 가능", self)
        self.free_hint.setObjectName("aiFreeHint")
        self.free_hint.setToolTip(
            "Google AI Studio에서 키를 받으면 무료 한도 안에서 쓸 수 "
            "있습니다. 모델별 한도는 모델 고르는 칸에 적어 두었습니다."
        )
        self.free_hint.setVisible(False)

        self.connection_row_widget = QWidget(self)
        connection_row = QHBoxLayout(self.connection_row_widget)
        connection_row.setContentsMargins(0, 0, 0, 0)
        connection_row.setSpacing(6)
        self.connection_status_label = QLabel("", self)
        self.connection_status_label.setObjectName("aiConnectionStatus")
        self.connection_status_label.hide()
        self.cli_install_status_label = QLabel("CLI : 확인 전", self)
        self.cli_install_status_label.setObjectName("aiCliStatusBadge")
        self.cli_install_status_label.setProperty("connectionState", "checking")
        # 글자가 "확인 전 → 확인 중 → 연결됨"으로 바뀔 때마다 폭이 달라져
        # 옆 단추와 헤더 전체가 흔들렸다. 가장 긴 문구에 맞춰 못박는다.
        self.cli_install_status_label.setFixedWidth(
            _label_width(
                self.cli_install_status_label,
                ("CLI : 확인 전", "CLI : 확인 중", "CLI : 연결됨", "CLI : 미연결"),
                margin=20,
            )
        )
        self.cli_install_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.connection_button = QPushButton("확인", self)
        self.connection_button.setObjectName("aiConnectionButton")
        # 글자가 "확인"과 "확인 중…" 사이를 오가므로 너비를 못박는다.
        # 안 그러면 누를 때마다 옆 배지와 헤더 전체가 흔들린다.
        self.connection_button.setFixedWidth(
            _label_width(self.connection_button, ("확인", "확인 중…"))
        )
        self.connection_button.setToolTip(
            "켤 때 자동으로 한 번 확인합니다. 이 단추는 CLI가 없을 때 "
            "npm으로 설치하거나, 방금 로그인한 것을 바로 반영할 때 씁니다."
        )
        self.connection_button.clicked.connect(self._connect_ai)
        # Gemini는 무료 한도로 쓸 수 있지만 이 둘은 각자 구독이 있어야
        # 한다. CLI가 깔려 있어도 구독이 없으면 답이 오지 않으므로,
        # 연결 배지 왼쪽에 미리 밝혀 둔다.
        self.subscription_hint = QLabel("유료 구독 필요", self)
        self.subscription_hint.setObjectName("aiSubscriptionHint")
        self.subscription_hint.setToolTip(
            "Claude는 Claude Pro·Max, Codex는 ChatGPT Plus·Pro 구독이 "
            "있어야 씁니다.\n무료로 써 보려면 Gemini 탭을 쓰세요."
        )
        # 좁은 사이드 패널에서는 이 줄에 자리가 없다. 그쪽은 배지에
        # 달린 설명으로 갈음한다.
        self.subscription_hint.setVisible(self.standalone)
        connection_row.addWidget(self.subscription_hint)
        connection_row.addWidget(self.cli_install_status_label)
        connection_row.addWidget(self.connection_button)

        # 본문 안의 좁은 에이전트에서는 이용 조건을 AI 선택칸 위에 따로
        # 둔다. 오른쪽 연결 배지 안에 섞으면 선택 전에는 조건을 놓치기 쉽다.
        self.embedded_access_hint = QLabel("무료 사용 가능", self)
        self.embedded_access_hint.setObjectName("aiEmbeddedAccessHint")
        self.embedded_access_hint.setFixedHeight(15)
        self.embedded_access_hint.setVisible(not self.standalone)

        # 제공자마다 오른쪽에 놓이는 것이 다르다 — Gemini는 API 설정
        # 단추, CLI 쪽은 상태 배지와 확인 단추다. 둘의 높이가 조금만
        # 달라도 탭을 옮길 때마다 아래 대화창이 통째로 위아래로 밀린다.
        # 그래서 둘 다 같은 높이로 못박고, 줄 자체도 탭 높이로 고정한다.
        self.api_settings_button.setFixedHeight(_HEADER_CONTROL_HEIGHT)
        self.connection_row_widget.setFixedHeight(_HEADER_CONTROL_HEIGHT)

        self.provider_header_widget = QWidget(self)
        # 바깥 AI의 탭은 스타일상 32px에 테두리까지 더해진다. 29px짜리
        # 컨테이너에 넣으면 첫 화면에서 탭 윗·아랫부분이 잘린다.
        self.provider_header_widget.setFixedHeight(
            36 if self.standalone else _HEADER_CONTROL_HEIGHT
        )
        provider_header = QHBoxLayout(self.provider_header_widget)
        provider_header.setContentsMargins(0, 0, 0, 0)
        provider_header.setSpacing(6)
        provider_header.addWidget(self.provider_tabs)
        provider_header.addWidget(self.provider_combo)
        provider_header.addStretch(1)
        provider_header.addWidget(self.free_hint)
        provider_header.addWidget(self.api_settings_button)
        provider_header.addWidget(self.connection_row_widget)
        # 줄 높이를 여기서 숫자로 못박지는 않는다. 이 시점에는 스타일이
        # 아직 안 먹어 탭 높이를 작게 재고, 그 값으로 고정하면 탭 윗부분이
        # 잘린다. 오른쪽 두 위젯의 높이만 같으면 탭을 옮겨도 줄 높이는
        # 늘 탭 높이 그대로다.
        if not self.standalone:
            layout.addWidget(self.embedded_access_hint)
        layout.addWidget(self.provider_header_widget)

        history_header = QHBoxLayout()
        history_header.setContentsMargins(0, 0, 0, 0)
        history_title = QLabel("채팅 목록", self)
        history_title.setObjectName("aiChatHistoryTitle")
        self.history_new_button = PlusButton("+", self)
        self.history_new_button.setObjectName("aiChatHistoryNew")
        self.history_new_button.setToolTip(
            "현재 대화를 채팅 목록에 저장하고 빈 대화를 시작합니다."
        )
        self.history_new_button.clicked.connect(self.reset_conversation)
        self.history_clear_button = QPushButton("비우기", self)
        self.history_clear_button.setObjectName("aiChatHistoryClear")
        self.history_clear_button.setToolTip(
            "이 AI의 저장된 채팅을 모두 지웁니다."
        )
        self.history_clear_button.clicked.connect(self._clear_chat_history)
        history_header.addWidget(history_title)
        history_header.addStretch(1)
        history_header.addWidget(self.history_clear_button)
        history_header.addWidget(self.history_new_button)

        self.chat_history_list = QListWidget()
        self.chat_history_list.setObjectName("aiChatHistoryList")
        self.chat_history_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.chat_history_list.itemClicked.connect(self._history_item_clicked)

        # 말풍선을 실제로 둥글게 그리려면 QTextDocument(HTML) 대신 진짜
        # 위젯을 하나씩 쌓아야 한다. Qt의 리치텍스트 렌더러는
        # border-radius를 읽지 않는다 — CSS로 넣어 봐도 각진 사각형으로
        # 그대로 나온다. QSS의 border-radius는 실제 QWidget에만 먹는다.
        self.transcript_scroll = QScrollArea()
        self.transcript_scroll.setObjectName("aiChatTranscript")
        self.transcript_scroll.setWidgetResizable(True)
        self.transcript_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.transcript_content = QWidget()
        self.transcript_content.setObjectName("aiChatTranscriptContent")
        # 스크롤 내용의 sizeHint가 긴 답변 한 줄 너비를 최소
        # 너비로 삼지 않게 해, 좁은 본문 패널에서도 줄바꿈한다.
        self.transcript_content.setMinimumWidth(0)
        self.transcript_content.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.transcript_layout = QVBoxLayout(self.transcript_content)
        self.transcript_layout.setContentsMargins(18, 14, 18, 14)
        self.transcript_layout.setSpacing(4)
        self.transcript_hint = QLabel()
        self.transcript_hint.setObjectName("aiChatHint")
        self.transcript_hint.setWordWrap(True)
        self.transcript_layout.addWidget(self.transcript_hint)
        # 늘어나는 spacer를 두면 긴 답변을 짧은 답변으로 바꾼 뒤에도
        # 이전 여유 높이가 스크롤 범위에 남을 수 있다. 내용은 위에 붙이고
        # QScrollArea가 짧은 대화일 때만 viewport 높이를 채우게 한다.
        self.transcript_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.transcript_scroll.setWidget(self.transcript_content)
        # 답이 길어지면 무엇을 물었는지 위로 밀려 사라진다. 대화창 위에
        # 겹쳐 뜨는 띠지로 지금 답하고 있는 질문을 계속 보여 준다.
        self.question_banner = QFrame(self.transcript_scroll.viewport())
        self.question_banner.setObjectName("aiChatQuestionBanner")
        banner_row = QHBoxLayout(self.question_banner)
        banner_row.setContentsMargins(10, 5, 10, 5)
        banner_row.setSpacing(7)
        banner_tag = QLabel("질문", self.question_banner)
        banner_tag.setObjectName("aiChatQuestionBannerTag")
        self.question_banner_label = QLabel("", self.question_banner)
        self.question_banner_label.setObjectName("aiChatQuestionBannerText")
        self.question_banner_label.setMinimumWidth(0)
        self.question_banner_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        banner_row.addWidget(banner_tag, 0, Qt.AlignmentFlag.AlignVCenter)
        banner_row.addWidget(
            self.question_banner_label, 1, Qt.AlignmentFlag.AlignVCenter
        )
        self.question_banner.hide()
        self._banner_question = ""
        self.transcript_scroll.viewport().installEventFilter(self)
        # 답이 흐르는 동안에는 화면이 바닥을 따라간다. 다만 사용자가
        # 위로 올려 읽는 중이면 따라가기를 놓아 주고, 다시 바닥까지
        # 내려오면 그때부터 또 따라간다.
        self._follow_bottom = True
        self._follow_pending = False
        # 글이 잠깐 멎으면 그때 스크롤 범위를 정확히 다시 잰다.
        self._follow_settle_timer = QTimer(self)
        self._follow_settle_timer.setSingleShot(True)
        self._follow_settle_timer.timeout.connect(self._settle_follow_scroll)
        self.transcript_scroll.verticalScrollBar().valueChanged.connect(
            self._transcript_scrolled
        )
        self._current_ai_label: QLabel | None = None
        self._update_hint()

        self.input_edit = ChatInput()
        self.input_edit.setObjectName("aiChatInput")
        self.input_edit.setPlaceholderText(
            "궁금한 법령을 물어보세요. 필요하면 직접 찾아 답합니다."
            if self.standalone
            else "지금 보고 있는 본문에 대해 물어보세요."
        )
        self.input_edit.setFont(QFont(FONT_FAMILY, 10))
        self.input_edit.setFixedHeight(64)
        self.input_edit.sendRequested.connect(self._send)

        send_row = QHBoxLayout()
        send_row.setContentsMargins(0, 0, 0, 0)
        send_row.setSpacing(4)
        self.reset_button = self.history_new_button
        self.send_button = SendButton()
        self.send_button.setObjectName("aiChatSend")
        self.send_button.setFixedSize(32, 32)
        self.send_button.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.send_button.setToolTip("보내기")
        self.send_button.clicked.connect(self._composer_action)
        model_label = QLabel("모델")
        model_label.setObjectName("aiChatModelLabel")
        send_row.addWidget(
            model_label, 0, Qt.AlignmentFlag.AlignVCenter
        )
        send_row.addWidget(
            self.model_menu_button,
            1,
            Qt.AlignmentFlag.AlignVCenter,
        )
        send_row.addStretch(1)
        send_row.addWidget(
            self.send_button, 0, Qt.AlignmentFlag.AlignVCenter
        )

        # 하단 상태바. 왼쪽 배지가 어느 AI의 상태인지를 밝히고, 문구는
        # 그 AI의 것만 적는다. 탭을 옮기면 그 탭의 문구로 갈아 끼운다.
        self.status_provider_label = QLabel("")
        self.status_provider_label.setObjectName("aiChatStatusProvider")
        self.status_label = QLabel("")
        self.status_label.setObjectName("aiChatStatus")
        self.status_label.setWordWrap(True)
        self.status_bar_widget = QWidget()
        self.status_bar_widget.setObjectName("aiChatStatusBar")
        status_bar = QHBoxLayout(self.status_bar_widget)
        status_bar.setContentsMargins(12, 0, 12, 0)
        status_bar.setSpacing(6)
        status_bar.addWidget(
            self.status_provider_label, 0, Qt.AlignmentFlag.AlignVCenter
        )
        status_bar.addWidget(self.status_label, 1, Qt.AlignmentFlag.AlignVCenter)
        # 문구가 없다가 생길 때마다 대화창이 위아래로 밀리지 않게
        # 한 줄 높이는 늘 잡아 둔다.
        self.status_bar_widget.setMinimumHeight(22)

        self.history_panel = QFrame()
        self.history_panel.setObjectName("aiChatHistoryPanel")
        history_layout = QVBoxLayout(self.history_panel)
        history_layout.setContentsMargins(8, 8, 8, 8)
        history_layout.setSpacing(6)
        history_layout.addLayout(history_header)
        history_layout.addWidget(self.chat_history_list, 1)

        self.composer_frame = QFrame()
        self.composer_frame.setObjectName("aiChatComposer")
        composer_layout = QVBoxLayout(self.composer_frame)
        composer_layout.setContentsMargins(10, 8, 10, 8)
        composer_layout.setSpacing(4)
        composer_layout.addWidget(self.input_edit)
        composer_layout.addLayout(send_row)

        composer_dock = QWidget()
        composer_dock.setObjectName("aiChatComposerDock")
        composer_dock_layout = QVBoxLayout(composer_dock)
        # 아래 여백은 상태바 쪽에서 한꺼번에 잡는다. 여기에 6px을
        # 더 두면 상태바가 입력창에 붙어 하단으로 몰려 보인다.
        composer_dock_layout.setContentsMargins(10, 0, 10, 0)
        composer_dock_layout.addWidget(self.composer_frame)

        if self.standalone:
            conversation_panel = QWidget()
            conversation_panel.setObjectName("aiChatConversationPanel")
            conversation_layout = QVBoxLayout(conversation_panel)
            # 마지막 칸이 상태바라, 아래 여백을 위 간격(12px)과 같게
            # 맞춰 상태바가 채팅 목록 상자 아래쪽 띠 한가운데에 놓이게 한다.
            conversation_layout.setContentsMargins(0, 0, 2, 12)
            conversation_layout.setSpacing(12)
            conversation_layout.addWidget(self.transcript_scroll, 1)
            conversation_layout.addWidget(composer_dock)
            conversation_layout.addWidget(self.status_bar_widget)

            self.chat_workspace = QSplitter(Qt.Orientation.Horizontal)
            self.chat_workspace.setObjectName("aiChatWorkspace")
            # 독립 탭은 목록과 대화를 나란히 두고 폭을 직접 조절한다.
            self.chat_workspace.setChildrenCollapsible(True)
            self.chat_workspace.setHandleWidth(12)
            self.chat_workspace.addWidget(self.history_panel)
            self.chat_workspace.addWidget(conversation_panel)
            self.history_panel.setMinimumWidth(0)
            self.history_panel.setMaximumWidth(16777215)
            conversation_panel.setMinimumWidth(0)
            self.history_panel.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
            )
            conversation_panel.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
            )
            self.chat_workspace.setCollapsible(0, True)
            self.chat_workspace.setCollapsible(1, True)
            self.chat_workspace.setSizes([220, 760])
            self.chat_workspace.setStretchFactor(0, 0)
            self.chat_workspace.setStretchFactor(1, 1)
            layout.addWidget(self.chat_workspace, 1)
        else:
            # 본문 옆의 좁은 패널에서는 목록과 답변을 겹쳐 전환한다.
            # 입력창은 전환 영역 밖에 두어 어느 화면에서도 그대로 쓴다.
            embedded_panel = QWidget()
            embedded_panel.setObjectName("aiChatConversationPanel")
            embedded_layout = QVBoxLayout(embedded_panel)
            # 독립 탭과 같은 이유로 상태바 아래 여백을 위 간격에 맞춘다.
            embedded_layout.setContentsMargins(0, 0, 2, 12)
            embedded_layout.setSpacing(12)
            self.embedded_chat_pages = QStackedWidget()
            self.embedded_chat_pages.setObjectName("aiEmbeddedChatPages")
            self.embedded_chat_pages.addWidget(self.transcript_scroll)
            self.embedded_chat_pages.addWidget(self.history_panel)
            embedded_layout.addWidget(self.embedded_chat_pages, 1)
            embedded_layout.addWidget(composer_dock)
            embedded_layout.addWidget(self.status_bar_widget)
            layout.addWidget(embedded_panel, 1)

    # -------------------------------------------------------------- 설정 저장
    def _provider_class(self):
        return self.provider_combo.currentData()

    def _connection_spec(self) -> AiCliSpec | None:
        return CLI_SPECS.get(self._provider_class())

    def _provider_tab_changed(self, index: int) -> None:
        provider_class = self.provider_tabs.tabData(index)
        combo_index = self.provider_combo.findData(provider_class)
        if combo_index >= 0:
            self.provider_combo.setCurrentIndex(combo_index)

    def _restore_settings(self) -> None:
        self._restore_saved_cli_statuses()
        saved_provider = str(self.settings.value("ai/provider", "") or "")
        for index in range(self.provider_combo.count()):
            if self.provider_combo.itemText(index) == saved_provider:
                self.provider_combo.setCurrentIndex(index)
                break
        # 첫 항목이 이미 선택된 상태라 currentIndexChanged가 안 울릴 수
        # 있으므로, 저장된 값이 없을 때를 위해 직접 한 번 불러 둔다.
        self._provider_changed()

    def _provider_changed(self) -> None:
        provider_class = self._provider_class()
        if provider_class is None:
            return
        if self._active_provider_name:
            self._save_active_provider_state()
            self._persist_current_chat()
        provider_name = provider_class.name
        self._active_provider_name = provider_name
        self.settings.setValue("ai/provider", provider_class.name)
        tab_index = -1
        for index in range(self.provider_tabs.count()):
            if self.provider_tabs.tabData(index) is provider_class:
                tab_index = index
                break
        if tab_index >= 0:
            self.provider_tabs.blockSignals(True)
            self.provider_tabs.setCurrentIndex(tab_index)
            self.provider_tabs.blockSignals(False)
        self._restore_active_provider_state()
        # 이 탭을 열어 봤으니 다른 탭에서 알리던 표시는 지우고,
        # 상태바도 이 AI의 것으로 갈아 끼운다.
        self._mark_provider_tab(provider_name, "")
        self._render_status()
        # 답이 다른 탭에서 도는 중이면 이 탭은 잠그지 않는다. 읽기는
        # 되고, 보내기만 _send에서 막으며 이유를 알려 준다.
        self._streaming = self._active_provider_name in self._streams
        self._set_busy(self._streaming)
        if self.key_row_widget.isVisible():
            self.key_row_widget.hide()
        self.api_settings_button.setVisible(provider_class.requires_api_key)
        self.free_hint.setVisible(
            self.standalone and provider_class.requires_api_key
        )
        if provider_class.requires_api_key:
            self.embedded_access_hint.setText("무료 사용 가능")
            self.embedded_access_hint.setProperty("accessType", "free")
            self.embedded_access_hint.setToolTip(
                "Google AI Studio API 키로 무료 한도 안에서 사용할 수 있습니다."
            )
        else:
            self.embedded_access_hint.setText("유료 구독 필요")
            self.embedded_access_hint.setProperty("accessType", "paid")
            self.embedded_access_hint.setToolTip(
                "Claude는 Claude Pro·Max, Codex는 ChatGPT Plus·Pro 구독이 필요합니다."
            )
        self.embedded_access_hint.style().unpolish(self.embedded_access_hint)
        self.embedded_access_hint.style().polish(self.embedded_access_hint)
        connection_spec = self._connection_spec()
        self.connection_row_widget.setVisible(connection_spec is not None)
        if connection_spec is not None:
            self.connection_status_label.setText(
                f"{connection_spec.label} 설치 및 로그인 여부를 확인합니다."
            )
            status_text, status_state = self._cli_statuses.get(
                connection_spec.label,
                ("CLI : 확인 전", "checking"),
            )
            self._set_cli_status(
                status_text,
                status_state,
                self._cli_tooltips.get(connection_spec.label, ""),
            )
            self.connection_button.setText("확인")
            self.connection_button.setToolTip(
                f"{connection_spec.label} 설치 여부를 확인하고, "
                "없으면 npm으로 설치한 뒤 로그인 여부까지 확인합니다."
            )
        if provider_class.requires_api_key:
            self.key_input.setText(
                str(self.settings.value(f"ai/key/{provider_class.name}", "") or "")
            )
            self._refresh_api_settings_button()
        self._fill_models(provider_class.fallback_models)
        saved = str(self.settings.value(f"ai/model/{provider_class.name}", "") or "")
        index = self.model_combo.findData(saved)
        if index >= 0:
            self.model_combo.setCurrentIndex(index)
        if provider_class.requires_api_key and self.key_input.text().strip():
            # 저장된 키가 있으면 열자마자 한 번 실제 모델 목록으로
            # 바꿔 둔다. "갱신" 단추를 눌러야만 진짜 목록이 보이는 것은
            # 있는 줄도 모르면 그냥 별칭만 쓰게 되는 구조라 좋지 않다.
            # 생성만 된 숨은 패널까지 조회하면 앱 시작 때 같은 요청이
            # 중복되고, 창을 닫을 때 보이지 않던 QThread가 남을 수 있다.
            # 실제로 화면에 들어온 첫 순간까지 미뤄 한 번만 요청한다.
            self._model_catalog_reload_pending = True
            if self.isVisible():
                self._model_catalog_reload_pending = False
                QTimer.singleShot(0, self._reload_models)
        else:
            self._model_catalog_reload_pending = False

    def _save_active_provider_state(self) -> None:
        if not self._active_provider_name:
            return
        self._provider_chat_states[self._active_provider_name] = {
            # 복사하지 않고 목록 자체를 넘긴다. 이 제공자의 답이 뒤에서
            # 계속 도는 중이면 작업 스레드가 이 목록에 글자를 쌓는다.
            "messages": self._messages,
            "context": self._context,
            "context_label": self._context_label,
            "session": self._session,
        }
        self._session = None

    def _restore_active_provider_state(self) -> None:
        state = self._provider_chat_states.get(self._active_provider_name, {})
        raw_messages = state.get("messages", [])
        stream = self._visible_stream()
        if stream is not None:
            # 뒤에서 도는 답이 있는 탭으로 돌아왔다. 사본을 뜨면 그 뒤에
            # 오는 글자가 화면에 안 붙으므로 같은 목록을 그대로 쓴다.
            self._messages = stream["messages"]
        else:
            self._messages = [
                self._copy_stored_message(message)
                for message in raw_messages
                if isinstance(message, (list, tuple)) and len(message) >= 2
            ]
        self._context = str(state.get("context") or "")
        self._context_label = str(state.get("context_label") or "")
        session = state.get("session")
        self._session = session if isinstance(session, ChatSession) else None
        self._render_saved_messages()
        self._refresh_chat_history()

    def _auto_check_cli(self) -> None:
        """켤 때 CLI 상태를 한 번 확인한다(설치는 하지 않는다)."""
        if self._connection_thread is not None:
            return
        self._cli_status_coordinator.request()

    def _auto_check_result(
        self, label: str, version: str, logged_in: object, detail: str
    ) -> None:
        if not label:
            return
        if version and logged_in is None:
            # 깔려는 있는데 로그인 여부를 못 읽었다. 기억해 둔 결과를
            # 이 애매한 값으로 덮어쓰면 멀쩡한 연결이 미연결로 바뀐다.
            return
        connected = bool(version) and logged_in is True
        status_text = "CLI : 연결됨" if connected else "CLI : 미연결"
        state = "connected" if connected else "disconnected"
        if not version:
            tooltip = "설치되어 있지 않습니다. [확인]을 누르면 설치합니다."
        elif connected:
            tooltip = f"{version}\n{detail}" if detail else version
        else:
            tooltip = f"{version}\n로그인이 필요합니다."
        self._cli_statuses[label] = (status_text, state)
        self._remember_cli_connection(label, connected, tooltip if connected else "")
        spec = self._connection_spec()
        if spec is not None and spec.label == label:
            self._set_cli_status(status_text, state, tooltip)

    def _connect_ai(self) -> None:
        if self._connection_thread is not None:
            return
        spec = self._connection_spec()
        if spec is None:
            return
        self.connection_button.setEnabled(False)
        self.connection_button.setText("확인 중…")
        self._set_cli_status("CLI : 확인 중", "checking")
        self.connection_status_label.setText(
            f"{spec.label} 설치 및 로그인 여부를 확인하는 중…"
        )
        self.provider_combo.setEnabled(False)

        self._connection_worker = AiConnectionWorker(spec)
        self._connection_thread = QThread(self)
        self._connection_worker.moveToThread(self._connection_thread)
        self._connection_thread.started.connect(self._connection_worker.run)
        self._connection_worker.progress.connect(self._set_connection_status)
        self._connection_worker.succeeded.connect(self._ai_connection_ready)
        self._connection_worker.failed.connect(self._ai_connection_failed)
        self._connection_worker.finished.connect(self._ai_connection_finished)
        self._connection_thread.start()

    def _ai_connection_ready(
        self,
        label: str,
        version: str,
        newly_installed: bool,
        logged_in: bool | None,
        login_detail: str,
    ) -> None:
        # ensure_cli가 돌려주는 두 번째 값은 "이번에 새로 깔았는지"다.
        # 이미 깔려 있으면 False로 온다 — 이것을 "설치되어 있는지"로 읽어
        # 연결 여부를 판단하면, 멀쩡히 깔린 CLI가 늘 미연결로 나온다.
        # 여기까지 왔다는 것 자체가 CLI를 쓸 수 있다는 뜻이다(못 쓰면
        # ensure_cli가 AiCliSetupError를 던져 _ai_connection_failed로 간다).
        installation = "설치 완료" if newly_installed else "설치됨"
        if logged_in is True:
            login = "로그인됨"
            if login_detail:
                login += f" ({login_detail})"
        elif logged_in is False:
            login = "로그인 필요"
        else:
            login = "로그인 여부 확인 실패"
            if login_detail:
                login += f" ({login_detail[-200:]})"
        self._set_connection_status(f"{label} {installation} · {version} · {login}")
        connected = logged_in is True
        status_text = "CLI : 연결됨" if connected else "CLI : 미연결"
        status_state = "connected" if connected else "disconnected"
        self._cli_statuses[label] = (status_text, status_state)
        tooltip = version
        if login_detail:
            tooltip += f"\n{login_detail}"
        self._remember_cli_connection(label, connected, tooltip)
        self._set_cli_status(status_text, status_state, tooltip)

    def _ai_connection_failed(self, message: str) -> None:
        self._set_connection_status(message)
        spec = self._connection_spec()
        if spec is not None:
            self._cli_statuses[spec.label] = ("CLI : 미연결", "disconnected")
            self._remember_cli_connection(spec.label, False)
        self._set_cli_status("CLI : 미연결", "disconnected", message)

    def _set_connection_status(self, text: str) -> None:
        """CLI 확인 경과와 결과를 화면에 보이는 상태줄에도 적는다.

        헤더의 connection_status_label은 폭을 아끼려고 숨겨 놓았다.
        거기에만 적으면 "미연결" 배지만 남고 왜 미연결인지는 어디에도
        보이지 않는다.
        """
        self.connection_status_label.setText(text)
        self._set_status(text)

    def _set_cli_status(
        self, text: str, state: str, tooltip: str = ""
    ) -> None:
        self.cli_install_status_label.setText(text)
        self.cli_install_status_label.setProperty("connectionState", state)
        self.cli_install_status_label.setToolTip(tooltip)
        self.cli_install_status_label.style().unpolish(
            self.cli_install_status_label
        )
        self.cli_install_status_label.style().polish(
            self.cli_install_status_label
        )
        self.cli_install_status_label.update()
        # 상태바가 할 말이 없을 때 보이는 줄이 곧 이 연결 여부다.
        self._render_status()

    def _cli_settings_key(self, label: str) -> str:
        return f"ai/cli_connected/{label}"

    def _restore_saved_cli_statuses(self) -> None:
        """지난번에 확인해 둔 연결 상태를 되살린다."""
        for spec in CLI_SPECS.values():
            saved = self.settings.value(self._cli_settings_key(spec.label), "")
            try:
                record = json.loads(str(saved or ""))
            except ValueError:
                continue
            if not isinstance(record, dict) or not record.get("connected"):
                continue
            self._cli_statuses[spec.label] = ("CLI : 연결됨", "connected")
            checked = str(record.get("checked_at") or "")
            note = (
                f"{checked}에 확인한 결과입니다. 다시 확인하려면 [확인]을 누르세요."
                if checked
                else ""
            )
            self._cli_tooltips[spec.label] = "\n".join(
                part for part in (str(record.get("detail") or ""), note) if part
            )

    def _remember_cli_connection(
        self, label: str, connected: bool, detail: str = ""
    ) -> None:
        """확인 결과를 다음 실행까지 남긴다. 연결됐을 때만 남긴다.

        미연결은 남기지 않는다 — 로그인만 하고 다시 켰을 때 여전히
        "미연결"로 뜨면 오히려 틀린 말이 된다.
        """
        key = self._cli_settings_key(label)
        if not connected:
            self.settings.remove(key)
            self._cli_tooltips.pop(label, None)
            return
        self._cli_tooltips[label] = detail
        self.settings.setValue(
            key,
            json.dumps(
                {
                    "connected": True,
                    "detail": detail,
                    "checked_at": time.strftime("%Y-%m-%d"),
                },
                ensure_ascii=False,
            ),
        )

    def _set_status(
        self, text: str, provider_name: str = "", kind: str = "info"
    ) -> None:
        """상태줄 문구를 그 AI 것으로 적어 둔다.

        하단 상태바는 하나지만 내용은 AI마다 다르다. 화면에 안 떠 있는
        AI의 소식은 저장만 해 두고 탭 글자색으로 알린 뒤, 그 탭으로
        갔을 때 보여 준다.
        """
        name = provider_name or self._active_provider_name
        if not name:
            return
        self._status_texts[name] = text
        if name == self._active_provider_name:
            self._render_status()
        else:
            self._mark_provider_tab(name, kind if text else "")

    def _render_status(self) -> None:
        """화면에 떠 있는 AI의 상태만 하단 상태바에 그린다."""
        name = self._active_provider_name
        self.status_provider_label.setText(_provider_label(name) if name else "")
        self.status_provider_label.setVisible(self.standalone and bool(name))
        self.status_label.setText(
            self._status_texts.get(name, "") or self._resting_status(name)
        )

    def _resting_status(self, provider_name: str) -> str:
        """할 말이 없을 때 그 AI를 지금 쓸 수 있는지를 한 줄로 보인다.

        AI마다 쓸 수 있는 조건이 다르다 — CLI 쪽은 연결 여부가, Gemini는
        API 키가 곧 "지금 물어볼 수 있는가"다.
        """
        provider_class = _PROVIDER_BY_NAME.get(provider_name)
        if provider_class is None:
            return ""
        if provider_name in self._streams:
            return "답하는 중입니다."
        spec = CLI_SPECS.get(provider_class)
        if spec is not None:
            text = self._cli_statuses.get(spec.label, ("CLI : 확인 전", ""))[0]
            return text.replace("CLI : ", "CLI ")
        if provider_class.requires_api_key:
            key = str(
                self.settings.value(f"ai/key/{provider_class.name}", "") or ""
            ).strip()
            if not key:
                return "API 키가 없습니다."
            if key == self._validated_api_key:
                return "API 키 확인됨"
            return "API 키 확인 필요"
        return ""

    def _mark_provider_tab(self, provider_name: str, kind: str) -> None:
        """다른 탭에서 생긴 소식을 그 탭 글자색과 툴팁으로만 알린다."""
        provider_class = _PROVIDER_BY_NAME.get(provider_name)
        if provider_class is None:
            return
        color = QColor()
        if kind == "error":
            color = QColor("#a12c2a")
        elif kind:
            color = QColor("#176b4b")
        tooltip = self._status_texts.get(provider_name, "") if kind else ""
        for index in range(self.provider_tabs.count()):
            if self.provider_tabs.tabData(index) is provider_class:
                self.provider_tabs.setTabTextColor(index, color)
                self.provider_tabs.setTabToolTip(index, tooltip)
        index = self.provider_combo.findData(provider_class)
        if index >= 0:
            self.provider_combo.setItemData(
                index,
                QBrush(color) if kind else None,
                Qt.ItemDataRole.ForegroundRole,
            )
            self.provider_combo.setItemData(
                index, tooltip, Qt.ItemDataRole.ToolTipRole
            )

    def _ai_connection_finished(self) -> None:
        if self._connection_thread is not None:
            self._connection_thread.quit()
            self._connection_thread.wait()
            self._connection_thread.deleteLater()
        if self._connection_worker is not None:
            self._connection_worker.deleteLater()
        self._connection_thread = None
        self._connection_worker = None
        self.connection_button.setText("확인")
        self.connection_button.setEnabled(not self._streaming)
        self.provider_combo.setEnabled(not self._streaming)
        self.provider_tabs.setEnabled(not self._streaming)

    def _save_key(self) -> None:
        provider_class = self._provider_class()
        if provider_class is not None:
            settings_key = f"ai/key/{provider_class.name}"
            old_key = str(self.settings.value(settings_key, "") or "")
            new_key = self.key_input.text()
            self.settings.setValue(
                settings_key, new_key
            )
            if old_key != new_key:
                self._validated_api_key = ""
                self._close_session()
        self._refresh_api_settings_button()

    def _refresh_api_settings_button(self) -> None:
        key = self.key_input.text().strip()
        configured = bool(key) and key == self._validated_api_key
        if configured:
            label = "Gemini API 키 확인됨"
        elif key:
            label = "Gemini API 키 확인 필요"
        else:
            label = "Gemini API 설정 필요"
        self.api_settings_button.setText(label)
        self.api_settings_button.setProperty("apiConfigured", configured)
        self.api_settings_button.style().unpolish(self.api_settings_button)
        self.api_settings_button.style().polish(self.api_settings_button)
        self.api_settings_button.update()

    def _set_api_status(self, text: str) -> None:
        """API 확인 결과를 팝업 안과 대화 상태줄 양쪽에 같이 적는다.

        팝업이 모달이라 대화 상태줄은 가려진다. 확인 결과를 그쪽에만
        적으면 사용자에게는 아무 일도 안 일어난 것으로 보인다.
        """
        self._set_status(text)
        self.key_dialog_status.setText(text)

    def _open_api_settings(self) -> None:
        self.key_dialog_status.setText("")
        self.key_row_widget.exec()

    def _save_and_close_api_settings(self) -> None:
        # 키는 입력할 때마다 이미 저장된다. 여기서는 아직 확인하지 않은
        # 키만 한 번 확인해 보고, 확인이 실패하더라도 창은 닫는다.
        # 예전에는 확인에 성공해야만 닫혔는데, 실패 사유가 팝업에 가려진
        # 상태줄에만 찍혀서 단추가 먹지 않는 것처럼 보였다.
        key = self.key_input.text().strip()
        if key and key != self._validated_api_key:
            self._reload_models()
        self.key_row_widget.accept()

    def _open_gemini_manual(self, *_args: object) -> None:
        """제미나이 API 키 발급 안내를 기본 웹 브라우저로 연다."""
        if not GEMINI_KEY_MANUAL_PATH.is_file():
            QMessageBox.warning(
                self,
                "안내 파일 없음",
                "제미나이 API 키 발급 안내 파일을 찾지 못했습니다.",
            )
            return
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(GEMINI_KEY_MANUAL_PATH))
        )

    @staticmethod
    def _open_gemini_usage_page() -> None:
        """AI Studio의 사용량·한도 화면을 연다.

        Gemini API로는 남은 요청 수를 조회할 수 없다. 실제로 얼마나
        썼는지는 이 화면에서만 볼 수 있다.
        """
        QDesktopServices.openUrl(QUrl(GEMINI_USAGE_URL))

    @staticmethod
    def _compact_model_label(label: str) -> str:
        """닫힌 선택부에는 모델명과 성격만 짧게 표시한다."""
        text = str(label or "모델 선택").strip()
        if text.startswith("기본 모델"):
            return "기본 모델"
        text = re.sub(r"\([^)]*\)\s*$", "", text).strip()
        text = text.replace(" - ", " — ")
        text = text.replace("가장 빠른답변", "가장 빠른 답변")
        return text

    def _sync_model_menu_button(self) -> None:
        label = self.model_combo.currentText()
        compact = self._compact_model_label(label)
        self.model_menu_button.setText(compact)
        self.model_menu_button.setToolTip(label or "모델 선택")

    def _select_model_index(self, index: int) -> None:
        if 0 <= index < self.model_combo.count():
            self.model_combo.setCurrentIndex(index)

    def _build_model_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setObjectName("aiChatModelMenu")
        if self._provider_class() is GeminiProvider:
            note = menu.addAction(GeminiProvider.FREE_QUOTA_MENU_NOTE)
            note.setEnabled(False)
            note.setObjectName("aiChatModelMenuNote")
        current = self.model_combo.currentIndex()
        for index in range(self.model_combo.count()):
            # 네이티브 메뉴 체크는 작은 비트맵이라 고해상도 화면에서
            # 깨지고, 체크 전용 열도 넓게 잡힌다. 글자와 함께 렌더링되는
            # 얇은 체크를 써서 여백을 최소화한다.
            prefix = "✓ " if index == current else " "
            action = menu.addAction(
                prefix + self.model_combo.itemText(index)
            )
            note = self.model_combo.itemData(index, Qt.ItemDataRole.ToolTipRole)
            if note:
                action.setToolTip(str(note))
            action.triggered.connect(
                functools.partial(self._select_model_index, index)
            )
        return menu

    def _open_model_menu(self) -> None:
        """짧은 모델명 아래에 전체 설명을 담은 선택 메뉴를 연다."""
        menu = self._build_model_menu()
        menu.exec(
            self.model_menu_button.mapToGlobal(
                self.model_menu_button.rect().bottomLeft()
            )
        )

    def _model_changed(self) -> None:
        provider_class = self._provider_class()
        model_id = self.model_combo.currentData()
        if provider_class is not None and model_id is not None:
            self.settings.setValue(f"ai/model/{provider_class.name}", model_id)
        self._sync_model_menu_button()
        # 모델을 바꾸면 지금 대화는 이어 갈 수 없다. 다음 질문에 새로 연다.
        self._close_session()

    def _fill_models(self, models) -> None:
        keep = self.model_combo.currentData()
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for index, model in enumerate(models):
            self.model_combo.addItem(model.label, model.model_id)
            # 무료 한도처럼 고를 근거가 되는 값은 목록을 좁히지 않도록
            # 툴팁으로만 붙인다.
            if getattr(model, "note", ""):
                self.model_combo.setItemData(
                    index, model.note, Qt.ItemDataRole.ToolTipRole
                )
        self.model_combo.blockSignals(False)
        if keep is not None:
            index = self.model_combo.findData(keep)
            if index >= 0:
                self.model_combo.setCurrentIndex(index)
        self._sync_model_menu_button()

    def _reload_models(self) -> None:
        provider_class = self._provider_class()
        if provider_class is None or not provider_class.requires_api_key:
            return
        if not self.key_input.text().strip():
            self._set_api_status("API 키를 먼저 넣으세요.")
            return
        self._set_api_status("모델을 확인하는 중…")
        self.refresh_button.setEnabled(False)
        self._model_catalog_request_key = self._model_catalog.request(
            provider_class, self.key_input.text().strip()
        )

    def _model_catalog_resolved(
        self, request_key: str, models: object
    ) -> None:
        if request_key != self._model_catalog_request_key:
            return
        self._model_catalog_request_key = ""
        self.refresh_button.setEnabled(True)
        self._validated_api_key = self.key_input.text().strip()
        self._refresh_api_settings_button()
        normalized = tuple(models) if isinstance(models, (list, tuple)) else ()
        self._fill_models(normalized)
        self._set_api_status(f"모델 {len(normalized)}개를 확인했습니다.")

    def _model_catalog_failed(self, request_key: str, message: str) -> None:
        if request_key != self._model_catalog_request_key:
            return
        self._model_catalog_request_key = ""
        self.refresh_button.setEnabled(True)
        self._validated_api_key = ""
        self._refresh_api_settings_button()
        self._set_api_status(message)

    def _open_key_page(self) -> None:
        provider_class = self._provider_class()
        if provider_class and provider_class.api_key_url:
            QDesktopServices.openUrl(QUrl(provider_class.api_key_url))

    # ------------------------------------------------------------------ 대화
    def _history_settings_key(self, provider_name: str = "") -> str:
        return f"ai/chat_history/{provider_name or self._active_provider_name}"

    def _emit_history_changed(self, provider_name: str, chat_id: str) -> None:
        """저장 내용을 디스크에 반영한 뒤 다른 채팅 패널에 알린다."""
        self.settings.sync()
        self.chatHistoryChanged.emit(provider_name, chat_id)

    def _provider_history(
        self, provider_name: str = "", *, reload: bool = False
    ) -> list[dict[str, object]]:
        name = provider_name or self._active_provider_name
        if not reload and name in self._chat_histories:
            return self._chat_histories[name]
        raw = str(self.settings.value(self._history_settings_key(name), "") or "")
        try:
            loaded = json.loads(raw) if raw else []
        except json.JSONDecodeError:
            loaded = []
        history = [item for item in loaded if isinstance(item, dict)]
        self._chat_histories[name] = history
        return history

    def _new_chat_id(self, name: str) -> str:
        """겹치지 않는 채팅 번호를 만든다.

        time_ns는 윈도우에서 15ms 단위로만 올라간다. 새 채팅을 잇달아
        열면 같은 번호가 나와 두 대화가 한 칸으로 합쳐져 버린다.
        """
        used = {
            str(item.get("id") or "")
            for item in self._provider_history(name)
        }
        used.update(str(value) for value in self._active_chat_ids.values())
        candidate = time.time_ns()
        while str(candidate) in used:
            candidate += 1
        return str(candidate)

    def _persist_current_chat(
        self,
        provider_name: str = "",
        messages: list[list[str]] | None = None,
    ) -> None:
        name = provider_name or self._active_provider_name
        if not name:
            return
        entries = self._messages if messages is None else messages
        first_user = next(
            (
                message[1].strip()
                for message in entries
                if message[0] == "user" and message[1].strip()
            ),
            "",
        )
        if not first_user:
            return
        chat_id = self._active_chat_ids.get(name, "")
        if not chat_id:
            chat_id = self._new_chat_id(name)
            self._active_chat_ids[name] = chat_id
        title = first_user if len(first_user) <= 32 else f"{first_user[:31]}…"
        history = self._provider_history(name)
        previous = next(
            (
                item
                for item in history
                if str(item.get("id") or "") == chat_id
            ),
            {},
        )
        record: dict[str, object] = {
            "id": chat_id,
            "title": title,
            "updated_at": time.time(),
            "model": str(self.model_combo.currentData() or ""),
            "messages": [list(message) for message in entries],
            "context": self._context,
            "context_label": self._context_label,
        }
        # 직접 바꾼 이름과 고정은 대화가 이어져도 그대로 둔다.
        for key in ("custom_title", "pinned"):
            if previous.get(key):
                record[key] = previous[key]
        position = next(
            (
                index
                for index, item in enumerate(history)
                if str(item.get("id") or "") == chat_id
            ),
            -1,
        )
        if position >= 0 and previous.get("messages") == record["messages"]:
            # 목록에서 골라 열어 보기만 했다. 주고받은 말이 그대로면
            # 순서도 그대로 둔다 — 훑어보기만 해도 목록이 뒤집히면
            # 어디까지 봤는지 알 수 없다.
            record["updated_at"] = previous.get("updated_at", record["updated_at"])
            history[position] = record
        else:
            history[:] = [
                item for item in history if str(item.get("id") or "") != chat_id
            ]
            history.insert(0, record)
        del history[50:]
        self.settings.setValue(
            self._history_settings_key(name),
            json.dumps(history, ensure_ascii=False),
        )
        if name == self._active_provider_name:
            self._refresh_chat_history()
        self._emit_history_changed(name, chat_id)

    def _refresh_chat_history(self) -> None:
        self.chat_history_list.clear()
        active_id = self._active_chat_ids.get(self._active_provider_name, "")
        # 고정한 채팅을 위로 올린다. 파이썬 정렬은 순서를 흐트러뜨리지
        # 않으므로 같은 무리 안에서는 최근 것이 그대로 앞에 남는다.
        records = sorted(
            self._provider_history(reload=True),
            key=lambda item: not item.get("pinned"),
        )
        for record in records:
            chat_id = str(record.get("id") or "")
            title = self._chat_title(record)
            # 글자는 얹는 위젯이 그린다. 항목 자체의 글자까지 있으면
            # 두 벌이 겹쳐 보인다.
            item = QListWidgetItem("")
            item.setData(Qt.ItemDataRole.UserRole, chat_id)
            model = str(record.get("model") or "")
            item.setToolTip(f"사용 모델: {model}" if model else title)
            self.chat_history_list.addItem(item)
            row = self._install_history_row(
                item, chat_id, title, bool(record.get("pinned"))
            )
            row.setProperty("selected", chat_id == active_id)
            if chat_id == active_id:
                self.chat_history_list.setCurrentItem(item)
        # setItemWidget 직후 목록이 아직 첫 폭을 계산하지 못하면 오른쪽
        # 메뉴 단추의 폭이 0으로 남아 점이 나중에 나타난다. 지금 한 번
        # 배치를 확정해 첫 페인트부터 제목과 단추가 함께 보이게 한다.
        self.chat_history_list.doItemsLayout()
        self._sync_history_selection()
        self.chat_history_list.viewport().update()

    def _sync_history_selection(self) -> None:
        """현재 열린 채팅 행만 음영을 주고 즉시 다시 그린다."""
        active_id = self._active_chat_ids.get(self._active_provider_name, "")
        for index in range(self.chat_history_list.count()):
            item = self.chat_history_list.item(index)
            selected = bool(
                active_id
                and str(item.data(Qt.ItemDataRole.UserRole) or "") == active_id
            )
            item.setSelected(selected)
            row = self.chat_history_list.itemWidget(item)
            if row is None:
                continue
            row.setProperty("selected", selected)
            row.style().unpolish(row)
            row.style().polish(row)
            row.update()

    @staticmethod
    def _chat_title(record: dict[str, object]) -> str:
        """목록에 보일 이름. 직접 바꾼 이름이 있으면 그것을 쓴다."""
        return str(
            record.get("custom_title")
            or record.get("title")
            or "제목 없는 대화"
        )

    def _install_history_row(
        self,
        item: QListWidgetItem,
        chat_id: str,
        title: str,
        pinned: bool = False,
    ) -> QWidget:
        """목록 한 줄에 제목과 ⋯ 단추를 얹고 그 위젯을 돌려준다.

        제목은 QLabel이라 마우스를 안 먹으므로, 제목 쪽을 누르면 그대로
        목록 항목이 눌린 것으로 넘어간다. ⋯ 단추만 따로 받는다.
        """
        row = QWidget()
        row.setObjectName("aiChatHistoryRow")
        # 평범한 QWidget은 이것을 켜야 스타일시트의 배경을 그린다.
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(9, 5, 5, 5)
        row_layout.setSpacing(4)
        label = ElidedLabel(("📌 " if pinned else "") + title)
        label.setObjectName("aiChatHistoryItemTitle")
        label.setToolTip(title)
        label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        label.setMinimumWidth(0)
        # 글꼴의 점 문자는 첫 페인트 때 잘리는 환경이 있어 직접 그린다.
        menu_button = HistoryMenuButton()
        menu_button.setObjectName("aiChatHistoryMenu")
        menu_button.setFixedSize(24, 24)
        menu_button.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        menu_button.setAccessibleName("채팅 메뉴")
        menu_button.setCursor(Qt.CursorShape.PointingHandCursor)
        menu_button.setToolTip("이름 바꾸기·삭제·고정")
        menu_button.clicked.connect(
            functools.partial(self._open_chat_menu, chat_id, menu_button)
        )
        row_layout.addWidget(label, 1)
        # 제목이 두 줄로 늘어나도 단추는 줄 가운데에 둔다. 예전에는
        # 아래로 붙어 내려가 눌러야 할 자리가 매번 달라 보였다.
        row_layout.addWidget(menu_button, 0, Qt.AlignmentFlag.AlignVCenter)
        row_layout.setStretch(0, 1)
        row_layout.setStretch(1, 0)
        # 제목의 자연 너비를 항목 너비로 저장하면 목록이 좁아졌을 때
        # 오른쪽 ⋯ 버튼이 클리핑된다. 위젯을 설치하기 전에 높이만
        # 확정해야 첫 배치부터 단추 자리가 확보된다.
        item.setSizeHint(QSize(0, max(30, row.sizeHint().height())))
        self.chat_history_list.setItemWidget(item, row)
        menu_button.show()
        menu_button.update()
        return row

    def _find_chat(self, chat_id: str) -> dict[str, object] | None:
        return next(
            (
                record
                for record in self._provider_history()
                if str(record.get("id") or "") == chat_id
            ),
            None,
        )

    def _save_provider_history(self, chat_id: str = "") -> None:
        self.settings.setValue(
            self._history_settings_key(),
            json.dumps(self._provider_history(), ensure_ascii=False),
        )
        if chat_id:
            self._emit_history_changed(self._active_provider_name, chat_id)

    def _open_chat_menu(self, chat_id: str, anchor: QWidget) -> None:
        """⋯를 누르면 이 채팅에 할 수 있는 일을 보여 준다."""
        record = self._find_chat(chat_id)
        if record is None:
            return
        menu = QMenu(self)
        menu.setObjectName("aiChatHistoryPopup")
        rename = menu.addAction("이름 바꾸기")
        pinned = bool(record.get("pinned"))
        pin = menu.addAction("고정 해제" if pinned else "채팅 고정")
        menu.addSeparator()
        remove = menu.addAction("삭제")
        chosen = menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        if chosen is None:
            return
        if chosen is rename:
            self._rename_chat(chat_id)
        elif chosen is pin:
            self._toggle_chat_pin(chat_id)
        elif chosen is remove:
            self._delete_chat(chat_id)

    def _rename_chat(self, chat_id: str) -> None:
        record = self._find_chat(chat_id)
        if record is None:
            return
        name, accepted = QInputDialog.getText(
            self,
            "채팅 이름 바꾸기",
            "새 이름을 넣으세요. 비우면 첫 질문으로 되돌립니다.",
            text=self._chat_title(record),
        )
        if not accepted:
            return
        name = name.strip()
        if name:
            record["custom_title"] = name
        else:
            record.pop("custom_title", None)
        self._save_provider_history(chat_id)
        self._refresh_chat_history()

    def _toggle_chat_pin(self, chat_id: str) -> None:
        record = self._find_chat(chat_id)
        if record is None:
            return
        if record.get("pinned"):
            record.pop("pinned", None)
        else:
            record["pinned"] = True
        self._save_provider_history(chat_id)
        self._refresh_chat_history()

    def _delete_chat(self, chat_id: str) -> None:
        """채팅 하나를 목록에서 지운다."""
        if self._streaming:
            self._set_status("답변이 끝난 뒤에 지울 수 있습니다.")
            return
        history = self._provider_history()
        history[:] = [
            item for item in history if str(item.get("id") or "") != chat_id
        ]
        self.settings.setValue(
            self._history_settings_key(),
            json.dumps(history, ensure_ascii=False),
        )
        self._emit_history_changed(self._active_provider_name, chat_id)
        # 지금 보고 있던 대화를 지웠으면 화면도 같이 비운다. 안 그러면
        # 목록에 없는 대화가 계속 떠 있고, 다음 질문에 되살아난다.
        if self._active_chat_ids.get(self._active_provider_name, "") == chat_id:
            self._start_empty_conversation()
        self._refresh_chat_history()

    def _clear_chat_history(self) -> None:
        """이 제공자의 저장된 채팅을 모두 지운다."""
        if self._streaming:
            self._set_status("답변이 끝난 뒤에 지울 수 있습니다.")
            return
        if not self._provider_history():
            self._set_status("지울 채팅이 없습니다.")
            return
        answer = QMessageBox.question(
            self,
            "채팅 목록 비우기",
            f"{_provider_label(self._active_provider_name)}의 저장된 채팅을 "
            "모두 지웁니다.\n"
            "되돌릴 수 없습니다. 계속할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._provider_history()[:] = []
        self.settings.setValue(self._history_settings_key(), "[]")
        self.settings.sync()
        self.chatHistoryCleared.emit(self._active_provider_name)
        self._start_empty_conversation()
        self._refresh_chat_history()
        self._set_status("채팅 목록을 비웠습니다.")

    def apply_external_history_clear(self, provider_name: str) -> None:
        """다른 채팅 패널에서 비운 제공자의 목록과 현재 대화를 동기화한다."""
        name = str(provider_name or "")
        if not name:
            return
        self._chat_histories[name] = []
        self._active_chat_ids[name] = ""
        if name != self._active_provider_name:
            return
        self._start_empty_conversation()
        self._refresh_chat_history()
        self._set_status("다른 AI 화면에서 채팅 목록을 비웠습니다.")

    def apply_external_history_change(
        self, provider_name: str, chat_id: str
    ) -> None:
        """다른 AI 화면에서 저장한 채팅과 현재 화면을 즉시 맞춘다."""
        name = str(provider_name or "")
        changed_id = str(chat_id or "")
        if not name or not changed_id:
            return
        # 패널마다 QSettings 객체가 달라도 방금 쓴 값을 읽을 수 있게 한다.
        self.settings.sync()
        history = self._provider_history(name, reload=True)
        record = next(
            (
                item
                for item in history
                if str(item.get("id") or "") == changed_id
            ),
            None,
        )
        if name == self._active_provider_name:
            self._refresh_chat_history()

        # 목록만 공유하는 다른 채팅은 현재 대화를 바꾸지 않는다.
        if self._active_chat_ids.get(name, "") != changed_id:
            return
        if record is None:
            self._active_chat_ids[name] = ""
            self._provider_chat_states.pop(name, None)
            if name == self._active_provider_name:
                self._start_empty_conversation()
                self._set_status("다른 AI 화면에서 이 채팅을 삭제했습니다.")
            return

        raw_messages = record.get("messages", [])
        if not isinstance(raw_messages, list):
            raw_messages = []
        messages = [
            self._copy_stored_message(message)
            for message in raw_messages
            if isinstance(message, (list, tuple)) and len(message) >= 2
        ]
        state = self._provider_chat_states.get(name)
        if state is not None:
            state["messages"] = messages
            state["context"] = str(record.get("context") or "")
            state["context_label"] = str(record.get("context_label") or "")
            state["session"] = None

        if name != self._active_provider_name or name in self._streams:
            return
        context = str(record.get("context") or "")
        context_label = str(record.get("context_label") or "")
        if (
            messages == self._messages
            and context == self._context
            and context_label == self._context_label
        ):
            self._sync_history_selection()
            return
        self._close_session()
        self._messages = messages
        self._context = context
        self._context_label = context_label
        model = str(record.get("model") or "")
        model_index = self.model_combo.findData(model)
        if model_index >= 0:
            self.model_combo.setCurrentIndex(model_index)
        self._render_saved_messages()
        self._save_active_provider_state()
        self._sync_history_selection()
        self._session = None
        self._set_status("다른 AI 화면에서 이어진 대화를 반영했습니다.")

    def _start_empty_conversation(self) -> None:
        """저장은 하지 않고 화면의 대화만 빈 채로 되돌린다."""
        self._close_session()
        self._active_chat_ids[self._active_provider_name] = ""
        self._messages = []
        self._current_ai_label = None
        self._reveal_timer.stop()
        self._render_saved_messages()
        self._update_hint()
        self._save_active_provider_state()

    def _show_embedded_conversation(self) -> None:
        pages = getattr(self, "embedded_chat_pages", None)
        if pages is None:
            return
        pages.setCurrentIndex(0)
        self.history_toggle_button.setToolTip("채팅 목록 보기")
        self.history_toggle_button.setProperty("historyVisible", False)
        self.history_toggle_button.style().unpolish(self.history_toggle_button)
        self.history_toggle_button.style().polish(self.history_toggle_button)

    def _toggle_embedded_chat_history(self) -> None:
        """본문 내 에이전트에서 답변과 채팅 목록을 전환한다."""
        pages = getattr(self, "embedded_chat_pages", None)
        if pages is None:
            return
        showing_history = pages.currentIndex() == 1
        pages.setCurrentIndex(0 if showing_history else 1)
        visible = not showing_history
        self.history_toggle_button.setToolTip(
            "대화로 돌아가기" if visible else "채팅 목록 보기"
        )
        self.history_toggle_button.setProperty("historyVisible", visible)
        self.history_toggle_button.style().unpolish(self.history_toggle_button)
        self.history_toggle_button.style().polish(self.history_toggle_button)
        if visible:
            self._refresh_chat_history()
            self.chat_history_list.setFocus()
        else:
            self.input_edit.setFocus()

    def _prepare_embedded_history_send(self) -> bool:
        """목록 화면에서 보낸 질문을 새 대화로 전환했는지 반환한다."""
        pages = getattr(self, "embedded_chat_pages", None)
        if pages is None or pages.currentIndex() != 1:
            return False
        self.reset_conversation()
        self._show_embedded_conversation()
        return True

    def _history_item_clicked(self, item: QListWidgetItem) -> None:
        if self._streaming:
            return
        self._show_embedded_conversation()
        chat_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if chat_id == self._active_chat_ids.get(self._active_provider_name, ""):
            return
        self._persist_current_chat()
        record = next(
            (
                entry
                for entry in self._provider_history()
                if str(entry.get("id") or "") == chat_id
            ),
            None,
        )
        if record is None:
            return
        self._close_session()
        self._active_chat_ids[self._active_provider_name] = chat_id
        raw_messages = record.get("messages", [])
        self._messages = [
            self._copy_stored_message(message)
            for message in raw_messages
            if isinstance(message, (list, tuple)) and len(message) >= 2
        ]
        self._context = str(record.get("context") or "")
        self._context_label = str(record.get("context_label") or "")
        model = str(record.get("model") or "")
        model_index = self.model_combo.findData(model)
        if model_index >= 0:
            self.model_combo.setCurrentIndex(model_index)
        self._render_saved_messages()
        self._save_active_provider_state()
        self._sync_history_selection()
        # 저장 직후 현재 패널에서 계속 쓸 수 있도록 세션 자리만 다시 비운다.
        self._session = None

    def _clear_transcript_widgets(self) -> None:
        self._latest_user_bubble = None
        while self.transcript_layout.count() > 1:
            item = self.transcript_layout.takeAt(1)
            widget = item.widget()
            if widget is not None:
                # deleteLater만 하면 긴 이전 대화 위젯이 다음 이벤트 루프까지
                # 자식으로 남아, 짧은 채팅을 열어도 예전 높이만큼 빈 스크롤
                # 공간이 유지될 수 있다.
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _fit_transcript_extent(self) -> None:
        """바꾼 채팅의 실제 내용 높이로 스크롤 범위를 다시 계산한다."""
        self.transcript_layout.invalidate()
        self.transcript_layout.activate()
        self.transcript_content.adjustSize()
        self.transcript_content.updateGeometry()
        self._follow_bottom = True
        # 다른 대화를 펼쳤다. 앞 대화의 질문 띠지는 남기지 않는다.
        if not self._streaming:
            self._hide_question_banner()
        if self._messages:
            self.transcript_scroll.verticalScrollBar().setValue(
                self.transcript_scroll.verticalScrollBar().maximum()
            )
        else:
            self.transcript_scroll.verticalScrollBar().setValue(0)
        self._sync_question_banner_visibility()

    @staticmethod
    def _copy_stored_message(message) -> list:
        """저장본에서 역할·글·도구 기록만 가져와 화면에 다시 붙인다."""
        copied: list = [str(message[0]), str(message[1])]
        extra = message[2] if len(message) >= 3 and isinstance(message[2], dict) else {}
        tools = extra.get("tools")
        if isinstance(tools, list) and tools:
            copied.append({"tools": [str(item) for item in tools if str(item)]})
        return copied

    @staticmethod
    def _tools_on(message) -> list[str]:
        extra = message[2] if len(message) >= 3 and isinstance(message[2], dict) else {}
        tools = extra.get("tools")
        if not isinstance(tools, list):
            return []
        return [str(item) for item in tools if str(item)]

    @staticmethod
    def _set_message_tools(message, tools: list[str]) -> None:
        cleaned = [str(item) for item in tools if str(item)]
        if not cleaned:
            if len(message) >= 3:
                del message[2:]
            return
        extra = {"tools": cleaned}
        if len(message) >= 3:
            message[2] = extra
        else:
            message.append(extra)

    def _render_saved_messages(self) -> None:
        self._reveal_timer.stop()
        self._current_ai_label = None
        self._current_status = None
        self._current_tool_log = None
        self._clear_transcript_widgets()
        stream = self._visible_stream()
        live = stream is not None
        last_index = len(self._messages) - 1
        for index, message in enumerate(self._messages):
            role = str(message[0])
            text = str(message[1])
            if role == "user":
                self._latest_user_bubble = self._make_user_bubble(text)
                self._insert_bubble(self._latest_user_bubble)
            elif role == "ai":
                column, label, status, tool_log = self._make_ai_bubble(text)
                label.raw_text = text
                if live and index == last_index:
                    # 이 답은 아직 돌고 있다. 진행줄·도구 기록을 다시
                    # 붙이고 타자기도 이어서 돌린다.
                    self._current_ai_label = label
                    self._current_status = status
                    self._current_tool_log = tool_log
                    self._revealed_chars = len(text)
                    status.start()
                    self._redraw_tool_log()
                    self._refresh_status_line()
                    self._reveal_timer.start(self._REVEAL_INTERVAL_MS)
                else:
                    status.hide()
                    # 저장해 둔 대화를 다시 펼칠 때도 끝난 답이므로
                    # 같은 완료 표시를 남긴다.
                    self._paint_tool_log(
                        tool_log,
                        self._tools_on(message),
                        highlight_last=False,
                        finished=True,
                    )
                    self._show_used_articles(column, text)
                self._insert_bubble(column)
            elif role == "error":
                self._insert_bubble(self._make_error_bubble(text))
        if live:
            question = next(
                (
                    str(message[1])
                    for message in reversed(self._messages)
                    if message[0] == "user"
                ),
                "",
            )
            self._banner_question = " ".join(question.split())
            self.question_banner.setToolTip(self._banner_question)
        else:
            self._hide_question_banner()
        self._update_hint()
        # 위젯 제거와 새 레이아웃 계산이 끝난 다음, 긴 대화의 높이가 짧은
        # 대화에 남지 않도록 실제 내용 크기로 한 번 더 맞춘다.
        QTimer.singleShot(0, self._fit_transcript_extent)

    def reset_conversation(self) -> None:
        """지금 보고 있는 본문으로 대화를 새로 연다."""
        self._persist_current_chat()
        self._close_session()
        self._context = ""
        self._context_label = ""
        self._messages.clear()
        if self._active_provider_name:
            self._active_chat_ids[self._active_provider_name] = ""
        self._current_ai_label = None
        self._reveal_timer.stop()
        self._clear_transcript_widgets()
        self._update_hint()
        self._save_active_provider_state()
        self._refresh_chat_history()
        self._set_status("본문을 다시 읽어 새 대화를 시작합니다.")

    def _gather_context(self) -> None:
        """세션을 새로 열기 전에 열어 둔 본문이 있으면 미리 읽어 둔다.

        본문이 없어도 검색 도구가 있으면 대화는 된다. 그래서 여기서는
        막지 않고 상태줄에만 무엇을 근거로 삼는지 적어 둔다.
        """
        if self._context.strip() or self.context_source is None:
            return
        text, label = self.context_source()
        if text.strip():
            self._context = text
            self._context_label = label

    def _oc_key(self) -> str:
        return self.oc_provider().strip() if self.oc_provider else ""

    def _current_provider(self) -> LlmProvider | None:
        provider_class = self._provider_class()
        model_id = self.model_combo.currentData()
        if provider_class is None or model_id is None:
            return None
        return provider_class(self.key_input.text(), str(model_id))

    def _close_session(self) -> None:
        session = self._session
        self._session = None
        if session is not None:
            session.close()

    def _send(self) -> None:
        if self._active_provider_name in self._streams:
            # 같은 AI에게 두 가지를 동시에 물을 수는 없다. 다른 탭은
            # 각자 따로 도니까 기다릴 필요가 없다.
            self._set_status(
                f"{_provider_label(self._active_provider_name)}는 "
                "답하는 중입니다. 다른 AI 탭에서는 바로 물어볼 수 있습니다."
            )
            return
        message = self.input_edit.toPlainText().strip()
        if not message:
            return
        provider_class = self._provider_class()
        if (
            provider_class is not None
            and provider_class.requires_api_key
            and not self.key_input.text().strip()
        ):
            self._set_status(
                "API 키를 먼저 넣으세요. [발급]으로 받을 수 있습니다."
            )
            return
        if getattr(self, "embedded_chat_pages", None) is not None:
            # 목록에서 입력한 질문은 선택 중인 과거 대화에 덧붙이지 않는다.
            # 입력 내용은 reset_conversation이 건드리지 않으므로 그대로 보낸다.
            self._prepare_embedded_history_send()
        # 이전 질문이 실패했으면 그 안내가 다음 질문에도 남아 헷갈린다.
        self._set_status("")
        if self._session is None:
            self._gather_context()
            oc_key = self._oc_key()
            if not self._context.strip() and not oc_key:
                self._set_status(
                    "본문을 가져오거나, 위쪽 API 인증키 칸에 법제처 OC "
                    "키를 넣어야 검색할 수 있습니다."
                )
                return
            provider = self._current_provider()
            if provider is None:
                self._set_status("쓸 모델을 고르세요.")
                return
            session_context = self._context
            if self._messages:
                previous = "\n".join(
                    f"{'사용자' if message[0] == 'user' else 'AI'}: {message[1]}"
                    for message in self._messages
                    if message[0] in {"user", "ai"} and str(message[1]).strip()
                )
                if previous:
                    session_context += (
                        "\n\n[이전에 저장된 이 AI의 대화]\n"
                        + previous[-30000:]
                    )
            try:
                self._session = provider.start_chat(
                    session_context,
                    oc_key=oc_key,
                    law_cache=self.document_cache,
                )
            except LlmError as error:
                self._set_status(str(error))
                return
            if self._context.strip():
                self._set_status(
                    f"{self._context_label} 본문 {len(self._context):,}자를 "
                    "근거로 이야기합니다."
                    + (" 필요하면 다른 법령도 직접 찾습니다." if oc_key else "")
                )
            elif oc_key:
                self._set_status(
                    "법제처 자료를 직접 찾아 답합니다."
                )

        self.input_edit.clear()
        self._append_user(message)
        self._begin_answer()
        self._set_busy(True)

        # 어느 제공자의 답인지를 신호마다 묶어 둔다. 여러 답이 동시에
        # 돌아도 각자 제 대화 목록에만 글자를 쌓게 하는 장치다.
        name = self._active_provider_name
        worker = ChatWorker(self._session, message, name)
        thread = QThread(self)
        stream = self._streams[name]
        stream["worker"] = worker
        stream["thread"] = thread
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        self._wire_answer_worker(worker)
        thread.start()

    def _wire_answer_worker(self, worker: ChatWorker) -> None:
        """답 신호를 이 패널에 잇는다.

        반드시 이 패널의 메서드에 그대로 이어야 한다. partial이나
        lambda로 감싸면 받는 QObject가 없어 PySide6가 직접 연결로 잇고,
        그러면 아래 슬롯이 작업 스레드에서 돈다. 말풍선을 만들고 타이머를
        멈추는 일이 거기서 벌어지면 Qt가 프로그램을 통째로 끝낸다.
        """
        worker.chunk.connect(self._append_chunk_for)
        worker.progress.connect(self._progress_for)
        worker.failed.connect(self._failure_for)
        worker.finished.connect(self._answer_finished)

    # ---------------------------------------------------------------- 말풍선
    #
    # 진짜 QWidget을 하나씩 쌓아 그린다. Qt의 리치텍스트(QTextDocument)는
    # border-radius를 읽지 않아 HTML로는 말풍선이 끝까지 각지게 나온다
    # (실측 확인함). QSS의 border-radius는 실제 위젯에만 먹으므로, 메시지
    # 하나마다 QFrame/QLabel을 만들어 레이아웃에 넣는다.
    #
    # 답이 흘러오는 동안 위젯을 매 조각마다 새로 만들면 느리므로, AI 쪽은
    # 라벨 하나를 만들어 두고 텍스트만 갈아 끼운다.
    #
    # 도착한 글자를 다 보여 주지 않고 일정 속도로 풀어서, 네트워크 조각이
    # 크든 작든 진짜 채팅처럼 한 글자씩 나오게 한다.
    _REVEAL_INTERVAL_MS = 16
    _REVEAL_CHARS_PER_TICK = 2
    _BUBBLE_MAX_WIDTH = 480
    # 바닥에서 이만큼 안쪽까지는 "바닥에 있다"로 본다. 휠을 굴려
    # 끝까지 내리면 대개 딱 맞아떨어지지만, 부드러운 스크롤은 몇
    # 픽셀을 남기고 멈추기도 한다.
    _BOTTOM_STICKY_PX = 6
    # 글이 이만큼 멎으면 스크롤 범위를 다시 잰다.
    _FOLLOW_SETTLE_MS = 120
    # 띠지 글자 오른쪽에 남기는 여백.
    _BANNER_TEXT_PAD_PX = 22
    # 말풍선을 대화창 가장자리에서 띄우는 거리.
    _BANNER_EDGE_PX = 8

    # 목록의 글자가 시작하는 자리와, 한 단계 더 들어갈 때의 폭.
    _LIST_LEFT_PX = 20
    _LIST_STEP_PX = 14
    # 표 선과 머리줄 바탕. 대화창 색과 같은 계열로 맞춘다.
    _TABLE_BORDER = "#cfdbe6"
    _TABLE_HEAD_BG = "#eef4f9"
    _TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
    # 머리줄과 본문을 가르는 줄. 하이픈이 하나는 있어야 표로 본다.
    _TABLE_DIVIDER = re.compile(r"^\s*\|[\s:|-]*-[\s:|-]*\|\s*$")

    @staticmethod
    def _table_cells(line: str) -> list[str]:
        body = line.strip()
        if body.startswith("|"):
            body = body[1:]
        if body.endswith("|"):
            body = body[:-1]
        return [cell.strip() for cell in body.split("|")]

    @staticmethod
    def _table_at(lines: list[str], start: int) -> tuple[str, int] | None:
        """마크다운 표를 진짜 표로 바꾼다. 표가 아니면 None.

        모델은 | 번호 | 용도 | 처럼 GFM 표로 답한다. 그대로 두면 세로
        막대가 그대로 보이고 칸이 안 맞아 읽기 어렵다.
        """
        if start + 1 >= len(lines):
            return None
        if not AiChatPanel._TABLE_ROW.match(lines[start]):
            return None
        if not AiChatPanel._TABLE_DIVIDER.match(lines[start + 1]):
            return None
        header = AiChatPanel._table_cells(lines[start])
        if not header:
            return None
        aligns: list[str] = []
        for cell in AiChatPanel._table_cells(lines[start + 1]):
            left = cell.startswith(":")
            right = cell.endswith(":")
            aligns.append(
                "center" if left and right else "right" if right else "left"
            )
        aligns += ["left"] * (len(header) - len(aligns))
        rows: list[list[str]] = []
        index = start + 2
        while index < len(lines) and AiChatPanel._TABLE_ROW.match(lines[index]):
            rows.append(AiChatPanel._table_cells(lines[index]))
            index += 1
        border = AiChatPanel._TABLE_BORDER
        head_html = "".join(
            f'<td align="{align}" style="border:1px solid {border}; '
            f'background-color:{AiChatPanel._TABLE_HEAD_BG}; color:#173b63; '
            f'font-weight:700;">{cell or "&nbsp;"}</td>'
            for cell, align in zip(header, aligns)
        )
        body_html: list[str] = []
        for row in rows:
            filled = (row + [""] * len(header))[: len(header)]
            body_html.append(
                "<tr>"
                + "".join(
                    f'<td align="{align}" style="border:1px solid {border};">'
                    f'{cell or "&nbsp;"}</td>'
                    for cell, align in zip(filled, aligns)
                )
                + "</tr>"
            )
        # Qt는 <table>에 준 margin을 무시하고, 표 아래쪽 여백도 먹지
        # 않는다. 위는 바깥 <div>로, 아래는 낮은 빈 줄 하나로 띄운다.
        html = (
            '<div style="margin:10px 0 0 0;">'
            '<table width="100%" cellspacing="0" cellpadding="5" '
            'style="border-collapse:collapse;">'
            f"<tr>{head_html}</tr>{''.join(body_html)}</table></div>"
            '<div style="font-size:5px; line-height:5px;">&nbsp;</div>'
        )
        return html, index - start

    @staticmethod
    def _to_html(text: str) -> str:
        """모델이 쓰는 마크다운을 최소한만 사람이 읽기 좋게 바꾼다.

        완전한 마크다운 변환기는 필요 없다. 답에 실제로 나오는 굵은 글씨,
        머리글, 글머리·번호 목록만 처리해도 읽기가 크게 나아진다. 먼저
        escape 하므로 본문에 든 꺾쇠가 태그로 새지 않는다.
        """
        escaped = escape(text)
        lines = escaped.split("\n")
        # (블록인가, 글) 짝으로 모은다. <div>로 만든 목록 줄은 그 자체로
        # 줄을 바꾸는 블록이라 <br>를 또 붙이면 한 줄이 더 빈다.
        entries: list[tuple[bool, str]] = []
        # 목록 줄 바로 뒤에 붙는 설명 문단은 그 항목의 글자 자리에 맞춘다.
        # 0이면 지금 목록 안이 아니라는 뜻이다.
        list_left = 0
        index = 0
        while index < len(lines):
            line = lines[index]
            stripped = line.strip()
            table = AiChatPanel._table_at(lines, index)
            if table is not None:
                html, used = table
                entries.append((True, html))
                index += used
                list_left = 0
                continue
            index += 1
            if stripped.startswith("#"):
                list_left = 0
                heading = stripped.lstrip("#").strip()
                entries.append(
                    (
                        False,
                        f'<b style="color:#173b63;">{heading}</b>'
                        if heading
                        else "",
                    )
                )
                continue
            circled = re.match(r"^([①-⑳])\s+(.*)$", stripped)
            if circled:
                list_left = 0
                top = 4 if not entries else 14
                entries.append(
                    (
                        True,
                        f'<div style="margin:{top}px 0 6px 0; font-weight:700; '
                        f'color:#173b63;">{circled.group(1)} {circled.group(2)}</div>',
                    )
                )
                continue
            if stripped.startswith("근거:"):
                list_left = 0
                entries.append(
                    (
                        True,
                        f'<div style="margin:2px 0 10px 0; font-size:12px; '
                        f'color:#5a6a7a;">{stripped}</div>',
                    )
                )
                continue
            # 원문 공백 수를 그대로 px로 쓰면, 모델이 두 칸을 들여쓸 때와
            # 네 칸을 들여쓸 때 같은 단계가 다른 자리에 놓인다. 몇 칸을
            # 썼든 단계로 바꿔 세면 한 답 안에서 줄이 가지런해진다.
            indent = len(line) - len(line.lstrip(" "))
            step = AiChatPanel._LIST_STEP_PX * min(indent // 2, 3)
            if stripped.startswith(("* ", "- ", "• ")):
                left = AiChatPanel._LIST_LEFT_PX + step
                list_left = left
                entries.append(
                    (
                        True,
                        f'<div style="margin:3px 0; margin-left:{left}px; '
                        f'text-indent:-12px;">• {stripped[2:]}</div>',
                    )
                )
                continue
            numbered = re.match(r"^(\d+)\.\s+(.*)$", stripped)
            if numbered:
                left = AiChatPanel._LIST_LEFT_PX + step
                list_left = left
                entries.append(
                    (
                        True,
                        f'<div style="margin:3px 0; margin-left:{left}px; '
                        f'text-indent:-16px;">'
                        f"{numbered.group(1)}. {numbered.group(2)}</div>",
                    )
                )
                continue
            if not stripped:
                list_left = 0
                entries.append((False, line))
                continue
            if list_left:
                # 항목에 이어지는 설명을 왼쪽 끝까지 되돌리면 목록이
                # 거기서 끊긴 것처럼 보인다. 그 항목 글자 아래에 붙인다.
                entries.append(
                    (
                        True,
                        f'<div style="margin:2px 0; margin-left:{list_left}px;">'
                        f"{stripped}</div>",
                    )
                )
                continue
            entries.append((False, line))

        # 블록 옆에는 <br>를 넣지 않는다. 예전에는 목록 한 줄마다 <br>가
        # 덧붙고, 모델이 항목 사이에 넣은 빈 줄까지 겹쳐 두 줄씩 벌어졌다.
        # 잇따른 빈 줄은 하나로 줄여 문단 사이만 한 줄 띄운다.
        chunks: list[str] = []
        previous_blank = False
        for index, (block, html) in enumerate(entries):
            if not block and not html:
                if previous_blank or not chunks:
                    continue
                previous_blank = True
            else:
                previous_blank = False
            if index and not block and not entries[index - 1][0]:
                chunks.append("<br>")
            chunks.append(html)
        joined = "".join(chunks)
        bolded = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", joined)
        current_name, current_id = AiChatPanel._law_context_from_answer(text)
        # 모델은 [법령명 제N조](law:법령ID:조번호)로 쓴다. 화면의 조항호목
        # 팝업과 같은 lawref:// 주소로 바꿔야 별도 파서 없이 그 팝업이 연다.
        cited = re.sub(
            r"\[([^\]]+)\]\(((?:law|doc):[^)]+)\)",
            lambda match: AiChatPanel._citation_anchor(
                match.group(1),
                match.group(2),
                related_name=current_name,
            ),
            bolded,
        )
        # 모델이 마크다운 링크를 빠뜨린 `법 제N조`·`시행령 제N조`·`제N조`도
        # 본문 화면과 같은 규칙으로 링크로 바꾼다. 이미 <a>가 된 인용은
        # 다시 건드리지 않는다.
        return AiChatPanel._linkify_plain_articles(
            cited,
            current_law_name=current_name,
            current_law_id=current_id,
        )

    @staticmethod
    def _law_context_from_answer(text: str) -> tuple[str, str]:
        """답에서 기준 법령명과 ID를 고른다. 마크다운 인용이 있으면 그걸 쓴다."""
        first_name = ""
        first_id = ""
        for match in re.finditer(
            r"\[([^\]]+)\]\(law:([^:)]+):[^)]+\)",
            text,
        ):
            label = match.group(1).strip()
            if AiChatPanel._ANNEX_LABEL.search(label):
                continue
            name = re.sub(r"\s*제\d+조.*$", "", label).strip()
            law_id = match.group(2).strip()
            if name and law_id:
                first_name = name
                first_id = law_id
                break
        if first_name:
            return first_name, first_id
        for match in re.finditer(r"「([^」]+)」", text):
            name = match.group(1).strip()
            if name and not AiChatPanel._ANNEX_LABEL.search(name):
                return name, ""
        return "", ""

    _SPACED_ARTICLE_UNITS = re.compile(
        r"(제\d+조(?:의\d+)?)"
        rf"((?:\s+제\d+항(?:의\d+)?)?(?:\s+제\d+호(?:의\d+)?)?(?:\s+[{KOREAN_ITEM_MARKERS}]목)?)"
    )

    @staticmethod
    def _squeeze_spaced_law_units(text: str) -> str:
        """채팅에서만 `제27조 제4항`을 법령 원문처럼 붙여 한 링크로 만든다.

        본문 화면 정규식은 건드리지 않는다. `제1조 제2조`처럼 조가 이어지면
        붙이지 않는다.
        """

        def join_units(match: re.Match[str]) -> str:
            tail = re.sub(r"\s+", "", match.group(2))
            return match.group(1) + tail

        return AiChatPanel._SPACED_ARTICLE_UNITS.sub(join_units, text)

    @staticmethod
    def _linkify_plain_articles(
        html: str,
        *,
        current_law_name: str,
        current_law_id: str,
    ) -> str:
        """이미 만든 <a> 밖의 평문 조항만 본문과 같은 규칙으로 링크로 바꾼다."""
        parts = re.split(r"(<[^>]+>)", html)
        in_anchor = False
        last_law = current_law_name
        out: list[str] = []
        for part in parts:
            if part.startswith("<"):
                lowered = part[:4].lower()
                if lowered.startswith("<a ") or lowered == "<a>":
                    in_anchor = True
                elif lowered.startswith("</a"):
                    in_anchor = False
                out.append(part)
                continue
            if in_anchor:
                named = re.search(r"「([^」]+)」", unescape(part))
                if named:
                    last_law = named.group(1).strip()
                out.append(part)
                continue
            if not part:
                out.append(part)
                continue
            raw = unescape(part)
            linked = law_reference_html_text(
                AiChatPanel._squeeze_spaced_law_units(raw),
                (),
                current_law_name=last_law,
                current_law_id=(
                    current_law_id if last_law == current_law_name else ""
                ),
                use_api_links=True,
            )
            named = re.search(r"「([^」]+)」", raw)
            if named:
                last_law = named.group(1).strip()
            out.append(linked)
        return "".join(out)

    @staticmethod
    def _citation_anchor(
        label: str, target: str, *, related_name: str = ""
    ) -> str:
        href = AiChatPanel._citation_to_href(
            unescape(label), target, related_name=related_name
        )
        raw_label = unescape(label)
        if target.startswith("law:"):
            shown_label = display_citation_label(raw_label)
        else:
            shown_label = raw_label
            if shown_label and not shown_label.startswith("「"):
                shown_label = f"「{shown_label.strip('「」')}」"
        return (
            f'<a href="{escape(href, quote=True)}" style="color:#1768aa; '
            f'text-decoration:none; border-bottom:1px dotted #1768aa;">'
            f"{escape(shown_label)}</a>"
        )

    _ANNEX_LABEL = re.compile(r"별표|별지|서식|양식")
    _ANNEX_DOC_CATEGORIES = ("licbyl", "admbyl", "ordinbyl")

    @staticmethod
    def _annex_href(label: str, target: str, related_name: str = "") -> str:
        """별표·별지서식 인용은 조문 팝업이 아니라 별표 원문으로 연다."""
        raw = str(label or "").strip()
        category = ""
        item_id = ""
        law_id = ""
        if target.startswith("doc:"):
            _, _, rest = target.partition(":")
            category, _, item_id = rest.partition(":")
            category = category.strip()
            item_id = item_id.strip()
            if category not in AiChatPanel._ANNEX_DOC_CATEGORIES:
                return ""
        elif target.startswith("law:") and AiChatPanel._ANNEX_LABEL.search(raw):
            category = "licbyl"
            _, _, rest = target.partition(":")
            law_id, _, _ = rest.partition(":")
            law_id = law_id.strip()
        else:
            return ""
        related = (
            annex_related_law_name(raw)
            or str(related_name or "").strip()
            or lookup_cached_document_label(law_id)
        )
        parameters = [f"name={quote(raw, safe='')}"]
        if category:
            parameters.append(f"category={quote(category, safe='')}")
        if item_id:
            parameters.append(f"id={quote(item_id, safe='')}")
        if related:
            parameters.append(f"related={quote(related, safe='')}")
        return f"annexref://open?{'&'.join(parameters)}"

    @staticmethod
    def _citation_to_href(
        label: str, target: str, related_name: str = ""
    ) -> str:
        """AI 인용을 본문 화면과 같은 lawref:// 조항호목 링크로 바꾼다."""
        annex = AiChatPanel._annex_href(
            label, target, related_name=related_name
        )
        if annex:
            return annex
        if target.startswith("doc:"):
            category, item_id = split_doc_reference(target)
            if is_inquiry_target(category) and item_id:
                return f"doc:{category}:{item_id}"
            return target
        if not target.startswith("law:"):
            return target
        label = AiChatPanel._squeeze_spaced_law_units(label)
        _, _, rest = target.partition(":")
        law_id, _, jo = rest.partition(":")
        name = re.sub(r"\s*제\d+조.*$", "", label).strip() or label
        unit = LAW_UNIT_REFERENCE_PATTERN.search(label)
        jo_number = (unit.group("jo") if unit else "") or ""
        jo_branch = (unit.group("jo_branch") if unit else "") or ""
        hang = (unit.group("hang") if unit else "") or ""
        hang_branch = (unit.group("hang_branch") if unit else "") or ""
        ho = (unit.group("ho") if unit else "") or ""
        ho_branch = (unit.group("ho_branch") if unit else "") or ""
        mok = (unit.group("mok") if unit else "") or ""
        if not jo_number and jo:
            try:
                code = normalize_article_jo(jo)
                jo_number = str(int(code[:4]))
                branch = int(code[4:])
                if branch and not jo_branch:
                    jo_branch = str(branch)
            except ValueError:
                jo_number = jo.lstrip("0") or jo
        parameters = []
        if name:
            parameters.append(f"name={quote(name, safe='')}")
        if law_id:
            parameters.append(f"id={quote(law_id, safe='')}")
        if jo_number:
            parameters.append(f"jo={quote(jo_number, safe='')}")
        if jo_branch:
            parameters.append(f"jo_branch={quote(jo_branch, safe='')}")
        if hang:
            parameters.append(f"hang={quote(hang, safe='')}")
        if hang_branch:
            parameters.append(f"hang_branch={quote(hang_branch, safe='')}")
        if ho:
            parameters.append(f"ho={quote(ho, safe='')}")
        if ho_branch:
            parameters.append(f"ho_branch={quote(ho_branch, safe='')}")
        if mok:
            parameters.append(f"mok={quote(mok, safe='')}")
        return f"lawref://open?{'&'.join(parameters)}"

    def _update_hint(self) -> None:
        if self.standalone:
            hint = (
                "법령ㆍ행정규칙ㆍ자치법규를 물어보면 법제처 자료에서 직접 "
                "찾아 답합니다. 이 프로그램 자료에 없는 내용은 지어내지 "
                "않습니다."
            )
        else:
            hint = (
                "지금 보고 있는 본문을 근거로 답합니다. 본문에서 일부만 "
                "드래그해 두면 그 부분만 근거로 삼습니다. 다른 법령이 "
                "필요하면 직접 찾아봅니다."
            )
        self.transcript_hint.setText(hint)
        empty = not self._messages
        self.transcript_hint.setVisible(empty)
        self.transcript_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            if empty
            else Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

    def _insert_bubble(self, widget: QWidget) -> None:
        self.transcript_layout.addWidget(widget)

    def _make_user_bubble(self, text: str) -> QWidget:
        row = QWidget()
        # 이름을 줘야 대화 영역과 같은 흰 바탕을 QSS로 지정할 수 있다.
        # 안 주면 시스템 기본 회색이 그대로 나와 말마다 회색 띠가 생긴다.
        row.setObjectName("aiChatRow")
        row.setMinimumWidth(0)
        row.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 6, 0, 2)
        row_layout.addStretch(1)

        bubble = QFrame()
        bubble.setObjectName("aiChatBubbleUser")
        bubble.setMaximumWidth(self._BUBBLE_MAX_WIDTH)
        bubble.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred
        )
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(14, 9, 14, 9)
        label = QLabel(self._to_html(text) or "&nbsp;")
        label.setObjectName("aiChatUserText")
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setFont(QFont(FONT_FAMILY, _CHAT_FONT_POINT))
        label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        bubble_layout.addWidget(label)

        row_layout.addWidget(bubble, 0)
        return row

    # 답을 기다리는 동안 보여 줄 자리표시자. 도구를 여러 번 부르는
    # 질문은 답이 오기까지 몇십 초씩 걸릴 수 있어서, 이게 없으면 멈춘
    # 것과 구분이 안 된다는 것을 실제로 겪었다.
    _THINKING_FALLBACK = "찾는 중"

    def _placeholder_html(self) -> str:
        """답이 아직 안 왔을 때 답변 자리에 넣을 것.

        진행 상황은 위의 진행줄이 맡으므로 여기는 비워 둔다. 빈 문자열을
        넣으면 줄 높이가 0이 되어 답이 오는 순간 화면이 튄다.
        """
        return "&nbsp;"

    def _make_ai_bubble(
        self, text: str
    ) -> tuple[QWidget, QLabel, ShimmerLabel, QLabel]:
        column = QWidget()
        column.setObjectName("aiChatRow")
        column.setMinimumWidth(0)
        column.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        column_layout = QVBoxLayout(column)
        column_layout.setContentsMargins(0, 10, 0, 8)
        column_layout.setSpacing(4)

        # 답보다 먼저 뜨는 줄. 몇 초가 지났고 무엇을 하는 중인지 여기서만
        # 알린다. 답이 나오기 시작해도 남겨 두어, 다 끝난 뒤에는 얼마나
        # 걸렸는지와 사용량이 그대로 남는다.
        status = ShimmerLabel()
        status.setObjectName("aiChatProgress")
        status.setFont(QFont(FONT_FAMILY, 8))
        # 레이아웃에 넣어 부모가 생긴 뒤에 보이게 한다. 부모 없는 위젯에
        # setVisible(True)를 부르면 Qt가 그것을 독립 창으로 띄우기 때문에,
        # 답을 시작할 때마다 빈 창이 깜빡였다가 사라졌다.
        column_layout.addWidget(status)
        status.setVisible(not text)

        # 어떤 도구로 무엇을 찾았는지 지나간 것까지 쌓아 둔다. 진행줄은
        # 덮어쓰기라 마지막 하나만 남는데, 답의 근거를 되짚으려면 무엇을
        # 거쳐 왔는지가 남아 있어야 한다.
        tool_log = QLabel()
        tool_log.setObjectName("aiChatToolLog")
        tool_log.setFont(QFont(FONT_FAMILY, 8))
        tool_log.setWordWrap(True)
        tool_log.setMinimumWidth(0)
        tool_log.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum
        )
        tool_log.setTextFormat(Qt.TextFormat.RichText)
        tool_log.setVisible(False)
        column_layout.addWidget(tool_log)

        label = QLabel(self._to_html(text) if text else self._placeholder_html())
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setFont(QFont(FONT_FAMILY, _CHAT_FONT_POINT))
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        # 마우스로 드래그해 고를 수 있게 하면서, 조문 링크(제N조)도 함께
        # 눌러야 하므로 두 상호작용을 같이 켠다.
        label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        label.setOpenExternalLinks(False)
        label.linkActivated.connect(self._article_link_clicked)
        column_layout.addWidget(label)

        # 검토 결과를 보고서에 옮겨 적는 일이 잦아서, 드래그해 고르는
        # 수고를 덜도록 답변 아래에 복사 자리를 둔다.
        copy_button = QPushButton("복사")
        copy_button.setObjectName("aiChatCopyLink")
        copy_button.setFlat(True)
        copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_button.clicked.connect(lambda: self._copy_message(label))
        copy_row = QHBoxLayout()
        copy_row.setContentsMargins(0, 0, 0, 0)
        copy_row.addWidget(copy_button)
        copy_row.addStretch(1)
        column_layout.addLayout(copy_row)
        return column, label, status, tool_log

    def _make_error_bubble(self, text: str) -> QWidget:
        label = QLabel(escape(text))
        label.setObjectName("aiChatErrorText")
        label.setWordWrap(True)
        label.setFont(QFont(FONT_FAMILY, 9))
        label.setContentsMargins(0, 8, 0, 2)
        return label

    def _copy_message(self, label: QLabel) -> None:
        # 원문은 툴팁이 아니라 보이지 않는 속성에 얹어 둔다. 툴팁에
        # 두면 마우스를 올릴 때마다 이미 화면에 있는 글을 그대로
        # 팝업으로 또 보여 줘서 거슬린다.
        QApplication.clipboard().setText(getattr(label, "raw_text", "") or label.text())
        self._set_status("답변을 클립보드에 복사했습니다.")

    def _article_link_clicked(self, href: str) -> None:
        """답변 속 조문·문서 링크를 본문 화면의 팝업으로 연다."""
        url = QUrl(href)
        scheme = url.scheme()
        if scheme in {"lawref", "doc", "annexref"}:
            if self.reference_handler is None:
                self._set_status(
                    "조문 참조를 열 법령검색 화면을 찾지 못했습니다."
                )
                return
            self.reference_handler(url)
            return
        if scheme == "law" and self.reference_handler is not None:
            # 예전에 그려 둔 law:ID:JO 링크도 같은 팝업으로 보낸다.
            self.reference_handler(
                QUrl(self._citation_to_href("", href))
            )

    # --- 질문 띠지 ---------------------------------------------------
    def eventFilter(self, watched, event):  # noqa: N802 (Qt 규약)
        if watched is self.transcript_scroll.viewport() and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Show,
        ):
            self._sync_question_banner_visibility()
        return super().eventFilter(watched, event)

    def _place_question_banner(self) -> None:
        """띠지를 대화창 맨 위에 폭 가득 놓고, 글이 넘치면 줄여 적는다."""
        if not self.question_banner.isVisible():
            return
        viewport = self.transcript_scroll.viewport()
        margin = self._BANNER_EDGE_PX
        width = max(0, viewport.width() - margin * 2)
        self.question_banner.setGeometry(
            margin,
            margin,
            width,
            self.question_banner.sizeHint().height(),
        )
        self.question_banner.raise_()
        room = max(
            0,
            self.question_banner.width()
            - self.question_banner_label.x()
            - self._BANNER_TEXT_PAD_PX,
        )
        metrics = QFontMetrics(self.question_banner_label.font())
        self.question_banner_label.setText(
            metrics.elidedText(
                self._banner_question, Qt.TextElideMode.ElideRight, room
            )
        )

    def _show_question_banner(self, question: str) -> None:
        text = " ".join(str(question or "").split())
        if not text:
            return
        self._banner_question = text
        self.question_banner.setToolTip(text)
        self._sync_question_banner_visibility()

    def _sync_question_banner_visibility(self) -> None:
        """최신 질문 말풍선이 위로 완전히 사라졌을 때만 띠지를 보인다."""
        bubble = self._latest_user_bubble
        if (
            not self._streaming
            or not self._banner_question
            or bubble is None
            or bubble.parentWidget() is None
        ):
            self.question_banner.hide()
            return

        viewport = self.transcript_scroll.viewport()
        # 말풍선의 아랫부분이 조금이라도 화면에 남아 있으면 같은 질문을
        # 두 번 보여 주지 않는다. 답이 쌓여 말풍선 전체가 위로 벗어난
        # 순간부터만 띠지가 그 자리를 대신한다.
        bubble_bottom = bubble.mapTo(viewport, bubble.rect().bottomLeft()).y()
        if bubble_bottom > 0:
            self.question_banner.hide()
            return
        self.question_banner.show()
        self._place_question_banner()

    def _release_question_banner(self) -> None:
        """답이 끝나면 질문 띠지와 그 표시 상태를 정리한다."""
        self._hide_question_banner()

    def _hide_question_banner(self) -> None:
        self._banner_question = ""
        self.question_banner.hide()

    def _transcript_at_bottom(self) -> bool:
        bar = self.transcript_scroll.verticalScrollBar()
        return bar.maximum() - bar.value() <= self._BOTTOM_STICKY_PX

    def _transcript_scrolled(self, _value: int) -> None:
        """손으로 올리면 따라가기를 놓고, 바닥으로 돌아오면 다시 잡는다.

        답이 흐르는 동안 글이 쌓이면 스크롤 범위만 늘고 값은 그대로라
        이 신호가 울리지 않는다. 그래서 여기서 바꾼 상태는 사용자가
        실제로 스크롤을 움직였을 때의 뜻 그대로 남는다.
        """
        self._follow_bottom = self._transcript_at_bottom()
        self._sync_question_banner_visibility()

    def _scroll_to_bottom(self) -> None:
        """바닥으로 내린다. 사용자가 올려 둔 것도 무시하고 내린다.

        질문을 보냈을 때처럼 사용자가 방금 무언가를 한 자리에서만 쓴다.
        """
        self._follow_bottom = True
        # 레이아웃이 이번 이벤트 루프 안에서 아직 새 높이를 확정하지
        # 않았을 수 있어 한 틱 늦춰서 끝까지 내린다. 두 번째 인자로 이
        # 패널을 넘기면, 그 사이에 패널이 닫혀도 예약이 함께 사라진다.
        QTimer.singleShot(0, self, self._apply_forced_scroll)

    def _apply_forced_scroll(self) -> None:
        # 방금 끼운 말풍선의 높이가 아직 안 잡혀 있으면 maximum이 작게
        # 나와, 끝까지 내렸는데도 새 말풍선이 화면 밖에 남는다.
        self.transcript_layout.activate()
        self.transcript_content.adjustSize()
        self._follow_bottom = True
        bar = self.transcript_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        self._sync_question_banner_visibility()

    def _follow_to_bottom(self) -> None:
        """답이 흐르는 동안 쓰는 자동 내림. 올려 읽는 중이면 안 건드린다."""
        if not self._follow_bottom or self._follow_pending:
            return
        self._follow_pending = True
        QTimer.singleShot(0, self, self._apply_follow_scroll)

    def _apply_follow_scroll(self) -> None:
        """한 틱 뒤에 실제로 내린다.

        예약해 둔 사이에 사용자가 위로 올렸을 수 있으므로 여기서 한 번
        더 확인한다. 이 확인이 없으면 올리자마자 예약분이 도로 끌어내려
        스크롤이 잠긴 것처럼 느껴진다.
        """
        self._follow_pending = False
        if not self._follow_bottom:
            return
        # 방금 늘어난 줄의 높이가 아직 안 잡혀 있으면 maximum이 작게
        # 나와, 끝까지 내렸는데도 마지막 줄이 화면 밖에 남는다.
        self.transcript_layout.activate()
        bar = self.transcript_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        self._sync_question_banner_visibility()
        # 스크롤 범위를 정확히 다시 재는 일(adjustSize)은 긴 대화에서
        # 한 번에 20ms 가까이 든다. 16ms마다 도는 타자기 효과에 그대로
        # 얹으면 화면이 굼떠지므로, 글이 잠깐 멎었을 때 한 번만 한다.
        self._follow_settle_timer.start(self._FOLLOW_SETTLE_MS)

    def _refit_transcript_height(self) -> None:
        """대화창 높이를 지금 들어 있는 내용에 다시 맞춘다."""
        self.transcript_layout.invalidate()
        self.transcript_layout.activate()
        self.transcript_content.adjustSize()
        self.transcript_content.updateGeometry()
        if self._follow_bottom:
            bar = self.transcript_scroll.verticalScrollBar()
            bar.setValue(bar.maximum())
        self._sync_question_banner_visibility()

    def _settle_follow_scroll(self) -> None:
        """글이 멎은 뒤 스크롤 범위를 다시 재고 바닥에 정확히 붙인다."""
        if not self._follow_bottom:
            return
        self.transcript_layout.activate()
        self.transcript_content.adjustSize()
        bar = self.transcript_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        self._sync_question_banner_visibility()

    def _append_user(self, message: str) -> None:
        self._messages.append(["user", message])
        self._update_hint()
        self._latest_user_bubble = self._make_user_bubble(message)
        self._insert_bubble(self._latest_user_bubble)
        self._scroll_to_bottom()

    def _begin_answer(self) -> None:
        question = next(
            (
                message[1]
                for message in reversed(self._messages)
                if message[0] == "user"
            ),
            "",
        )
        self._messages.append(["ai", ""])
        self._streaming = True
        self._show_question_banner(question)
        self._streams[self._active_provider_name] = {
            "messages": self._messages,
            "thread": None,
            "worker": None,
            "started_at": time.monotonic(),
            "progress": "",
            "usage": "",
            "tools": [],
            "failed": False,
        }
        self._revealed_chars = 0
        widget, label, status, tool_log = self._make_ai_bubble("")
        self._current_ai_label = label
        self._current_status = status
        self._current_tool_log = tool_log
        status.start()
        self._refresh_status_line()
        self._elapsed_timer.start()
        self._insert_bubble(widget)
        self._scroll_to_bottom()
        self._reveal_timer.start(self._REVEAL_INTERVAL_MS)

    def _show_progress(self, text: str, kind: str) -> None:
        """화면에 보이는 제공자의 진행 상황을 흘린다."""
        self._progress_for(self._active_provider_name, text, kind)

    def _progress_for(self, name: str, text: str, kind: str) -> None:
        """"법령을 검색하는 중" 같은 진행 상황을 그 답의 진행줄에 흘린다."""
        stream = self._streams.get(name)
        if stream is None:
            return
        if kind == "usage":
            # 사용량은 도중에 여러 번 갱신되어 온다. 마지막 값만 뜻이
            # 있으므로 들고 있다가 다 끝난 뒤에 한 번 보인다.
            stream["usage"] = text
            return
        if kind == "tool":
            text = self._name_documents(text)
            self._record_tool(name, text)
        stream["progress"] = text
        if name == self._active_provider_name:
            self._refresh_status_line()

    def _record_tool(self, name: str, text: str) -> None:
        """거쳐 온 도구를 한 줄씩 쌓는다."""
        stream = self._streams.get(name)
        if stream is None:
            return
        tools = stream["tools"]
        # 같은 일을 잇달아 알려 오는 경우가 있어 바로 앞과 같으면 넘긴다.
        if tools and tools[-1] == text:
            return
        tools.append(text)
        messages = stream.get("messages")
        if isinstance(messages, list) and messages and messages[-1][0] == "ai":
            self._set_message_tools(messages[-1], tools)
        if name == self._active_provider_name:
            self._redraw_tool_log()

    def _name_documents(self, text: str) -> str:
        """진행 문구의 "[문서 009294]"를 그 법령 정식 명칭으로 바꾼다.

        도구가 받는 인자에는 법령 id만 있고 이름이 없다. 검색 때 적어
        둔 이름이나 저장 본문에서 찾아
        "「산업입지 및 개발에 관한 법률」 제2조"처럼 붙인다.
        못 찾으면 숫자 id는 그리지 않는다.
        """

        def replace(match: "re.Match[str]") -> str:
            return self._document_name(match.group(1))

        named = re.sub(r"\[문서 ([^\]]+)\]", replace, text)
        named = re.sub(r" {2,}", " ", named).strip()
        named = re.sub(r":\s*$", "", named)
        prefix, sep, hint = named.partition(": ")
        if sep and hint:
            named = f"{prefix}: {display_citation_label(hint)}"
        return named

    def _document_name(self, item_id: str) -> str:
        """저장된 본문·검색 기록에서 그 id의 법령 정식 명칭을 찾는다."""
        if item_id in self._document_names:
            return self._document_names[item_id]
        name = self._lookup_document_name(item_id)
        self._document_names[item_id] = name
        return name

    def _lookup_document_name(self, item_id: str) -> str:
        cache = self.document_cache
        if cache is not None:
            for target in ("law", "admrul", "ordin"):
                try:
                    record = cache.load_for_row({"target": target, "id": item_id})
                    if record is None and target != "law":
                        record = cache.load_snapshot(
                            {"target": target, "id": item_id}
                        )
                except Exception:  # noqa: BLE001 - 이름 못 찾아도 진행줄은 떠야 한다
                    record = None
                label = self._label_from_record(record)
                if label:
                    return label
        try:
            return lookup_cached_document_label(item_id)
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _label_from_record(record: object) -> str:
        if not isinstance(record, dict):
            return ""
        row = record.get("row")
        row = row if isinstance(row, dict) else {}
        full = str(record.get("name") or row.get("name") or "").strip()
        short = str(
            row.get("short_name") or row.get("법령약칭명") or ""
        ).strip()
        return " ".join(full.split()) or " ".join(short.split())

    def _paint_tool_log(
        self,
        tool_log: QLabel | None,
        tools: list[str],
        *,
        highlight_last: bool,
        finished: bool = False,
    ) -> None:
        if tool_log is None or not tools:
            if tool_log is not None and not tools:
                tool_log.clear()
                tool_log.setVisible(False)
            return
        last = len(tools) - 1
        parts = []
        for index, item in enumerate(tools):
            line = f"· {escape(item)}"
            if highlight_last and index == last:
                line = f'<span style="color:#1768aa;">{line}</span>'
            parts.append(line)
        if finished:
            # 여기서 끝났다는 표시가 없으면, 도구를 여러 번 부른 답은
            # 기록이 중간에 멈춘 것인지 다 된 것인지 알기 어렵다.
            parts.append(
                '<span style="color:#1f7a4d; font-weight:600;">'
                "· 답변 완료</span>"
            )
        tool_log.setText(
            f'<span style="color:#8a97a6;">{"<br>".join(parts)}</span>'
        )
        tool_log.setVisible(True)

    def _redraw_tool_log(self) -> None:
        """거쳐 온 도구 기록을 현재 말풍선에 다시 써 넣는다.

        지금 하고 있는 일은 지나간 기록과 같은 회색으로 두면 어디까지
        했는지 눈으로 못 짚는다. 마지막 줄만 진행줄과 같은 파란색으로
        띄워 "여기를 읽는 중"을 표시한다.
        """
        stream = self._visible_stream()
        tools = list(stream["tools"]) if stream is not None else []
        if not tools and self._messages and self._messages[-1][0] == "ai":
            tools = self._tools_on(self._messages[-1])
        running = bool(self._streaming and stream is not None)
        self._paint_tool_log(
            self._current_tool_log,
            tools,
            highlight_last=running,
            finished=not running,
        )
        # 도구를 여러 번 부르는 질문은 답이 나오기 전 이 기록만 몇 분씩
        # 쌓인다. 답 글자에만 자동 내림을 걸어 두면 그동안 화면이 따라가지
        # 않아, 지금 무엇을 하는 중인지가 아래로 밀려 안 보인다.
        self._follow_to_bottom()

    def _refresh_status_line(self) -> None:
        """진행줄을 "12초 동안 조문을 읽는 중: 제18조"처럼 고쳐 쓴다."""
        if self._current_status is None:
            return
        stream = self._visible_stream()
        if stream is None:
            return
        seconds = int(time.monotonic() - float(stream["started_at"]))
        if self._streaming:
            doing = str(stream["progress"]) or self._THINKING_FALLBACK
            self._current_status.setText(f"{seconds}초 동안 {doing}")
            return
        # 토큰 수는 자릿수가 커서 답보다 눈에 먼저 들어온다. 줄에서는
        # 빼고, 알고 싶을 때만 볼 수 있게 툴팁으로만 남긴다.
        self._current_status.setText(f"{seconds}초 걸렸습니다")
        self._current_status.setToolTip(str(stream["usage"]))

    def _append_chunk(self, text: str) -> None:
        """화면에 보이는 제공자의 답에 글자를 쌓는다."""
        self._append_chunk_for(self._active_provider_name, text)

    def _append_chunk_for(self, name: str, text: str) -> None:
        # 다른 탭을 보고 있어도 글자는 그 답의 목록에 쌓인다. 그 탭으로
        # 돌아오면 _messages가 다시 이 목록을 가리킨다.
        stream = self._streams.get(name)
        target = stream["messages"] if stream is not None else self._messages
        if not target or target[-1][0] != "ai":
            target.append(["ai", ""])
        target[-1][1] += text
        # 보여 주는 속도는 _reveal_tick이 정한 리듬대로 계속 돈다. 여기서는
        # 도착한 글자를 쌓아 두기만 하면 된다.

    def _reveal_tick(self) -> None:
        """진짜 채팅처럼 한 글자씩 나오도록, 도착한 글자를 조금씩 보여 준다.

        네트워크로 오는 조각은 크기가 들쭉날쭉해서 그대로 그리면 뭉텅뭉텅
        나온다. 도착한 만큼을 별도 속도로 풀어 주면 타자기처럼 보인다.
        """
        if self._current_ai_label is None or not self._messages:
            self._reveal_timer.stop()
            return
        text = self._messages[-1][1]
        if not text:
            return  # 아직 도구 호출 중이라 자리표시자만 떠 있다.
        if self._revealed_chars >= len(text):
            if not self._streaming:
                self._reveal_timer.stop()
            return
        self._revealed_chars = min(
            len(text), self._revealed_chars + self._REVEAL_CHARS_PER_TICK
        )
        self._render_ai_label(text, self._revealed_chars)
        self._follow_to_bottom()

    def _render_ai_label(self, full_text: str, revealed_chars: int) -> None:
        shown = full_text[:revealed_chars]
        self._current_ai_label.setText(
            self._to_html(shown) if shown else self._placeholder_html()
        )
        # 복사 단추가 마크다운을 걷어낸 원문 그대로를 복사하도록 보이지
        # 않는 속성에 얹어 둔다. 아직 덜 보였어도 그때까지 온 전체를
        # 복사하는 게 사용자에게 더 쓸모 있다.
        self._current_ai_label.raw_text = full_text

    def _flush_render(self) -> None:
        """스트림이 끝났을 때 타자기 효과를 건너뛰고 한 번에 완성한다."""
        self._reveal_timer.stop()
        if self._current_ai_label is None or not self._messages:
            return
        text = self._messages[-1][1]
        self._revealed_chars = len(text)
        self._render_ai_label(text, self._revealed_chars)

    def _show_failure(self, message: str) -> None:
        """화면에 보이는 제공자의 답이 실패했을 때."""
        self._failure_for(self._active_provider_name, message)

    def _failure_for(self, name: str, message: str) -> None:
        stream = self._streams.get(name)
        if stream is not None:
            stream["failed"] = True
        target = stream["messages"] if stream is not None else self._messages
        shown = name == self._active_provider_name
        if shown:
            self._set_status(message)
            self._reveal_timer.stop()
        else:
            # 다른 탭에서 터진 실패는 그 탭의 상태바에 적고, 여기서는
            # 탭 글자색으로만 알린다. 보고 있는 AI의 상태바에 남의
            # 소식을 적으면 지금 무엇이 잘못됐는지 알 수 없다.
            self._set_status(message, name, kind="error")
        # 답이 일부라도 왔으면 타자기 효과를 끊지 말고 마저 보여 준다.
        if shown and self._current_ai_label is not None and target:
            text = target[-1][1]
            self._render_ai_label(text, len(text))
        # 답이 한 글자도 안 왔으면 빈 말풍선을 지우고 시작한다.
        if target and target[-1] == ["ai", ""]:
            target.pop()
            if shown and self._current_ai_label is not None:
                bubble = self._current_ai_label.parentWidget()
                if bubble is not None:
                    self.transcript_layout.removeWidget(bubble)
                    bubble.deleteLater()
        if shown:
            self._current_ai_label = None
        target.append(["error", message])
        if shown:
            self._insert_bubble(self._make_error_bubble(message))
            self._scroll_to_bottom()

    def _add_favorite_buttons(self) -> None:
        """도구가 이번 턴에 실제로 읽은 법령마다 즐겨찾기 단추를 단다.

        검색 결과 후보 전부가 아니라 get_article/get_document로 실제로
        연 문서만 대상이다 — 후보 목록까지 단추로 걸면 모델이 훑어보기만
        하고 안 쓴 법령까지 걸려서 지저분해진다.
        """
        if (
            self.favorite_handler is None
            or self._session is None
            or self._current_ai_label is None
        ):
            return
        documents = self._session.touched_documents()
        if not documents:
            return
        column = self._current_ai_label.parentWidget()
        if column is None or column.layout() is None:
            return

        row = QHBoxLayout()
        row.setContentsMargins(0, 2, 0, 0)
        row.setSpacing(6)
        for category, item_id, name in documents[:4]:
            label = RESOURCE_CATEGORIES.get(category, {}).get("label", category)
            title = name or item_id
            button = QPushButton(f"☆ {title} 즐겨찾기에 추가")
            button.setObjectName("aiChatFavoriteButton")
            button.setMinimumWidth(0)
            button.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
            )
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(f"{label} · id={item_id}")
            # 이미 걸어 둔 법령이면 눌러 봐야 "이미 있습니다"만 듣는다.
            # 처음부터 그렇게 보여 준다.
            already = False
            if self.favorite_checker is not None:
                try:
                    already = bool(self.favorite_checker(category, item_id))
                except Exception:  # noqa: BLE001 - 확인 실패는 단추만 살린다
                    already = False
            if already:
                button.setText(f"★ {title} 즐겨찾기에 있음")
                button.setEnabled(False)
            else:
                button.clicked.connect(
                    functools.partial(
                        self._favorite_button_clicked,
                        button,
                        category,
                        item_id,
                        name,
                    )
                )
            row.addWidget(button)
        row.addStretch(1)
        column.layout().addLayout(row)
        self._add_article_favorite_buttons(column)

    def _add_article_favorite_buttons(self, column: QWidget) -> None:
        """이번 답이 인용한 조문마다 그 조만 거는 단추를 단다.

        법령 전체를 거는 단추와는 다르다. 실무에서는 "그 법 어디쯤"이
        아니라 "그 조"를 다시 찾는 일이 훨씬 잦다. 조문 즐겨찾기는 그
        법령의 저장본 안에 얹히므로, 즐겨찾기 목록에서는 법령 밑에
        딸린 줄로 보인다.
        """
        if self.article_favorite_handler is None:
            return
        text = ""
        if self._messages and self._messages[-1][0] == "ai":
            text = self._messages[-1][1]
        articles = extract_cited_articles(text)
        if not articles:
            return
        layout = column.layout()
        if layout is None:
            return
        row = QHBoxLayout()
        row.setContentsMargins(0, 2, 0, 0)
        row.setSpacing(6)
        for law_id, jo, label in articles[:6]:
            short = label or f"제{jo}조"
            button = QPushButton(f"☆ {short}만 즐겨찾기")
            button.setObjectName("aiChatFavoriteButton")
            button.setMinimumWidth(0)
            button.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
            )
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(f"법령 {law_id} 제{jo}조를 즐겨찾기에 겁니다.")
            already = False
            if self.article_favorite_checker is not None:
                try:
                    already = bool(self.article_favorite_checker(law_id, jo))
                except Exception:  # noqa: BLE001 - 확인 실패는 단추만 살린다
                    already = False
            if already:
                button.setText(f"★ {short} 즐겨찾기에 있음")
                button.setEnabled(False)
            else:
                button.clicked.connect(
                    functools.partial(
                        self._article_favorite_clicked,
                        button,
                        law_id,
                        jo,
                        short,
                    )
                )
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)

    def _article_favorite_clicked(
        self, button: QPushButton, law_id: str, jo: str, label: str
    ) -> None:
        self.article_favorite_handler(law_id, jo, label, "")
        button.setText(f"★ {label} 즐겨찾기에 있음")
        button.setEnabled(False)

    def _favorite_button_clicked(
        self, button: QPushButton, category: str, item_id: str, name: str
    ) -> None:
        self.favorite_handler(category, item_id, name)
        button.setText(f"★ {name or item_id} 즐겨찾기에 있음")
        button.setEnabled(False)

    def _show_used_articles(self, column: QWidget | None, text: str) -> None:
        """답에서 사용한 조문을 모은다. 별도의 실존 재확인은 하지 않는다."""
        if column is None or not text.strip():
            return
        html = verification_html(collect_citations(text))
        if not html:
            return
        layout = column.layout()
        if layout is None:
            return
        label = QLabel(html)
        label.setObjectName("aiChatCitationCheck")
        # 복사 줄에 바로 붙지 않게 한 줄만큼만 띄운다.
        label.setContentsMargins(0, 6, 0, 0)
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum
        )
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setFont(QFont(FONT_FAMILY, 8))
        label.setOpenExternalLinks(False)
        label.linkActivated.connect(self._article_link_clicked)
        layout.addWidget(label)
        self._follow_to_bottom()

    def _visible_stream(self) -> dict[str, object] | None:
        """화면에 떠 있는 제공자의 답. 안 돌고 있으면 None."""
        return self._streams.get(self._active_provider_name)

    def _answer_finished(self, name: str = "") -> None:
        """답 하나가 끝났다. 그 답의 스레드를 정리하고 마무리한다.

        답은 제공자마다 따로 돈다. 끝난 것이 지금 보고 있는 탭의 답이
        아닐 수도 있으므로, 화면을 건드리는 마무리는 보일 때만 한다.
        저장은 어느 쪽이든 그 제공자 쪽에 해 둔다 — 그 탭으로 돌아가면
        저장된 대화로 그린다.
        """
        name = name or self._active_provider_name
        stream = self._streams.get(name)
        if stream is None:
            return
        thread = stream.get("thread")
        worker = stream.get("worker")
        if thread is not None:
            thread.quit()
            thread.wait()
            thread.deleteLater()
        if worker is not None:
            worker.deleteLater()
        stream["thread"] = None
        stream["worker"] = None
        shown = name == self._active_provider_name
        stream_messages = stream["messages"]
        failed = bool(stream["failed"])
        tools = list(stream.get("tools") or [])
        if (
            tools
            and isinstance(stream_messages, list)
            and stream_messages
            and stream_messages[-1][0] == "ai"
        ):
            self._set_message_tools(stream_messages[-1], tools)
        column = None
        if shown:
            self._streaming = False
            # 답이 끝났다. 띠지는 그대로 두되, 이제 스크롤을 움직이면
            # 원래 화면으로 돌아가게 놓아 준다.
            self._release_question_banner()
            # 빛을 멈추고 얼마나 걸렸는지를 그 자리에 남긴다.
            self._elapsed_timer.stop()
            if self._current_status is not None:
                self._current_status.stop()
                self._refresh_status_line()
                self._current_status = None
            # 기록줄은 화면에 그대로 두고 참조만 놓는다. 무엇을 거쳐
            # 답했는지 나중에도 되짚을 수 있어야 한다. 놓기 전에 마지막
            # 줄의 "진행 중" 색만 걷어 낸다.
            self._redraw_tool_log()
            self._current_tool_log = None
            # 타자기 효과가 아직 다 못 풀었어도 여기서 한 번에 완성한다.
            self._flush_render()
            # 흐르는 동안 잡아 둔 높이가 실제 내용보다 클 수 있다. 그대로
            # 두면 답 아래로 빈 자리가 길게 남는다. 끝난 김에 다시 잰다.
            QTimer.singleShot(0, self, self._refit_transcript_height)
            if self._current_ai_label is not None:
                column = self._current_ai_label.parentWidget()
        answer_text = ""
        if stream_messages and stream_messages[-1][0] == "ai":
            answer_text = stream_messages[-1][1]
        if not failed and shown:
            self._add_favorite_buttons()
            connection_spec = self._connection_spec()
            if connection_spec is not None:
                status_text = "CLI : 연결됨"
                self._cli_statuses[connection_spec.label] = (
                    status_text,
                    "connected",
                )
                self._set_cli_status(status_text, "connected")
        if shown:
            self._current_ai_label = None
            self._set_busy(False)
            if not failed:
                self._set_status("")
                self._show_used_articles(column, answer_text)
        self._persist_current_chat(name, stream_messages)
        if not shown:
            self._set_status("답변이 끝났습니다.", name, kind="done")
        # 상태줄까지 다 쓴 뒤에 지운다. _refresh_status_line이 이 기록에서
        # 걸린 시간을 읽는다.
        self._streams.pop(name, None)
        # 지운 다음에 한 번 더 그린다. 앞에서 그린 상태줄은 이 기록이
        # 아직 남아 있어 "답하는 중입니다."로 읽혔고, 답이 끝난 뒤에도
        # 그 문구가 그대로 남아 있었다.
        if shown:
            self._render_status()
        if shown:
            self.input_edit.setFocus()

    def _composer_action(self) -> None:
        if self._streaming:
            self._stop()
        else:
            self._send()

    def _stop(self) -> None:
        """지금 보고 있는 탭의 답만 멈춘다. 다른 탭의 답은 그대로 둔다."""
        stream = self._visible_stream()
        worker = stream.get("worker") if stream is not None else None
        if worker is not None:
            worker.stop()
            self._set_status("중지했습니다.")

    def _set_busy(self, busy: bool) -> None:
        self.reset_button.setEnabled(not busy)
        self.send_button.setText("■" if busy else "↑")
        self.send_button.set_stopping(busy)
        self.send_button.setToolTip("답변 중지" if busy else "보내기")
        self.send_button.setEnabled(True)
        self.provider_combo.setEnabled(not busy)
        self.provider_tabs.setEnabled(True)
        self.chat_history_list.setEnabled(not busy)
        self.history_new_button.setEnabled(not busy)
        self.model_combo.setEnabled(not busy)
        self.model_menu_button.setEnabled(not busy)
        self.key_input.setEnabled(not busy)
        self.refresh_button.setEnabled(not busy)
        if self._connection_thread is None:
            self.connection_button.setEnabled(not busy)

    def shutdown(self) -> None:
        # 돌고 있는 답이 여럿일 수 있다. 하나라도 남으면 프로그램이
        # 끝나지 않으므로 전부 멈춘다.
        for stream in list(self._streams.values()):
            worker = stream.get("worker")
            if worker is not None:
                worker.stop()
            thread = stream.get("thread")
            if thread is not None:
                thread.quit()
                thread.wait(3000)
        if self._connection_thread is not None:
            if self._connection_worker is not None:
                self._connection_worker.stop()
            self._connection_thread.quit()
            self._connection_thread.wait(5000)
        self._persist_current_chat()
        self._save_active_provider_state()
        for state in self._provider_chat_states.values():
            session = state.get("session")
            if isinstance(session, ChatSession):
                session.close()
                state["session"] = None
