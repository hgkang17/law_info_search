"""중앙부처 질의회신·법령해석례·판례 검색 화면."""

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
    StableHorizontalTableWidget,
    batch_table_updates,
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
    EXPC_AGENCY,
    PREC_AGENCY,
)
from storage.cache import LawDocumentCache, SearchResultCache
from storage.recent import RecentSearchManager
from storage.paths import (
    SEARCH_RESULT_CACHE_DIR,
)
from workers.search_worker import (
    ApiWorker,
)
from utils.constants import (
    DEFAULT_DETAIL_FONT_POINT,
    DETAIL_FONT_FAMILY,
    FONT_FAMILY,
)
from utils.formatting import (
    body_to_html,
    detail_document_header,
    strip_search_highlight_html,
)
from utils.parsing import (
    deserialize_agency_search_payload,
    row_search_text,
    search_terms,
    whitespace_insensitive_contains,
    serialize_agency_search_payload,
)
from PySide6.QtCore import QRect, QTimer, QUrl, Qt
from PySide6.QtGui import QColor, QDesktopServices, QFont, QKeySequence, QShortcut, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QAbstractItemView, QApplication, QDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QSizePolicy, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
from html import escape
from molit_cgm_expc_api import (
    AGENCIES,
    AGENCY_BY_TARGET,
    AgencyConfig,
    _find_text,
)
from ui.dialogs import _position_dialog_beside


# 화면 이름 띠의 높이. 법령검색 화면의 검색칸 시작 자리와 맞춘 값이다.
PAGE_HEADING_HEIGHT = 50


class LawSearchTab(QWidget):
    """중앙부처 1차 해석과 법령해석례가 공유하는 검색 탭."""

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
        self.worker: ApiWorker | None = None
        self.result_rows: list[dict[str, object]] = []
        self._pending_detail_row: dict[str, object] | None = None
        self._pending_favorite_row: dict[str, object] | None = None
        self._active_detail_row: dict[str, object] | None = None
        self._visible_memos: list[dict[str, object]] = []
        self._updating_cache_checks = False
        self.current_detail_text = ""
        self.highlight_terms: tuple[str, ...] = ()
        self.is_central = service == "central"
        self.is_expc = service == "expc"
        self.is_prec = service == "prec"
        self.detail_font_size = self._saved_font_size(
            f"{service}_detail_font_size", DEFAULT_DETAIL_FONT_POINT
        )
        self.detail_font_family = str(
            self.recent_search_manager.settings.value(
                f"{service}_detail_font_family", DETAIL_FONT_FAMILY
            )
            or DETAIL_FONT_FAMILY
        )
        self._reading_mode = False
        self._normal_window_margins: tuple[int, int, int, int] | None = None
        self.ai_chat_panel: AiChatPanel | None = None
        self._build_ui()
        install_text_color_shortcuts(self)
        self.law_cache.changed.connect(self._refresh_snapshot_checks)

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
        # 위아래 여백을 두지 않는다. 왼쪽 메뉴 카드는 이 탭 바깥에 있어
        # 여기 여백만큼 본문이 늦게 시작하고 먼저 끝나 두 칸의 위아래 선이
        # 어긋난다.
        root.setContentsMargins(12, 0, 12, 0)
        root.setSpacing(14)

        page_names = {
            "central": "중앙부처 질의회신",
            "expc": "법령해석례",
            "prec": "판례",
        }
        self.page_heading = QFrame()
        self.page_heading.setObjectName("pageHeadingTrack")
        # 법령검색 화면에서 검색칸이 시작하는 자리(64px)와 같아지도록 잡은
        # 값이다. 여기가 어긋나면 화면을 오갈 때 검색칸이 위아래로 흔들린다.
        # 값을 바꿀 때는 tests/test_search_row_alignment.py를 함께 본다.
        self.page_heading.setFixedHeight(PAGE_HEADING_HEIGHT)
        page_heading_layout = QHBoxLayout(self.page_heading)
        page_heading_layout.setContentsMargins(12, 0, 12, 0)
        self.page_heading_label = QLabel(page_names.get(self.service, self.service))
        self.page_heading_label.setObjectName("pageHeadingLabel")
        page_heading_layout.addWidget(
            self.page_heading_label, 0, Qt.AlignmentFlag.AlignVCenter
        )
        page_heading_layout.addStretch(1)
        root.addWidget(self.page_heading)

        search_card = QFrame()
        search_card.setObjectName("card")
        search_layout = QHBoxLayout(search_card)
        search_layout.setContentsMargins(10, 12, 10, 12)
        search_layout.setSpacing(8)

        self.agency_combo: DropdownComboBox | None = None
        if self.is_central:
            self.agency_combo = DropdownComboBox()
            self.agency_combo.addItem("전체 기관", "__all__")
            for agency in AGENCIES:
                self.agency_combo.addItem(agency.name, agency.target)
            self.agency_combo.setCurrentIndex(
                self.agency_combo.findData("molitCgmExpc")
            )
            self.agency_combo.setMaxVisibleItems(15)
            self.agency_combo.setFixedWidth(SEARCH_COMBO_WIDTH)
            search_layout.addWidget(self.agency_combo)

        self.scope_combo = DropdownComboBox()
        scope_label = (
            "안건명"
            if self.is_central
            else "해석례명" if self.is_expc else "판례명"
        )
        self.scope_combo.addItem(scope_label, 1)
        self.scope_combo.addItem("본문", 2)
        self.scope_combo.setFixedWidth(SEARCH_COMBO_WIDTH)

        self.query_input = QLineEdit()
        self.query_input.setPlaceholderText("검색어를 입력하세요")
        self.query_input.setClearButtonEnabled(True)
        self.query_input.returnPressed.connect(self.start_search)

        self.search_button = QPushButton("검색")
        self.search_button.setObjectName("primaryButton")
        self.search_button.setFixedWidth(56)
        self.search_button.clicked.connect(self.start_search)

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

        if self.is_central:
            headers = ["저장", "기관", "안건명", "안건번호", "해석일자", "질의기관"]
        elif self.is_expc:
            headers = ["저장", "안건명", "안건번호", "회신일자", "질의기관"]
        else:
            headers = ["저장", "사건명", "사건번호", "선고일자", "법원명", "데이터출처"]
        self.title_column = 2 if self.is_central else 1
        self.result_table = StableHorizontalTableWidget(0, len(headers))
        self.result_table.setAccessibleName("검색 결과 표")
        self.result_empty_label = ResultOverlayLabel(self.result_table.viewport())
        self.result_table.setHorizontalHeader(
            ResultHeaderView(Qt.Orientation.Horizontal, self.result_table)
        )
        self.result_table.setHorizontalHeaderLabels(headers)
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
        self.title_highlight_delegate = FavoriteTitleDelegate(
            self._toggle_favorite_at_row,
            self._is_favorite_at_row,
            self.result_table,
        )
        self.save_check_delegate = CenteredCheckDelegate(self.result_table)
        self.result_table.setItemDelegateForColumn(0, self.save_check_delegate)
        self.result_table.setItemDelegateForColumn(
            self.title_column, self.title_highlight_delegate
        )
        self.result_table.verticalHeader().setVisible(False)
        configure_adaptive_result_rows(
            self.result_table, (self.title_column,)
        )
        table_header = self.result_table.horizontalHeader()
        table_header.setStretchLastSection(False)
        for column in range(len(headers)):
            mode = (
                QHeaderView.ResizeMode.Stretch
                if column == self.title_column
                else QHeaderView.ResizeMode.ResizeToContents
            )
            table_header.setSectionResizeMode(column, mode)
        self.result_table.itemSelectionChanged.connect(
            self._selection_changed
        )
        self.result_table.itemChanged.connect(self._snapshot_check_changed)
        self.result_table.cellDoubleClicked.connect(
            self._open_detail_expanded
        )
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
        self.detail_view.setOpenExternalLinks(True)
        self.detail_view.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self.detail_view.viewport().setCursor(Qt.CursorShape.IBeamCursor)
        self.detail_view.setPlaceholderText(
            "검색 결과에서 항목을 더블클릭하면 본문을 조회합니다."
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
        # 처음에는 법령검색과 똑같이 검색 조건과 결과 목록만 전체 폭으로
        # 보여 준다. 질의회신·해석례·판례 본문은 결과를 두 번 눌렀을 때만
        # 오른쪽 분할 화면으로 연다.
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
        self.status_label = QLabel("검색어를 입력하고 검색 버튼을 누르세요.")
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
        """검색 목록 옆에 질의회신·해석례·판례 본문 칸을 연다."""
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

    def _hide_detail_split(self) -> None:
        """새 검색에서는 본문 칸을 닫고 결과 목록을 다시 넓힌다."""
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
        """AI가 현재 사례 본문 또는 사용자가 드래그한 부분을 근거로 삼는다."""
        selected = self.detail_view.textCursor().selectedText()
        if selected.strip():
            return selected.replace(" ", "\n"), "선택한 부분"
        return self.detail_view.toPlainText(), "본문 전체"

    def _resource_action(self, name: str, *args: object):
        """AI 답변의 법령 링크·즐겨찾기를 기존 법령검색 기능에 맡긴다."""
        resource_tab = getattr(self.window(), "resource_tab", None)
        action = getattr(resource_tab, name, None)
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

        # 독립 AI 화면·법령 본문 AI와 같은 저장 채팅을 쓰므로, 어느 곳에서
        # 목록을 비워도 이미 열린 패널들이 즉시 함께 비운다.
        window = self.window()
        peers = [
            getattr(window, "ai_review_tab", None),
            getattr(getattr(window, "resource_tab", None), "ai_chat_panel", None),
        ]
        for tab_name in ("central_tab", "expc_tab", "prec_tab"):
            peer_tab = getattr(window, tab_name, None)
            peers.append(getattr(peer_tab, "ai_chat_panel", None))
        for peer in peers:
            if peer is None or peer is panel:
                continue
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
        """필요할 때 만든 AI 패널의 백그라운드 작업을 앱 종료 전에 정리."""
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
            if central_layout is not None:
                self._normal_window_margins = central_layout.getContentsMargins()
            self.detail_card.show()

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

        if central_layout is not None:
            if self._normal_window_margins is not None:
                central_layout.setContentsMargins(*self._normal_window_margins)
        self.root_layout.setContentsMargins(
            0 if expanded else 12,
            0 if expanded else 12,
            0 if expanded else 12,
            0 if expanded else 12,
        )

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
        family = str(font.family() or DETAIL_FONT_FAMILY)
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
        preserve_existing_formatting: bool = True,
    ) -> None:
        previous_text = (
            self.detail_view.toPlainText() if preserve_existing_formatting else ""
        )
        previous_base_foregrounds = (
            capture_base_foreground_spans(self.detail_view.document())
            if preserve_existing_formatting
            else []
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
        """본문에서 드래그해 둔 구간을 돌려준다. 없으면 아무 일도 하지 않는다.

        색을 먼저 골라 두고 그 다음 글자를 드래그하는 순서로도 쓸 수 있어야
        한다. 예전에는 선택이 없으면 대화상자를 띄워 그 순서를 막았다.
        고르기만 한 것으로는 아무 일도 일어나지 않으면 그만이라, 굳이
        알림을 띄우지 않는다.
        """
        cursor = self.detail_view.textCursor()
        if cursor.hasSelection():
            return cursor
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

        excerpt = cursor.selectedText().replace(" ", " ").strip()
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
        self.title_highlight_delegate.set_terms(())
        replace_search_term_backgrounds(self.detail_view, ())
        self.result_table.viewport().update()
        self.search_shade_reset_button.setEnabled(False)
        self.status_label.setText("검색어 음영을 초기화했습니다.")

    def _search_cache_target(self) -> str:
        if self.is_central and self.agency_combo is not None:
            return f"central_{self.agency_combo.currentData()}"
        return self.service

    def _refresh_search_from_api(self) -> None:
        self.start_search(force_api=True)

    def start_search(self, *_args: object, force_api: bool = False) -> None:
        query = self.query_input.text().strip()
        if not query:
            QMessageBox.information(self, "검색어 확인", "검색어를 입력해 주세요.")
            self.query_input.setFocus()
            return

        self._hide_detail_split()
        self.recent_search_manager.add(query)
        self.highlight_terms = search_terms(query)
        self.search_shade_reset_button.setEnabled(bool(self.highlight_terms))
        self.title_highlight_delegate.set_terms(self.highlight_terms)
        self.result_table.viewport().update()
        self.result_table.setRowCount(0)
        self.result_rows.clear()
        self.result_count.setText("0건")
        self.result_empty_label.show_message("검색 중…")
        self.detail_view.clear()
        self.current_detail_text = ""
        self.copy_button.setEnabled(False)

        if self.is_central:
            selected_target = str(self.agency_combo.currentData())
            if selected_target == "__all__":
                agencies = AGENCIES
                agency_label = "전체 기관"
            else:
                agencies = (AGENCY_BY_TARGET[selected_target],)
                agency_label = agencies[0].name
        elif self.is_expc:
            agencies = (EXPC_AGENCY,)
            agency_label = "법령해석례"
        else:
            agencies = (PREC_AGENCY,)
            agency_label = "판례"

        search_scope = int(self.scope_combo.currentData())
        cache_target = self._search_cache_target()
        if not force_api:
            cached = self.search_result_cache.load(
                cache_target, query, search_scope
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
                agencies=agencies,
                parent=self,
            ),
            f"{agency_label}에서 '{query}' 검색 중...",
        )

    def _start_worker(self, worker: ApiWorker, message: str) -> None:
        if self.worker and self.worker.isRunning():
            return
        self.worker = worker
        self._set_busy(True, message)
        worker.succeeded.connect(self._worker_succeeded)
        worker.failed.connect(self._worker_failed)
        worker.finished.connect(self._worker_finished)
        worker.start()

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.search_button.setEnabled(not busy)
        if self.search_refresh_button is not None:
            self.search_refresh_button.setEnabled(not busy)
        if not busy:
            self._selection_changed()
        self.query_input.setEnabled(not busy)
        self.scope_combo.setEnabled(not busy)
        if self.agency_combo is not None:
            self.agency_combo.setEnabled(not busy)
        self._progress_opacity.setOpacity(1.0 if busy else 0.0)
        if message:
            self.status_label.setText(message)

    def _worker_finished(self) -> None:
        self._set_busy(False)
        if self.worker:
            self.worker.deleteLater()
        self.worker = None

    def _worker_succeeded(self, operation: str, payload: object) -> None:
        try:
            if operation == "search":
                self._show_search_results(payload)
                worker = self.worker
                if isinstance(worker, ApiWorker):
                    serialized = serialize_agency_search_payload(payload)
                    if self.search_result_cache.save(
                        self._search_cache_target(),
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
            else:
                self._show_detail(payload)
        except Exception as exc:
            self._worker_failed(operation, str(exc))

    def _worker_failed(self, operation: str, error: str) -> None:
        action = "검색" if operation == "search" else "본문 조회"
        self.status_label.setText(f"{action}에 실패했습니다.")
        if operation == "detail":
            self._pending_detail_row = None
            self._refresh_snapshot_checks()
        QMessageBox.critical(
            self,
            f"{action} 실패",
            f"{action} 중 오류가 발생했습니다.\n\n{error}",
        )

    def _show_search_results(self, payload: object) -> None:
        roots = payload["roots"]
        request_errors = list(payload["errors"])
        rows: list[dict[str, object]] = []
        total_count = 0
        response_errors: list[tuple[AgencyConfig, str]] = []
        if self.is_central:
            item_tag = "cgmexpc"
            id_tag = "법령해석일련번호"
            title_tag = "안건명"
            case_tag = "안건번호"
            date_tag = "해석일자"
        elif self.is_expc:
            item_tag = "expc"
            id_tag = "법령해석례일련번호"
            title_tag = "안건명"
            case_tag = "안건번호"
            date_tag = "회신일자"
        else:
            item_tag = "prec"
            id_tag = "판례일련번호"
            title_tag = "사건명"
            case_tag = "사건번호"
            date_tag = "선고일자"

        for agency, root in roots:
            result_code = _find_text(root, "resultCode")
            result_msg = _find_text(root, "resultMsg")
            if result_code and result_code != "00":
                response_errors.append(
                    (agency, f"{result_code} {result_msg}".strip())
                )
                continue

            agency_rows = 0
            for node in root.iter():
                tag_name = str(node.tag).rsplit("}", 1)[-1].lower()
                if tag_name != item_tag or "id" not in node.attrib:
                    continue
                item_id = _find_text(node, id_tag)
                title = _find_text(node, title_tag)
                if not item_id and not title:
                    continue
                rows.append(
                    {
                        "agency": agency.name,
                        "target": agency.target,
                        "detail_available": agency.detail_available,
                        "id": item_id,
                        "id_tag": id_tag,
                        "title": title,
                        "case_number": _find_text(node, case_tag),
                        "date": _find_text(node, date_tag),
                        "inquiry_org": _find_text(node, "질의기관명"),
                        "court": _find_text(node, "법원명"),
                        "data_source": _find_text(node, "데이터출처명"),
                    }
                )
                agency_rows += 1

            try:
                total_count += int(_find_text(root, "totalCnt"))
            except (TypeError, ValueError):
                total_count += agency_rows

        all_errors = request_errors + response_errors
        if not roots and all_errors:
            summary = "\n".join(
                f"{agency.name}: {message}"
                for agency, message in all_errors[:8]
            )
            raise ValueError(summary)

        rows.sort(key=lambda row: 0 if self.law_cache.has_snapshot(row) else 1)
        self.result_rows = rows
        self.result_filter_input.clear()
        self._updating_cache_checks = True
        try:
            with batch_table_updates(self.result_table):
                self.result_table.setRowCount(len(rows))
                for row_index, row in enumerate(rows):
                    self.result_table.setItem(
                        row_index, 0, self._snapshot_item_for_row(row)
                    )
                    if self.is_prec:
                        values = (
                            str(row["title"]),
                            str(row["case_number"]),
                            str(row["date"]),
                            str(row["court"]),
                            str(row["data_source"]),
                        )
                    else:
                        common_values = (
                            str(row["title"]),
                            str(row["case_number"]),
                            str(row["date"]),
                            str(row["inquiry_org"]),
                        )
                        values = (
                            (str(row["agency"]),) + common_values
                            if self.is_central
                            else common_values
                        )
                    for column, value in enumerate(values, start=1):
                        display_value = (
                            " ".join(value.split())
                            if column == self.title_column
                            else value
                        )
                        item = QTableWidgetItem(display_value)
                        if column == self.title_column:
                            item.setToolTip(display_value)
                            font = item.font()
                            font.setFamily(FONT_FAMILY)
                            font.setWeight(QFont.Weight.Medium)
                            item.setFont(font)
                        else:
                            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        self.result_table.setItem(row_index, column, item)
        finally:
            self._updating_cache_checks = False

        resize_adaptive_result_rows(self.result_table)
        self.result_count.setText(f"{total_count}건")
        status = f"검색 완료: 총 {total_count}건 중 {len(rows)}건을 불러왔습니다."
        if all_errors:
            status += f" ({len(all_errors)}개 기관 조회 실패)"
            self.status_label.setToolTip(
                "\n".join(
                    f"{agency.name}: {message}"
                    for agency, message in all_errors
                )
            )
        else:
            self.status_label.setToolTip("")
        self.status_label.setText(status)
        if rows:
            self.result_empty_label.clear_message()
            self.result_table.selectRow(0)
        else:
            self.result_empty_label.show_message("검색 결과가 없습니다.")
            self.detail_view.setPlainText("검색 결과가 없습니다.")

    def _snapshot_item_for_row(
        self, row: dict[str, object]
    ) -> QTableWidgetItem:
        item = QTableWidgetItem()
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        flags = Qt.ItemFlag.ItemIsEnabled
        external_prec = bool(
            self.is_prec and "국세" in str(row.get("data_source", ""))
        )
        if not bool(row.get("detail_available")) or external_prec:
            item.setCheckState(Qt.CheckState.Unchecked)
            flags = Qt.ItemFlag.NoItemFlags
            item.setToolTip(
                "API 본문이 제공되지 않아 저장할 수 없는 결과입니다."
            )
        else:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
            if self.law_cache.has_snapshot(row):
                item.setCheckState(Qt.CheckState.Checked)
                item.setToolTip(
                    "저장된 본문입니다. 체크를 풀면 저장 본문 파일을 삭제합니다."
                )
            else:
                item.setCheckState(Qt.CheckState.Unchecked)
                item.setToolTip("체크하거나 본문을 열면 자동 저장됩니다.")
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
            if self.worker and self.worker.isRunning():
                self.status_label.setText(
                    "다른 API 요청이 끝난 뒤 즐겨찾기를 설정해 주세요."
                )
                return
            self._pending_favorite_row = row
            self.result_table.selectRow(row_index)
            self._request_detail(row, force_api=False)
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
        if str(pending.get("id")) != str(saved_row.get("id")):
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
        if self.worker and self.worker.isRunning():
            self.status_label.setText(
                "다른 API 요청이 끝난 뒤 저장 체크를 해제해 주세요."
            )
            self._refresh_snapshot_checks()
            return
        self.result_table.selectRow(row_index)
        self._request_detail(row, force_api=False)

    def _selection_changed(self) -> None:
        row = self.result_table.currentRow()
        has_selection = 0 <= row < len(self.result_rows)

        # 목록만 보이는 동안에는 선택 표시만 바꾼다. 첫 행 자동 선택이나
        # 목록을 훑는 한 번 누르기로 숨은 본문을 미리 만들지 않는다.
        # 더블클릭으로 분할 화면을 연 뒤에는 기존처럼 한 번 누른 항목의
        # 저장 본문 또는 조회 안내를 오른쪽에 보여 준다.
        if not has_selection or self.detail_card.isHidden():
            return
        selected = self.result_rows[row]
        if self.law_cache.has_snapshot(selected):
            self._request_detail(selected, force_api=False)
            return
        self._show_selection_preview(selected)

    def _show_selection_preview(self, selected: dict[str, object]) -> None:
        """저장되지 않은 검색 결과의 정보와 본문 조회 안내를 표시한다."""
        self._active_detail_row = None
        self._pending_detail_row = None
        self._set_visible_memos([])

        metadata = [
            ("조회 기관", str(selected.get("agency") or "")),
            ("ID", str(selected.get("id") or "")),
            ("안건번호", str(selected.get("case_number") or "")),
            ("해석일자", str(selected.get("date") or "")),
            ("질의기관명", str(selected.get("inquiry_org") or "")),
        ]
        if self.is_prec:
            metadata = [
                ("법원명", str(selected.get("court") or "")),
                ("ID", str(selected.get("id") or "")),
                ("사건번호", str(selected.get("case_number") or "")),
                ("선고일자", str(selected.get("date") or "")),
                ("데이터출처명", str(selected.get("data_source") or "")),
            ]
        metadata = [(label, value) for label, value in metadata if value]
        note = (
            "본문을 조회하려면 검색 결과를 더블클릭하세요.\n"
            "조회한 본문은 저장되어 다음부터 API 호출 없이 바로 열립니다.\n"
            "저장 체크를 풀면 저장된 본문 파일을 삭제합니다."
        )
        html_parts, plain_parts = detail_document_header(
            str(selected.get("title") or "검색 결과"),
            metadata,
            self.highlight_terms,
        )
        html_parts.append("<h2>안내</h2>")
        html_parts.append(f'<div class="content">{body_to_html(note, ())}</div>')
        plain_parts.extend(("", "[안내]", note))

        self._replace_detail_content(html="".join(html_parts), source_font_size=10)
        self.current_detail_text = "\n".join(plain_parts)
        self.copy_button.setEnabled(False)
        self.status_label.setText(
            "항목을 선택했습니다. 더블클릭하면 본문을 불러옵니다."
        )

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

    def _open_detail_expanded(self, *_args: object) -> None:
        """검색결과 더블클릭: 본문을 열고 바로 크게 보기로 전환한다."""
        row = self.result_table.currentRow()
        if row < 0 or row >= len(self.result_rows):
            return
        if self._request_detail(self.result_rows[row]):
            self._set_reading_mode(True)

    def open_selected_detail(self, *_args: object) -> bool:
        row = self.result_table.currentRow()
        if row < 0 or row >= len(self.result_rows):
            QMessageBox.information(self, "항목 선택", "조회할 항목을 선택해 주세요.")
            return False
        return self._request_detail(self.result_rows[row])

    def _request_detail(
        self, selected: dict[str, object], *, force_api: bool = False
    ) -> bool:
        if self.is_prec and "국세" in str(selected.get("data_source", "")):
            item_id = str(selected["id"])
            url = QUrl(
                "https://www.law.go.kr/LSW/precInfoP.do"
                f"?precSeq={item_id}&mode=0"
            )
            if not QDesktopServices.openUrl(url):
                QMessageBox.warning(
                    self, "원문 열기 실패", "판례 원문 페이지를 열지 못했습니다."
                )
                return False
            self.status_label.setText(
                f"국세청 판례 ID {item_id} 원문 페이지를 열었습니다."
            )
            return False
        if not force_api:
            snapshot = self.law_cache.load_snapshot(selected)
            if snapshot is not None:
                self._active_detail_row = dict(selected)
                self._replace_detail_content(
                    html=str(snapshot.get("html") or ""),
                    source_font_size=10,
                    preserve_existing_formatting=False,
                )
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
                    f"{selected.get('agency', '')} ID {selected.get('id', '')} 저장된 본문 열기"
                )
                return True
        if not selected["detail_available"]:
            QMessageBox.information(
                self,
                "본문 조회 미제공",
                f"{selected['agency']}는 본문 조회 API를 제공하지 않습니다.",
            )
            return False
        self._pending_detail_row = dict(selected)
        item_id = str(selected["id"])
        agency = (
            AGENCY_BY_TARGET[str(selected["target"])]
            if self.is_central
            else EXPC_AGENCY if self.is_expc else PREC_AGENCY
        )
        self._start_worker(
            ApiWorker(
                "detail",
                oc=self.oc_provider().strip(),
                item_id=item_id,
                agency=agency,
                parent=self,
            ),
            f"{agency.name} ID {item_id} 본문 조회 중...",
        )
        return True

    def open_cached_snapshot(self, record: dict[str, object]) -> None:
        """열람내역의 질의회신·해석례·판례 저장 화면을 다시 표시."""
        row = record.get("row")
        html = record.get("html")
        if not isinstance(row, dict) or not isinstance(html, str):
            raise ValueError("저장 파일에 본문 화면이 없습니다.")
        self._active_detail_row = dict(row)
        self._replace_detail_content(
            html=html,
            source_font_size=10,
            preserve_existing_formatting=False,
        )
        replace_search_term_backgrounds(self.detail_view, self.highlight_terms)
        self.detail_view.moveCursor(QTextCursor.MoveOperation.Start)
        self.current_detail_text = str(record.get("plain_text") or "")
        self.copy_button.setEnabled(bool(self.current_detail_text))
        self._restore_cached_formatting(record)
        self._restore_cached_memos(record)
        self._set_reading_mode(True)
        title = str(row.get("title") or row.get("name") or "저장 본문")
        self.status_label.setText(f"{title} 저장된 본문 열기 · API 호출 없음")

    def _show_detail(self, payload: object) -> None:
        root = payload["root"]
        agency = payload["agency"]
        if self.is_central:
            title_tag = "안건명"
            id_tag = "법령해석일련번호"
            fallback_title = f"{agency.name} 법령해석"
        elif self.is_expc:
            title_tag = "안건명"
            id_tag = "법령해석례일련번호"
            fallback_title = "법령해석례"
        else:
            title_tag = "사건명"
            id_tag = "판례정보일련번호"
            fallback_title = "판례"
        title = _find_text(root, title_tag) or fallback_title
        item_id = _find_text(root, id_tag)
        primary_content_tag = "판례내용" if self.is_prec else "질의요지"
        if not item_id and not _find_text(root, primary_content_tag):
            message = "".join(root.itertext()).strip()
            raise ValueError(message or "본문 응답을 파싱하지 못했습니다.")

        metadata = []
        if self.is_central:
            metadata.append(("조회 기관", agency.name))
        if self.is_central:
            metadata_fields = (
                "법령해석일련번호",
                "안건번호",
                "해석일자",
                "해석기관명",
                "질의기관명",
                "대분류",
                "중분류",
                "소분류",
            )
        elif self.is_expc:
            metadata_fields = (
                "법령해석례일련번호",
                "안건번호",
                "해석일자",
                "해석기관명",
                "질의기관명",
                "등록일시",
            )
        else:
            metadata_fields = (
                "판례정보일련번호",
                "사건번호",
                "선고일자",
                "법원명",
                "사건종류명",
                "판결유형",
            )
        for label in metadata_fields:
            value = _find_text(root, label)
            if value and value.lower() != "null":
                metadata.append((label, value))

        sections = []
        section_fields = (
            ("판시사항", "판결요지", "참조조문", "참조판례", "판례내용")
            if self.is_prec
            else ("질의요지", "회답", "이유", "관련법령")
        )
        for label in section_fields:
            value = _find_text(root, label)
            if value and value.lower() != "null":
                sections.append((label, value))

        html_parts, plain_parts = detail_document_header(
            title, metadata, self.highlight_terms
        )

        for label, value in sections:
            html_parts.append(f"<h2>{escape(label)}</h2>")
            html_parts.append(
                f'<div class="content">{body_to_html(value, self.highlight_terms)}</div>'
            )
            plain_parts.extend(("", f"[{label}]", value))

        self._replace_detail_content(
            html="".join(html_parts), source_font_size=10
        )
        self.current_detail_text = "\n".join(plain_parts)
        self.copy_button.setEnabled(True)
        self._set_visible_memos([])
        if self._pending_detail_row is not None:
            self._active_detail_row = dict(self._pending_detail_row)
            self.law_cache.save_snapshot(
                self._pending_detail_row,
                html=strip_search_highlight_html("".join(html_parts)),
                plain_text=self.current_detail_text,
            )
            self._finalize_pending_favorite(self._pending_detail_row)
            self._pending_detail_row = None
        self.status_label.setText(f"{agency.name} ID {item_id} 본문 조회 완료")

    def close_open_document(self) -> None:
        """열린 본문 표시줄에서 이 화면의 본문을 닫는다.

        법령 본문은 화면 안에 탭이 여러 개라 탭 하나를 지우면 되지만,
        질의회신ㆍ해석례ㆍ판례는 화면 하나에 본문 칸이 붙어 있는 구조다.
        그래서 오랫동안 표시줄에서 지울 방법이 없었고, 한 번 연 본문이
        새 검색을 할 때까지 계속 남았다. 여기서 본문 상태를 비우면
        ``_collect_open_documents``가 다음 갱신에서 이 화면을 뺀다.
        """
        self._active_detail_row = None
        self._pending_detail_row = None
        self.current_detail_text = ""
        self.detail_view.clear()
        self.copy_button.setEnabled(False)
        self._set_visible_memos([])
        self._hide_detail_split()

    def copy_detail(self) -> None:
        if not self.current_detail_text:
            return
        QApplication.clipboard().setText(self.current_detail_text)
        self.status_label.setText("본문을 클립보드에 복사했습니다.")
