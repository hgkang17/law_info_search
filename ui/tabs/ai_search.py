"""키워드 직접검색·연관법령 화면."""

from __future__ import annotations

from ui.assets import (
    SEARCH_API_REFRESH_TOOLTIP,
)
from ui.theme import (
    detail_font as make_detail_font,
    SEARCH_COMBO_WIDTH,
    apply_base_foreground_spans,
    build_color_palette_toolbar,
    capture_base_foreground_spans,
    clear_user_colors,
    install_text_color_shortcuts,
    remember_base_foregrounds_for_cursor,
    scale_document_font_sizes,
    user_format_color,
)
from ui.widgets import (
    CenteredCheckDelegate,
    DropdownComboBox,
    DeferredWrapTextBrowser,
    DetailSearchBar,
    FavoriteTitleDelegate,
    MemoMarkerBar,
    RecentSearchBar,
    ResultHeaderView,
    ResultOverlayLabel,
    SearchHighlightDelegate,
    SegmentedModeSwitch,
    StableHorizontalTableWidget,
    build_detail_header_controls,
    build_restore_view_button,
    build_search_result_head,
    clamp_detail_font_size,
    normalize_detail_font_size,
    prompt_oc_api_key,
    replace_search_term_backgrounds,
    configure_adaptive_result_rows,
    configure_horizontal_splitter,
    resize_adaptive_result_rows,
    restore_text_view_scroll,
)
from ui.dialogs import (
    MemoNoteDialog,
)
from ui.tabs.ai_chat_panel import AiChatPanel
from models.law import (
    AI_RELATED_AGENCY,
    AI_SEARCH_AGENCY,
    KEYWORD_CATEGORY_LABELS,
    KEYWORD_DIRECT_TARGET,
    KEYWORD_RELATED_TARGET,
)
from storage.cache import LawDocumentCache, SearchResultCache
from storage.recent import RecentSearchManager
from storage.paths import (
    SEARCH_RESULT_CACHE_DIR,
)
from workers.search_worker import (
    ApiWorker,
    RelatedArticleWorker,
)
from utils.constants import DEFAULT_DETAIL_FONT_POINT
from utils.formatting import (
    body_to_html,
    detail_document_header,
    strip_search_highlight_html,
)
from utils.parsing import (
    admin_rule_plain_text,
    admin_rule_text,
    deserialize_agency_search_payload,
    extract_admin_rule_article,
    json_list,
    json_text,
    law_unit_code,
    row_search_text,
    search_terms,
    whitespace_insensitive_contains,
    serialize_agency_search_payload,
)
from PySide6.QtCore import QEvent, QRect, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QKeySequence, QShortcut, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QAbstractItemView, QApplication, QDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QSizePolicy, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
from html import escape
import re
from molit_cgm_expc_api import ADMIN_RULE_IMAGES_KEY, _find_text
from ui.dialogs import _position_dialog_beside


class AiLawSearchTab(QWidget):
    """지능형 직접검색 또는 연관법령 추천 결과를 표시하는 탭."""

    # 검색줄의 모드 스위치가 다른 API를 고르면 법령검색 탭에 알린다.
    mode_requested = Signal(str)

    def __init__(
        self,
        service: str,
        oc_provider,
        recent_search_manager: RecentSearchManager,
        law_cache: LawDocumentCache,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.oc_provider = oc_provider
        self.recent_search_manager = recent_search_manager
        self.law_cache = law_cache
        self.search_result_cache = SearchResultCache(SEARCH_RESULT_CACHE_DIR)
        self.is_related = service == "ai_related"
        self.worker: ApiWorker | RelatedArticleWorker | None = None
        self.result_rows: list[dict[str, str]] = []
        self._pending_article_row = -1
        self._related_article_cache: dict[tuple[str, str, str], str] = {}
        self._pending_favorite_row: dict[str, object] | None = None
        self.highlight_terms: tuple[str, ...] = ()
        self.current_detail_text = ""
        self._updating_cache_checks = False
        self._active_detail_row: dict[str, object] | None = None
        self._visible_memos: list[dict[str, object]] = []
        self.detail_font_size = self._saved_font_size(
            f"{service}_detail_font_size", DEFAULT_DETAIL_FONT_POINT
        )
        self.detail_font_family = str(
            self.recent_search_manager.settings.value(
                f"{service}_detail_font_family", "Malgun Gothic"
            )
            or "Malgun Gothic"
        )
        self._reading_mode = False
        self._sort_column = -1
        self._sort_ascending = True
        self._normal_window_margins: tuple[int, int, int, int] | None = None
        self.ai_chat_panel: AiChatPanel | None = None
        # 조문 참조 팝업과 3단비교는 법령검색 탭이 이미 갖고 있으므로
        # 여기서 다시 만들지 않고 그 탭에 넘긴다. main_window가 지정한다.
        self.reference_tab = None
        self._build_ui()
        install_text_color_shortcuts(self)
        self.law_cache.changed.connect(self._refresh_snapshot_checks)

    def idle_status_text(self) -> str:
        """검색 전 하단 상태바에 띄우는 안내.

        예전에는 화면 위쪽 배너로 띄우고 ✕로 닫을 수 있었는데, 한 번 닫으면
        다시 뜨지 않아 이 화면이 무엇을 찾는지 알 길이 없었다. 다른 화면과
        같이 하단 상태바로 옮겨 늘 보이게 한다.
        """
        if self.is_related:
            return "키워드와 연관성이 높은 법령·행정규칙 조문을 추천합니다."
        return (
            "키워드가 직접 포함된 법령·행정규칙의 조문 또는 별표·서식을 "
            "찾습니다. 키워드가 검색되는 모든 조문을 표시합니다."
        )

    def _saved_font_size(self, key: str, default: float) -> float:
        try:
            value = float(
                self.recent_search_manager.settings.value(key, default)
            )
        except (TypeError, ValueError):
            value = default
        return clamp_detail_font_size(value)

    def use_shared_status(self, bar) -> None:
        """창 아래 공용 상태줄을 이 화면의 상태 자리로 삼는다.

        화면 코드는 계속 ``self.status_label``ㆍ``self.progress``에 쓰지만,
        실제 표시는 공용 하단바가 맡는다. 이 화면이 앞에 나올 때만 그 문구가
        올라가므로 뒤에서 끝난 검색이 보고 있는 화면을 덮어쓰지 않는다.
        """
        line = bar.line_for(self)
        line.setText(self.status_label.text())
        self.status_row.hide()
        self.status_label = line
        self.progress = line
        self._progress_opacity = line

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        # 법령검색 탭 안에 끼워지므로 바깥 12px를 또 두면 검색칸이
        # 법령ㆍ별표서식보다 안쪽으로 줄어든다.
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        search_card = QFrame()
        search_card.setObjectName("card")
        self.search_card = search_card
        search_layout = QHBoxLayout(search_card)
        search_layout.setContentsMargins(10, 12, 10, 12)
        search_layout.setSpacing(8)

        # 연관검색ㆍ직접검색은 카테고리 바에서 캡슐 하나로 묶였다. 어느
        # API를 쓰는지는 여기서 고르고, 화면 전환은 법령검색 탭이 맡는다.
        self.mode_switch = SegmentedModeSwitch(
            (
                (KEYWORD_CATEGORY_LABELS[KEYWORD_RELATED_TARGET],
                 KEYWORD_RELATED_TARGET),
                (KEYWORD_CATEGORY_LABELS[KEYWORD_DIRECT_TARGET],
                 KEYWORD_DIRECT_TARGET),
            )
        )
        self.mode_switch.set_current_value(self.service)
        self.mode_switch.changed.connect(self.mode_requested)
        self.mode_switch.setToolTip(
            "연관검색은 키워드와 연관성이 높은 조문을 추천하고, "
            "직접검색은 키워드가 그대로 들어간 조문을 찾습니다."
        )

        self.scope_combo = DropdownComboBox()
        if self.is_related:
            self.scope_combo.addItem("법령 조문", 0)
            self.scope_combo.addItem("행정규칙 조문", 1)
        else:
            self.scope_combo.addItem("법령 조문", 0)
            self.scope_combo.addItem("법령 별표·서식", 1)
            self.scope_combo.addItem("행정규칙 조문", 2)
            self.scope_combo.addItem("행정규칙 별표·서식", 3)
        self.scope_combo.setFixedWidth(SEARCH_COMBO_WIDTH)

        self.query_input = QLineEdit()
        self.query_input.setPlaceholderText("검색할 키워드를 입력하세요")
        self.query_input.setClearButtonEnabled(True)
        self.query_input.returnPressed.connect(self.start_search)

        self.search_button = QPushButton("검색")
        self.search_button.setObjectName("primaryButton")
        self.search_button.setFixedWidth(56)
        self.search_button.clicked.connect(self.start_search)

        search_layout.addWidget(self.mode_switch, 0, Qt.AlignmentFlag.AlignVCenter)
        search_layout.addWidget(self.scope_combo)
        search_layout.addWidget(self.query_input, 1)
        search_layout.addWidget(self.search_button)
        self.recent_search_bar = RecentSearchBar(
            self.query_input, self.recent_search_manager, self
        )

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(True)
        self.main_splitter = splitter

        result_card = QFrame()
        result_card.setObjectName("card")
        result_layout = QVBoxLayout(result_card)
        result_layout.setContentsMargins(16, 16, 16, 16)
        result_layout.setSpacing(10)
        result_head = build_search_result_head(
            on_clear_highlight=self._clear_search_highlighting,
            on_refresh_api=self._refresh_search_from_api,
            refresh_tooltip=SEARCH_API_REFRESH_TOOLTIP,
        )
        self.result_count = result_head.count
        self.search_shade_reset_button = result_head.shade_reset
        self.search_refresh_button = result_head.refresh
        result_layout.addLayout(result_head.layout)

        self.result_table = StableHorizontalTableWidget(0, 6)
        self.result_table.setAccessibleName("검색 결과 표")
        self.result_empty_label = ResultOverlayLabel(self.result_table.viewport())
        self.result_table.setHorizontalHeader(
            ResultHeaderView(Qt.Orientation.Horizontal, self.result_table)
        )
        self.result_table.setHorizontalHeaderLabels(
            [
                "저장",
                "구분",
                "조문·별표",
                "법령·행정규칙명",
                "시행일자",
                "소관기관",
            ]
        )
        self.result_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.result_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.result_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setShowGrid(False)
        self.result_table.setWordWrap(True)
        self.result_table.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.provision_delegate = FavoriteTitleDelegate(
            self._toggle_favorite_at_row,
            self._is_favorite_at_row,
            self.result_table,
        )
        self.name_delegate = SearchHighlightDelegate(self.result_table)
        self.save_check_delegate = CenteredCheckDelegate(self.result_table)
        self.result_table.setItemDelegateForColumn(0, self.save_check_delegate)
        self.result_table.setItemDelegateForColumn(2, self.provision_delegate)
        self.result_table.setItemDelegateForColumn(3, self.name_delegate)
        self.result_table.verticalHeader().setVisible(False)
        configure_adaptive_result_rows(self.result_table, (2, 3))
        table_header = self.result_table.horizontalHeader()
        table_header.setStretchLastSection(False)
        table_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        table_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionsClickable(True)
        table_header.setSortIndicatorShown(False)
        table_header.sectionClicked.connect(self._sort_by_column)
        self.result_table.cellDoubleClicked.connect(
            self._open_detail_expanded
        )
        self.result_table.itemSelectionChanged.connect(
            self._selection_changed
        )
        self.result_table.itemChanged.connect(self._snapshot_check_changed)
        result_layout.addWidget(self.result_table)

        self.result_filter_input = QLineEdit()
        self.result_filter_input.setObjectName("resultFilterInput")
        self.result_filter_input.setPlaceholderText(
            "검색결과 내에서 찾기 (제목 등으로 필터)"
        )
        self.result_filter_input.setClearButtonEnabled(True)
        self.result_filter_input.textChanged.connect(self._filter_result_rows)
        result_layout.addWidget(self.result_filter_input)

        detail_card = QFrame()
        detail_card.setObjectName("card")
        self.detail_card = detail_card
        detail_layout = QVBoxLayout(detail_card)
        detail_layout.setContentsMargins(16, 16, 16, 16)
        detail_layout.setSpacing(10)
        detail_head = QHBoxLayout()
        detail_head.setContentsMargins(0, 0, 0, 0)
        detail_head.setSpacing(5)
        detail_controls = build_detail_header_controls(
            self.detail_font_size, self.detail_font_family
        )
        detail_title = detail_controls.title
        detail_title.doubleClicked.connect(self._toggle_reading_mode)
        self.detail_font_combo = detail_controls.font_combo
        self.detail_font_spin = detail_controls.font_spin
        self.detail_font_combo.currentFontChanged.connect(
            self._set_detail_font_family
        )
        self.detail_font_spin.valueChanged.connect(self._set_detail_font_size)

        palette_toolbar = build_color_palette_toolbar(
            self._apply_palette_color,
            self._reset_selected_colors,
            self._reset_all_colors,
            self._edit_selection_memo,
        )
        self.color_tools = palette_toolbar.color_tools
        self.palette_buttons = palette_toolbar.palette_buttons
        self.color_reset_tools = palette_toolbar.color_reset_tools
        self.color_reset_button = palette_toolbar.color_reset_button
        self.all_color_reset_button = palette_toolbar.all_color_reset_button
        self.memo_button = palette_toolbar.memo_button

        self.expand_detail_button = QPushButton("크게\n보기")
        self.expand_detail_button.setObjectName("readingModeButton")
        self.expand_detail_button.setFixedSize(44, 42)
        self.expand_detail_button.setToolTip("F11: 본문 크게 보기로 전환")
        self.expand_detail_button.clicked.connect(self._toggle_reading_mode)

        self.ai_agent_button = QPushButton("AI\n에이전트")
        self.ai_agent_button.setObjectName("readingModeButton")
        self.ai_agent_button.setProperty("buttonMode", "ai")
        self.ai_agent_button.setFixedSize(58, 42)
        self.ai_agent_button.setToolTip(
            "보고 있는 본문이나 선택한 부분에 대해 AI 에이전트에게 물어봅니다."
        )
        self.ai_agent_button.clicked.connect(self._toggle_ai_chat)

        self.copy_button = QPushButton("본문 복사")
        self.copy_button.setObjectName("ghostButton")
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self.copy_detail)
        self.copy_button.hide()
        self.restore_view_button = build_restore_view_button(self)
        detail_head.addWidget(self.restore_view_button)
        detail_head.addWidget(detail_title)
        detail_head.addSpacing(8)
        detail_head.addWidget(self.detail_font_combo)
        detail_head.addWidget(self.detail_font_spin)
        detail_head.addSpacing(8)
        detail_head.addWidget(self.color_tools)
        detail_head.addWidget(self.color_reset_tools)
        detail_head.addWidget(self.memo_button)
        detail_head.addStretch()
        detail_head.addWidget(self.expand_detail_button)
        detail_head.addWidget(self.ai_agent_button)
        detail_head.addWidget(self.copy_button)
        detail_layout.addLayout(detail_head)

        self.detail_view = DeferredWrapTextBrowser()
        self.detail_view.setAccessibleName("본문")
        detail_font = make_detail_font(
            self.detail_font_size, self.detail_font_family
        )
        self.detail_view.setFont(detail_font)
        self.detail_view.document().setDefaultFont(detail_font)
        self.detail_view.setOpenExternalLinks(False)
        self.detail_view.setOpenLinks(False)
        self.detail_view.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self.detail_view.anchorClicked.connect(self._detail_link_clicked)
        self.detail_view.viewport().setCursor(Qt.CursorShape.IBeamCursor)
        self.detail_view.setPlaceholderText(
            "검색 결과에서 항목을 더블클릭하면 본문을 엽니다."
        )
        self.detail_view.viewport().installEventFilter(self)
        self.three_stage_button = QPushButton(
            "3단", self.detail_view.viewport()
        )
        self.three_stage_button.setObjectName("threeStageArticleButton")
        self.three_stage_button.setFixedSize(56, 24)
        self.three_stage_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.three_stage_button.setToolTip(
            "이 조문의 법률·시행령·시행규칙을 3단으로 비교합니다."
        )
        self.three_stage_button.clicked.connect(
            self._open_three_stage_comparison
        )
        self.three_stage_button.hide()
        self._three_stage_position = -1
        self.detail_view.verticalScrollBar().valueChanged.connect(
            self._position_inline_three_stage_button
        )
        self.detail_search = DetailSearchBar(self.detail_view, self)
        detail_layout.addWidget(self.detail_search)
        detail_view_row = QWidget()
        detail_view_row.setObjectName("detailViewRow")
        detail_view_row_layout = QHBoxLayout(detail_view_row)
        detail_view_row_layout.setContentsMargins(0, 0, 0, 0)
        detail_view_row_layout.setSpacing(2)
        self.memo_marker_bar = MemoMarkerBar(self.detail_view, detail_view_row)
        self.memo_marker_bar.activated.connect(self._open_memo_marker_popup)
        detail_view_row_layout.addWidget(self.detail_view, 1)
        detail_view_row_layout.addWidget(self.memo_marker_bar)
        detail_layout.addWidget(detail_view_row, 1)

        search_results_panel = QWidget()
        search_results_panel.setObjectName("searchResultsPanel")
        self.search_results_panel = search_results_panel
        search_results_layout = QVBoxLayout(search_results_panel)
        search_results_layout.setContentsMargins(0, 0, 0, 0)
        search_results_layout.setSpacing(12)
        search_results_layout.addWidget(search_card)
        search_results_layout.addWidget(self.recent_search_bar)
        search_results_layout.addWidget(result_card, 1)

        for panel in (search_results_panel, detail_card):
            panel.setMinimumWidth(0)
            panel.setSizePolicy(
                QSizePolicy.Policy.Ignored,
                QSizePolicy.Policy.Preferred,
            )
        splitter.addWidget(search_results_panel)
        splitter.addWidget(detail_card)
        configure_horizontal_splitter(splitter)
        splitter.setCollapsible(0, True)
        splitter.setCollapsible(1, True)
        splitter.setSizes([2000, 0])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        detail_card.hide()
        root.addWidget(splitter, 1)
        self._normal_splitter_sizes = [360, 1040]
        self.root_layout = root

        # 상태줄은 창 하나에 하나만 두는 것이 원칙이라, main_window가
        # use_shared_status로 공용 하단바를 넘겨 준다. 이 화면만 따로 띄우는
        # 경우(테스트 등)를 위해 자체 상태줄도 그대로 만들어 둔다.
        self.status_row = QWidget()
        status_layout = QHBoxLayout(self.status_row)
        status_layout.setContentsMargins(0, 0, 0, 0)
        self.status_label = QLabel(self.idle_status_text())
        self.status_label.setObjectName("mutedText")
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedSize(120, 8)
        self.progress.setTextVisible(False)
        # hide()/show()로 껐다 켜면 상태줄 폭이 바뀌면서 그 위 본문
        # 영역까지 흔들린다. 항상 자리(120x8)는 차지하되, 투명도만
        # 조절해 대기 중에는 안 보이게 한다.
        self._progress_opacity = QGraphicsOpacityEffect(self.progress)
        self._progress_opacity.setOpacity(0.0)
        self.progress.setGraphicsEffect(self._progress_opacity)
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        status_layout.addWidget(self.progress)
        root.addWidget(self.status_row)

        self.reading_mode_shortcut = QShortcut(QKeySequence("F11"), self)
        self.reading_mode_shortcut.activated.connect(self._toggle_reading_mode)

    def _show_detail_split(self) -> None:
        """검색 목록 오른쪽에 직접검색·연관검색 본문 칸을 연다."""
        if self._reading_mode:
            return
        self.detail_card.show()
        self.main_splitter.setStretchFactor(0, 4)
        self.main_splitter.setStretchFactor(1, 12)
        sizes = list(self._normal_splitter_sizes)
        if self.ai_chat_panel is not None:
            sizes.append(0)
        self.main_splitter.setSizes(sizes)
        QTimer.singleShot(0, self.memo_marker_bar.refresh_after_layout_change)

    def _hide_detail_split(self, *_args: object) -> None:
        """본문과 AI 칸을 닫고 검색 목록을 다시 전체 폭으로 넓힌다."""
        if self._reading_mode:
            self._set_reading_mode(False)
        self._hide_ai_chat()
        total = sum(self.main_splitter.sizes()) or self.main_splitter.width()
        self.detail_card.hide()
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 0)
        sizes = [max(1, total), 0]
        if self.ai_chat_panel is not None:
            self.main_splitter.setStretchFactor(2, 0)
            sizes.append(0)
        self.main_splitter.setSizes(sizes)

    def _chat_context(self) -> tuple[str, str]:
        """AI가 현재 조문·별표 본문 또는 드래그한 부분을 근거로 삼는다."""
        selected = self.detail_view.textCursor().selectedText()
        if selected.strip():
            return selected.replace(" ", "\n"), "선택한 부분"
        return self.detail_view.toPlainText(), "본문 전체"

    def _resource_action(self, name: str, *args: object):
        action = getattr(self.reference_tab, name, None)
        if action is None:
            return False
        return action(*args)

    def _ensure_ai_chat_panel(self) -> AiChatPanel:
        if self.ai_chat_panel is not None:
            return self.ai_chat_panel

        panel = AiChatPanel(self.recent_search_manager.settings, parent=self)
        panel.context_source = self._chat_context
        panel.oc_provider = self.oc_provider
        panel.document_cache = self.law_cache
        panel.favorite_handler = lambda *args: self._resource_action(
            "add_favorite_by_id", *args
        )
        panel.favorite_checker = lambda *args: self._resource_action(
            "is_favorite_by_id", *args
        )
        panel.article_favorite_handler = lambda *args: self._resource_action(
            "add_article_favorite_by_id", *args
        )
        panel.article_favorite_checker = lambda *args: self._resource_action(
            "is_article_favorite_by_id", *args
        )
        panel.reference_handler = lambda *args: self._resource_action(
            "open_reference_link", *args
        )
        panel.closeRequested.connect(self._hide_ai_chat)
        panel.hide()
        self.main_splitter.addWidget(panel)
        # 드래그 중 최소 폭에서 0으로 접히지 않게 한다. 닫기는 ×로만 한다.
        self.main_splitter.setCollapsible(2, False)
        self.main_splitter.setStretchFactor(2, 0)
        self.ai_chat_panel = panel

        window = self.window()
        peers = [
            getattr(window, "ai_review_tab", None),
            getattr(getattr(window, "resource_tab", None), "ai_chat_panel", None),
        ]
        for tab_name in (
            "central_tab",
            "expc_tab",
            "prec_tab",
            "ai_related_tab",
            "ai_search_tab",
        ):
            peer_tab = getattr(window, tab_name, None)
            peers.append(getattr(peer_tab, "ai_chat_panel", None))
        for peer in peers:
            if peer is None or peer is panel:
                continue
            panel.chatHistoryChanged.connect(peer.apply_external_history_change)
            peer.chatHistoryChanged.connect(panel.apply_external_history_change)
            panel.chatHistoryCleared.connect(peer.apply_external_history_clear)
            peer.chatHistoryCleared.connect(panel.apply_external_history_clear)
        return panel

    def _toggle_ai_chat(self, *_args: object) -> None:
        panel = self._ensure_ai_chat_panel()
        if panel.isVisible():
            self._hide_ai_chat()
        else:
            self._show_ai_chat()

    def _show_ai_chat(self) -> None:
        panel = self._ensure_ai_chat_panel()
        sizes = self.main_splitter.sizes()
        total = sum(sizes) or self.main_splitter.width()
        left_width = 0 if self._reading_mode else sizes[0]
        chat_width = max(300, total // 4)
        detail_width = max(1, total - left_width - chat_width)
        panel.show()
        self.main_splitter.setStretchFactor(2, 4)
        self.main_splitter.setSizes([left_width, detail_width, chat_width])
        panel.input_edit.setFocus()

    def _hide_ai_chat(self, *_args: object) -> None:
        panel = self.ai_chat_panel
        if panel is None or not panel.isVisible():
            return
        sizes = self.main_splitter.sizes()
        total = sum(sizes) or self.main_splitter.width()
        left_width = 0 if self._reading_mode else sizes[0]
        panel.hide()
        self.main_splitter.setStretchFactor(2, 0)
        self.main_splitter.setSizes(
            [left_width, max(1, total - left_width), 0]
        )
        self.detail_view.setFocus()

    def shutdown(self) -> None:
        if self.ai_chat_panel is not None:
            self.ai_chat_panel.shutdown()

    def _toggle_reading_mode(self, *_args: object) -> None:
        self._set_reading_mode(not self._reading_mode)

    def _exit_reading_mode(self) -> None:
        if self._reading_mode:
            self._set_reading_mode(False)

    def _set_reading_mode(self, expanded: bool) -> None:
        expanded = bool(expanded)
        if expanded == self._reading_mode:
            return

        window = self.window()
        central_widget = (
            window.centralWidget() if hasattr(window, "centralWidget") else None
        )
        central_layout = central_widget.layout() if central_widget is not None else None
        if expanded:
            current_sizes = self.main_splitter.sizes()
            if sum(current_sizes) > 0:
                self._normal_splitter_sizes = current_sizes[:2]
            self.detail_card.show()
            if central_layout is not None:
                self._normal_window_margins = central_layout.getContentsMargins()

        self._reading_mode = expanded
        self.search_results_panel.setVisible(not expanded)
        self.status_label.setVisible(not expanded)
        self.progress.setVisible(
            not expanded and bool(self.worker and self.worker.isRunning())
        )

        if hasattr(window, "apply_reading_mode_chrome"):
            window.apply_reading_mode_chrome(expanded)
        elif hasattr(window, "navigation_card"):
            window.navigation_card.setVisible(not expanded)
        elif hasattr(window, "tabs") and hasattr(window.tabs, "tabBar"):
            window.tabs.tabBar().setVisible(not expanded)

        # 직접검색·연관검색은 법령검색 안쪽 페이지이므로 바깥 카테고리 바와
        # 여백도 함께 접어야 질의회신과 같은 실제 전체 본문이 된다.
        host = self.reference_tab
        if host is not None:
            category_tabs = getattr(host, "category_tabs", None)
            if category_tabs is not None:
                category_tabs.setVisible(not expanded)
            host_layout = getattr(host, "root_layout", None)
            if host_layout is not None:
                host_layout.setContentsMargins(
                    0 if expanded else 12,
                    0,
                    0 if expanded else 12,
                    0,
                )

        if central_layout is not None:
            if expanded:
                central_layout.setContentsMargins(6, 6, 6, 6)
            elif self._normal_window_margins is not None:
                central_layout.setContentsMargins(*self._normal_window_margins)
        self.root_layout.setContentsMargins(0, 0, 0, 0)

        scroll_bar = self.detail_view.verticalScrollBar()
        scroll_ratio = (
            scroll_bar.value() / scroll_bar.maximum()
            if scroll_bar.maximum() > 0
            else 0.0
        )
        if expanded:
            current_sizes = self.main_splitter.sizes()
            total = sum(current_sizes) or sum(self._normal_splitter_sizes)
            chat_width = (
                current_sizes[2]
                if self.ai_chat_panel is not None
                and self.ai_chat_panel.isVisible()
                and len(current_sizes) > 2
                else 0
            )
            sizes = [0, max(1, total - chat_width)]
            if self.ai_chat_panel is not None:
                sizes.append(chat_width)
            self.main_splitter.setSizes(sizes)
            self.expand_detail_button.hide()
            self.restore_view_button.show()
            self.detail_view.setFocus()
        else:
            self._hide_ai_chat()
            total = sum(self.main_splitter.sizes()) or self.main_splitter.width()
            self.detail_card.hide()
            sizes = [max(1, total), 0]
            if self.ai_chat_panel is not None:
                sizes.append(0)
            self.main_splitter.setSizes(sizes)
            self.expand_detail_button.show()
            self.expand_detail_button.setText("크게\n보기")
            self.restore_view_button.hide()
            self.expand_detail_button.setToolTip("F11: 본문 크게 보기로 전환")
            callback = getattr(self, "_reading_mode_exit_callback", None)
            if callback is not None:
                self._reading_mode_exit_callback = None
                callback()
        # 패널 너비가 바뀌면 본문이 다시 줄바꿈되어 스크롤 위치가 어긋나므로
        # 레이아웃이 반영된 뒤 같은 비율 위치로 복원함.
        QTimer.singleShot(
            0,
            lambda bar=scroll_bar, ratio=scroll_ratio: bar.setValue(
                round(ratio * bar.maximum())
            ),
        )
        QTimer.singleShot(0, self.memo_marker_bar.refresh_after_layout_change)

    def _set_detail_font_size(self, size: float, *, persist: bool = True) -> None:
        size = normalize_detail_font_size(size)
        previous_size = self.detail_font_size
        if size != previous_size:
            html = self.detail_view.toHtml()
            scroll_bar = self.detail_view.verticalScrollBar()
            scroll_ratio = (
                scroll_bar.value() / scroll_bar.maximum()
                if scroll_bar.maximum() > 0
                else 0.0
            )
            self.detail_font_size = size
            self._replace_detail_content(
                html=html, source_font_size=previous_size
            )
            scroll_bar.setValue(round(scroll_ratio * scroll_bar.maximum()))
        if persist:
            settings = self.recent_search_manager.settings
            settings.setValue(f"{self.service}_detail_font_size", size)
            settings.sync()

    def _set_detail_font_family(self, font: QFont) -> None:
        family = str(font.family() or "Malgun Gothic")
        if family == self.detail_font_family:
            return
        self.detail_font_family = family
        selected = make_detail_font(self.detail_font_size, family)
        self.detail_view.setFont(selected)
        self.detail_view.document().setDefaultFont(selected)
        cursor = QTextCursor(self.detail_view.document())
        cursor.select(QTextCursor.SelectionType.Document)
        character_format = QTextCharFormat()
        character_format.setFontFamilies([family])
        cursor.mergeCharFormat(character_format)
        settings = self.recent_search_manager.settings
        settings.setValue(f"{self.service}_detail_font_family", family)
        settings.sync()

    def _replace_detail_content(
        self,
        *,
        html: str | None = None,
        text: str | None = None,
        source_font_size: float = 10,
    ) -> None:
        previous_text = self.detail_view.toPlainText()
        previous_base_foregrounds = capture_base_foreground_spans(
            self.detail_view.document()
        )
        self.detail_search.begin_document_change()
        try:
            font = make_detail_font(
                self.detail_font_size, self.detail_font_family
            )
            self.detail_view.setFont(font)
            self.detail_view.document().setDefaultFont(font)
            if html is not None:
                self.detail_view.setHtml(
                    scale_document_font_sizes(
                        html, source_font_size, self.detail_font_size
                    )
                )
            elif text is not None:
                self.detail_view.setPlainText(text)
            else:
                self.detail_view.clear()
            if (
                previous_base_foregrounds
                and previous_text == self.detail_view.toPlainText()
            ):
                apply_base_foreground_spans(
                    self.detail_view.document(), previous_base_foregrounds
                )
            else:
                # 원래 글자색은 실제 글자색 변경 범위에서 지연 기록한다.
                pass
        finally:
            self.detail_search.end_document_change()

    def _selected_detail_cursor(self) -> QTextCursor | None:
        cursor = self.detail_view.textCursor()
        if cursor.hasSelection():
            return cursor
        QMessageBox.information(
            self,
            "본문 선택",
            "색상을 적용할 본문 구간을 먼저 드래그해 선택해 주세요.",
        )
        self.detail_view.setFocus()
        return None

    def _apply_palette_color(
        self, color_value: str, *, background: bool
    ) -> None:
        cursor = self._selected_detail_cursor()
        if cursor is None:
            return
        self._apply_selected_color(
            cursor, QColor(color_value), background=background
        )

    @staticmethod
    def _clear_cursor_colors(cursor: QTextCursor) -> None:
        clear_user_colors(cursor)

    def _restore_memo_markers_for_range(self, start: int, end: int) -> None:
        document = self.detail_view.document()
        maximum_position = max(0, document.characterCount() - 1)
        for memo in self._visible_memos:
            memo_start = max(0, int(memo.get("start") or 0))
            memo_end = min(maximum_position, int(memo.get("end") or 0))
            if memo_end <= start or memo_start >= end or memo_end <= memo_start:
                continue
            memo_cursor = QTextCursor(document)
            memo_cursor.setPosition(memo_start)
            memo_cursor.setPosition(
                memo_end, QTextCursor.MoveMode.KeepAnchor
            )
            self._apply_memo_marker(memo_cursor, str(memo.get("text") or ""))

    def _reset_selected_colors(self) -> None:
        cursor = self._selected_detail_cursor()
        if cursor is None:
            return
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        self._clear_cursor_colors(cursor)
        self._restore_memo_markers_for_range(start, end)
        self.detail_view.setTextCursor(cursor)

        row = self._active_detail_row
        saved: bool | None = None
        if row is not None and self.law_cache.has_snapshot(row):
            saved = self.law_cache.clear_formatting_range(row, start, end)
        if saved is True:
            status = "선택한 본문의 색상을 초기화하고 저장본에도 반영했습니다."
        elif saved is False:
            status = (
                "색상은 초기화했지만 저장본에 반영하지 못했습니다: "
                f"{self.law_cache.last_error}"
            )
        else:
            status = "선택한 본문의 음영색과 글자색을 초기화했습니다."
        self.status_label.setText(status)
        self.detail_view.setFocus()

    def _reset_all_colors(self) -> None:
        document = self.detail_view.document()
        end = max(0, document.characterCount() - 1)
        if end <= 0:
            self.status_label.setText("초기화할 본문이 없습니다.")
            return
        vertical_position = self.detail_view.verticalScrollBar().value()
        horizontal_position = self.detail_view.horizontalScrollBar().value()
        cursor = QTextCursor(document)
        cursor.setPosition(0)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self._clear_cursor_colors(cursor)
        self._restore_memo_markers_for_range(0, end)

        row = self._active_detail_row
        saved: bool | None = None
        if row is not None and self.law_cache.has_snapshot(row):
            saved = self.law_cache.clear_formatting_range(row, 0, end)
        if saved is True:
            status = "본문 전체 색상을 초기화하고 저장본에도 반영했습니다."
        elif saved is False:
            status = (
                "전체 색상은 초기화했지만 저장본에 반영하지 못했습니다: "
                f"{self.law_cache.last_error}"
            )
        else:
            status = "본문 전체의 음영색과 글자색을 초기화했습니다."
        self.status_label.setText(status)
        self.detail_view.setFocus()
        restore_text_view_scroll(
            self.detail_view, vertical_position, horizontal_position
        )

    def _apply_selected_color(
        self, cursor: QTextCursor, color: QColor, *, background: bool
    ) -> None:
        if not background:
            remember_base_foregrounds_for_cursor(cursor)
        character_format = QTextCharFormat()
        if background:
            character_format.setBackground(
                user_format_color(color, background=True)
            )
            description = "음영색"
        else:
            character_format.setForeground(color)
            description = "글자색"
        cursor.mergeCharFormat(character_format)
        self.detail_view.setTextCursor(cursor)
        formatting_saved = self._persist_active_detail_formatting(
            cursor, color, background=background
        )
        if formatting_saved is True:
            status = f"선택한 본문에 {description}을 적용하고 저장본에 보관했습니다."
        elif formatting_saved is False:
            status = (
                f"{description}은 적용했지만 저장하지 못했습니다: "
                f"{self.law_cache.last_error}"
            )
        else:
            status = f"선택한 본문에 {description}을 적용했습니다."
        self.status_label.setText(status)
        self.detail_view.setFocus()

    def _persist_active_detail_formatting(
        self, cursor: QTextCursor, color: QColor, *, background: bool
    ) -> bool | None:
        row = self._active_detail_row
        if row is None or not self.law_cache.has_snapshot(row):
            return None
        return self.law_cache.update_formatting(
            row,
            {
                "start": cursor.selectionStart(),
                "end": cursor.selectionEnd(),
                "mode": "background" if background else "text",
                "color": color.name(QColor.NameFormat.HexRgb),
            },
        )

    @staticmethod
    def _apply_memo_marker(cursor: QTextCursor, text: str) -> None:
        character_format = QTextCharFormat()
        if text:
            character_format.setUnderlineStyle(
                QTextCharFormat.UnderlineStyle.SingleUnderline
            )
            character_format.setUnderlineColor(QColor("#d9362e"))
            character_format.setToolTip(f"📝 메모: {text}")
        else:
            character_format.setUnderlineStyle(
                QTextCharFormat.UnderlineStyle.NoUnderline
            )
            character_format.setToolTip("")
        cursor.mergeCharFormat(character_format)

    def _restore_cached_colors_for_range(
        self, row: dict[str, object], start: int, end: int
    ) -> None:
        record = self.law_cache.load_snapshot(row)
        spans = record.get("formatting_spans") if isinstance(record, dict) else []
        if not isinstance(spans, list):
            return
        for span in spans:
            if not isinstance(span, dict):
                continue
            span_start = int(span.get("start") or 0)
            span_end = int(span.get("end") or 0)
            overlap_start = max(start, span_start)
            overlap_end = min(end, span_end)
            color = QColor(str(span.get("color") or ""))
            if overlap_end <= overlap_start or not color.isValid():
                continue
            restore_cursor = QTextCursor(self.detail_view.document())
            restore_cursor.setPosition(overlap_start)
            restore_cursor.setPosition(
                overlap_end, QTextCursor.MoveMode.KeepAnchor
            )
            character_format = QTextCharFormat()
            if str(span.get("mode") or "background") == "text":
                character_format.setForeground(color)
            else:
                character_format.setBackground(
                    user_format_color(color, background=True)
                )
            restore_cursor.mergeCharFormat(character_format)

    def _set_visible_memos(self, memos: object) -> None:
        cleaned: list[dict[str, object]] = []
        if isinstance(memos, list):
            for memo in memos:
                if not isinstance(memo, dict):
                    continue
                text = str(memo.get("text") or "").strip()
                if not text:
                    continue
                cleaned.append(
                    {
                        "start": int(memo.get("start") or 0),
                        "end": int(memo.get("end") or 0),
                        "excerpt": str(memo.get("excerpt") or ""),
                        "text": text,
                    }
                )
        self._visible_memos = cleaned
        self.memo_marker_bar.set_memos(cleaned)

    def _restore_cached_memos(self, record: dict[str, object]) -> int:
        memos = record.get("memos")
        if not isinstance(memos, list):
            self._set_visible_memos([])
            return 0
        document = self.detail_view.document()
        maximum_position = max(0, document.characterCount() - 1)
        restored = 0
        visible_memos: list[dict[str, object]] = []
        for memo in memos:
            if not isinstance(memo, dict):
                continue
            try:
                start = max(0, min(int(memo.get("start") or 0), maximum_position))
                end = max(start, min(int(memo.get("end") or 0), maximum_position))
            except (TypeError, ValueError):
                continue
            text = str(memo.get("text") or "").strip()
            if end <= start or not text:
                continue
            cursor = QTextCursor(document)
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            self._apply_memo_marker(cursor, text)
            visible_memos.append(
                {
                    "start": start,
                    "end": end,
                    "excerpt": str(memo.get("excerpt") or ""),
                    "text": text,
                }
            )
            restored += 1
        self._set_visible_memos(visible_memos)
        return restored

    def _restore_cached_formatting(self, record: dict[str, object]) -> int:
        spans = record.get("formatting_spans")
        if not isinstance(spans, list):
            return 0
        document = self.detail_view.document()
        maximum_position = max(0, document.characterCount() - 1)
        restored = 0
        for span in spans:
            if not isinstance(span, dict):
                continue
            try:
                start = max(0, min(int(span.get("start") or 0), maximum_position))
                end = max(start, min(int(span.get("end") or 0), maximum_position))
            except (TypeError, ValueError):
                continue
            color = QColor(str(span.get("color") or ""))
            if end <= start or not color.isValid():
                continue
            cursor = QTextCursor(document)
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            character_format = QTextCharFormat()
            if str(span.get("mode") or "background") == "text":
                remember_base_foregrounds_for_cursor(cursor)
                character_format.setForeground(color)
            else:
                character_format.setBackground(
                    user_format_color(color, background=True)
                )
            cursor.mergeCharFormat(character_format)
            restored += 1
        return restored

    def _open_memo_marker_popup(self, index: int) -> None:
        self._edit_selection_memo(
            anchor_rect=self.memo_marker_bar.marker_global_rect(index)
        )

    def _edit_selection_memo(self, anchor_rect: QRect | None = None) -> None:
        row = self._active_detail_row
        if row is None or not self.law_cache.has_snapshot(row):
            QMessageBox.information(
                self,
                "메모 저장",
                "저장된 본문을 연 뒤 메모할 구간을 선택해 주세요.",
            )
            return
        record = self.law_cache.load_snapshot(row)
        memos = record.get("memos") if isinstance(record, dict) else None
        if not isinstance(memos, list):
            memos = []
        cursor = self.detail_view.textCursor()
        existing_memo: dict[str, object] | None = None
        if cursor.hasSelection():
            start = cursor.selectionStart()
            end = cursor.selectionEnd()
            existing_memo = next(
                (
                    memo
                    for memo in memos
                    if isinstance(memo, dict)
                    and int(memo.get("start") or 0) == start
                    and int(memo.get("end") or 0) == end
                ),
                None,
            )
        else:
            position = cursor.position()
            existing_memo = next(
                (
                    memo
                    for memo in memos
                    if isinstance(memo, dict)
                    and int(memo.get("start") or 0) <= position
                    < int(memo.get("end") or 0)
                ),
                None,
            )
            if existing_memo is None:
                QMessageBox.information(
                    self,
                    "본문 선택",
                    "메모할 본문 구간을 먼저 드래그해 선택해 주세요.",
                )
                self.detail_view.setFocus()
                return
            cursor.setPosition(int(existing_memo.get("start") or 0))
            cursor.setPosition(
                int(existing_memo.get("end") or 0),
                QTextCursor.MoveMode.KeepAnchor,
            )

        excerpt = cursor.selectedText().replace(" ", " ").strip()
        initial_text = (
            str(existing_memo.get("text") or "") if existing_memo else ""
        )
        self.detail_view.setTextCursor(cursor)
        self.detail_view.ensureCursorVisible()
        dialog = MemoNoteDialog(excerpt, initial_text, self)
        dialog.memo_saved.connect(
            lambda text, selected_cursor=QTextCursor(cursor):
            self._apply_memo_marker(selected_cursor, text)
        )
        if isinstance(anchor_rect, QRect):
            _position_dialog_beside(dialog, anchor_rect)
        start = cursor.selectionStart()
        end = cursor.selectionEnd()

        def finish_memo(result: int) -> None:
            if result != int(QDialog.DialogCode.Accepted):
                return
            memo_text = dialog.memo_text()
            if not self.law_cache.update_memo(
                row,
                {
                    "start": start,
                    "end": end,
                    "excerpt": excerpt,
                    "text": memo_text,
                },
            ):
                QMessageBox.critical(
                    self,
                    "메모 저장 실패",
                    self.law_cache.last_error or "메모를 저장하지 못했습니다.",
                )
                return
            saved_cursor = QTextCursor(cursor)
            self._apply_memo_marker(saved_cursor, memo_text)
            if not memo_text:
                self._restore_cached_colors_for_range(row, start, end)
            visible_memos = [
                memo
                for memo in self._visible_memos
                if not (
                    int(memo.get("start") or 0) == start
                    and int(memo.get("end") or 0) == end
                )
            ]
            if memo_text:
                visible_memos.append(
                    {
                        "start": start,
                        "end": end,
                        "excerpt": excerpt,
                        "text": memo_text,
                    }
                )
            self._set_visible_memos(visible_memos)
            saved_cursor.setPosition(end)
            self.detail_view.setTextCursor(saved_cursor)
            self.status_label.setText(
                "선택 본문의 메모를 저장했습니다."
                if memo_text
                else "선택 본문의 메모를 삭제했습니다."
            )

        dialog.memo_saved.connect(
            lambda _text: finish_memo(int(QDialog.DialogCode.Accepted))
        )
        dialog.finished.connect(finish_memo)
        dialog.setModal(False)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _clear_search_highlighting(self) -> None:
        terms = self.highlight_terms
        if not terms:
            return
        self.highlight_terms = ()
        self.name_delegate.set_terms(())
        self.provision_delegate.set_terms(())
        # 저장 HTML에 남아 있던 더 긴 과거 검색어 음영까지 전부 지운다.
        # 현재 검색어 범위만 지우면 ``개발제한구역`` → ``개발제한`` 검색
        # 뒤 초기화할 때 끝의 ``구역``만 노랗게 남을 수 있다.
        replace_search_term_backgrounds(self.detail_view, ())
        self.result_table.viewport().update()
        self.search_shade_reset_button.setEnabled(False)
        self.status_label.setText("검색어 음영을 초기화했습니다.")

    def _refresh_search_from_api(self) -> None:
        self.start_search(force_api=True)

    def start_search(self, *_args: object, force_api: bool = False) -> None:
        query = self.query_input.text().strip()
        if not query:
            QMessageBox.information(self, "검색어 확인", "키워드를 입력해 주세요.")
            self.query_input.setFocus()
            return

        self._hide_detail_split()
        self.recent_search_manager.add(query)
        self.highlight_terms = search_terms(query)
        self.search_shade_reset_button.setEnabled(bool(self.highlight_terms))
        self.name_delegate.set_terms(self.highlight_terms)
        self.provision_delegate.set_terms(self.highlight_terms)
        self.result_table.setRowCount(0)
        self.result_rows.clear()
        self.result_count.setText("0건")
        self.result_empty_label.show_message("검색 중…")
        self.detail_view.clear()
        self.current_detail_text = ""
        self.copy_button.setEnabled(False)
        agency = AI_RELATED_AGENCY if self.is_related else AI_SEARCH_AGENCY
        search_scope = int(self.scope_combo.currentData())
        if not force_api:
            cached = self.search_result_cache.load(
                self.service, query, search_scope
            )
            if cached is not None:
                restored = deserialize_agency_search_payload(cached["payload"])
                self._show_search_results(restored)
                saved_at = str(cached.get("saved_at") or "").replace("T", " ")
                if "+" in saved_at:
                    saved_at = saved_at.rsplit("+", 1)[0]
                self.status_label.setText(
                    "저장된 검색목록을 불러왔습니다 · API 호출 없음"
                    + (f" · 저장 {saved_at}" if saved_at else "")
                    + " · 최신 목록은 API갱신"
                )
                return

        oc = self.oc_provider().strip()
        if not oc:
            prompt_oc_api_key(self)
            return

        self._start_worker(
            ApiWorker(
                "search",
                oc=oc,
                query=query,
                search_scope=search_scope,
                agencies=(agency,),
                parent=self,
            ),
            f"'{query}' 키워드 검색 중...",
        )

    def _start_worker(
        self, worker: ApiWorker | RelatedArticleWorker, message: str
    ) -> None:
        # 이전 작업의 finished 슬롯까지 처리되기 전에는 다음 작업으로
        # self.worker를 덮어쓰지 않는다. 검색 성공 직후 연관 조문 작업이
        # 먼저 시작되면 새 QThread를 이전 작업으로 오인해 삭제할 수 있다.
        if self.worker is not None:
            return
        self.worker = worker
        self.search_button.setEnabled(False)
        self.search_refresh_button.setEnabled(False)
        self.query_input.setEnabled(False)
        self.scope_combo.setEnabled(False)
        if worker.operation == "related_article":
            self.result_table.setEnabled(False)
        self._progress_opacity.setOpacity(1.0)
        self.status_label.setText(message)
        worker.succeeded.connect(self._worker_succeeded)
        worker.failed.connect(self._worker_failed)
        # lambda로 감싸면 받는 QObject가 없어 직접 연결이 되고, 이 뒷정리가
        # 작업 스레드에서 돌아 화면을 건드리다 프로그램이 죽는다.
        # 끝난 작업은 sender()로 찾는다.
        worker.finished.connect(self._worker_finished)
        worker.start()

    def _worker_finished(self) -> None:
        finished_worker = self.sender()
        if not isinstance(finished_worker, (ApiWorker, RelatedArticleWorker)):
            return
        operation = finished_worker.operation
        is_current = self.worker is finished_worker
        if not is_current:
            finished_worker.deleteLater()
            return
        self.search_button.setEnabled(True)
        self.search_refresh_button.setEnabled(True)
        self.query_input.setEnabled(True)
        self.scope_combo.setEnabled(True)
        if operation == "related_article":
            self.result_table.setEnabled(True)
        self._progress_opacity.setOpacity(0.0)
        self.worker = None
        finished_worker.deleteLater()

    def _worker_succeeded(self, operation: str, payload: object) -> None:
        try:
            if operation == "related_article":
                self._show_related_article_result(payload)
            else:
                self._show_search_results(payload)
                worker = self.worker
                if isinstance(worker, ApiWorker):
                    serialized = serialize_agency_search_payload(payload)
                    if self.search_result_cache.save(
                        self.service,
                        worker.query,
                        worker.search_scope,
                        serialized,
                    ):
                        self.status_label.setText(
                            self.status_label.text()
                            + " · 검색목록 로컬 저장 완료"
                        )
                    else:
                        self.status_label.setText(
                            self.status_label.text()
                            + " · 검색목록 저장 실패: "
                            + self.search_result_cache.last_error
                        )
        except Exception as exc:
            self._worker_failed(operation, str(exc))

    def _worker_failed(self, operation: str, error: str) -> None:
        if operation == "related_article":
            if 0 <= self._pending_article_row < len(self.result_rows):
                row = self.result_rows[self._pending_article_row]
                row["article_loading"] = ""
                row["article_error"] = error
                if self.result_table.currentRow() == self._pending_article_row:
                    self._show_selected_result()
            self.status_label.setText(f"연관 조문을 불러오지 못했습니다: {error}")
            return
        self.status_label.setText("검색에 실패했습니다.")
        QMessageBox.critical(
            self, "검색 실패", f"검색 중 오류가 발생했습니다.\n\n{error}"
        )

    @staticmethod
    def _clean_number(value: str) -> str:
        if value.isdigit():
            return str(int(value))
        return value

    @classmethod
    def _provision_label(cls, node, is_annex: bool) -> str:
        if is_annex:
            number = cls._clean_number(_find_text(node, "별표서식번호"))
            branch = cls._clean_number(_find_text(node, "별표서식가지번호"))
            title = _find_text(node, "별표서식제목")
            prefix = f"별표·서식 {number}" if number else "별표·서식"
            if branch and branch != "0":
                prefix += f"의{branch}"
        else:
            number = cls._clean_number(_find_text(node, "조문번호"))
            branch = cls._clean_number(_find_text(node, "조문가지번호"))
            title = _find_text(node, "조문제목")
            prefix = f"제{number}조" if number else "조문"
            if branch and branch != "0":
                prefix += f"의{branch}"
        return f"{prefix} {title}".strip()

    @staticmethod
    def _display_date(value: str) -> str:
        digits = re.sub(r"\D", "", value)
        if len(digits) >= 8:
            return f"{digits[:4]}.{digits[4:6]}.{digits[6:8]}"
        return value

    @staticmethod
    def _direct_row_matches_query(
        row: dict[str, str], query: str
    ) -> bool:
        terms = search_terms(query)
        if not terms:
            return True
        searchable = " ".join(
            (
                row.get("name", ""),
                row.get("provision", ""),
                row.get("content", ""),
            )
        ).casefold()
        for term in terms:
            normalized = term.casefold()
            variants = [normalized]
            for suffix in ("시행규칙", "시행령", "법"):
                if normalized.endswith(suffix) and len(normalized) > len(suffix) + 1:
                    variants.append(normalized[: -len(suffix)])
                    break
            if not any(variant in searchable for variant in variants):
                return False
        return True

    def _show_search_results(self, payload: object) -> None:
        roots = payload["roots"]
        errors = list(payload["errors"])
        if not roots and errors:
            raise ValueError("\n".join(message for _, message in errors))

        rows: list[dict[str, str]] = []
        total_count = 0
        for _agency, root in roots:
            count_text = _find_text(root, "검색결과개수")
            try:
                total_count += int(count_text)
            except (TypeError, ValueError):
                pass
            for node in root.iter():
                if "id" not in node.attrib:
                    continue
                item_tag = str(node.tag).rsplit("}", 1)[-1]
                is_admin = item_tag.startswith("행정규칙")
                is_annex = "별표서식" in item_tag
                name = _find_text(
                    node, "행정규칙명" if is_admin else "법령명"
                )
                if not name:
                    continue
                provision = self._provision_label(node, is_annex)
                article_number = _find_text(node, "조문번호")
                article_branch = _find_text(node, "조문가지번호")
                source_id = _find_text(
                    node, "행정규칙ID" if is_admin else "법령ID"
                )
                jo_code = ""
                if article_number.isdigit():
                    jo_code = law_unit_code(
                        article_number,
                        article_branch if article_branch.isdigit() else "",
                    )
                content = _find_text(node, "조문내용")
                row = {
                        "target": self.service,
                        "kind": item_tag,
                        "name": name,
                        "provision": provision,
                        "date": self._display_date(
                            _find_text(node, "시행일자")
                            or _find_text(node, "발령일자")
                        ),
                        "agency": _find_text(
                            node, "발령기관명" if is_admin else "소관부처명"
                        ),
                        "content": content,
                        "source_id": source_id,
                        "article_number": article_number,
                        "article_branch": article_branch,
                        "jo_code": jo_code,
                        "article_loading": "",
                        "article_error": "",
                        "publication_date": self._display_date(
                            _find_text(node, "발령일자" if is_admin else "공포일자")
                        ),
                        "publication_number": _find_text(
                            node, "발령번호" if is_admin else "공포번호"
                        ),
                    }
                if self.is_related or self._direct_row_matches_query(
                    row, self.query_input.text()
                ):
                    rows.append(row)

        if not self.is_related:
            total_count = len(rows)
        elif not total_count:
            total_count = len(rows)
        rows.sort(key=lambda row: 0 if self.law_cache.has_snapshot(row) else 1)
        self.result_rows = rows
        self.result_filter_input.clear()
        # 새 검색 결과는 저장 여부 기준 기본 차례로 돌아간다.
        self._sort_column = -1
        self._sort_ascending = True
        self.result_table.horizontalHeader().setSortIndicatorShown(False)
        self._render_result_rows()
        self.result_count.setText(f"{total_count}건")
        self.status_label.setText(
            f"검색 완료: {len(rows)}건을 불러왔습니다."
        )
        if rows:
            self.result_empty_label.clear_message()
            self.result_table.selectRow(0)
        else:
            self.result_empty_label.show_message("검색 결과가 없습니다.")
            self.detail_view.setPlainText("검색 결과가 없습니다.")

    def _render_result_rows(self) -> None:
        """result_rows 차례 그대로 표를 다시 그린다."""
        self._updating_cache_checks = True
        try:
            self.result_table.setRowCount(len(self.result_rows))
            for row_index, row in enumerate(self.result_rows):
                self.result_table.setItem(
                    row_index, 0, self._snapshot_item_for_row(row)
                )
                values = (
                    row["kind"],
                    row["provision"],
                    row["name"],
                    row["date"],
                    row["agency"],
                )
                for column, value in enumerate(values, start=1):
                    item = QTableWidgetItem(" ".join(value.split()))
                    if column in (1, 4, 5):
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if column in (2, 3):
                        item.setToolTip(item.text())
                    self.result_table.setItem(row_index, column, item)
        finally:
            self._updating_cache_checks = False
        resize_adaptive_result_rows(self.result_table)

    def _sort_key_for_column(self, logical_index: int):
        """열 번호에 맞는 정렬 기준을 돌려준다. 없으면 None."""

        def provision_key(row: dict[str, str]) -> tuple[int, str, str]:
            # 조문 번호는 글자로 견주면 제10조가 제2조보다 앞선다.
            # 여섯 자리 조문 코드가 있으면 그것으로 견준다.
            code = str(row.get("jo_code") or "")
            return (0 if code else 1, code, str(row.get("provision") or ""))

        return {
            0: lambda row: (
                0 if self.law_cache.has_snapshot(row) else 1,
                str(row.get("name") or ""),
            ),
            1: lambda row: str(row.get("kind") or ""),
            2: provision_key,
            3: lambda row: str(row.get("name") or ""),
            4: lambda row: str(row.get("date") or ""),
            5: lambda row: str(row.get("agency") or ""),
        }.get(logical_index)

    def _sort_by_column(self, logical_index: int) -> None:
        """열 머리를 누르면 그 열로 정렬하고, 다시 누르면 뒤집는다."""
        if not self.result_rows:
            return
        key_func = self._sort_key_for_column(logical_index)
        if key_func is None:
            return
        if logical_index == self._sort_column:
            self._sort_ascending = not self._sort_ascending
        else:
            self._sort_column = logical_index
            self._sort_ascending = True
        self.result_rows.sort(key=key_func, reverse=not self._sort_ascending)
        self._render_result_rows()
        self._filter_result_rows(self.result_filter_input.text())
        header = self.result_table.horizontalHeader()
        header.setSortIndicatorShown(True)
        header.setSortIndicator(
            logical_index,
            Qt.SortOrder.AscendingOrder
            if self._sort_ascending
            else Qt.SortOrder.DescendingOrder,
        )
        if self.result_rows:
            self.result_table.selectRow(0)

    def _snapshot_item_for_row(
        self, row: dict[str, str]
    ) -> QTableWidgetItem:
        item = QTableWidgetItem()
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
        if self.law_cache.has_snapshot(row):
            item.setCheckState(Qt.CheckState.Checked)
            item.setToolTip(
                "저장된 조문입니다. 체크를 풀면 저장 본문 파일을 삭제합니다."
            )
        else:
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setToolTip("체크하거나 조문을 열면 자동 저장됩니다.")
        item.setFlags(flags)
        return item

    def _is_favorite_at_row(self, row_index: int) -> bool:
        if not (0 <= row_index < len(self.result_rows)):
            return False
        return self.law_cache.is_favorite(self.result_rows[row_index])

    def _toggle_favorite_at_row(self, row_index: int) -> None:
        if not (0 <= row_index < len(self.result_rows)):
            return
        row = self.result_rows[row_index]
        wants_favorite = not self.law_cache.is_favorite(row)
        if wants_favorite and not self.law_cache.has_snapshot(row):
            self._pending_favorite_row = row
            self.result_table.selectRow(row_index)
            if self.is_related and not row.get("content"):
                self._request_related_article(row_index, row)
            else:
                self._show_selected_result(force_live=True)
            return
        if self.law_cache.set_favorite(row, wants_favorite):
            self.status_label.setText(
                "즐겨찾기에 추가했습니다."
                if wants_favorite
                else "즐겨찾기에서 뺐습니다."
            )
        else:
            self.status_label.setText(
                f"즐겨찾기 설정에 실패했습니다: {self.law_cache.last_error}"
            )
        self.result_table.viewport().update()

    def _refresh_snapshot_checks(self) -> None:
        if not hasattr(self, "result_table"):
            return
        self._updating_cache_checks = True
        try:
            for row_index, row in enumerate(self.result_rows):
                if row_index >= self.result_table.rowCount():
                    break
                self.result_table.setItem(
                    row_index, 0, self._snapshot_item_for_row(row)
                )
        finally:
            self._updating_cache_checks = False
        self.result_table.viewport().update()

    def _finalize_pending_favorite(self, saved_row: dict[str, object]) -> None:
        pending = self._pending_favorite_row
        if pending is None:
            return
        if str(pending.get("source_id")) != str(
            saved_row.get("source_id")
        ) or str(pending.get("jo_code")) != str(saved_row.get("jo_code")):
            return
        self._pending_favorite_row = None
        if not self.law_cache.set_favorite(saved_row, True):
            self.status_label.setText(
                f"즐겨찾기 설정에 실패했습니다: {self.law_cache.last_error}"
            )
        self.result_table.viewport().update()

    def _snapshot_check_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_cache_checks or item.column() != 0:
            return
        row_index = item.row()
        if not (0 <= row_index < len(self.result_rows)):
            return
        row = self.result_rows[row_index]
        cached = self.law_cache.has_snapshot(row)
        wants_saved = item.checkState() == Qt.CheckState.Checked
        if wants_saved == cached:
            return
        if not wants_saved:
            if self.law_cache.delete(row):
                self.status_label.setText("저장된 본문을 삭제했습니다.")
            else:
                self.status_label.setText(
                    f"저장본 삭제에 실패했습니다: {self.law_cache.last_error}"
                )
            self._refresh_snapshot_checks()
            return
        self.result_table.selectRow(row_index)
        if self.is_related:
            if row.get("content"):
                self._show_selected_result(force_live=True)
            else:
                self._request_related_article(row_index, row)
        else:
            self._show_selected_result(force_live=True)

    def _filter_result_rows(self, text: str) -> None:
        query = text.strip().casefold()
        visible = 0
        for row_index, row in enumerate(self.result_rows):
            matches = whitespace_insensitive_contains(row_search_text(row), query)
            self.result_table.setRowHidden(row_index, not matches)
            if matches:
                visible += 1
        total = len(self.result_rows)
        self.result_count.setText(
            f"{visible}/{total}건" if query else f"{total}건"
        )

    def _request_related_article(
        self,
        row_index: int,
        row: dict[str, str],
        *,
        force_api: bool = False,
    ) -> None:
        cache_key = self._related_article_cache_key(row)
        cached = "" if force_api else self._related_article_cache.get(cache_key, "")
        if cached:
            row["content"] = cached
            self._show_selected_result()
            self.status_label.setText(
                f"{row.get('name', '')} {row.get('provision', '')} 저장된 조문 표시"
            )
            return
        if self.worker is not None:
            return
        oc = self.oc_provider().strip()
        if not oc:
            row["article_error"] = "API 인증키가 없습니다."
            return
        row["article_loading"] = "1"
        row["article_error"] = ""
        self._pending_article_row = row_index
        self._start_worker(
            RelatedArticleWorker(
                oc=oc,
                row_index=row_index,
                row=row,
                parent=self,
            ),
            f"{row.get('name', '연관법령')} {row.get('provision', '')} 조문 조회 중...",
        )

    @staticmethod
    def _related_article_cache_key(
        row: dict[str, str]
    ) -> tuple[str, str, str]:
        return (
            str(row.get("kind") or ""),
            str(row.get("source_id") or row.get("name") or ""),
            str(row.get("jo_code") or row.get("provision") or ""),
        )

    @classmethod
    def _append_related_law_children(
        cls, node: object, output: list[str]
    ) -> None:
        if not isinstance(node, dict):
            return
        content = json_text(
            node.get("항내용") or node.get("호내용") or node.get("목내용")
        )
        if content:
            output.append(content)
        for key in ("호", "목"):
            for child in json_list(node.get(key)):
                cls._append_related_law_children(child, output)

    @classmethod
    def _extract_related_law_article(cls, payload: object) -> str:
        if not isinstance(payload, dict):
            raise ValueError("법령 조문 응답 형식이 올바르지 않습니다.")
        law = payload.get("법령")
        if not isinstance(law, dict):
            raise ValueError("법령 조문 본문을 찾지 못했습니다.")
        articles = law.get("조문", {})
        units = articles.get("조문단위") if isinstance(articles, dict) else []
        output: list[str] = []
        for unit in json_list(units):
            if not isinstance(unit, dict):
                continue
            content = json_text(unit.get("조문내용"))
            if content:
                output.append(content)
            for paragraph in json_list(unit.get("항")):
                cls._append_related_law_children(paragraph, output)
        return "\n".join(output).strip()

    @staticmethod
    def _extract_related_admin_article(
        payload: object, article_number: str, article_branch: str
    ) -> str:
        if not isinstance(payload, dict):
            raise ValueError("행정규칙 본문 응답 형식이 올바르지 않습니다.")
        service = payload.get("AdmRulService")
        if not isinstance(service, dict):
            message = json_text(payload.get("Law"))
            raise ValueError(message or "행정규칙 본문을 찾지 못했습니다.")
        raw_body = service.get("조문내용")
        body = admin_rule_text(raw_body)
        if not body:
            raise ValueError("행정규칙 조문내용이 없습니다.")
        selected = extract_admin_rule_article(
            body, article_number, article_branch
        )
        if not selected:
            raise ValueError("행정규칙 본문에서 해당 조문을 찾지 못했습니다.")
        return selected

    def _show_related_article_result(self, result: object) -> None:
        if not isinstance(result, dict):
            raise ValueError("연관 조문 응답 형식이 올바르지 않습니다.")
        row_index = int(result.get("row_index", -1))
        if not (0 <= row_index < len(self.result_rows)):
            raise ValueError("연관 조문을 적용할 검색결과를 찾지 못했습니다.")
        row = self.result_rows[row_index]
        if result.get("target") == "admrul":
            payload = result.get("payload")
            content = self._extract_related_admin_article(
                payload,
                row.get("article_number", ""),
                row.get("article_branch", ""),
            )
            embedded_images = (
                payload.get(ADMIN_RULE_IMAGES_KEY, {})
                if isinstance(payload, dict)
                else {}
            )
            row["embedded_images"] = (
                {
                    str(image_id): str(uri)
                    for image_id, uri in embedded_images.items()
                    if str(image_id).isdigit()
                    and str(uri).casefold().startswith("data:image/")
                }
                if isinstance(embedded_images, dict)
                else {}
            )
        else:
            content = self._extract_related_law_article(result.get("payload"))
        if not content:
            raise ValueError("조회한 조문에 표시할 내용이 없습니다.")
        row["content"] = content
        row["article_loading"] = ""
        row["article_error"] = ""
        self._related_article_cache[
            self._related_article_cache_key(row)
        ] = content
        if self.result_table.currentRow() == row_index:
            self._show_selected_result(force_live=True)
        self.status_label.setText(
            f"{row['name']} {row['provision']} 조문 조회 완료 · 재선택 시 저장 결과 사용"
        )

    def _open_detail_expanded(self, *_args: object) -> None:
        """검색결과 더블클릭: 본문을 열고 바로 크게 보기로 전환한다."""
        row = self.result_table.currentRow()
        if row < 0 or row >= len(self.result_rows):
            return
        self._show_selected_result()
        self._set_reading_mode(True)

    def _selection_changed(self) -> None:
        """목록 화면에서는 선택만, 분할 본문이 열린 뒤에는 내용을 바꾼다."""
        row_index = self.result_table.currentRow()
        selection_model = self.result_table.selectionModel()
        has_selection = bool(
            selection_model is not None and selection_model.hasSelection()
        )
        if (
            not has_selection
            or row_index < 0
            or row_index >= len(self.result_rows)
        ):
            self.copy_button.setEnabled(False)
            self._update_three_stage_button(None)
            return
        if self.detail_card.isHidden():
            return
        self._show_selected_result()

    def _show_selected_result(self, *, force_live: bool = False) -> None:
        row_index = self.result_table.currentRow()
        if row_index < 0 or row_index >= len(self.result_rows):
            self.copy_button.setEnabled(False)
            self._update_three_stage_button(None)
            return
        row = self.result_rows[row_index]
        self._update_three_stage_button(row)
        if not force_live:
            snapshot = self.law_cache.load_snapshot(row)
            if snapshot is not None:
                self._active_detail_row = dict(row)
                self._replace_detail_content(
                    html=str(snapshot.get("html") or ""), source_font_size=10
                )
                self._update_three_stage_button(self._active_detail_row)
                replace_search_term_backgrounds(
                    self.detail_view, self.highlight_terms
                )
                self.current_detail_text = str(
                    snapshot.get("plain_text") or ""
                )
                self.copy_button.setEnabled(bool(self.current_detail_text))
                self._restore_cached_formatting(snapshot)
                self._restore_cached_memos(snapshot)
                self.status_label.setText(
                    f"{row.get('name', '')} {row.get('provision', '')} 저장된 본문 열기"
                )
                return
        metadata = [
            ("구분", row["kind"]),
            ("조문·별표", row["provision"]),
            ("시행일자", row["date"]),
            ("소관기관", row["agency"]),
            ("공포·발령일자", row["publication_date"]),
            ("공포·발령번호", row["publication_number"]),
        ]
        html_parts, plain_parts = detail_document_header(
            row["name"], metadata, self.highlight_terms
        )
        if row["content"]:
            # 법령검색 탭과 같은 규칙으로 링크를 건다. 행정규칙은 조문 번호
            # 체계가 달라 자기 참조 링크를 만들지 않는다.
            is_admin_rule = str(row.get("kind") or "").startswith("행정규칙")
            content_html = body_to_html(
                row["content"],
                self.highlight_terms,
                current_law_name="" if is_admin_rule else row["name"],
                current_law_id=(
                    "" if is_admin_rule else str(row.get("source_id") or "")
                ),
                use_api_links=True,
                administrative_rule=is_admin_rule,
                embedded_images=(
                    row.get("embedded_images")
                    if is_admin_rule
                    and isinstance(row.get("embedded_images"), dict)
                    else None
                ),
            )
            html_parts.append("<h2>조문내용</h2>")
            html_parts.append(f'<div class="content">{content_html}</div>')
            plain_parts.extend(
                (
                    "",
                    "[조문내용]",
                    (
                        admin_rule_plain_text(row["content"])
                        if is_admin_rule
                        else row["content"]
                    ),
                )
            )
        else:
            if self.is_related:
                error = row.get("article_error", "")
                note = (
                    f"해당 조문을 불러오지 못했습니다: {error}"
                    if error
                    else "선택한 연관법령의 해당 조문을 불러오는 중입니다."
                )
            else:
                note = "이 검색범위의 API 응답에는 별표·서식 본문이 포함되지 않습니다."
            html_parts.append("<h2>안내</h2>")
            html_parts.append(f'<div class="content">{escape(note)}</div>')
            plain_parts.extend(("", "[안내]", note))
        rendered_html = "".join(html_parts)
        self._active_detail_row = dict(row) if row["content"] else None
        self._replace_detail_content(html=rendered_html, source_font_size=10)
        self._update_three_stage_button(self._active_detail_row)
        self._set_visible_memos([])
        self.current_detail_text = "\n".join(plain_parts)
        self.copy_button.setEnabled(True)
        if row["content"]:
            self.law_cache.save_snapshot(
                row,
                # 자동 검색 음영은 검색어마다 달라지므로 저장하지 않는다.
                # 다시 열 때 현재 검색어만 정확히 적용한다.
                html=strip_search_highlight_html(rendered_html),
                plain_text=self.current_detail_text,
            )
            self._finalize_pending_favorite(row)
        if (
            self.is_related
            and not row["content"]
            and not row.get("article_loading")
            and not row.get("article_error")
        ):
            self._request_related_article(row_index, row)

    def open_cached_snapshot(self, record: dict[str, object]) -> None:
        """열람내역의 직접검색·연관법령 저장 화면을 다시 표시."""
        row = record.get("row")
        html = record.get("html")
        if not isinstance(row, dict) or not isinstance(html, str):
            raise ValueError("저장 파일에 본문 화면이 없습니다.")
        self._active_detail_row = dict(row)
        self._replace_detail_content(html=html, source_font_size=10)
        self._update_three_stage_button(self._active_detail_row)
        replace_search_term_backgrounds(self.detail_view, self.highlight_terms)
        self.detail_view.moveCursor(QTextCursor.MoveOperation.Start)
        self.current_detail_text = str(record.get("plain_text") or "")
        self.copy_button.setEnabled(bool(self.current_detail_text))
        self._restore_cached_formatting(record)
        self._restore_cached_memos(record)
        self._set_reading_mode(True)
        name = str(row.get("name") or "저장 본문")
        provision = str(row.get("provision") or "").strip()
        self.status_label.setText(
            f"{name}{f' {provision}' if provision else ''} 저장된 본문 열기 · API 호출 없음"
        )

    def _three_stage_target(
        self, row: dict[str, object] | None
    ) -> dict[str, str] | None:
        """행이 법령 조문이면 3단비교에 필요한 값을 돌려준다."""
        if not isinstance(row, dict):
            return None
        if str(row.get("kind") or "").startswith("행정규칙"):
            return None
        law_id = str(row.get("source_id") or "").strip()
        jo = str(row.get("jo_code") or "").strip()
        if not law_id or not jo:
            return None
        return {
            "law_id": law_id,
            "jo": jo,
            "law_name": str(row.get("name") or "법령"),
            "label": str(row.get("provision") or "").strip(),
        }

    def _update_three_stage_button(
        self, row: dict[str, object] | None
    ) -> None:
        """현재 본문이 법령 조문일 때만 조문 안에 버튼을 둔다."""
        target = self._three_stage_target(row)
        available = target is not None and self.reference_tab is not None
        self.three_stage_button.setEnabled(available)
        if not available or not isinstance(row, dict):
            self._three_stage_position = -1
            self.three_stage_button.hide()
            return
        provision = str(row.get("provision") or "").strip()
        plain_text = self.detail_view.toPlainText()
        self._three_stage_position = plain_text.rfind(provision) if provision else -1
        if self._three_stage_position < 0:
            self.three_stage_button.hide()
            return
        cursor = QTextCursor(self.detail_view.document())
        cursor.setPosition(self._three_stage_position)
        block_format = cursor.blockFormat()
        block_format.setTopMargin(32.0)
        cursor.setBlockFormat(block_format)
        self._position_inline_three_stage_button()

    def _position_inline_three_stage_button(self, _value: object = None) -> None:
        if self._three_stage_position < 0 or not self.three_stage_button.isEnabled():
            self.three_stage_button.hide()
            return
        cursor = QTextCursor(self.detail_view.document())
        cursor.setPosition(self._three_stage_position)
        rect = self.detail_view.cursorRect(cursor)
        y = rect.top() - self.three_stage_button.height() - 4
        visible = rect.bottom() >= 0 and y <= self.detail_view.viewport().height()
        if not visible:
            self.three_stage_button.hide()
            return
        self.three_stage_button.move(max(1, rect.left() - 7), y)
        self.three_stage_button.show()
        self.three_stage_button.raise_()

    def eventFilter(self, watched, event) -> bool:
        if (
            hasattr(self, "detail_view")
            and watched is self.detail_view.viewport()
            and event.type() in (QEvent.Type.Resize, QEvent.Type.Show)
        ):
            QTimer.singleShot(0, self._position_inline_three_stage_button)
        return super().eventFilter(watched, event)

    def _open_three_stage_comparison(self) -> None:
        """현재 본문 조문의 3단비교를 법령검색 탭 팝업으로 연다."""
        target = self._three_stage_target(self._active_detail_row)
        if target is None:
            self.status_label.setText(
                "이 항목은 3단비교를 지원하지 않습니다."
            )
            return
        if self.reference_tab is None:
            self.status_label.setText(
                "3단비교를 열 법령검색 화면을 찾지 못했습니다."
            )
            return
        self.reference_tab.open_three_stage_for_article(**target)

    def _detail_link_clicked(self, url: QUrl) -> None:
        """조문 참조는 법령검색 탭 팝업으로, 나머지는 브라우저로 연다."""
        if url.scheme().casefold() == "lawref":
            if self.reference_tab is None:
                self.status_label.setText(
                    "조문 참조를 열 법령검색 화면을 찾지 못했습니다."
                )
                return
            self.reference_tab.open_reference_link(url)
            return
        if url.scheme().casefold() not in ("http", "https"):
            self.status_label.setText("지원하지 않는 링크 형식입니다.")
            return
        if QDesktopServices.openUrl(url):
            self.status_label.setText(
                "법령 링크를 웹 브라우저에서 열었습니다."
            )
        else:
            QMessageBox.warning(
                self, "링크 열기 실패", "법령 링크를 열지 못했습니다."
            )

    def copy_detail(self) -> None:
        if not self.current_detail_text:
            return
        QApplication.clipboard().setText(self.current_detail_text)
        self.status_label.setText("본문을 클립보드에 복사했습니다.")
