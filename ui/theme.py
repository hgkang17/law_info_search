"""글꼴·색상과 사용자가 칠한 서식을 다루는 층."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Callable
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
    QKeySequence,
    QShortcut,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from storage.paths import APP_DIR
from ui.assets import HIGHLIGHTER_ICON_PATH
from utils.constants import (
    DETAIL_FONT_CSS_FAMILY,
    DETAIL_FONT_FAMILIES,
    DETAIL_FONT_FAMILY,
    DETAIL_HEADER_CONTROL_HEIGHT,
    FONT_FAMILY,
    UI_FONT_FAMILIES,
    UI_FONT_PIXEL_SIZE,
)
from utils.formatting import LAW_HEADING_COLOR
from PySide6.QtWidgets import QLabel
import re


PALETTE_COLORS: tuple[tuple[str, str], ...] = (
    ("빨강", "#ef4444"),
    ("주황", "#f59e0b"),
    ("노랑", "#fde047"),
    ("초록", "#22c55e"),
    ("파랑", "#3b82f6"),
    ("보라", "#8b5cf6"),
    ("흰색", "#ffffff"),
    ("검정", "#000000"),
)


WORKBENCH_COLORS: dict[str, str] = {
    "canvas": "#f4f4f3",
    "surface": "#ffffff",
    "ink": "#242529",
    "navy": "#242529",
    "accent": "#2563eb",
    "accent_hover": "#1d4ed8",
    "border": "#dedfdf",
    "focus": "#3b82f6",
    "muted": "#62666f",
}


def apply_workbench_color_tokens(style_sheet: str) -> str:
    """QSS의 의미 기반 작업대 색상 토큰을 실제 색으로 치환한다."""
    for role, value in WORKBENCH_COLORS.items():
        style_sheet = style_sheet.replace(
            f"__WB_{role.upper()}__", value
        )
    return style_sheet


USER_BACKGROUND_ALPHA = 128


# 검색줄 콤보(기관ㆍ검색범위ㆍ별표 대상)의 공통 너비. 화면마다 다른 폭을
# 쓰면 탭을 오갈 때 검색어 칸의 시작 자리가 흔들린다. 가장 긴 항목인
# ``행정중심복합도시건설청``이 잘리지 않는 값으로 맞춰 두었다.
SEARCH_COMBO_WIDTH = 170


BASE_FOREGROUND_PROPERTY = int(QTextFormat.Property.UserProperty) + 1


TEXT_COLOR_SHORTCUTS = (
    ("Ctrl+G", "#22c55e", "초록"),
    ("Ctrl+R", "#ef4444", "빨강"),
    ("Ctrl+K", "#000000", "검정"),
    ("Ctrl+W", "#ffffff", "흰색"),
    ("Ctrl+Y", "#fde047", "노랑"),
    ("Ctrl+B", "#3b82f6", "파랑"),
)


TEXT_COLOR_SHORTCUT_BY_VALUE = {
    color_value: sequence
    for sequence, color_value, _color_name in TEXT_COLOR_SHORTCUTS
}


PRETENDARD_FONT_DIR = APP_DIR / "fonts"


PRETENDARD_VARIABLE_FONT_PATH = PRETENDARD_FONT_DIR / "PretendardVariable.ttf"


PRETENDARD_STATIC_STYLES = (
    "Thin",
    "ExtraLight",
    "Light",
    "Regular",
    "Medium",
    "SemiBold",
    "Bold",
    "ExtraBold",
    "Black",
)


_PRETENDARD_FONTS_REGISTERED = False


_PRETENDARD_FONT_IDS: list[int] = []


_SYSTEM_DETAIL_FONT_IDS: list[int] = []


def _register_windows_detail_font() -> None:
    """Qt가 Windows 기본 굴림을 열거하지 못한 경우 OS 파일로 보완한다."""
    if sys.platform != "win32" or QFontDatabase.hasFamily(DETAIL_FONT_FAMILY):
        return
    windows_dir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    font_path = windows_dir / "Fonts" / "gulim.ttc"
    if not font_path.is_file():
        return
    font_id = QFontDatabase.addApplicationFont(str(font_path))
    if font_id >= 0:
        _SYSTEM_DETAIL_FONT_IDS.append(font_id)


def register_bundled_pretendard_fonts() -> bool:
    """UI용 Pretendard와 Windows 본문용 굴림을 Qt 앱에 등록."""
    global _PRETENDARD_FONTS_REGISTERED
    if _PRETENDARD_FONTS_REGISTERED:
        return bool(_PRETENDARD_FONT_IDS)
    _PRETENDARD_FONTS_REGISTERED = True
    _register_windows_detail_font()
    if PRETENDARD_VARIABLE_FONT_PATH.is_file():
        font_id = QFontDatabase.addApplicationFont(
            str(PRETENDARD_VARIABLE_FONT_PATH)
        )
        if font_id >= 0:
            _PRETENDARD_FONT_IDS.append(font_id)
    for style in PRETENDARD_STATIC_STYLES:
        font_path = PRETENDARD_FONT_DIR / f"Pretendard-{style}.ttf"
        if not font_path.is_file():
            continue
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        if font_id >= 0:
            _PRETENDARD_FONT_IDS.append(font_id)
    return bool(_PRETENDARD_FONT_IDS)


def ui_font(
    point_size: float | None = None,
    weight: QFont.Weight = QFont.Weight.Normal,
) -> QFont:
    """화면 UI에 쓰는 글꼴 한 벌.

    글꼴을 새로 만드는 자리마다 이름만 적어 두면 대체 글꼴과 힌팅이 환경
    따라 흔들린다. 화면 글꼴은 모두 이 함수를 거치게 해서 한곳에서 바꾼다.

    **중간 굵기를 주지 않는다.** 맑은 고딕은 Windows에 Semilight(290)ㆍ
    Regular(400)ㆍBold(700) 세 벌뿐이라, Medium(500)이나 DemiBold(600)을
    지정해도 실제 글꼴 파일이 없어 Regular로 그려진다. 값을 올려도 화면이
    그대로여서 굵기를 계속 올리다 시간을 버리기 쉽다. 굵게 보여야 하는
    자리는 Bold(700)를 쓴다.
    """
    font = QFont(FONT_FAMILY)
    font.setFamilies(list(UI_FONT_FAMILIES))
    font.setWeight(weight)
    if point_size is None:
        font.setPixelSize(UI_FONT_PIXEL_SIZE)
    else:
        font.setPointSizeF(point_size)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def detail_font(
    point_size: float | None = None, family: str | None = None
) -> QFont:
    """본문(법령ㆍ행정규칙 조문)에 쓰는 글꼴 한 벌.

    글꼴 이름만 정하고 목록을 비워 두면 위젯이 앱 기본 글꼴의 목록을 물려받아
    본문 글꼴이 화면 UI 글꼴로 덮인다. 목록까지 못박아야 본문만 다른 글꼴을
    쓸 수 있다.
    """
    selected_family = str(family or DETAIL_FONT_FAMILY).strip()
    font = QFont(selected_family)
    fallback_families = [selected_family, *DETAIL_FONT_FAMILIES]
    font.setFamilies(list(dict.fromkeys(fallback_families)))
    font.setWeight(QFont.Weight.Normal)
    if point_size is not None:
        font.setPointSizeF(point_size)
    # 본문은 화면 UI와 달리 힌팅을 켠다. 오래 읽는 글이라 획이 화소에 맞아
    # 또렷한 편이 낫다. 화면 UI(ui_font)는 힌팅을 끈 채로 둔다.
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def user_format_color(color: QColor | str, *, background: bool) -> QColor:
    """Return a copy of a user-selected color with 50% background opacity."""
    result = QColor(color)
    if background and result.isValid():
        result.setAlpha(USER_BACKGROUND_ALPHA)
    return result


def palette_swatch_color(color: str, *, background: bool) -> str:
    value = user_format_color(color, background=background)
    if not background:
        return value.name(QColor.NameFormat.HexRgb)
    return (
        f"rgba({value.red()}, {value.green()}, {value.blue()}, "
        f"{value.alpha()})"
    )


def palette_color_tooltip(
    row_label: str, color_name: str, color_value: str, *, background: bool
) -> str:
    """Return a palette tooltip, including body text-color shortcuts."""
    tooltip = f"{row_label} · {color_name}"
    if not background:
        shortcut = TEXT_COLOR_SHORTCUT_BY_VALUE.get(color_value.lower())
        if shortcut:
            tooltip += f" ({shortcut})"
    return tooltip


def capture_base_foreground_spans(document: object) -> list[dict[str, object]]:
    """Return the original foreground recorded for each document fragment."""
    spans: list[dict[str, object]] = []
    block = document.begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            character_format = fragment.charFormat()
            if character_format.hasProperty(BASE_FOREGROUND_PROPERTY):
                spans.append(
                    {
                        "start": fragment.position(),
                        "end": fragment.position() + fragment.length(),
                        "color": str(
                            character_format.property(BASE_FOREGROUND_PROPERTY) or ""
                        ),
                    }
                )
            iterator += 1
        block = block.next()
    return spans


def apply_base_foreground_spans(
    document: object, spans: list[dict[str, object]]
) -> None:
    """Attach previously captured base foregrounds to a rebuilt document."""
    maximum_position = max(0, document.characterCount() - 1)
    for span in spans:
        try:
            start = max(0, min(int(span.get("start") or 0), maximum_position))
            end = max(start, min(int(span.get("end") or 0), maximum_position))
        except (AttributeError, TypeError, ValueError):
            continue
        if end <= start:
            continue
        cursor = QTextCursor(document)
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        character_format = QTextCharFormat()
        character_format.setProperty(
            BASE_FOREGROUND_PROPERTY, str(span.get("color") or "")
        )
        cursor.mergeCharFormat(character_format)


def remember_base_foregrounds(document: object) -> None:
    """Record HTML-defined foregrounds before user color formatting is applied."""
    fragments: list[tuple[int, int, str]] = []
    block = document.begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            character_format = fragment.charFormat()
            brush = character_format.foreground()
            color = (
                brush.color().name(QColor.NameFormat.HexArgb)
                if brush.style() != Qt.BrushStyle.NoBrush
                else ""
            )
            fragments.append(
                (fragment.position(), fragment.position() + fragment.length(), color)
            )
            iterator += 1
        block = block.next()
    apply_base_foreground_spans(
        document,
        [
            {"start": start, "end": end, "color": color}
            for start, end, color in fragments
        ],
    )


def remember_base_foregrounds_for_cursor(cursor: QTextCursor) -> None:
    """글자색을 바꾸기 직전 선택 범위의 원래 색만 지연 기록."""
    if not cursor.hasSelection():
        return
    document = cursor.document()
    start = cursor.selectionStart()
    end = cursor.selectionEnd()
    spans: list[dict[str, object]] = []
    block = document.findBlock(start)
    while block.isValid() and block.position() < end:
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            run_start = max(start, fragment.position())
            run_end = min(end, fragment.position() + fragment.length())
            if run_end > run_start:
                character_format = fragment.charFormat()
                if not character_format.hasProperty(BASE_FOREGROUND_PROPERTY):
                    brush = character_format.foreground()
                    color = (
                        brush.color().name(QColor.NameFormat.HexArgb)
                        if brush.style() != Qt.BrushStyle.NoBrush
                        else ""
                    )
                    spans.append(
                        {"start": run_start, "end": run_end, "color": color}
                    )
            iterator += 1
        block = block.next()
    if spans:
        apply_base_foreground_spans(document, spans)


def clear_user_colors(cursor: QTextCursor) -> None:
    """Clear user colors while restoring the HTML document's original text colors."""
    if not cursor.hasSelection():
        return
    document = cursor.document()
    start = cursor.selectionStart()
    end = cursor.selectionEnd()
    runs: list[tuple[int, int, str | None]] = []
    block = document.findBlock(start)
    while block.isValid() and block.position() < end:
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            run_start = max(start, fragment.position())
            run_end = min(end, fragment.position() + fragment.length())
            if run_end > run_start:
                character_format = fragment.charFormat()
                base_color = (
                    str(character_format.property(BASE_FOREGROUND_PROPERTY) or "")
                    if character_format.hasProperty(BASE_FOREGROUND_PROPERTY)
                    else None
                )
                runs.append((run_start, run_end, base_color))
            iterator += 1
        block = block.next()

    for run_start, run_end, base_color in runs:
        run_cursor = QTextCursor(document)
        run_cursor.setPosition(run_start)
        run_cursor.setPosition(run_end, QTextCursor.MoveMode.KeepAnchor)
        character_format = QTextCharFormat()
        character_format.setBackground(QBrush(Qt.BrushStyle.NoBrush))
        if base_color is not None:
            color = QColor(base_color)
            character_format.setForeground(
                color if color.isValid() else QBrush(Qt.BrushStyle.NoBrush)
            )
        run_cursor.mergeCharFormat(character_format)


def apply_legal_title_colors(html: str) -> str:
    """저장 HTML의 조 제목도 현재 법령 제목 색으로 맞춘다."""
    pattern = re.compile(
        r'(<span\b[^>]*class=["\'][^"\']*\blaw-article-title\b[^"\']*'
        r'["\'][^>]*style=["\'])([^"\']*)(["\'])',
        flags=re.IGNORECASE,
    )

    def replace(match: re.Match) -> str:
        style = re.sub(
            r"color\s*:\s*[^;]+;?",
            "",
            match.group(2),
            flags=re.IGNORECASE,
        ).rstrip()
        if style and not style.endswith(";"):
            style += ";"
        return (
            f"{match.group(1)}{style} color:{LAW_HEADING_COLOR};{match.group(3)}"
        )

    return pattern.sub(replace, html)


def detail_font_css_family(family: str = "") -> str:
    """고른 글꼴을 맨 앞에 세운 CSS 글꼴 목록.

    글꼴이 없는 환경을 위해 기본 대체 목록을 뒤에 붙인다.
    """
    chosen = str(family or "").strip()
    if not chosen:
        return DETAIL_FONT_CSS_FAMILY
    names = list(dict.fromkeys([chosen, *DETAIL_FONT_FAMILIES]))
    return ", ".join(f"'{name}'" for name in names)


def apply_detail_font_family(html: str, family: str = "") -> str:
    """저장된 본문 HTML을 지금 고른 본문 글꼴과 기본 두께로 통일.

    ``family``를 주지 않으면 기본 글꼴로 맞춘다. 예전에는 늘 기본 글꼴로
    덮어써서, 글꼴 칸에서 다른 글꼴을 골라도 본문은 그대로였다.
    """
    html = re.sub(
        r"font-family\s*:\s*[^;\"]+",
        f"font-family:{detail_font_css_family(family)}",
        html,
        flags=re.IGNORECASE,
    )
    return re.sub(
        r"font-weight\s*:\s*(?:300|normal)\b",
        "font-weight:400",
        html,
        flags=re.IGNORECASE,
    )


def scale_document_font_sizes(
    html: str, source_size: float, target_size: float, family: str = ""
) -> str:
    """저장된 본문 HTML의 글꼴·제목색을 맞추고 글자 크기를 비율대로 바꾼다.

    법령검색·키워드검색·중앙부처 탭이 모두 같은 규칙으로 본문을 그리므로
    한곳에 두고 함께 쓴다.
    """
    html = apply_detail_font_family(apply_legal_title_colors(html), family)
    if source_size <= 0 or source_size == target_size:
        return html
    ratio = target_size / source_size

    # 법령ID·소관부처는 본문 크기 조절 대상이 아닌 작은 보조 정보다.
    # 본문 배율을 올려도 사용자가 지정한 7pt가 함께 커지지 않게 잠시 뺀다.
    fixed_fragments: list[str] = []

    def protect_fixed(match: re.Match) -> str:
        fixed_fragments.append(match.group(0))
        return f"__FIXED_DETAIL_META_{len(fixed_fragments) - 1}__"

    html = re.sub(
        r'<div\b[^>]*class=["\']doc-meta["\'][^>]*>.*?</div>',
        protect_fixed,
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    def replace(match: re.Match) -> str:
        scaled = max(1.0, float(match.group(2)) * ratio)
        value = f"{scaled:.2f}".rstrip("0").rstrip(".")
        return f"{match.group(1)}{value}{match.group(3)}"

    html = re.sub(
        r"(font-size\s*:\s*)(\d+(?:\.\d+)?)(px|pt)",
        replace,
        html,
        flags=re.IGNORECASE,
    )
    for index, fragment in enumerate(fixed_fragments):
        html = html.replace(f"__FIXED_DETAIL_META_{index}__", fragment)
    return html


@dataclass
class ColorPaletteToolbar:
    """음영색·글자색 팔레트 + 초기화 버튼 + 메모 버튼 묶음.

    법령검색·중앙부처/해석례/판례·키워드검색 세 탭에서 동일하게 쓰인다.
    """

    color_tools: QWidget
    palette_buttons: list[QToolButton]
    color_reset_tools: QWidget
    color_reset_button: QPushButton
    all_color_reset_button: QPushButton
    memo_button: QPushButton


def build_color_palette_toolbar(
    apply_color: Callable[..., None],
    reset_selected: Callable[[], None],
    reset_all: Callable[[], None],
    edit_memo: Callable[[], None],
) -> ColorPaletteToolbar:
    """본문 음영색/글자색 팔레트 도구줄을 생성한다.

    세 검색 탭(법령검색·중앙부처 등·키워드검색)이 각자 복제해 두었던
    동일한 팔레트 UI를 한 곳에서 만들어 재사용한다.
    """
    color_tools = QWidget()
    color_tools.setObjectName("colorTools")
    color_tools.setFixedSize(78, DETAIL_HEADER_CONTROL_HEIGHT)
    color_tools.setSizePolicy(
        QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
    )
    color_tools_layout = QHBoxLayout(color_tools)
    color_tools_layout.setContentsMargins(0, 0, 0, 0)
    color_tools_layout.setSpacing(0)
    palette_buttons: list[QToolButton] = []

    def tool_icon(kind: str, color_value: str) -> QIcon:
        if kind == "background":
            return QIcon(str(HIGHLIGHTER_ICON_PATH))
        pixmap = QPixmap(22, 20)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        ink = QColor("#34465a")
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(13)
        painter.setFont(font)
        painter.setPen(ink)
        painter.drawText(3, 0, 16, 16, Qt.AlignmentFlag.AlignCenter, "A")
        painter.setPen(QPen(QColor(color_value), 2.5))
        painter.drawLine(4, 17, 18, 17)
        painter.end()
        return QIcon(pixmap)

    def swatch_icon(color_value: str) -> QIcon:
        pixmap = QPixmap(28, 18)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor("#b7bec7"), 1.0))
        painter.setBrush(QColor(color_value))
        painter.drawRoundedRect(2, 2, 24, 14, 2.5, 2.5)
        painter.end()
        return QIcon(pixmap)

    for row_label, is_background in (("음영색", True), ("글자색", False)):
        current = {"value": "#fde047" if is_background else "#ef4444"}
        button = QToolButton()
        button.setObjectName("colorPaletteToolButton")
        # QSS의 좌우 1px 테두리까지 합친 실제 크기다. 부모 영역과 같은
        # 수치로 잡아 아래ㆍ오른쪽 테두리가 잘리지 않게 한다.
        button.setFixedSize(39, DETAIL_HEADER_CONTROL_HEIGHT)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setIconSize(QSize(22, 20))
        button.setIcon(
            tool_icon("background" if is_background else "text", current["value"])
        )
        button.setToolTip(f"{row_label} · 현재 색 적용 또는 화살표로 색 선택")
        button.setAccessibleName(row_label)
        menu = QMenu(button)
        for color_name, color_value in PALETTE_COLORS:
            action = menu.addAction(swatch_icon(color_value), "")
            action.setData(color_value)
            action.setToolTip(
                palette_color_tooltip(
                    row_label, color_name, color_value, background=is_background
                )
            )
            def choose(
                _checked=False,
                *,
                value=color_value,
                background=is_background,
                target=button,
                state=current,
            ) -> None:
                state["value"] = value
                target.setIcon(
                    tool_icon("background" if background else "text", value)
                )
                apply_color(value, background=background)

            action.triggered.connect(choose)
        button.setMenu(menu)
        button.clicked.connect(
            lambda _checked=False, background=is_background, state=current: (
                apply_color(state["value"], background=background)
            )
        )
        palette_buttons.append(button)
        color_tools_layout.addWidget(button)

    color_reset_tools = QWidget()
    color_reset_tools.setObjectName("colorResetTools")
    color_reset_tools.setFixedSize(124, DETAIL_HEADER_CONTROL_HEIGHT)
    color_reset_layout = QHBoxLayout(color_reset_tools)
    color_reset_layout.setContentsMargins(0, 0, 0, 0)
    color_reset_layout.setSpacing(4)
    color_reset_button = QPushButton("선택초기화")
    color_reset_button.setObjectName("colorResetButton")
    color_reset_button.setFixedSize(60, DETAIL_HEADER_CONTROL_HEIGHT)
    color_reset_button.setToolTip(
        "선택한 본문의 음영색과 글자색을 모두 지웁니다."
    )
    color_reset_button.clicked.connect(reset_selected)
    all_color_reset_button = QPushButton("전체초기화")
    all_color_reset_button.setObjectName("colorResetButton")
    all_color_reset_button.setFixedSize(60, DETAIL_HEADER_CONTROL_HEIGHT)
    all_color_reset_button.setToolTip(
        "현재 본문의 사용자 음영색과 글자색을 모두 지웁니다."
    )
    all_color_reset_button.clicked.connect(reset_all)
    color_reset_layout.addWidget(color_reset_button)
    color_reset_layout.addWidget(all_color_reset_button)

    memo_button = QPushButton("메모")
    memo_button.setObjectName("memoButton")
    memo_button.setFixedSize(40, DETAIL_HEADER_CONTROL_HEIGHT)
    memo_button.setToolTip("본문을 드래그해 선택한 뒤 메모를 작성합니다.")
    memo_button.clicked.connect(lambda _checked=False: edit_memo())

    return ColorPaletteToolbar(
        color_tools=color_tools,
        palette_buttons=palette_buttons,
        color_reset_tools=color_reset_tools,
        color_reset_button=color_reset_button,
        all_color_reset_button=all_color_reset_button,
        memo_button=memo_button,
    )


def install_text_color_shortcuts(owner: QWidget) -> None:
    """Install selection text-color shortcuts scoped to a detail browser."""
    owner.text_color_shortcuts = []
    for sequence, color_value, _color_name in TEXT_COLOR_SHORTCUTS:
        shortcut = QShortcut(QKeySequence(sequence), owner.detail_view)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(
            lambda color=color_value: owner._apply_palette_color(
                color, background=False
            )
        )
        owner.text_color_shortcuts.append(shortcut)


def apply_light_title_bar(widget) -> None:
    """Windows 네이티브 제목줄을 밝은 작업공간과 같은 계열로 맞춘다."""
    if sys.platform != "win32" or widget is None:
        return
    hwnd = int(widget.winId())
    if not hwnd:
        return
    import ctypes

    value = ctypes.c_int(0)
    dwmapi = ctypes.windll.dwmapi
    # 20은 Windows 10 2004 이후, 19는 그 이전. 되는 쪽만 적용된다.
    for attribute in (20, 19):
        dwmapi.DwmSetWindowAttribute(
            hwnd,
            attribute,
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
