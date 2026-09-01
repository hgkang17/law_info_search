"""법령·행정규칙·자치법규 검색과 본문 화면."""

from __future__ import annotations

from ui.assets import (
    ADMIN_RULE_PARSE_VERSION,
    SEARCH_API_REFRESH_TOOLTIP,
)
from ui.theme import (
    BASE_FOREGROUND_PROPERTY,
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
    DeferredWrapTextBrowser,
    DetailSearchBar,
    FavoriteTitleDelegate,
    MemoMarkerBar,
    PairedCategoryBar,
    RecentSearchBar,
    ReferenceHistoryBar,
    ResultHeaderView,
    SearchHighlightDelegate,
    StableHorizontalTableWidget,
    TabStripScrollArea,
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
    LawReferencePopup,
    MemoNoteDialog,
    PdfPreviewPopup,
)
from models.law import (
    KEYWORD_CATEGORY_LABELS,
    KEYWORD_DIRECT_TARGET,
    KEYWORD_RELATED_TARGET,
    RESOURCE_ALL_TARGET,
    RESOURCE_CATEGORIES,
)
from storage.cache import LawDocumentCache, SearchResultCache
from storage.recent import RecentSearchManager
from storage.paths import (
    LAW_REFERENCE_CACHE_DIR,
    LAW_REFERENCE_CACHE_SCHEMA,
    LAW_RENDER_SNAPSHOT_VERSION,
    SEARCH_RESULT_CACHE_DIR,
)
from workers.search_worker import (
    AnnexReferenceWorker,
    ResourceApiWorker,
)
from ui.tabs.ai_chat_panel import AiChatPanel
from llm.inquiries import is_inquiry_target, split_doc_reference
from molit_cgm_expc_api import AGENCY_BY_TARGET, _find_text
from utils.annex_notation import annex_hint_in_query, annex_related_law_name, row_matches_annex_hint
from utils.annex_parse import parse_annex_bytes
from utils.constants import DETAIL_FONT_FAMILY, FONT_FAMILY
from utils.law_download import download_law_file
from utils.formatting import (
    body_to_html,
    detail_document_header,
    full_law_url,
    highlight_html_text,
    law_base_name,
    law_short_name,
)
from utils.parsing import (
    extract_law_article,
    insert_admin_clause_breaks,
    json_list,
    json_text,
    law_unit_code,
    normalize_admin_rule_text,
    row_search_text,
    search_terms,
    whitespace_insensitive_contains,
)
from utils.patterns import (
    CIRCLED_NUMBER_MARKERS,
    KOREAN_ITEM_MARKERS,
    LAW_UNIT_REFERENCE_PATTERN,
)
from utils.three_stage_alignment import (
    block_index_for_unit_or_none,
    hang_groups_from_blocks,
    html_to_plain_text,
    law_content_blocks,
    primary_source_unit,
)
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QTimer, QUrl, QUrlQuery, Qt
from PySide6.QtGui import QBrush, QColor, QCursor, QDesktopServices, QFont, QKeySequence, QShortcut, QTextCharFormat, QTextCursor, QTextDocument, QTextFormat
from PySide6.QtWidgets import QAbstractItemView, QApplication, QComboBox, QDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QMessageBox, QProgressBar, QPushButton, QSizePolicy, QSplitter, QStackedWidget, QTabBar, QTableWidget, QTableWidgetItem, QTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget
from datetime import datetime
from html import escape, unescape
from pathlib import Path
from urllib.parse import quote
import base64
import bisect
import hashlib
import json
import re
import binascii
from urllib.parse import unquote
import xml.etree.ElementTree as ET
from ui.dialogs import _position_dialog_beside


def query_value(query: QUrlQuery, key: str) -> str:
    """링크 질의값을 원래 글자 그대로 읽는다.

    queryItemValue는 기본이 PrettyDecoded라 한글은 풀어 주면서 괄호 같은
    구분자는 %28ㆍ%29로 남긴다. 그대로 쓰면 팝업 제목에 %28이 보이고,
    그 글자로 법제처를 검색해 별표ㆍ서식을 못 찾는다.
    """
    return query.queryItemValue(
        key, QUrl.ComponentFormattingOption.FullyDecoded
    )


# 법제처 별표 목록에는 "[별표 1의7]로 이동" 같은 이동용 껍데기 행이
# 섞여 나온다. 별표 원문이 아니라 목차 안의 길잡이라, 열어 봐야 빈
# 화면이다. 고를 후보에서 먼저 빼 둔다.
_ANNEX_STUB_NAME = re.compile(r"(?:(?:으?로)\s*이동|바로\s*가기)\s*$")


def is_annex_stub_name(value: str) -> bool:
    return bool(_ANNEX_STUB_NAME.search(str(value or "").strip()))


def same_annex_number(left: str, right: str) -> bool:
    """두 이름이 같은 별표 번호를 가리키는지. 한쪽에 번호가 없으면 참.

    이게 없으면 "별표 1"이 "별표 1의7"에 그대로 들어 있어 부분일치로
    엉뚱한 별표가 뽑힌다.
    """
    first = annex_hint_in_query(left)
    second = annex_hint_in_query(right)
    if not first or not second:
        return True
    return first == second


def annex_name_key(value: str) -> str:
    """별표ㆍ서식 이름을 견주기 좋게 다듬는다.

    법제처 이름에는 [별지 제1호서식] 같은 머리표와 괄호ㆍ가운뎃점이
    섞여 있고, 모델이 적는 이름은 그중 일부만 옮긴다. 글자만 남겨
    견주어야 같은 서식을 알아본다.
    """
    text = re.sub(r"\[[^\]]*\]", " ", str(value or ""))
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", text)


def annex_name_similarity(left: str, right: str) -> float:
    """두 이름이 얼마나 겹치는지 0~1로 센다(글자 두 개씩 견주는 방식)."""
    first = annex_name_key(left)
    second = annex_name_key(right)
    if not first or not second:
        return 0.0
    if first == second:
        return 1.0
    if len(first) < 2 or len(second) < 2:
        return 1.0 if first in second or second in first else 0.0
    pairs_a = [first[index : index + 2] for index in range(len(first) - 1)]
    pairs_b = [second[index : index + 2] for index in range(len(second) - 1)]
    shared = 0
    remaining = list(pairs_b)
    for pair in pairs_a:
        if pair in remaining:
            remaining.remove(pair)
            shared += 1
    return 2.0 * shared / (len(pairs_a) + len(pairs_b))


# 본문 조문 링크는 글자 폭이 좁아, 커서 한 점이 살짝 벗어나도
# 팝업이 닫혔다. 링크 주변 이 픽셀까지는 같은 링크 위에 있는 것으로 본다.
_LINK_HOVER_SLACK = 12


def _browser_href_at(browser, position: QPoint) -> str:
    href = str(browser.anchorAt(position) or "").strip()
    if href:
        return href
    for dx, dy in (
        (0, -_LINK_HOVER_SLACK),
        (0, _LINK_HOVER_SLACK),
        (-_LINK_HOVER_SLACK, 0),
        (_LINK_HOVER_SLACK, 0),
        (-_LINK_HOVER_SLACK, -_LINK_HOVER_SLACK),
        (_LINK_HOVER_SLACK, -_LINK_HOVER_SLACK),
        (-_LINK_HOVER_SLACK, _LINK_HOVER_SLACK),
        (_LINK_HOVER_SLACK, _LINK_HOVER_SLACK),
    ):
        candidate = str(
            browser.anchorAt(position + QPoint(dx, dy)) or ""
        ).strip()
        if candidate:
            return candidate
    return ""


class ResourceSearchTab(QWidget):
    """법령·행정규칙·자치법규와 각 별표·서식을 통합 검색."""

    # 조문 제목 왼쪽 별표. 제N조 블록에만 큰 왼쪽 여백을 두면 ①·1. 항호가
    # 조보다 앞에 있는 것처럼 보이므로, 별 크기와 틈만큼만 자리를 낸다.
    _ARTICLE_FAVORITE_SIZE = 24
    _ARTICLE_FAVORITE_GAP = 2
    _ARTICLE_FAVORITE_HEADING_MARGIN = 22.0

    def __init__(
        self,
        oc_provider,
        recent_search_manager: RecentSearchManager,
        law_cache: LawDocumentCache,
        parent=None,
        settings=None,
    ) -> None:
        super().__init__(parent)
        # 본문 옆 대화 패널이 창 쪽과 같은 설정 저장소를 쓰게 물려준다.
        # 같은 파일을 가리키는 QSettings를 따로 만들면 각자 값을 메모리에
        # 들고 있다가 오래된 값을 덮어써서, 넣어 둔 API 키가 잘린 옛날
        # 값으로 되돌아간다.
        self.settings = settings
        self.oc_provider = oc_provider
        self.recent_search_manager = recent_search_manager
        self.law_cache = law_cache
        self.search_result_cache = SearchResultCache(SEARCH_RESULT_CACHE_DIR)
        self.worker: ResourceApiWorker | None = None
        self._annex_worker: AnnexReferenceWorker | None = None
        self.result_rows: list[dict[str, object]] = []
        self.highlight_terms: tuple[str, ...] = ()
        # 연관검색ㆍ직접검색 화면은 main_window가 만들어 넘겨 준다.
        self._keyword_page = None
        self._keyword_page_selector = None
        self.current_detail_text = ""
        self.pending_row: dict[str, object] | None = None
        self._pending_reference_title = "인용 조문"
        self._pending_reference_key = ""
        self._pending_favorite_row: dict[str, object] | None = None
        # 크게 보기에서 대화 패널을 열어 둔 채로 나왔는지. 다시 들어갈 때
        # 그대로 되살린다.
        self._ai_chat_was_open = False
        # 본문을 아직 안 받은 법령의 조항호목을 즐겨찾기에 걸 때, 저장이
        # 끝나기를 기다리는 (row, 조, 항, 호, 목, 이름).
        self._pending_article_favorite: tuple[
            dict[str, object], str, str, str, str, str
        ] | None = None
        self._article_favorite_waiting_for_worker = False
        self._reference_popup_states: dict[str, dict[str, object]] = {}
        # 법령명(공백 제거) -> 법제처 공식 약칭
        self._law_short_name_cache: dict[str, str] = {}
        # 대통령령·부령 위임 링크로 연 조문의 출처(어느 조문이 위임했는지)
        self._pending_delegation_source: dict[str, str] = {}
        self._three_stage_payload_cache: dict[str, dict] = {}
        self._pending_three_stage_article: dict[str, str] = {}
        self._current_three_stage_articles: list[dict[str, object]] = []
        self._three_stage_buttons: list[QPushButton] = []
        # 법령 전문 안의 각 ``제N조`` 왼쪽에 놓는 조문 즐겨찾기 별표.
        # 3단비교 단추와 같은 조문 앵커를 쓰지만, 비교 자료가 없어도 모든
        # 조문에 보여야 하므로 별도 목록으로 관리한다.
        self._article_favorite_buttons: list[QPushButton] = []
        self._three_stage_anchor_positions: dict[str, int] = {}
        self._three_stage_position_pending = False
        self._pending_three_stage_link_request: dict[str, str] | None = None
        self._three_stage_link_request_in_flight: dict[str, str] | None = None
        self._updating_cache_checks = False
        self.detail_font_size = self._saved_font_size(
            "resource_detail_font_size", 10
        )
        self._sort_column = -1
        self._sort_ascending = True
        self._build_ui()
        install_text_color_shortcuts(self)
        self.law_cache.changed.connect(self._refresh_cache_checkmarks)
        # 즐겨찾기 탭에서 별을 풀어도 열려 있는 본문 탭의 별표가 따라간다.
        self.law_cache.changed.connect(self._refresh_document_tab_favorites)
        self.law_cache.changed.connect(self._refresh_reference_popup_favorites)
        self.law_cache.changed.connect(self._refresh_inline_article_favorites)
        self.reference_popup = LawReferencePopup(
            self._detail_link_clicked, self
        )
        self.reference_popup.favorite_checker = self._is_reference_favorite
        self.reference_popup.favoriteRequested.connect(
            self._toggle_reference_favorite
        )
        self.reference_popup.refreshRequested.connect(
            self._refresh_reference_popup
        )
        self.reference_popup.hover_guard = (
            lambda popup=self.reference_popup: self._cursor_over_reference_link(
                popup
            )
        )
        self.reference_popup.browser.verticalScrollBar().valueChanged.connect(
            lambda value, popup=self.reference_popup: (
                self._reference_popup_scrolled(popup, value)
            )
        )
        self._pending_reference_popup = self.reference_popup
        self._pending_document_row: dict[str, object] | None = None
        self._extra_reference_popups: list[LawReferencePopup] = []
        self.three_stage_popup = LawReferencePopup(
            self._detail_link_clicked, self
        )
        self.three_stage_popup.refresh_button.hide()
        self.three_stage_popup.favorite_button.hide()
        self.three_stage_popup.setMinimumSize(720, 360)
        self.three_stage_popup.resize(1040, 650)
        self.three_stage_popup.hover_guard = self._cursor_over_three_stage_button
        self.three_stage_popup.browser.verticalScrollBar().valueChanged.connect(
            lambda value: self._reference_popup_scrolled(
                self.three_stage_popup, value
            )
        )
        self.detail_view.verticalScrollBar().valueChanged.connect(
            self._schedule_three_stage_button_positions
        )
        self.detail_view.horizontalScrollBar().valueChanged.connect(
            self._schedule_three_stage_button_positions
        )
        self.detail_view.document().contentsChanged.connect(
            self._schedule_three_stage_button_positions
        )
        self.detail_view.viewport().installEventFilter(self)

    @property
    def category_target(self) -> str:
        return str(self.category_tabs.tabData(self.category_tabs.currentIndex()))

    @property
    def category(self) -> dict:
        if self.category_target == RESOURCE_ALL_TARGET:
            return {"label": "통합검색"}
        if self.category_target in KEYWORD_CATEGORY_LABELS:
            return {"label": KEYWORD_CATEGORY_LABELS[self.category_target]}
        return RESOURCE_CATEGORIES[self.category_target]

    @property
    def is_keyword_category(self) -> bool:
        """연관검색ㆍ직접검색처럼 키워드검색 화면이 맡는 분류인지."""
        return self.category_target in KEYWORD_CATEGORY_LABELS

    def ensure_body_page_for_target(self, target: str) -> None:
        """키워드검색 화면이 법령 본문을 가리지 않게 목록 페이지로 돌린다.

        카테고리 변경 신호를 그대로 타면 검색 결과와 열어 둔 본문을 지운다.
        크게 보기 직전에 부르므로 화면만 바꾸고 내용은 유지한다.
        """
        mapped = str(target or "law")
        if mapped == "law_article":
            mapped = "law"
        if mapped not in RESOURCE_CATEGORIES:
            mapped = "law"
        if not self.is_keyword_category and (
            self.content_stack.currentWidget() is self.resource_body
        ):
            return
        self.category_tabs.blockSignals(True)
        selected = self.select_category(mapped)
        self.category_tabs.blockSignals(False)
        if not selected:
            return
        self._sync_content_page()
        self._sync_detail_button_visibility()

    def _sync_detail_button_visibility(self) -> None:
        """여러 유형이 섞인 통합검색에서만 공용 열기 단추를 보인다."""
        self.detail_button.setVisible(
            self.category_target == RESOURCE_ALL_TARGET
        )

    def attach_keyword_page(self, widget) -> None:
        """키워드검색 화면을 카테고리 바 아래 스택에 끼운다.

        연관검색ㆍ직접검색은 표와 본문 구성이 목록 검색과 달라서 이 탭이
        직접 그리지 않고, main_window가 만들어 둔 화면을 그대로 받아 쓴다.
        """
        self._keyword_page = widget
        self.content_stack.addWidget(widget)
        self._sync_content_page()

    def _sync_content_page(self) -> None:
        """고른 카테고리에 맞는 페이지를 스택에서 띄운다."""
        if self.is_keyword_category and self._keyword_page is not None:
            self.content_stack.setCurrentWidget(self._keyword_page)
            if self._keyword_page_selector is not None:
                self._keyword_page_selector(self.category_target)
        else:
            self.content_stack.setCurrentWidget(self.resource_body)
        # 목록 검색용 검색줄은 키워드검색 화면이 자기 것을 갖고 있어 겹친다.
        self.search_card.setVisible(not self.is_keyword_category)

    def select_category(self, target: str) -> bool:
        """대상 이름으로 카테고리를 고른다. 없으면 그대로 두고 False."""
        target = str(target or "").strip()
        for index in range(self.category_tabs.count()):
            if self.category_tabs.tabData(index) == target:
                self.category_tabs.setCurrentIndex(index)
                return True
        return False

    def search_resource_name(self, target: str, name: str) -> None:
        """Select a resource category and search its list by title."""
        target = str(target or "").strip()
        name = str(name or "").strip()
        if target not in ("law", "admrul") or not name:
            return
        for index in range(self.category_tabs.count()):
            if self.category_tabs.tabData(index) == target:
                self.category_tabs.setCurrentIndex(index)
                break
        self.query_input.setText(name)
        self.query_input.setFocus()
        self.start_search()

    def _saved_font_size(self, key: str, default: float) -> float:
        try:
            value = float(
                self.recent_search_manager.settings.value(key, default)
            )
        except (TypeError, ValueError):
            value = default
        return clamp_detail_font_size(value)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        self.root_layout = root

        self.category_tabs = PairedCategoryBar()
        self.category_tabs.setObjectName("resourceSubTabs")
        integrated_index = self.category_tabs.addTab("통합검색")
        self.category_tabs.setTabData(integrated_index, RESOURCE_ALL_TARGET)
        default_category_index = integrated_index
        related_index, direct_index = self.category_tabs.add_pair(
            "연관검색", "직접검색"
        )
        self.category_tabs.setTabData(related_index, KEYWORD_RELATED_TARGET)
        self.category_tabs.setTabData(direct_index, KEYWORD_DIRECT_TARGET)
        category_items = list(RESOURCE_CATEGORIES.items())
        for pair_start in range(0, len(category_items), 2):
            (first_target, first_config), (second_target, second_config) = (
                category_items[pair_start : pair_start + 2]
            )
            first_index, second_index = self.category_tabs.add_pair(
                str(first_config["label"]),
                str(second_config.get("tab_label") or second_config["label"]),
            )
            self.category_tabs.setTabData(first_index, first_target)
            self.category_tabs.setTabData(second_index, second_target)
            if first_target == "law":
                default_category_index = first_index
        self.category_tabs.add_stretch()
        self.category_tabs.setCurrentIndex(default_category_index)
        root.addWidget(self.category_tabs)

        search_card = QFrame()
        search_card.setObjectName("card")
        self.search_card = search_card
        search_layout = QHBoxLayout(search_card)
        search_layout.setContentsMargins(10, 12, 10, 12)
        search_layout.setSpacing(8)

        self.query_input = QLineEdit()
        self.query_input.setPlaceholderText("검색할 키워드를 입력하세요")
        self.query_input.setClearButtonEnabled(True)
        self.query_input.returnPressed.connect(self.start_search)

        self.annex_search_scope = QComboBox()
        self.annex_search_scope.setObjectName("resourceSearchScope")
        self.annex_search_scope.addItem("별표·서식명", 1)
        self.annex_search_scope.addItem("해당 법령명", 2)
        self.annex_search_scope.addItem("별표 본문", 3)
        self.annex_search_scope.setCurrentIndex(0)
        self.annex_search_scope.setFixedWidth(86)
        self.annex_search_scope.setToolTip(
            "법령 별표·서식 API 검색범위(search=1/2/3)를 선택합니다."
        )
        self.annex_search_scope.currentIndexChanged.connect(
            self._annex_search_scope_changed
        )
        self.annex_search_scope.hide()

        self.search_button = QPushButton("검색")
        self.search_button.setObjectName("primaryButton")
        self.search_button.setFixedWidth(56)
        self.search_button.clicked.connect(self.start_search)

        search_layout.addWidget(self.annex_search_scope)
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
        self.result_card = result_card
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

        self.result_table = StableHorizontalTableWidget(0, 7)
        self.result_table.setAccessibleName("검색 결과 표")
        self.result_table.setHorizontalHeader(
            ResultHeaderView(Qt.Orientation.Horizontal, self.result_table)
        )
        self.result_table.setHorizontalHeaderLabels(
            [
                "저장",
                "구분",
                "ID",
                "명칭",
                "관련 법령·기관",
                "공포·발령일자",
                "시행일자",
            ]
        )
        self.result_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.result_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.result_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setShowGrid(False)
        self.result_table.setWordWrap(True)
        self.result_table.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.name_delegate = FavoriteTitleDelegate(
            self._toggle_favorite_at_row,
            self._is_favorite_at_row,
            self.result_table,
        )
        self.related_delegate = SearchHighlightDelegate(self.result_table)
        self.save_check_delegate = CenteredCheckDelegate(self.result_table)
        self.result_table.setItemDelegateForColumn(0, self.save_check_delegate)
        self.result_table.setItemDelegateForColumn(3, self.name_delegate)
        self.result_table.setItemDelegateForColumn(4, self.related_delegate)
        self.result_table.verticalHeader().setVisible(False)
        configure_adaptive_result_rows(self.result_table, (3, 4))
        table_header = self.result_table.horizontalHeader()
        table_header.setStretchLastSection(False)
        table_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        table_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.result_table.setColumnHidden(
            1, self.category_target != RESOURCE_ALL_TARGET
        )
        self.result_table.setColumnHidden(2, True)
        table_header.setSectionsClickable(True)
        table_header.setSortIndicatorShown(True)
        table_header.sectionClicked.connect(self._sort_by_column)
        self.result_table.itemSelectionChanged.connect(self._selection_changed)
        self.result_table.itemDoubleClicked.connect(
            self._open_detail_expanded
        )
        self.result_table.itemChanged.connect(self._cache_check_changed)
        self._apply_result_table_font()
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
        detail_controls = build_detail_header_controls(self.detail_font_size)
        detail_title = detail_controls.title
        self.detail_title_label = detail_title
        self.expand_detail_button = QPushButton("크게\n보기")
        self.expand_detail_button.setObjectName("readingModeButton")
        # 폭은 글자에 맞춰 잡는다. 44px로 못박아 두면 크게 보기에서
        # "AI / 에이전트"로 바뀔 때 "에이전트"가 잘린다.
        self.expand_detail_button.setFixedHeight(42)
        self.expand_detail_button.clicked.connect(self._expand_button_clicked)
        self._set_expand_button_mode("expand")
        detail_title.doubleClicked.connect(self._toggle_reading_mode)
        self.detail_button = QPushButton("본문\n조회")
        self.detail_button.setObjectName("resourceDetailButton")
        self.detail_button.setFixedSize(42, 42)
        self.detail_button.setEnabled(False)
        self.detail_button.clicked.connect(self._open_detail_expanded)
        self.copy_button = QPushButton(self)
        self.copy_button.hide()
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
        detail_font_label = detail_controls.font_label
        self.detail_font_label = detail_font_label
        self.detail_font_spin = detail_controls.font_spin
        self.restore_view_button = build_restore_view_button(self)
        detail_head.addWidget(self.restore_view_button)
        detail_head.addWidget(detail_title)
        detail_head.addWidget(detail_font_label)
        detail_head.addWidget(self.detail_font_spin)
        detail_head.addSpacing(8)
        detail_head.addWidget(self.color_tools)
        detail_head.addWidget(self.color_reset_tools)
        detail_head.addWidget(self.memo_button)
        detail_head.addStretch()
        detail_head.addWidget(self.expand_detail_button)

        # 여러 유형이 섞인 통합검색만 결과 제목줄에 공용 열기 단추를 둔다.
        # 단일 유형은 결과 더블클릭이나 별표 원문 링크로 열 수 있다.
        result_head.layout.addWidget(self.detail_button)
        self._sync_detail_button_visibility()

        self.document_tabs = QTabBar()
        self.document_tabs.setObjectName("documentTabs")
        self.document_tabs.setDrawBase(False)
        self.document_tabs.setExpanding(False)
        self.document_tabs.setMovable(True)
        # 기본 닫기 단추는 스타일마다 모양이 달라(윈도우에서는 빨간
        # 네모로 뜬다) 탭 안에서 혼자 튄다. 별표와 같은 방식으로
        # 우리가 만든 얇은 × 를 오른쪽에 단다.
        self.document_tabs.setTabsClosable(False)
        # 가로 스크롤은 바깥 띠가 맡는다. 탭 자체 스크롤 버튼을 함께 두면
        # 탭 줄 폭이 버튼만큼 줄어 제목이 더 잘린다.
        self.document_tabs.setUsesScrollButtons(False)
        self.document_tabs.setElideMode(Qt.TextElideMode.ElideNone)
        self.document_tab_strip = TabStripScrollArea(self.document_tabs)
        self.document_tab_strip.setObjectName("documentTabStrip")

        document_tabs_layout = QHBoxLayout()
        document_tabs_layout.setContentsMargins(0, 0, 0, 0)
        document_tabs_layout.setSpacing(0)
        document_tabs_layout.addWidget(self.document_tab_strip, 1)
        detail_layout.addLayout(document_tabs_layout)
        detail_layout.addLayout(detail_head)
        self.document_tab_strip.hide()

        self.detail_view = DeferredWrapTextBrowser()
        self.detail_view.setAccessibleName("본문")
        detail_font = QFont(DETAIL_FONT_FAMILY)
        detail_font.setWeight(QFont.Weight.Normal)
        detail_font.setPointSizeF(self.detail_font_size)
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
        self.detail_view.viewport().setMouseTracking(True)
        self.detail_view.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self.detail_view.setPlaceholderText("검색 결과에서 항목을 선택하세요.")
        self.detail_search = DetailSearchBar(self.detail_view, self)
        self.detail_font_spin.valueChanged.connect(self._set_detail_font_size)

        self.toc_tree = QTreeWidget()
        self.toc_tree.setAccessibleName("조문 목차")
        self.toc_tree.setObjectName("articleToc")
        self.toc_tree.setHeaderLabel("조문 목차")
        self.toc_tree.setIndentation(14)
        self.toc_tree.setUniformRowHeights(True)
        self.toc_tree.setMinimumWidth(170)
        self.toc_tree.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.toc_tree.itemClicked.connect(self._toc_item_clicked)

        self.toc_search_input = QLineEdit()
        self.toc_search_input.setObjectName("tocSearchInput")
        self.toc_search_input.setPlaceholderText("조문 번호 또는 조문명")
        self.toc_search_input.setClearButtonEnabled(True)
        self.toc_search_count = QLabel("0/0")
        self.toc_search_count.setObjectName("tocSearchCount")
        self.toc_search_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.toc_search_count.setFixedWidth(48)
        self.toc_shade_reset_button = QPushButton("음영\n초기화")
        self.toc_shade_reset_button.setObjectName("tocShadeResetButton")
        self.toc_shade_reset_button.setFixedWidth(46)
        self.toc_shade_reset_button.setToolTip(
            "조문 이동으로 표시된 파란 음영을 지웁니다."
        )
        self.toc_shade_reset_button.clicked.connect(self._clear_toc_highlight)
        self.toc_previous_button = QPushButton("이전")
        self.toc_previous_button.setObjectName("tocSearchButton")
        self.toc_previous_button.setFixedWidth(48)
        self.toc_next_button = QPushButton("다음")
        self.toc_next_button.setObjectName("tocSearchButton")
        self.toc_next_button.setFixedWidth(48)

        toc_search_label = QLabel("조문 검색")
        toc_search_label.setObjectName("tocSearchLabel")
        toc_navigation = QHBoxLayout()
        toc_navigation.setContentsMargins(0, 0, 0, 0)
        toc_navigation.setSpacing(5)
        toc_navigation.addWidget(self.toc_search_count)
        toc_navigation.addStretch()
        toc_navigation.addWidget(self.toc_shade_reset_button)
        toc_navigation.addWidget(self.toc_previous_button)
        toc_navigation.addWidget(self.toc_next_button)

        self.toc_panel = QWidget()
        self.toc_panel.setObjectName("articleTocPanel")
        toc_panel_layout = QVBoxLayout(self.toc_panel)
        # 조문 검색 영역이 왼쪽 분할선에 달라붙아 보이지
        # 않도록 본문 검색줄과 같은 여백을 준다.
        toc_panel_layout.setContentsMargins(8, 0, 0, 0)
        toc_panel_layout.setSpacing(6)
        toc_panel_layout.addWidget(toc_search_label)
        toc_panel_layout.addWidget(self.toc_search_input)
        toc_panel_layout.addLayout(toc_navigation)
        toc_panel_layout.addWidget(self.toc_tree, 1)
        self.toc_panel.hide()

        self._toc_items: list[QTreeWidgetItem] = []
        self._toc_search_matches: list[QTreeWidgetItem] = []
        self._toc_search_index = -1
        self.toc_search_input.textChanged.connect(self._refresh_toc_search)
        self.toc_search_input.returnPressed.connect(
            lambda: self._move_toc_search(1)
        )
        self.toc_previous_button.clicked.connect(
            lambda: self._move_toc_search(-1)
        )
        self.toc_next_button.clicked.connect(lambda: self._move_toc_search(1))

        detail_body = QWidget()
        detail_body.setObjectName("detailBodyContainer")
        detail_body_layout = QVBoxLayout(detail_body)
        detail_body_layout.setContentsMargins(0, 0, 0, 0)
        detail_body_layout.setSpacing(8)
        detail_body_layout.addWidget(self.detail_search)
        detail_view_row = QWidget()
        detail_view_row.setObjectName("detailViewRow")
        detail_view_row_layout = QHBoxLayout(detail_view_row)
        detail_view_row_layout.setContentsMargins(0, 0, 0, 0)
        detail_view_row_layout.setSpacing(2)
        self.memo_marker_bar = MemoMarkerBar(self.detail_view, detail_view_row)
        self.memo_marker_bar.activated.connect(self._open_memo_marker_popup)
        self._visible_memos: list[dict[str, object]] = []

        self.pdf_preview_popup = PdfPreviewPopup(self)
        # 고정해 둔 미리보기는 그대로 두고 새 별표를 옆에 띄운다.
        self._extra_pdf_popups: list[PdfPreviewPopup] = []
        detail_view_row_layout.addWidget(self.detail_view, 1)
        detail_view_row_layout.addWidget(self.memo_marker_bar)
        detail_body_layout.addWidget(detail_view_row, 1)

        self.detail_content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.detail_content_splitter.setChildrenCollapsible(False)
        self.detail_content_splitter.addWidget(self.toc_panel)
        self.detail_content_splitter.addWidget(detail_body)
        configure_horizontal_splitter(self.detail_content_splitter)
        self.detail_content_splitter.setSizes([210, 700])
        self.detail_content_splitter.setStretchFactor(0, 0)
        self.detail_content_splitter.setStretchFactor(1, 1)
        detail_layout.addWidget(self.detail_content_splitter)

        self.reference_tabs = ReferenceHistoryBar()
        self.reference_tabs.setToolTip(
            "조회한 조항목·3단비교 기록입니다. 항목을 누르면 팝업을 다시 "
            "표시하고, 끌어서 순서를 바꿀 수 있습니다."
        )
        self.reference_tabs.tabBarClicked.connect(
            self._reference_history_clicked
        )
        self.reference_tabs.tabCloseRequested.connect(
            self._close_reference_history
        )
        detail_layout.addWidget(self.reference_tabs)

        self._document_states: dict[str, dict[str, object]] = {
            "__preview__": self._empty_document_state()
        }
        self._active_document_key = "__preview__"
        self._document_cache_order: list[str] = []
        self._document_cache_limit = 4
        self._current_toc_entries: list[tuple[int, str, str]] = []
        self._restoring_document = False
        self._pending_selection_row = -1
        self._selection_open_scheduled = False
        self.document_tabs.currentChanged.connect(self._document_tab_changed)
        self.document_tabs.tabBarClicked.connect(self._document_tab_clicked)
        self.document_tabs.tabCloseRequested.connect(self._close_document_tab)

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
        # 크게 보기에서 본문 오른쪽에 붙는 대화 패널. 평소에는 접혀 있다.
        self.ai_chat_panel = AiChatPanel(self.settings, parent=self)
        self.ai_chat_panel.context_source = self._chat_context
        # oc_provider는 창에서 만든 API 인증키 조회 함수를 그대로 물려받는다.
        # 검색 도구가 국토부 OC 키로 실제 법제처 API를 부르는 데 쓴다.
        self.ai_chat_panel.oc_provider = self.oc_provider
        self.ai_chat_panel.document_cache = self.law_cache
        self.ai_chat_panel.favorite_handler = self.add_favorite_by_id
        self.ai_chat_panel.favorite_checker = self.is_favorite_by_id
        self.ai_chat_panel.article_favorite_handler = (
            self.add_article_favorite_by_id
        )
        self.ai_chat_panel.article_favorite_checker = (
            self.is_article_favorite_by_id
        )
        self.ai_chat_panel.reference_handler = self.open_reference_link
        self.ai_chat_panel.closeRequested.connect(self._close_ai_chat)
        self.ai_chat_panel.hide()
        splitter.addWidget(self.ai_chat_panel)
        configure_horizontal_splitter(splitter)
        splitter.setCollapsible(0, True)
        splitter.setCollapsible(1, True)
        # AI 패널은 손잡이를 왼쪽 끝까지 끌어도 갑자기 0폭으로 접지 않는다.
        # 완전히 닫는 동작은 패널의 ×가 맡고, 폭은 최소 제한 없이 줄인다.
        splitter.setCollapsible(2, False)
        # 목록 화면에서는 오른쪽 본문 위젯 자체를 숨긴다. splitter 크기만
        # 0으로 두면 창 크기나 복원 시 다시 벌어질 수 있다.
        splitter.setSizes([2000, 0, 0])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 0)
        detail_card.hide()
        # 카테고리 바 아래는 스택으로 둔다. 법령·행정규칙 같은 목록 검색은
        # 이 페이지를 쓰고, 연관검색·직접검색은 main_window가 넣어 주는
        # 키워드검색 화면으로 통째로 갈아 끼운다.
        self.content_stack = QStackedWidget()
        self.resource_body = QWidget()
        body_layout = QVBoxLayout(self.resource_body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(12)
        self.content_stack.addWidget(self.resource_body)
        root.addWidget(self.content_stack, 1)
        body_layout.addWidget(splitter, 1)

        status_layout = QHBoxLayout()
        self.status_label = QLabel("검색 유형과 키워드를 선택해 주세요.")
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
        body_layout.addLayout(status_layout)
        self.category_tabs.currentChanged.connect(self._category_changed)
        self._reading_mode = False
        self._normal_splitter_sizes = [2000, 0]
        self._normal_window_margins: tuple[int, int, int, int] | None = None
        self.reading_mode_shortcut = QShortcut(QKeySequence("F11"), self)
        self.reading_mode_shortcut.activated.connect(self._toggle_reading_mode)

    def _toggle_reading_mode(self, *_args: object) -> None:
        self._set_reading_mode(not self._reading_mode)

    def _set_expand_button_mode(self, mode: str) -> None:
        """단추의 글자·설명·색을 지금 하는 일에 맞춘다.

        같은 자리에서 "크게 보기"와 "AI 에이전트" 두 가지 일을 한다.
        무슨 일을 하는 단추인지 색으로도 구분되게 하고, 폭은 그때그때
        글자에 맞춰 잡는다 — 44px로 못박아 두면 "에이전트"가 잘린다.
        """
        button = self.expand_detail_button
        if mode == "ai":
            button.setText("AI\n에이전트")
            button.setToolTip(
                "보고 있는 본문에 대해 물어봅니다. (◀ 또는 F11로 원래 화면)"
            )
        else:
            button.setText("크게\n보기")
            button.setToolTip("F11: 본문 크게 보기로 전환")
        button.setProperty("buttonMode", mode)
        button.style().unpolish(button)
        button.style().polish(button)
        metrics = button.fontMetrics()
        widest = max(
            metrics.horizontalAdvance(line) for line in button.text().split("\n")
        )
        # 테두리와 좌우 여백(QSS padding 0 4px)에 넉넉히 얹는다. 이 시점에
        # 스타일이 아직 안 먹어 글자 폭을 작게 재는 경우까지 감안한다.
        button.setFixedWidth(widest + 20)
        button.update()

    def _expand_button_clicked(self, *_args: object) -> None:
        """한 단추가 두 가지 일을 한다.

        평소에는 크게 보기로 들어가고, 크게 보기 상태에서는 대화 패널을
        연다. 크게 보기에서 되돌아가는 일은 ◀ 단추와 F11이 맡고 있어서
        이 자리를 대화에 내줄 수 있다.
        """
        if self._reading_mode:
            self._toggle_ai_chat()
        else:
            self._set_reading_mode(True)

    def _chat_context(self) -> tuple[str, str]:
        """대화의 근거로 삼을 본문을 고른다.

        일부를 드래그해 두었으면 그 부분만 쓴다. 법령 전문을 통째로
        보내면 답이 흐려지기 때문이다.
        """
        selected = self.detail_view.textCursor().selectedText()
        if selected.strip():
            # QTextEdit은 문단 구분을 U+2029로 돌려준다.
            return selected.replace("", "\n"), "선택한 부분"
        return self.detail_view.toPlainText(), "본문 전체"

    def _toggle_ai_chat(self) -> None:
        if self.ai_chat_panel.isVisible():
            self._hide_ai_chat()
        else:
            self._show_ai_chat()
        self._ai_chat_was_open = self.ai_chat_panel.isVisible()

    def _show_ai_chat(self) -> None:
        sizes = self.main_splitter.sizes()
        total = sum(sizes) or self.main_splitter.width()
        # 본문을 가리지 않도록 다섯 중 하나만 쓴다. 다만 너무 좁으면
        # 글이 한 줄에 몇 자 안 들어가므로 최소 폭은 지킨다.
        chat_width = max(300, total // 5)
        self.ai_chat_panel.show()
        self.main_splitter.setSizes([0, max(1, total - chat_width), chat_width])
        self.ai_chat_panel.input_edit.setFocus()

    def _close_ai_chat(self, *_args: object) -> None:
        """× 로 닫으면 다음 크게 보기에서도 닫힌 채로 시작한다."""
        self._hide_ai_chat()
        self._ai_chat_was_open = False

    def _hide_ai_chat(self, *_args: object) -> None:
        if not self.ai_chat_panel.isVisible():
            return
        total = sum(self.main_splitter.sizes())
        self.ai_chat_panel.hide()
        if self._reading_mode:
            self.main_splitter.setSizes([0, max(1, total), 0])
            self.detail_view.setFocus()

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
            row_target = "law"
            state = self._document_states.get(self._active_document_key or "")
            if isinstance(state, dict) and isinstance(state.get("row"), dict):
                row_target = str(state["row"].get("target") or "law")
            pending = getattr(self, "pending_row", None)
            if isinstance(pending, dict) and pending.get("target"):
                row_target = str(pending.get("target") or row_target)
            self.ensure_body_page_for_target(row_target)
            current_sizes = self.main_splitter.sizes()
            if sum(current_sizes) > 0:
                self._normal_splitter_sizes = [sum(current_sizes), 0]
            if central_layout is not None:
                self._normal_window_margins = central_layout.getContentsMargins()
            self.detail_card.show()

        self._reading_mode = expanded
        for widget in (
            self.category_tabs,
            self.search_card,
            self.recent_search_bar,
            self.result_card,
            self.search_results_panel,
            self.status_label,
        ):
            widget.setVisible(not expanded)
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
            self.main_splitter.setSizes(
                [0, max(1, sum(self._normal_splitter_sizes)), 0]
            )
            # 크게 보기에서는 ◀ 단추가 원래 화면으로 되돌리므로, 이 자리는
            # 본문을 읽다가 바로 물어보는 대화 패널을 여는 데 쓴다.
            self._set_expand_button_mode("ai")
            self.restore_view_button.show()
            self.document_tab_strip.hide()
            self.detail_view.setFocus()
            # 지난번에 열어 둔 채로 나왔으면 이번에도 열어 둔다. 켜고
            # 끄는 것은 사람이 정한 것이지 화면이 바뀌었다고 되돌릴
            # 일이 아니다.
            if self._ai_chat_was_open:
                self._show_ai_chat()
        else:
            self._ai_chat_was_open = self.ai_chat_panel.isVisible()
            self._hide_ai_chat()
            self.main_splitter.setSizes(
                [max(1, sum(self._normal_splitter_sizes)), 0, 0]
            )
            self.detail_card.hide()
            self._set_expand_button_mode("expand")
            self.restore_view_button.hide()
            if self.document_tabs.count():
                self.document_tab_strip.show()
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

    def _apply_result_table_font(self) -> None:
        size = 9.0
        font = QFont(FONT_FAMILY)
        font.setPointSizeF(size)
        self.result_table.setFont(font)
        self.result_table.horizontalHeader().setFont(font)
        minimum_height = max(24, round(size * 2.6 + 2))
        self.result_table.verticalHeader().setMinimumSectionSize(minimum_height)
        self.result_table.verticalHeader().setDefaultSectionSize(minimum_height)
        self.result_table.setStyleSheet(
            f"QTableWidget {{ font-size:{size:g}pt; }}"
            f"QHeaderView::section {{ font-size:{size:g}pt; }}"
        )
        resize_adaptive_result_rows(self.result_table)
        self.result_table.viewport().update()

    @staticmethod
    def _scale_document_font_sizes(
        html: str, source_size: float, target_size: float
    ) -> str:
        return scale_document_font_sizes(html, source_size, target_size)

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
            self._save_active_document_state()

        if persist:
            settings = self.recent_search_manager.settings
            settings.setValue("resource_detail_font_size", size)
            settings.sync()

    def _empty_document_state(self) -> dict[str, object]:
        return {
            "html": "",
            "source_html": "",
            "prefer_source_html": False,
            "plain_text": "",
            "toc_entries": [],
            "detail_query": "",
            "toc_query": "",
            "scroll": 0,
            "font_size": self.detail_font_size,
            "memos": [],
            "base_foregrounds": [],
            "three_stage_articles": [],
            "render_highlight_terms": [],
            "document": None,
            # 탭의 별표(즐겨찾기)를 켜고 끄려면 어떤 문서인지 알아야 한다.
            "row": None,
        }

    def _set_active_text_document(self, document: QTextDocument) -> None:
        """렌더링을 반복하지 않고 이미 배치된 탭 문서로 전환."""
        current = self.detail_view.document()
        if current is document:
            return
        try:
            current.contentsChanged.disconnect(
                self._schedule_three_stage_button_positions
            )
        except (RuntimeError, TypeError):
            pass
        current.setParent(self)
        document.setParent(self)
        self.detail_view.setDocument(document)
        self.detail_search.bind_document(document)
        self.memo_marker_bar.bind_document(document)
        document.contentsChanged.connect(self._schedule_three_stage_button_positions)
        self._touch_document_cache(self._active_document_key)

    def _touch_document_cache(self, key: str) -> None:
        if key in self._document_cache_order:
            self._document_cache_order.remove(key)
        self._document_cache_order.append(key)
        while len(self._document_cache_order) > self._document_cache_limit:
            stale_key = self._document_cache_order.pop(0)
            if stale_key == self._active_document_key:
                self._document_cache_order.append(stale_key)
                continue
            stale_state = self._document_states.get(stale_key)
            stale_document = (
                stale_state.get("document")
                if isinstance(stale_state, dict)
                else None
            )
            if isinstance(stale_document, QTextDocument):
                stale_state["document"] = None
                stale_document.deleteLater()

    def _ensure_active_text_document(self) -> QTextDocument:
        state = self._document_states.get(self._active_document_key)
        if not isinstance(state, dict):
            return self.detail_view.document()
        document = state.get("document")
        if not isinstance(document, QTextDocument):
            document = QTextDocument(self)
            state["document"] = document
        self._set_active_text_document(document)
        return document

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

    def _replace_detail_content(
        self,
        *,
        html: str | None = None,
        text: str | None = None,
        source_font_size: float = 10,
    ) -> None:
        self._ensure_active_text_document()
        previous_text = self.detail_view.toPlainText()
        previous_base_foregrounds = capture_base_foreground_spans(
            self.detail_view.document()
        )
        self.detail_search.begin_document_change()
        try:
            font = QFont(DETAIL_FONT_FAMILY)
            font.setWeight(QFont.Weight.Normal)
            font.setPointSizeF(self.detail_font_size)
            self.detail_view.setFont(font)
            self.detail_view.document().setDefaultFont(font)
            if html is not None:
                self.detail_view.setHtml(
                    self._scale_document_font_sizes(
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
                # 전체 문서에 사용자 속성을 미리 쓰는 작업은 Qt 문서
                # 레이아웃을 반복 무효화한다. 원래 글자색은 사용자가
                # 실제로 글자색을 바꾸는 선택 범위에서만 기록한다.
                pass
        finally:
            self.detail_search.end_document_change()

    def _save_active_document_state(self) -> None:
        if self._restoring_document:
            return
        state = self._document_states.get(self._active_document_key)
        if state is None:
            return
        # toHtml()과 글자색 수집은 문서 전체를 훑는 일이라 큰 법령에서는
        # 합쳐서 20ms가 넘는다. 화면에 넣은 뒤로 문서가 바뀐 적이 없으면
        # 지난번에 저장해 둔 값이 그대로 유효하므로 다시 뽑지 않는다.
        document = self.detail_view.document()
        if document.isModified() or not state.get("html"):
            html = self.detail_view.toHtml()
            base_foregrounds = capture_base_foreground_spans(document)
            document.setModified(False)
        else:
            html = str(state.get("html") or "")
            base_foregrounds = state.get("base_foregrounds") or []
        state.update(
            {
                "document": document,
                "html": html,
                "plain_text": self.current_detail_text,
                "toc_entries": list(self._current_toc_entries),
                "detail_query": self.detail_search.query_input.text(),
                "toc_query": self.toc_search_input.text(),
                "scroll": self.detail_view.verticalScrollBar().value(),
                # 목차는 문서가 바뀌어도 같은 나무 위젯을 다시 채워 쓴다.
                # 그래서 스크롤을 따로 기억해 두지 않으면 앞 문서에서
                # 내려 둔 자리가 그대로 남아, 시행령 목차인데 법률에서
                # 보던 조문 근처가 펼쳐져 있었다.
                "toc_scroll": self.toc_tree.verticalScrollBar().value(),
                "font_size": self.detail_font_size,
                "memos": [dict(memo) for memo in self._visible_memos],
                "base_foregrounds": base_foregrounds,
                "three_stage_articles": [
                    dict(article)
                    for article in self._current_three_stage_articles
                ],
                "render_highlight_terms": list(self.highlight_terms),
                "prefer_source_html": False,
            }
        )

    @staticmethod
    def _document_identity(row: object) -> str:
        """저장 파일 주소로 쓰는 문서 신원. 모르면 빈 글자.

        저장소가 파일 이름을 정할 때 쓰는 규칙을 그대로 빌린다. 같은
        규칙을 두 벌 두면 언젠가 어긋나고, 어긋나는 순간 이 검사가
        무력해진다.
        """
        if not isinstance(row, dict) or not row:
            return ""
        try:
            return LawDocumentCache._cache_key(row)
        except (AttributeError, TypeError, ValueError):
            return ""

    @classmethod
    def _snapshot_belongs_to(
        cls, snapshot: dict[str, object], row: dict[str, object]
    ) -> bool:
        """이 화면을 이 행의 저장 파일에 써도 되는지 본다.

        신원을 못 밝히는 화면(예전 판이 만든 것)은 여기서 막지 않는다.
        막아 버리면 멀쩡한 저장까지 사라진다. 그런 화면은 조문 수를
        보는 ``_snapshot_covers_payload``가 계속 뒤를 받친다.
        """
        rendered_for = str(snapshot.get("rendered_for") or "")
        if not rendered_for:
            return True
        return rendered_for == cls._document_identity(row)

    @staticmethod
    def _law_render_snapshot_from_state(
        state: dict[str, object],
    ) -> dict[str, object]:
        """법률 저장본을 다시 조립하지 않고 표시하는 최소 화면 상태."""
        return {
            "render_snapshot_version": LAW_RENDER_SNAPSHOT_VERSION,
            # 이 화면이 어느 문서의 것인지 스스로 밝힌다. 저장 위치를
            # 부르는 쪽에서 따로 계산하다 보니, 조문 하나짜리 화면이
            # 법령 전문 파일에 저장되는 일이 있었다. 신원을 화면에
            # 붙여 두면 어긋난 곳에 쓰는 것을 쓰기 직전에 막을 수 있다.
            "rendered_for": ResourceSearchTab._document_identity(
                state.get("row")
            ),
            # QTextDocument.toHtml() 결과는 원본보다 몇 배 장황하고,
            # 다시 setHtml() 할 때 국토계획법 기준 1초 이상 걸렸다.
            # 최초에 만든 간결한 HTML을 저장하고 링크·메모·색상은
            # 별도 상태로 복원한다.
            "rendered_html": str(
                state.get("source_html") or state.get("html") or ""
            ),
            "rendered_plain_text": str(state.get("plain_text") or ""),
            "rendered_toc_entries": list(state.get("toc_entries") or []),
            "rendered_font_size": float(state.get("font_size") or 10),
            "rendered_three_stage_articles": [
                dict(article)
                for article in state.get("three_stage_articles", []) or []
                if isinstance(article, dict)
            ],
            "render_highlight_terms": [
                str(term)
                for term in state.get("render_highlight_terms", []) or []
                if str(term)
            ],
        }

    def _active_law_render_snapshot(self) -> dict[str, object]:
        state = self._document_states.get(self._active_document_key)
        if not isinstance(state, dict):
            return {}
        return self._law_render_snapshot_from_state(state)

    @staticmethod
    def _cached_memos_for_state(record: dict[str, object]) -> list[dict[str, object]]:
        memos = record.get("memos")
        if not isinstance(memos, list):
            return []
        return [dict(memo) for memo in memos if isinstance(memo, dict)]

    def _clear_pending_document_view(self) -> None:
        """새 본문을 곧 그릴 때, 이전 문서의 흔적만 걷어낸다."""
        self.detail_search.query_input.blockSignals(True)
        self.toc_search_input.blockSignals(True)
        self.detail_search.query_input.clear()
        self.toc_search_input.clear()
        self.detail_search.query_input.blockSignals(False)
        self.toc_search_input.blockSignals(False)
        # 문서 오른쪽 여백까지 여기서 되돌리면 아직 화면에 남아 있는
        # 이전 본문이 통째로 다시 배치되어(큰 법령은 30ms 가까이) 클릭이
        # 굼떠진다. 여백은 새 본문을 그린 뒤 _set_three_stage_articles가
        # 알맞게 정한다.
        self._clear_three_stage_buttons()
        self._current_three_stage_articles = []

    def _restore_document_state(self, key: str) -> None:
        state = self._document_states.get(key, self._empty_document_state())
        self._restoring_document = True
        # 탭을 바꿀 때마다 detail_view 하나에 새 문서 HTML을 다시
        # 불러오는데, 최종 폭이 자리 잡기 전에 한 번 그려졌다가 폭이
        # 정해진 뒤 다시 줄바꿈되면서 가로 스크롤이 잠깐 나타났다
        # 사라지는 게 눈에 보였다. 복원이 끝날 때까지 화면 갱신을
        # 잠가서 중간 상태가 그려지지 않게 한다.
        self.detail_view.setUpdatesEnabled(False)
        try:
            cached_document = state.get("document")
            has_rendered_document = isinstance(cached_document, QTextDocument)
            if has_rendered_document:
                self._set_active_text_document(cached_document)
            else:
                self._ensure_active_text_document()
            self.detail_search.query_input.blockSignals(True)
            self.toc_search_input.blockSignals(True)
            self.detail_search.query_input.clear()
            self.toc_search_input.clear()
            self.detail_search.query_input.blockSignals(False)
            self.toc_search_input.blockSignals(False)

            html = str(
                state.get("source_html")
                if state.get("prefer_source_html") and state.get("source_html")
                else state.get("html", "")
            )
            try:
                source_font_size = float(state.get("font_size", 10) or 10)
            except (TypeError, ValueError):
                source_font_size = 10
            if has_rendered_document:
                # 본문과 목차는 같은 문서 상태이므로 함께 즉시 바꾼다.
                # 목차를 지연하면 그 짧은 사이에 다른 탭을 누를 때 이전
                # 조항호목 목차가 현재 법령 탭 상태로 잘못 저장될 수 있다.
                self._clear_three_stage_buttons()
                self._current_three_stage_articles = []
                self.current_detail_text = str(state.get("plain_text", "") or "")
                self.copy_button.setEnabled(bool(self.current_detail_text))
                self._populate_toc(list(state.get("toc_entries", []) or []))
                self._restore_toc_scroll(key)
                self.detail_view.verticalScrollBar().setValue(
                    int(state.get("scroll", 0) or 0)
                )
                QTimer.singleShot(
                    16,
                    lambda restore_key=key: self._restore_cached_document_controls(
                        restore_key
                    ),
                )
                return
            elif html:
                self._replace_detail_content(
                    html=html, source_font_size=source_font_size
                )
            else:
                self._replace_detail_content()
            # 3단비교 버튼 자리를 위한 본문 오른쪽 여백은
            # _set_three_stage_articles가 정하는데, 이걸 뒤에서(목차
            # 채운 뒤) 실행하면 본문이 일단 여백 없이 넓게 한 번
            # 그려졌다가 여백이 좁아지며 다시 줄바꿈되는 게 화면에
            # 비쳤다. 내용을 불러오자마자 바로 여백부터 맞춘다.
            self._set_three_stage_articles(
                list(state.get("three_stage_articles", []) or [])
            )
            base_foregrounds = state.get("base_foregrounds", [])
            if isinstance(base_foregrounds, list) and base_foregrounds:
                apply_base_foreground_spans(
                    self.detail_view.document(), base_foregrounds
                )
            self.current_detail_text = str(state.get("plain_text", "") or "")
            self._populate_toc(list(state.get("toc_entries", []) or []))
            self._restore_toc_scroll(key)
            self._set_visible_memos(state.get("memos", []))

            self.detail_search.query_input.setText(
                str(state.get("detail_query", "") or "")
            )
            self.toc_search_input.setText(str(state.get("toc_query", "") or ""))
            self.copy_button.setEnabled(bool(self.current_detail_text))
            self.detail_view.verticalScrollBar().setValue(
                int(state.get("scroll", 0) or 0)
            )
            state["font_size"] = self.detail_font_size
            state["memos"] = [dict(memo) for memo in self._visible_memos]
            state["three_stage_articles"] = [
                dict(article)
                for article in self._current_three_stage_articles
            ]
        finally:
            self._restoring_document = False
            # 화면 갱신을 다시 열기 전에 문서 레이아웃을 지금 당장
            # 확정 짓는다. size()를 읽으면 Qt가 미뤄뒀던 재배치를
            # 그 자리에서 끝내므로, 다시 그릴 때 이미 낡은(여백 적용
            # 전) 배치가 아니라 최종 배치로 바로 그려진다.
            if not has_rendered_document:
                self.detail_view.document().size()
            self.detail_view.setUpdatesEnabled(True)
            self.detail_view.viewport().update()

    def _restore_cached_document_controls(self, key: str) -> None:
        if key != self._active_document_key:
            return
        state = self._document_states.get(key)
        if not isinstance(state, dict):
            return
        self._set_three_stage_articles(
            list(state.get("three_stage_articles", []) or []),
            document_prepared=True,
        )
        self._set_visible_memos(state.get("memos", []))
        self.detail_search.query_input.setText(
            str(state.get("detail_query", "") or "")
        )
        self.toc_search_input.setText(str(state.get("toc_query", "") or ""))

    def _document_tab_changed(self, index: int) -> None:
        self._activate_document_tab(index)

    def _document_tab_clicked(self, index: int) -> None:
        # 미리보기 상태에서는 QTabBar가 첫 탭을 선택된 모양으로 남길 수
        # 있으므로 currentChanged가 발생하지 않는 동일 탭 클릭도 처리한다.
        self._activate_document_tab(index)

    def _activate_document_tab(self, index: int) -> None:
        if index < 0:
            return
        key = str(self.document_tabs.tabData(index) or "")
        if not key or key == self._active_document_key:
            return
        self._save_active_document_state()
        self._active_document_key = key
        self._restore_document_state(key)

    def _document_tab_index(self, key: str) -> int:
        for index in range(self.document_tabs.count()):
            if str(self.document_tabs.tabData(index) or "") == key:
                return index
        return -1

    def _activate_preview(self) -> None:
        if self._active_document_key == "__preview__":
            return
        self._save_active_document_state()
        self._active_document_key = "__preview__"
        self._restore_document_state("__preview__")

    def _open_document_tab(
        self, row: dict[str, object], *, defer_restore: bool = False
    ) -> None:
        key = f"{row['target']}:{row['id'] or row['name']}"
        index = self._document_tab_index(key)
        if index < 0:
            full_title = str(row["name"] or row["label"])
            tab_title = self._two_line_tab_title(full_title)
            index = self.document_tabs.addTab(tab_title)
            self.document_tabs.setTabData(index, key)
            self.document_tabs.setTabToolTip(
                index, f"{row['label']} · {full_title}"
            )
            self._document_states[key] = self._empty_document_state()
            self._install_document_tab_favorite(index, key)
        state = self._document_states.setdefault(
            key, self._empty_document_state()
        )
        state["row"] = dict(row)
        self._refresh_document_tab_favorites()
        if key != self._active_document_key:
            self._save_active_document_state()
            self._active_document_key = key
            if defer_restore:
                # 부르는 쪽이 곧바로 새 본문을 그려 넣는 경우다. 여기서
                # 저장해 둔 상태를 한 번 그려 두면 같은 클릭 안에서
                # setHtml과 문서 재배치가 두 번씩 돌아 큰 법령은 100ms
                # 넘게 화면이 멈춘다. 다만 활성 키만 먼저 바꾸고 이전
                # 법률 QTextDocument를 그대로 물려 두면, 그 사이 상태
                # 저장에서 조문 탭과 법률 탭이 같은 문서를 공유하게 된다.
                # 대상 탭 전용 문서를 먼저 연결한 뒤 내용 그리기만 넘긴다.
                self._ensure_active_text_document()
                self._clear_pending_document_view()
            else:
                self._restore_document_state(key)
        if self._reading_mode:
            self.document_tab_strip.hide()
        else:
            self.document_tab_strip.show()
        self.document_tab_strip.refresh()
        self.document_tabs.blockSignals(True)
        self.document_tabs.setCurrentIndex(index)
        self.document_tabs.blockSignals(False)
        self.document_tab_strip.ensure_visible(
            self.document_tabs.tabRect(index)
        )

    def _install_document_tab_favorite(self, index: int, key: str) -> None:
        """본문 탭 양쪽에 즐겨찾기 별표와 닫기 × 를 단다."""
        star = QPushButton("☆")
        star.setObjectName("documentTabFavorite")
        star.setFlat(True)
        star.setFixedSize(22, 22)
        star.setCursor(Qt.CursorShape.PointingHandCursor)
        star.setAccessibleName("본문 탭 즐겨찾기")
        star.setToolTip("이 본문을 즐겨찾기에 추가하거나 해제합니다.")
        star.clicked.connect(
            lambda _checked=False, tab_key=key: (
                self._toggle_document_tab_favorite(tab_key)
            )
        )
        self.document_tabs.setTabButton(
            index, QTabBar.ButtonPosition.LeftSide, star
        )
        close = QPushButton("×")
        close.setObjectName("documentTabClose")
        close.setFlat(True)
        close.setFixedSize(22, 22)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setAccessibleName("본문 탭 닫기")
        close.setToolTip("이 본문 탭을 닫습니다.")
        close.clicked.connect(
            lambda _checked=False, tab_key=key: (
                self._close_document_tab_by_key(tab_key)
            )
        )
        self.document_tabs.setTabButton(
            index, QTabBar.ButtonPosition.RightSide, close
        )

    def _close_document_tab_by_key(self, key: str) -> None:
        """탭 자리는 닫을 때마다 밀리므로, 누른 탭을 키로 다시 찾는다.

        닫기 함수를 직접 부르지 않고 원래 신호를 울린다. 바깥 상단바의
        "열린 본문" 목록도 이 신호를 듣고 있어서, 건너뛰면 닫은 본문이
        위쪽 띠에 그대로 남는다.
        """
        index = self._document_tab_index(key)
        if index >= 0:
            self.document_tabs.tabCloseRequested.emit(index)

    def _document_tab_row(self, key: str) -> dict[str, object] | None:
        state = self._document_states.get(key)
        row = state.get("row") if isinstance(state, dict) else None
        return row if isinstance(row, dict) else None

    def _refresh_document_tab_favorites(self) -> None:
        """탭 별표를 저장된 즐겨찾기 상태에 맞춘다."""
        if not hasattr(self, "document_tabs"):
            return
        for index in range(self.document_tabs.count()):
            star = self.document_tabs.tabButton(
                index, QTabBar.ButtonPosition.LeftSide
            )
            if not isinstance(star, QPushButton):
                continue
            key = str(self.document_tabs.tabData(index) or "")
            row = self._document_tab_row(key)
            if row and str(row.get("target") or "") == "law_article":
                source_row = row.get("source_row")
                unit = row.get("favorite_unit")
                is_favorite = bool(
                    isinstance(source_row, dict)
                    and isinstance(unit, dict)
                    and self.law_cache.is_article_favorite(
                        source_row,
                        str(unit.get("jo") or ""),
                        hang=str(unit.get("hang") or ""),
                        ho=str(unit.get("ho") or ""),
                        mok=str(unit.get("mok") or ""),
                    )
                )
            else:
                is_favorite = bool(row) and self.law_cache.is_favorite(row)
            star.setText("★" if is_favorite else "☆")
            star.setEnabled(row is not None)
            star.setToolTip(
                "즐겨찾기에서 뺍니다." if is_favorite else "즐겨찾기에 넣습니다."
            )
            # 결과 목록의 별표와 같은 색을 쓴다.
            star.setStyleSheet(
                "QPushButton#documentTabFavorite {"
                f"color: {'#e2a400' if is_favorite else '#c3ccd6'};"
                "border: none; background: transparent;"
                "font-size: 13px; padding: 0;}"
                "QPushButton#documentTabFavorite:hover { color: #e2a400; }"
            )

    def _toggle_document_tab_favorite(self, key: str) -> None:
        row = self._document_tab_row(key)
        if row is None:
            self.status_label.setText(
                "이 탭의 문서 정보를 찾지 못해 즐겨찾기를 바꾸지 못했습니다."
            )
            return
        if str(row.get("target") or "") == "law_article":
            source_row = row.get("source_row")
            unit = row.get("favorite_unit")
            if not isinstance(source_row, dict) or not isinstance(unit, dict):
                return
            jo = str(unit.get("jo") or "")
            hang = str(unit.get("hang") or "")
            ho = str(unit.get("ho") or "")
            mok = str(unit.get("mok") or "")
            favorite = self.law_cache.is_article_favorite(
                source_row, jo, hang=hang, ho=ho, mok=mok
            )
            label = str(unit.get("label") or row.get("name") or "")
            if self.law_cache.set_article_favorite(
                source_row,
                jo,
                label,
                not favorite,
                hang=hang,
                ho=ho,
                mok=mok,
            ):
                self.status_label.setText(
                    f"{label} 즐겨찾기를 "
                    + ("해제했습니다." if favorite else "추가했습니다.")
                )
            else:
                self.status_label.setText(
                    f"즐겨찾기 설정에 실패했습니다: {self.law_cache.last_error}"
                )
            return
        self._toggle_favorite_for_row(row)

    @staticmethod
    def _two_line_tab_title(value: str, max_line_length: int = 12) -> str:
        """긴 문서명을 최대 두 줄의 탭 제목으로 정리."""
        title = " ".join(value.split())
        if len(title) <= max_line_length:
            return title

        max_total_length = max_line_length * 2
        if len(title) > max_total_length:
            title = f"{title[:max_total_length - 1].rstrip()}…"

        midpoint = len(title) / 2
        candidates = [
            index
            for index, character in enumerate(title)
            if character == " "
            and index <= max_line_length
            and len(title) - index - 1 <= max_line_length
        ]
        split_at = (
            min(candidates, key=lambda index: abs(index - midpoint))
            if candidates
            else min(max_line_length, len(title))
        )
        first_line = title[:split_at].rstrip()
        second_line = title[split_at:].lstrip()
        return f"{first_line}\n{second_line}"

    def _close_document_tab(self, index: int) -> None:
        key = str(self.document_tabs.tabData(index) or "")
        if not key or key == "__preview__":
            return
        self._save_active_document_state()
        was_active = key == self._active_document_key
        self.document_tabs.blockSignals(True)
        self.document_tabs.removeTab(index)
        self.document_tabs.blockSignals(False)
        self._document_states.pop(key, None)
        if key in self._document_cache_order:
            self._document_cache_order.remove(key)
        if self.document_tabs.count() == 0:
            self.document_tab_strip.hide()
        else:
            # 탭이 하나 줄었으니 띠 안쪽 폭도 다시 맞춘다.
            self.document_tab_strip.refresh()
        if was_active:
            current_index = self.document_tabs.currentIndex()
            new_key = (
                str(self.document_tabs.tabData(current_index) or "__preview__")
                if current_index >= 0
                else "__preview__"
            )
            self._active_document_key = new_key
            # 크게 보기에서 현재 본문을 닫으면 빈 미리보기의 ``안내``를
            # 전체 화면에 띄우지 않는다. 먼저 크게 보기를 끝내야 법령검색
            # 결과 목록으로 돌아가고, 저장내역·즐겨찾기·AI에서 들어온
            # 경우에는 기존에 붙들어 둔 복귀 콜백이 원래 화면을 되살린다.
            # 다른(비활성) 탭의 ×를 누른 경우에는 읽던 본문을 유지한다.
            if self._reading_mode:
                self._set_reading_mode(False)
            self._restore_document_state(new_key)

    def _restore_toc_scroll(self, key: str = "") -> None:
        """그 문서에서 보던 목차 자리로 되돌린다. 기억이 없으면 맨 위."""
        state = self._document_states.get(key or self._active_document_key)
        value = 0
        if isinstance(state, dict):
            try:
                value = int(state.get("toc_scroll", 0) or 0)
            except (TypeError, ValueError):
                value = 0
        bar = self.toc_tree.verticalScrollBar()
        bar.setValue(max(0, min(value, bar.maximum())))

    def _populate_toc(self, entries: list[tuple[int, str, str]]) -> None:
        self._current_toc_entries = list(entries)
        self.toc_tree.clear()
        self._toc_items = []
        self._toc_search_matches = []
        self._toc_search_index = -1
        if not entries:
            self.toc_search_count.setText("0/0")
            self.toc_panel.hide()
            return

        parents: dict[int, QTreeWidgetItem] = {}
        for depth, label, anchor in entries:
            for existing_depth in tuple(parents):
                if existing_depth >= depth:
                    del parents[existing_depth]
            parent_depths = [level for level in parents if level < depth]
            parent = parents[max(parent_depths)] if parent_depths else None
            item = (
                QTreeWidgetItem(parent, [label])
                if parent is not None
                else QTreeWidgetItem(self.toc_tree, [label])
            )
            item.setData(0, Qt.ItemDataRole.UserRole, anchor)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, depth)
            self._toc_items.append(item)
            if depth < 4:
                font = item.font(0)
                font.setWeight(QFont.Weight.DemiBold)
                item.setFont(0, font)
                parents[depth] = item

        self.toc_tree.expandAll()
        self.toc_panel.show()
        self.detail_content_splitter.setSizes([210, 700])
        self._refresh_toc_search()
        # 새로 채운 목차는 맨 위에서 시작한다. 나무를 비우고 다시 채워도
        # 스크롤 값은 남아, 문서를 바꾸면 앞 문서에서 보던 자리가 그대로
        # 보였다. 기억해 둔 자리가 있으면 부르는 쪽이 뒤이어 되돌린다.
        self.toc_tree.verticalScrollBar().setValue(0)

    def _refresh_toc_search(self) -> None:
        query = self.toc_search_input.text().strip().casefold()
        self._toc_search_matches = (
            [
                item
                for item in self._toc_items
                if item.data(0, Qt.ItemDataRole.UserRole + 1) == 4
                and query in item.text(0).casefold()
            ]
            if query
            else []
        )
        self._toc_search_index = 0 if self._toc_search_matches else -1
        self._update_toc_search_controls()
        if self._toc_search_matches:
            self._activate_toc_search_match()

    def _move_toc_search(self, direction: int) -> None:
        if not self._toc_search_matches:
            self._update_toc_search_controls()
            return
        self._toc_search_index = (
            self._toc_search_index + direction
        ) % len(self._toc_search_matches)
        self._update_toc_search_controls()
        self._activate_toc_search_match()

    def _update_toc_search_controls(self) -> None:
        total = len(self._toc_search_matches)
        current = self._toc_search_index + 1 if total else 0
        self.toc_search_count.setText(f"{current}/{total}")
        enabled = total > 0
        self.toc_previous_button.setEnabled(enabled)
        self.toc_next_button.setEnabled(enabled)

    def _activate_toc_search_match(self) -> None:
        if not (0 <= self._toc_search_index < len(self._toc_search_matches)):
            return
        item = self._toc_search_matches[self._toc_search_index]
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        self.toc_tree.setCurrentItem(item)
        self.toc_tree.scrollToItem(
            item, QAbstractItemView.ScrollHint.PositionAtCenter
        )
        anchor = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        if anchor:
            self.detail_view.scrollToAnchor(anchor)
            self._highlight_toc_article(item)

    def _toc_item_clicked(self, item: QTreeWidgetItem) -> None:
        anchor = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        if anchor:
            self.detail_view.scrollToAnchor(anchor)
            self._highlight_toc_article(item)
            self.detail_view.setFocus()

    def scroll_to_favorite_article(self, jo: str) -> None:
        """즐겨찾기 조문을 팝업이 아닌 현재 법령 본문에서 찾아간다."""
        raw = str(jo or "").strip()
        if not raw:
            return
        if raw.isdigit() and len(raw) == 6:
            article_code = raw
        else:
            match = re.search(r"(?:제)?\s*(\d+)\s*조(?:의\s*(\d+))?", raw)
            if match is None:
                match = re.fullmatch(r"(\d+)(?:의(\d+))?", raw)
            if match is None:
                return
            article_code = law_unit_code(
                match.group(1), match.group(2) or ""
            )
        article = next(
            (
                item
                for item in self._current_three_stage_articles
                if str(item.get("jo") or "") == article_code
            ),
            None,
        )
        if article is None:
            return
        anchor = str(article.get("anchor") or "")
        if not anchor:
            return
        self.detail_view.scrollToAnchor(anchor)
        for index in range(self.toc_tree.topLevelItemCount()):
            stack = [self.toc_tree.topLevelItem(index)]
            while stack:
                item = stack.pop()
                if str(item.data(0, Qt.ItemDataRole.UserRole) or "") == anchor:
                    self.toc_tree.setCurrentItem(item)
                    self._highlight_toc_article(item)
                    self.detail_view.setFocus()
                    return
                stack.extend(
                    item.child(child_index)
                    for child_index in range(item.childCount())
                )

    def _anchor_position(self, anchor: str) -> int | None:
        """HTML 이름 앵커가 적용된 첫 글자의 문서 위치를 반환."""
        block = self.detail_view.document().begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid() and anchor in fragment.charFormat().anchorNames():
                    return fragment.position()
                iterator += 1
            block = block.next()
        return None

    def _clear_three_stage_buttons(self) -> None:
        """본문 조문 옆 3단비교·즐겨찾기 단추를 걷어낸다."""
        for button in (
            *self._three_stage_buttons,
            *self._article_favorite_buttons,
        ):
            button.hide()
            button.deleteLater()
        self._three_stage_buttons = []
        self._article_favorite_buttons = []
        self._three_stage_anchor_positions = {}

    def _set_three_stage_articles(
        self, articles: list, *, document_prepared: bool = False
    ) -> None:
        """현재 법령 조문의 3단비교 버튼과 본문 내 하위법령 링크를 구성."""
        self._clear_three_stage_buttons()
        self._current_three_stage_articles = [
            {
                "anchor": str(article.get("anchor") or ""),
                "label": str(article.get("label") or ""),
                "jo": str(article.get("jo") or ""),
                "law_id": str(article.get("law_id") or ""),
                "law_name": str(article.get("law_name") or ""),
                "subordinate_links": [
                    dict(link)
                    for link in article.get("subordinate_links", [])
                    if isinstance(link, dict)
                    and link.get("href")
                    and link.get("text")
                ],
                "comparison_available": article.get("comparison_available"),
            }
            for article in articles
            if isinstance(article, dict)
            and article.get("anchor")
            and article.get("jo")
            and article.get("law_id")
        ]

        root_frame = self.detail_view.document().rootFrame()
        frame_format = root_frame.frameFormat()
        # 조문 첫 줄의 오른쪽 끝에 버튼 자리를 따로 확보한다.
        frame_format.setRightMargin(64.0)
        root_frame.setFrameFormat(frame_format)

        viewport = self.detail_view.viewport()
        star_size = self._ARTICLE_FAVORITE_SIZE
        for article in self._current_three_stage_articles:
            favorite_button = QPushButton("☆", viewport)
            favorite_button.setObjectName("articleFavoriteButton")
            favorite_button.setFixedSize(star_size, star_size)
            favorite_button.setCursor(Qt.CursorShape.PointingHandCursor)
            favorite_button.setAccessibleName(
                f"{article['label']} 조문 즐겨찾기"
            )
            favorite_button.clicked.connect(
                lambda _checked=False, item=dict(article): (
                    self._toggle_inline_article_favorite(item)
                )
            )
            favorite_button.hide()
            self._article_favorite_buttons.append(favorite_button)

            button = QPushButton("3단비교", viewport)
            button.setObjectName("threeStageArticleButton")
            # 글자 크기는 유지하고 버튼 안쪽 여백만 줄인다.
            button.setFixedSize(56, 24)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(
                f"{article['label']}의 법률·시행령·시행규칙을 3단으로 비교합니다."
            )
            button.clicked.connect(
                lambda _checked=False, item=dict(article): (
                    self._open_three_stage_comparison(item)
                )
            )
            button.hide()
            self._three_stage_buttons.append(button)
        remaining_anchors = {
            article["anchor"] for article in self._current_three_stage_articles
        }
        block = self.detail_view.document().begin()
        while block.isValid() and remaining_anchors:
            iterator = block.begin()
            while not iterator.atEnd() and remaining_anchors:
                fragment = iterator.fragment()
                if fragment.isValid():
                    for anchor in set(fragment.charFormat().anchorNames()).intersection(
                        remaining_anchors
                    ):
                        self._three_stage_anchor_positions[anchor] = (
                            fragment.position()
                        )
                        remaining_anchors.remove(anchor)
                iterator += 1
            block = block.next()
        if not document_prepared:
            self._apply_inline_subordinate_links()
        document = self.detail_view.document()
        try:
            document.contentsChanged.disconnect(
                self._schedule_three_stage_button_positions
            )
            connected = True
        except (RuntimeError, TypeError):
            connected = False
        heading_margin = self._ARTICLE_FAVORITE_HEADING_MARGIN
        # setBlockFormat을 조문마다 확정하면 매번 전체 문서 레이아웃을
        # 다시 계산한다. 한 편집 블록으로 묶어 마지막에 한 번만 배치한다.
        format_cursor = QTextCursor(document)
        format_cursor.beginEditBlock()
        try:
            for article in self._current_three_stage_articles:
                position = self._three_stage_anchor_positions.get(
                    article["anchor"]
                )
                if position is None:
                    continue
                format_cursor.setPosition(position)
                block_format = format_cursor.blockFormat()
                changed = False
                if block_format.topMargin() < 14.0:
                    block_format.setTopMargin(14.0)
                    changed = True
                # 별이 제N조 글자와 겹치지 않도록 조문 첫 블록에만 자리를 낸다.
                # 문서 전체 왼쪽 여백을 바꾸면 제목·기본정보까지 함께 밀린다.
                if block_format.leftMargin() != heading_margin:
                    block_format.setLeftMargin(heading_margin)
                    changed = True
                if changed:
                    format_cursor.setBlockFormat(block_format)
        finally:
            format_cursor.endEditBlock()
            if connected:
                document.contentsChanged.connect(
                    self._schedule_three_stage_button_positions
                )
        self._refresh_inline_article_favorites()
        self._schedule_three_stage_button_positions()

    def _refresh_inline_article_favorites(self) -> None:
        """본문의 조문별 별표를 저장 상태와 맞춘다."""
        if not hasattr(self, "_article_favorite_buttons"):
            return
        favorite_keys: dict[str, set[tuple[str, str, str, str]]] = {}
        star_size = self._ARTICLE_FAVORITE_SIZE
        for article, button in zip(
            self._current_three_stage_articles,
            self._article_favorite_buttons,
        ):
            law_id = str(article.get("law_id") or "")
            jo = str(article.get("jo") or "")
            law_name = str(article.get("law_name") or "")
            row = self._law_row(law_id, law_name) if law_id and jo else None
            favorite = False
            if row is not None:
                keys = favorite_keys.get(law_id)
                if keys is None:
                    keys = {
                        (
                            str(entry.get("jo") or ""),
                            str(entry.get("hang") or ""),
                            str(entry.get("ho") or ""),
                            str(entry.get("mok") or ""),
                        )
                        for entry in self.law_cache.article_favorites(row)
                    }
                    favorite_keys[law_id] = keys
                favorite = (jo, "", "", "") in keys
            label = str(article.get("label") or self._law_reference_label(jo))
            button.setText("★" if favorite else "☆")
            button.setEnabled(row is not None)
            button.setToolTip(
                f"{label} 즐겨찾기를 "
                + ("해제합니다." if favorite else "추가합니다.")
            )
            button.setAccessibleName(button.toolTip())
            button.setStyleSheet(
                "QPushButton#articleFavoriteButton {"
                f"color: {'#e2a400' if favorite else '#aeb9c5'};"
                "border:none; background:transparent; padding:0;"
                f"font-size:13px; min-width:{star_size}px; max-width:{star_size}px;"
                f"min-height:{star_size}px; max-height:{star_size}px;}}"
                "QPushButton#articleFavoriteButton:hover {color:#e2a400;}"
            )

    def _toggle_inline_article_favorite(
        self, article: dict[str, object]
    ) -> None:
        """법령 전문의 제N조 왼쪽 별표로 그 조문만 즐겨찾기 토글."""
        law_id = str(article.get("law_id") or "")
        jo = str(article.get("jo") or "")
        law_name = str(article.get("law_name") or "")
        label = str(article.get("label") or self._law_reference_label(jo))
        row = self._law_row(law_id, law_name) if law_id and jo else None
        if row is None:
            self.status_label.setText("이 조문은 즐겨찾기에 걸 수 없습니다.")
            return
        favorite = self.law_cache.is_article_favorite(row, jo)
        if favorite:
            if self.law_cache.set_article_favorite(row, jo, label, False):
                self.status_label.setText(f"{label} 즐겨찾기를 해제했습니다.")
            else:
                self.status_label.setText(
                    f"즐겨찾기 해제에 실패했습니다: {self.law_cache.last_error}"
                )
        else:
            self.add_article_favorite_by_id(
                law_id, jo, label, law_name
            )
        self._refresh_inline_article_favorites()

    @staticmethod
    def _inline_subordinate_href(links: list[dict[str, str]]) -> str:
        if not links:
            # 링크 후보가 없으면 빈 배열([])을 인코딩한 "그럴듯한"
            # href를 만들지 않는다. 그러면 클릭 가능한 것처럼 밑줄이
            # 쳐지고서 눌렀을 때만 "하위법령 링크 없음"이 뜨게 된다.
            return ""
        if len(links) == 1:
            return str(links[0].get("href") or "")
        payload = json.dumps(
            [
                {
                    "text": str(link.get("text") or "하위법령"),
                    "href": str(link.get("href") or ""),
                }
                for link in links
                if link.get("href")
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        encoded = base64.urlsafe_b64encode(payload.encode("utf-8")).decode(
            "ascii"
        ).rstrip("=")
        return f"lawsub://open?data={encoded}" if encoded else ""

    _INLINE_HO_PATTERN = re.compile(r"(?m)^\s*(\d+)(?:의\s*(\d+))?\.\s+")

    @classmethod
    def _build_inline_source_index(
        cls, article_text: str
    ) -> tuple[list[int], list[str], list[int], list[str]]:
        """조문 전체의 항(①…)·호(1. 2. …) 표식 위치를 한 번만 훑어
        표를 만든다. 대통령령·부령 언급이 나올 때마다 그 앞부분을
        매번 처음부터 다시 훑으면(원래 방식) 언급이 많은 긴 조문에서
        문서 하나 여는 데 몇 초씩 걸릴 수 있어, 위치 목록을 미리
        만들어 두고 이분 탐색으로 찾도록 바꿨다."""
        circled_numbers = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
        hang_positions: list[int] = []
        hang_codes: list[str] = []
        for match in re.finditer(f"[{circled_numbers}]", article_text):
            hang_positions.append(match.start())
            hang_codes.append(
                law_unit_code(str(circled_numbers.index(match.group(0)) + 1))
            )
        ho_positions: list[int] = []
        ho_codes: list[str] = []
        for match in cls._INLINE_HO_PATTERN.finditer(article_text):
            try:
                ho_code = law_unit_code(match.group(1), match.group(2) or "")
            except ValueError:
                continue
            ho_positions.append(match.start())
            ho_codes.append(ho_code)
        return hang_positions, hang_codes, ho_positions, ho_codes

    @staticmethod
    def _inline_law_source_context(
        position: int,
        hang_positions: list[int],
        hang_codes: list[str],
        ho_positions: list[int],
        ho_codes: list[str],
    ) -> tuple[str, str]:
        """position 바로 앞에서 가장 가까운 법률 항·호를 찾음."""
        hang_index = bisect.bisect_right(hang_positions, position) - 1
        hang_code = hang_codes[hang_index] if hang_index >= 0 else ""
        hang_start = hang_positions[hang_index] if hang_index >= 0 else 0
        ho_index = bisect.bisect_right(ho_positions, position) - 1
        ho_code = (
            ho_codes[ho_index]
            if ho_index >= 0 and ho_positions[ho_index] >= hang_start
            else ""
        )
        return hang_code, ho_code

    @staticmethod
    def _links_for_inline_source(
        links: list[dict[str, str]], hang_code: str, ho_code: str
    ) -> list[dict[str, str]]:
        scoped_links = [
            link
            for link in links
            if link.get("source_hang") or link.get("source_ho")
        ]
        exact_links = [
            link
            for link in scoped_links
            if (
                not link.get("source_hang")
                or link.get("source_hang") == hang_code
            )
            and (
                not link.get("source_ho")
                or link.get("source_ho") == ho_code
            )
        ]
        if exact_links:
            return exact_links
        return [
            link
            for link in links
            if not link.get("source_hang") and not link.get("source_ho")
        ]

    @staticmethod
    def _specific_ministerial_rule_link(
        article: dict[str, object], authority: str, hang_code: str
    ) -> dict[str, str] | None:
        """Resolve a ministerial-rule delegation fixed by its legal context."""
        law_name = re.sub(r"\s+", "", str(article.get("law_name") or ""))
        source_location = (
            law_name,
            str(article.get("jo") or ""),
            hang_code,
        )
        facility_rule_sources = {
            ("국토의계획및이용에관한법률", "004300", "000300"),
            ("국토의계획및이용에관한법률시행령", "000200", "000300"),
        }
        if source_location in facility_rule_sources and authority == "국토교통부령":
            target_name = "도시ㆍ군계획시설의 결정ㆍ구조 및 설치기준에 관한 규칙"
            return {
                "text": target_name,
                "href": f"lawref://open?name={quote(target_name, safe='')}",
            }
        return None

    @staticmethod
    def _with_delegation_source(
        href: str,
        *,
        law_name: str,
        source_label: str,
        authority: str,
    ) -> str:
        """위임 링크에 '어느 조문이 위임했는지'를 덧붙인다."""
        if not href.startswith("lawref://") or not source_label:
            return href
        extra = [f"via_label={quote(source_label, safe='')}"]
        if law_name:
            extra.append(f"via_name={quote(law_name, safe='')}")
        if authority:
            extra.append(f"via_authority={quote(authority, safe='')}")
        separator = "&" if "?" in href else "?"
        return href + separator + "&".join(extra)

    def _apply_inline_subordinate_links(self) -> None:
        """조문 문장 속 대통령령·소관부처령 표현에 대응 조문 링크를 적용."""
        document = self.detail_view.document()
        plain_text = document.toPlainText()
        # mergeCharFormat도 호출마다 문서를 재배치하므로 한 편집으로 묶는다.
        # 링크별 범위는 같은 커서를 옮겨도 그대로 독립적으로 적용된다.
        format_cursor = QTextCursor(document)
        format_cursor.beginEditBlock()
        positioned_articles = [
            (self._three_stage_anchor_positions.get(str(article["anchor"])), article)
            for article in self._current_three_stage_articles
        ]
        positioned_articles = [
            (position, article)
            for position, article in positioned_articles
            if position is not None
        ]
        positioned_articles.sort(key=lambda entry: int(entry[0]))
        try:
            for article_index, (start_value, article) in enumerate(
                positioned_articles
            ):
                start = int(start_value)
                end = (
                    int(positioned_articles[article_index + 1][0])
                    if article_index + 1 < len(positioned_articles)
                    else max(0, document.characterCount() - 1)
                )
                if end <= start:
                    continue
                grouped_links: dict[str, list[dict[str, str]]] = {}
                for link in article.get("subordinate_links", []):
                    if not isinstance(link, dict):
                        continue
                    text = str(link.get("text") or "")
                    authority_match = re.match(r"(.+?)\s+제\d+조", text)
                    authority = (
                        authority_match.group(1).strip()
                        if authority_match is not None
                        else ""
                    )
                    if authority and link.get("href"):
                        grouped_links.setdefault(authority, []).append(dict(link))
                article_text = plain_text[start:end]
                source_index = self._build_inline_source_index(article_text)
                for authority, links in grouped_links.items():
                    search_term = authority
                    if search_term not in article_text and authority.endswith("부령"):
                        search_term = "부령"
                    for match in re.finditer(re.escape(search_term), article_text):
                        hang_code, ho_code = self._inline_law_source_context(
                            match.start(), *source_index
                        )
                        matched_links = self._links_for_inline_source(
                            links, hang_code, ho_code
                        )
                        specific_link = self._specific_ministerial_rule_link(
                            article, authority, hang_code
                        )
                        if specific_link is not None:
                            matched_links = [specific_link]
                        href = self._inline_subordinate_href(matched_links)
                        if not href:
                            continue
                        # 하단 기록에 "국토계획법 제3조의2제2항 대통령령"처럼
                        # 어느 조문이 위임했는지 남기려고 출처를 함께 싣는다.
                        href = self._with_delegation_source(
                            href,
                            law_name=str(article.get("law_name") or ""),
                            source_label=self._law_reference_label(
                                str(article.get("jo") or ""), hang_code, ho_code
                            ),
                            authority=authority,
                        )
                        format_cursor.setPosition(start + match.start())
                        format_cursor.setPosition(
                            start + match.end(), QTextCursor.MoveMode.KeepAnchor
                        )
                        character_format = QTextCharFormat()
                        character_format.setAnchor(True)
                        character_format.setAnchorHref(href)
                        # 아래 「도시개발법」 같은 일반 조문 인용 링크와 같은
                        # 색·밑줄로 맞춘다(law_reference_html_text가 만드는
                        # <a style="color:#006dcc; text-decoration:underline;">
                        # 와 동일).
                        character_format.setForeground(QColor("#006dcc"))
                        character_format.setFontUnderline(True)
                        character_format.setFontWeight(int(QFont.Weight.DemiBold))
                        target_labels = [
                            str(link.get("text") or "").strip()
                            for link in matched_links
                            if str(link.get("text") or "").strip()
                        ]
                        if target_labels:
                            character_format.setToolTip(
                                "연결 조문: " + " / ".join(target_labels)
                            )
                        character_format.setProperty(
                            BASE_FOREGROUND_PROPERTY, "#006dcc"
                        )
                        format_cursor.mergeCharFormat(character_format)
        finally:
            format_cursor.endEditBlock()

    def _schedule_three_stage_button_positions(
        self, _value: object = None
    ) -> None:
        if self._three_stage_position_pending:
            return
        self._three_stage_position_pending = True
        QTimer.singleShot(0, self._position_three_stage_buttons)

    def _position_three_stage_buttons(self) -> None:
        self._three_stage_position_pending = False
        viewport = self.detail_view.viewport()
        if not self.detail_view.isVisible() or not viewport.isVisible():
            for button in (
                *self._three_stage_buttons,
                *self._article_favorite_buttons,
            ):
                button.hide()
            return
        for article, button in zip(
            self._current_three_stage_articles,
            self._article_favorite_buttons,
        ):
            position = self._three_stage_anchor_positions.get(article["anchor"])
            if position is None:
                button.hide()
                continue
            cursor = QTextCursor(self.detail_view.document())
            cursor.setPosition(position)
            rect = self.detail_view.cursorRect(cursor)
            button_x = max(
                1,
                rect.left() - button.width() - self._ARTICLE_FAVORITE_GAP,
            )
            button_y = rect.top()
            visible = (
                rect.bottom() >= 0
                and button_y <= viewport.height()
            )
            if not visible:
                button.hide()
                continue
            button.move(button_x, button_y)
            button.show()
            button.raise_()
        for article, button in zip(
            self._current_three_stage_articles,
            self._three_stage_buttons,
        ):
            # None은 아직 3단비교 API 확인 전인 상태다. 예전에는 이때도
            # 버튼을 먼저 보여 줘서, 비교 조문이 없는 항목의 버튼이
            # 응답이 온 1초 뒤 사라지는 깜빡임이 있었다. 실제 비교가
            # 확인된 True 항목만 표시한다.
            if article.get("comparison_available") is not True:
                button.hide()
                continue
            position = self._three_stage_anchor_positions.get(
                article["anchor"]
            )
            if position is None:
                button.hide()
                continue
            cursor = QTextCursor(self.detail_view.document())
            cursor.setPosition(position)
            rect = self.detail_view.cursorRect(cursor)
            button_x = max(1, viewport.width() - button.width() - 8)
            button_y = rect.top()
            visible = (
                rect.bottom() >= 0
                and button_y <= viewport.height()
            )
            if not visible:
                button.hide()
                continue
            button.move(button_x, button_y)
            button.show()
            button.raise_()

    def _cursor_over_three_stage_button(self) -> bool:
        return any(
            button.isVisible() and button.underMouse()
            for button in self._three_stage_buttons
        )

    def _highlight_toc_article(self, item: QTreeWidgetItem) -> None:
        """이동한 조문의 첫 문단 한 줄만 아주 옅게 표시."""
        depth = int(item.data(0, Qt.ItemDataRole.UserRole + 1) or 0)
        anchor = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        if depth != 4 or not anchor:
            self.detail_search.set_base_selections([])
            return

        start = self._anchor_position(anchor)
        if start is None:
            self.detail_search.set_base_selections([])
            return
        cursor = QTextCursor(self.detail_view.document())
        cursor.setPosition(start)
        block = cursor.block()
        cursor.setPosition(
            max(start, block.position() + block.length() - 1),
            QTextCursor.MoveMode.KeepAnchor,
        )
        selection = QTextEdit.ExtraSelection()
        selection.cursor = cursor
        selection.format.setBackground(QColor("#edf5fb"))
        selection.format.setProperty(
            QTextFormat.Property.FullWidthSelection, True
        )
        self.detail_search.set_base_selections([selection])

    def _clear_toc_highlight(self) -> None:
        """조문 이동 시 표시된 파란 음영을 지워 아래 실제 색상 서식이 또렷이 보이게 함."""
        self.detail_search.set_base_selections([])
        self.toc_tree.clearSelection()

    def eventFilter(self, watched, event) -> bool:
        if (
            watched is self.detail_view.viewport()
            and event.type() == QEvent.Type.MouseMove
        ):
            position = event.position()
            href = self.detail_view.anchorAt(position.toPoint())
            document_position = QPointF(
                position.x() + self.detail_view.horizontalScrollBar().value(),
                position.y() + self.detail_view.verticalScrollBar().value(),
            )
            text_position = self.detail_view.document().documentLayout().hitTest(
                document_position,
                Qt.HitTestAccuracy.ExactHit,
            )
            self.detail_view.viewport().setCursor(
                Qt.CursorShape.PointingHandCursor
                if href
                else Qt.CursorShape.IBeamCursor
                if text_position >= 0
                else Qt.CursorShape.ArrowCursor
            )
        if (
            watched is self.detail_view.viewport()
            and event.type() in (QEvent.Type.Resize, QEvent.Type.Show)
        ):
            self._schedule_three_stage_button_positions()
        return super().eventFilter(watched, event)

    def _show_pdf_preview(self, url: str) -> None:
        self._open_pdf_preview(url, "PDF 미리보기")

    def _all_pdf_popups(self) -> list[PdfPreviewPopup]:
        return [self.pdf_preview_popup, *self._extra_pdf_popups]

    def _open_pdf_preview(self, url: str, title: str) -> None:
        """PDF 미리보기를 연다. 고정된 창은 덮지 않고 새 창을 띄운다.

        조문 참조 팝업과 같은 규칙이다 — 고정하지 않은 창이 있으면 거기에
        보여 주고, 모두 고정돼 있으면 새로 하나 만든다. 그래야 별표 두
        개를 나란히 놓고 견줄 수 있다.
        """
        popup = self._pdf_popup_for_request(url)
        popup.show_pdf(url, title, QCursor.pos())
        self._place_pdf_popup(popup)

    # 창이 끝없이 늘지 않게 상한을 둔다. 넘으면 가장 먼저 띄운 것을 쓴다.
    _MAX_PDF_POPUPS = 8

    def _pdf_popup_for_request(self, url: str) -> PdfPreviewPopup:
        """어느 창에 보여 줄지 고른다.

        PDF 미리보기는 "고정"이 기본으로 켜져 있어(마우스가 떠나도 닫히지
        않는다) 고정 여부로는 가를 수 없다. 대신 화면에 떠 있는 창은
        건드리지 않고, 닫아 둔 창부터 다시 쓴다. 그래야 별표 두 개를
        나란히 놓고 볼 수 있으면서도 창이 무한정 쌓이지 않는다.
        """
        popups = self._all_pdf_popups()
        for popup in popups:
            if popup.isVisible() and popup.current_url() == url:
                # 같은 별표를 또 눌렀다. 새 창 대신 그 창을 앞으로.
                return popup
        for popup in popups:
            if not popup.isVisible():
                return popup
        if len(popups) >= self._MAX_PDF_POPUPS:
            return popups[0]
        popup = PdfPreviewPopup(self)
        popup.resize(self.pdf_preview_popup.size())
        self._extra_pdf_popups.append(popup)
        return popup

    def _place_pdf_popup(self, popup: PdfPreviewPopup) -> None:
        """고정해 둔 미리보기와 똑같은 자리에 겹쳐 뜨지 않게 물린다."""
        others = [
            candidate
            for candidate in self._all_pdf_popups()
            if candidate is not popup and candidate.isVisible()
        ]
        if not others:
            return
        screen = (
            QApplication.screenAt(popup.frameGeometry().center())
            or QApplication.primaryScreen()
        )
        if screen is None:
            return
        area = screen.availableGeometry()
        step = 28
        for _attempt in range(len(others) + 1):
            corner = popup.frameGeometry().topLeft()
            clash = any(
                abs(candidate.frameGeometry().topLeft().x() - corner.x()) < step
                and abs(candidate.frameGeometry().topLeft().y() - corner.y())
                < step
                for candidate in others
            )
            if not clash:
                return
            popup.move(
                max(
                    area.left(),
                    min(corner.x() + step, area.right() - popup.width()),
                ),
                max(
                    area.top(),
                    min(corner.y() + step, area.bottom() - popup.height()),
                ),
            )

    def _open_three_stage_comparison(
        self, article: dict[str, str]
    ) -> None:
        law_id = str(article.get("law_id") or "")
        jo = str(article.get("jo") or "")
        law_name = str(article.get("law_name") or "법령")
        label = str(article.get("label") or self._law_reference_label(jo))
        if not law_id or not jo:
            QMessageBox.warning(
                self,
                "3단비교 정보 없음",
                "3단비교에 필요한 법령 ID 또는 조문 번호가 없습니다.",
            )
            return

        self._pending_three_stage_article = dict(article)
        self.three_stage_popup.reference_key = f"thdcmp:{law_id}:{jo}"
        cached_payload = self._three_stage_payload_cache.get(law_id)
        if cached_payload is not None:
            try:
                self._show_three_stage_comparison(
                    {
                        "payload": cached_payload,
                        "item_id": law_id,
                        "law_name": law_name,
                        "jo": jo,
                    },
                    cached=True,
                )
            except Exception as exc:
                self.three_stage_popup.show_loading(
                    f"{law_name} {label} 3단비교",
                    QCursor.pos(),
                    "받아 둔 3단비교 자료를 확인하는 중입니다…",
                )
                self.three_stage_popup.set_error(str(exc))
                self.status_label.setText("3단비교 자료를 찾지 못했습니다.")
            return

        if self.worker and self.worker.isRunning():
            self.status_label.setText(
                "현재 API 조회가 진행 중입니다 · 완료 후 다시 눌러 주세요."
            )
            return
        oc = self.oc_provider().strip()
        if not oc:
            prompt_oc_api_key(self)
            return

        popup_title = f"{law_name} {label} 3단비교"
        self.three_stage_popup.show_loading(
            popup_title,
            QCursor.pos(),
            "3단비교 API에서 법률·시행령·시행규칙을 불러오는 중입니다…",
        )
        self._start_worker(
            ResourceApiWorker(
                "three_stage_comparison",
                oc=oc,
                target="law",
                item_id=law_id,
                law_name=law_name,
                jo=jo,
                parent=self,
            ),
            f"{law_name} {label} 3단비교 조회 중...",
        )

    @staticmethod
    def _three_stage_article_code(node: dict) -> str:
        try:
            number = int(re.sub(r"\D", "", json_text(node.get("조번호"))) or "0")
            branch = int(
                re.sub(r"\D", "", json_text(node.get("조가지번호"))) or "0"
            )
        except (TypeError, ValueError):
            return ""
        return f"{number:04d}{branch:02d}"

    @classmethod
    def _three_stage_child_nodes(cls, value: object) -> list[dict]:
        if isinstance(value, list):
            nodes: list[dict] = []
            for item in value:
                nodes.extend(cls._three_stage_child_nodes(item))
            return nodes
        if not isinstance(value, dict):
            return []
        if any(key in value for key in ("조제목", "조내용", "조번호")):
            return [value]
        nodes = []
        for nested in value.values():
            nodes.extend(cls._three_stage_child_nodes(nested))
        return nodes

    _THREE_STAGE_GENERIC_LAW_NAMES = frozenset(
        {"시행령", "시행규칙", "부령", "대통령령", "총리령"}
    )

    @classmethod
    def _three_stage_named_law(cls, name: str) -> str:
        """열 머리·조문 식별에 쓸 실제 법령명. 빈 값과 자리표시는 뺀다."""
        cleaned = re.sub(r"\s+", "", json_text(name))
        if not cleaned or cleaned in cls._THREE_STAGE_GENERIC_LAW_NAMES:
            return ""
        return cleaned

    @staticmethod
    def _three_stage_content_fingerprint(node: dict) -> str:
        content = re.sub(r"<[^>]+>", "", json_text(node.get("조내용")))
        return re.sub(r"\s+", "", content)

    @classmethod
    def _deduplicate_three_stage_nodes(cls, nodes: list[dict]) -> list[dict]:
        """위임 건수만큼 반복된 같은 조문을 하나로 합친다.

        법제처는 위임마다 같은 시행령 조를 다시 싣고, 어떤 항목은
        법령명이 비어 있다. 법령명까지 키에 넣으면 제25조가 두 번
        남는다. 조번호·본문이 같고 한쪽만 이름이 없으면 이름 있는
        쪽을 남긴다. 다른 법령의 같은 조번호는 합치지 않는다.
        """
        unique: list[dict] = []
        seen_named: set[tuple[str, str, str]] = set()
        seen_anonymous: set[tuple[str, str]] = set()
        named_fingerprints: set[tuple[str, str]] = set()

        for node in nodes:
            code = cls._three_stage_article_code(node)
            content = cls._three_stage_content_fingerprint(node)
            named = cls._three_stage_named_law(json_text(node.get("법령명")))
            fingerprint = (code, content)
            if named:
                key = (code, content, named)
                if key in seen_named:
                    continue
                seen_named.add(key)
                named_fingerprints.add(fingerprint)
                unique.append(node)
                continue
            if fingerprint in seen_anonymous:
                continue
            seen_anonymous.add(fingerprint)
            unique.append(node)

        return [
            node
            for node in unique
            if cls._three_stage_named_law(json_text(node.get("법령명")))
            or (
                cls._three_stage_article_code(node),
                cls._three_stage_content_fingerprint(node),
            )
            not in named_fingerprints
        ]

    @staticmethod
    def _three_stage_comparison_body(payload: dict) -> dict:
        service = next(
            (
                value
                for value in payload.values()
                if isinstance(value, dict)
                and (
                    "위임조문삼단비교" in value
                    or "인용조문삼단비교" in value
                )
            ),
            None,
        )
        if not isinstance(service, dict):
            return {}
        comparison = service.get("위임조문삼단비교")
        if not isinstance(comparison, dict):
            comparison = service.get("인용조문삼단비교")
        return comparison if isinstance(comparison, dict) else {}

    @classmethod
    def _three_stage_reference_link(
        cls,
        node: dict,
        *,
        authority: str,
        fallback_law_name: str,
    ) -> dict[str, str] | None:
        law_name = json_text(node.get("법령명")) or fallback_law_name
        code = cls._three_stage_article_code(node)
        if not law_name or not code:
            return None
        number = int(code[:4])
        branch = int(code[4:])
        article_label = f"제{number}조" + (f"의{branch}" if branch else "")
        parameters = [
            f"name={quote(law_name, safe='')}",
            f"jo={number}",
        ]
        if branch:
            parameters.append(f"jo_branch={branch}")
        title = json_text(node.get("조제목")) or article_label
        return {
            "href": f"lawref://open?{'&'.join(parameters)}",
            "text": f"{authority} {article_label}",
            "tooltip": f"{law_name} {title} 조문을 엽니다.",
            "target_code": code,
            "law_name": law_name,
        }

    _RULE_DECREE_UNIT_PATTERN = re.compile(
        # ``영 제4조``뿐 아니라 ``「…법률 시행령」(이하 “영”이라 한다)
        # 제4조제2호``처럼 낫표와 약칭 선언을 사이에 두는 인용도 잡는다.
        r"(?:영|시행령)」?\s*(?:\([^)]{0,40}\)\s*)?"
        r"제\s*(\d+)\s*조(?:의\s*(\d+))?"
        r"(?:\s*제\s*(\d+)\s*항(?:의\s*(\d+))?)?"
        r"(?:\s*제\s*(\d+)\s*호(?:의\s*(\d+))?)?"
        rf"(?:\s*([{KOREAN_ITEM_MARKERS}])\s*목)?"
    )

    @classmethod
    def _decree_units_referenced_by_rule(cls, content: str) -> list[dict[str, str]]:
        """시행규칙 조문에서 근거 시행령의 조·항·호·목을 추출."""
        references: list[dict[str, str]] = []
        seen: set[tuple[str, str, str, str]] = set()
        for match in cls._RULE_DECREE_UNIT_PATTERN.finditer(content):
            try:
                article_code = law_unit_code(match.group(1), match.group(2) or "")
                hang_code = (
                    law_unit_code(match.group(3), match.group(4) or "")
                    if match.group(3)
                    else ""
                )
                ho_code = (
                    law_unit_code(match.group(5), match.group(6) or "")
                    if match.group(5)
                    else ""
                )
            except ValueError:
                continue
            mok = str(match.group(7) or "")
            key = (article_code, hang_code, ho_code, mok)
            if key in seen:
                continue
            seen.add(key)
            references.append(
                {
                    "article_code": article_code,
                    "source_hang": hang_code,
                    "source_ho": ho_code,
                    "source_mok": mok,
                }
            )
        return references

    @classmethod
    def _decree_codes_referenced_by_rule(cls, content: str) -> set[str]:
        return {
            unit["article_code"]
            for unit in cls._decree_units_referenced_by_rule(content)
            if unit.get("article_code")
        }

    @staticmethod
    def _law_source_units_referenced_by_decree(
        content: str, base_article_code: str
    ) -> list[dict[str, str]]:
        """시행령 조문에서 근거 법률의 항·호 단위를 추출."""
        references: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        pattern = re.compile(
            r"제\s*(\d+)\s*조(?:의\s*(\d+))?"
            r"(?:\s*제\s*(\d+)\s*항(?:의\s*(\d+))?)?"
            r"(?:\s*제\s*(\d+)\s*호(?:의\s*(\d+))?)?"
            # ``법 제2조제2호다목``처럼 목까지 지목하는 위임이 있다.
            # ``[가-하]``로 쓰면 ``제1호 각 목 외의 부분``의 ``각``까지
            # 목 표지로 잡히므로 실제 표지 글자만 나열한다.
            rf"(?:\s*([{KOREAN_ITEM_MARKERS}])\s*목)?"
        )
        for match in pattern.finditer(content):
            try:
                article_code = law_unit_code(
                    match.group(1), match.group(2) or ""
                )
                if article_code != base_article_code:
                    continue
                hang_code = (
                    law_unit_code(match.group(3), match.group(4) or "")
                    if match.group(3)
                    else ""
                )
                ho_code = (
                    law_unit_code(match.group(5), match.group(6) or "")
                    if match.group(5)
                    else ""
                )
            except ValueError:
                continue
            if not hang_code and not ho_code:
                continue
            mok = str(match.group(7) or "")
            key = (hang_code, ho_code, mok)
            if key in seen:
                continue
            seen.add(key)
            references.append(
                {
                    "source_hang": hang_code,
                    "source_ho": ho_code,
                    "source_mok": mok,
                }
            )
            # 시행령 한 조문이 법률의 여러 항·호(제8조제2항, 제3항,
            # 제4항제4호 등)를 한꺼번에 위임 근거로 나열하는 경우가
            # 있으므로, 첫 번째 것만 취하지 않고 전부 모은다.
        return references

    @classmethod
    def _three_stage_subordinate_links(
        cls,
        payload: dict,
        *,
        document_level: str,
        organization: str = "",
    ) -> dict[str, list[dict[str, str]]]:
        # 검색 API의 소관부처 값에는 ``국토교통부&#x20;``처럼 HTML 공백
        # 엔티티가 붙기도 한다. 그대로 두면 ``endswith('부')`` 판정이
        # 실패해 링크 표기가 일반 ``부령``으로 축약된다.
        organization = json_text(organization)
        comparison = cls._three_stage_comparison_body(payload)
        articles = [
            article
            for article in json_list(comparison.get("법률조문"))
            if isinstance(article, dict)
        ]
        links_by_article: dict[str, list[dict[str, str]]] = {}

        def add_link(code: str, link: dict[str, str] | None) -> None:
            if not code or link is None:
                return
            links = links_by_article.setdefault(code, [])
            target = str(link.get("target_code") or "")
            for index, existing in enumerate(links):
                same_source = (
                    existing.get("source_hang") == link.get("source_hang")
                    and existing.get("source_ho") == link.get("source_ho")
                )
                same_target = bool(
                    existing.get("href") == link.get("href")
                    or (
                        target
                        and existing.get("target_code") == target
                    )
                )
                if not (same_source and same_target):
                    continue
                # 법령명이 비어 온 같은 조 링크는 이름 있는 쪽으로 교체한다.
                existing_named = cls._three_stage_named_law(
                    str(existing.get("law_name") or "")
                )
                new_named = cls._three_stage_named_law(
                    str(link.get("law_name") or "")
                )
                if new_named and not existing_named:
                    links[index] = link
                return
            links.append(link)

        if document_level == "law":
            for article in articles:
                base_code = cls._three_stage_article_code(article)
                decree_nodes: list[dict] = []
                rule_nodes: list[dict] = []
                for key in ("시행령조문", "시행령조문목록"):
                    decree_nodes.extend(cls._three_stage_child_nodes(article.get(key)))
                for key in ("시행규칙조문", "시행규칙조문목록"):
                    rule_nodes.extend(cls._three_stage_child_nodes(article.get(key)))
                for decree in cls._deduplicate_three_stage_nodes(decree_nodes):
                    link = cls._three_stage_reference_link(
                        decree,
                        authority="대통령령",
                        fallback_law_name="시행령",
                    )
                    if link is None:
                        continue
                    source_units = cls._law_source_units_referenced_by_decree(
                        json_text(decree.get("조내용")), base_code
                    )
                    if not source_units:
                        add_link(base_code, link)
                        continue
                    for source_unit in source_units:
                        scoped_link = dict(link)
                        scoped_link.update(source_unit)
                        add_link(base_code, scoped_link)
                # 법률이 시행령을 거치지 않고 소관부처령에 직접 위임하는
                # 경우도 시행규칙 조문을 연결한다.
                rule_authority = (
                    f"{organization}령"
                    if organization and organization.endswith("부")
                    else "부령"
                )
                for rule in cls._deduplicate_three_stage_nodes(rule_nodes):
                    link = cls._three_stage_reference_link(
                        rule,
                        authority=rule_authority,
                        fallback_law_name="시행규칙",
                    )
                    if link is None:
                        continue
                    source_units = cls._law_source_units_referenced_by_decree(
                        json_text(rule.get("조내용")), base_code
                    )
                    if not source_units:
                        add_link(base_code, link)
                        continue
                    for source_unit in source_units:
                        scoped_link = dict(link)
                        scoped_link.update(source_unit)
                        add_link(base_code, scoped_link)
            return links_by_article

        if document_level == "rule":
            # 시행규칙 화면도 실제 3단비교 응답에 포함된 시행규칙 조문만
            # 버튼을 표시한다. 예전에는 시행규칙을 선조회 대상에서 빼서
            # 모든 조문이 '미확인(None)' 상태로 남고 버튼이 노출됐다.
            for article in articles:
                rule_nodes: list[dict] = []
                for key in ("시행규칙조문", "시행규칙조문목록"):
                    rule_nodes.extend(
                        cls._three_stage_child_nodes(article.get(key))
                    )
                for rule in cls._deduplicate_three_stage_nodes(rule_nodes):
                    rule_code = cls._three_stage_article_code(rule)
                    if rule_code:
                        links_by_article.setdefault(rule_code, [])
            return links_by_article

        if document_level != "decree":
            return links_by_article

        rule_authority = (
            f"{organization}령"
            if organization and organization.endswith("부")
            else "부령"
        )
        for article in articles:
            decree_nodes: list[dict] = []
            rule_nodes: list[dict] = []
            for key in ("시행령조문", "시행령조문목록"):
                decree_nodes.extend(cls._three_stage_child_nodes(article.get(key)))
            for key in ("시행규칙조문", "시행규칙조문목록"):
                rule_nodes.extend(cls._three_stage_child_nodes(article.get(key)))
            decree_nodes = cls._deduplicate_three_stage_nodes(decree_nodes)
            rule_nodes = cls._deduplicate_three_stage_nodes(rule_nodes)
            decree_codes = {
                cls._three_stage_article_code(node) for node in decree_nodes
            }
            decree_codes.discard("")
            # 시행령 조문은 연결된 시행규칙이 없어도 모법 조문과의 비교가
            # 성립한다. 키 자체가 API 비교표에 존재한다는 사실을 남겨 두어
            # 시행령 쪽 3단비교 버튼을 숨기지 않는다.
            for decree_code in decree_codes:
                links_by_article.setdefault(decree_code, [])
            if not decree_codes or not rule_nodes:
                continue
            for rule in rule_nodes:
                referenced_codes = (
                    cls._decree_codes_referenced_by_rule(
                        json_text(rule.get("조내용"))
                    )
                    & decree_codes
                )
                if not referenced_codes and len(decree_codes) == 1:
                    referenced_codes = set(decree_codes)
                for decree_code in referenced_codes:
                    add_link(
                        decree_code,
                        cls._three_stage_reference_link(
                            rule,
                            authority=rule_authority,
                            fallback_law_name="시행규칙",
                        ),
                    )
        return links_by_article

    @staticmethod
    def _law_document_level(row: dict[str, object], law_name: str) -> str:
        raw = row.get("raw")
        raw = raw if isinstance(raw, dict) else {}
        law_kind = json_text(raw.get("법령구분명"))
        if "대통령령" in law_kind or law_name.strip().endswith("시행령"):
            return "decree"
        if re.search(
            r"(?:시행규칙|규칙|부령|총리령)$", law_name.strip()
        ):
            return "rule"
        if "법률" in law_kind or not re.search(
            r"(?:시행규칙|규칙|부령|총리령)$", law_name.strip()
        ):
            return "law"
        return ""

    @staticmethod
    def _apply_subordinate_links_to_articles(
        articles: list[dict[str, object]],
        links_by_article: dict[str, list[dict[str, str]]],
    ) -> list[dict[str, object]]:
        updated: list[dict[str, object]] = []
        for article in articles:
            item = dict(article)
            article_code = str(item.get("jo") or "")
            item["subordinate_links"] = [
                dict(link)
                for link in links_by_article.get(article_code, [])
            ]
            # 이 값은 API가 정상 응답한 뒤에만 기록된다. False는 조회 실패나
            # 미조회가 아니라 해당 조문에 실제 하위 비교 조문이 없다는 뜻이다.
            item["comparison_available"] = article_code in links_by_article
            updated.append(item)
        return updated

    def _three_stage_link_row(self) -> dict[str, object] | None:
        """지금 화면에 떠 있는 문서의 행을 고른다.

        조항호목 탭은 그 조문을 뽑아 온 법령의 행을 대신 쓴다. 탭 정보를
        못 찾을 때만 마지막 조회 행으로 물러선다.
        """
        row = self._document_tab_row(self._active_document_key)
        if isinstance(row, dict) and str(row.get("target")) == "law_article":
            source = row.get("source_row")
            row = source if isinstance(source, dict) else None
        if not isinstance(row, dict):
            row = self.pending_row
        return row if isinstance(row, dict) else None

    def _queue_three_stage_link_request(self, law_name: str) -> None:
        if not self._current_three_stage_articles or not isinstance(
            self.pending_row, dict
        ):
            return
        # 저장된 완성 화면에 하위법령 링크까지 들어 있으면 다시 원문
        # 3단비교 자료를 읽고 전 조문을 훑을 필요가 없다.
        if all(
            article.get("comparison_available") is not None
            for article in self._current_three_stage_articles
            if isinstance(article, dict)
        ):
            return
        # pending_row는 "마지막으로 조회한 행"이라 지금 화면에 떠 있는
        # 문서와 다를 수 있다. 그 값으로 법령ID를 잡으면, 아래 링크 결과가
        # 돌아왔을 때 이 화면을 엉뚱한 법령의 저장 파일에 써 넣는다.
        row = self._three_stage_link_row()
        if row is None:
            return
        document_level = self._law_document_level(row, law_name)
        item_id = str(row.get("law_id") or row.get("id") or "")
        if document_level not in ("law", "decree", "rule") or not item_id:
            return
        organization = json_text(
            row.get("organization") or row.get("related") or ""
        )
        request = {
            "document_key": self._active_document_key,
            "document_level": document_level,
            "item_id": item_id,
            "law_name": law_name,
            "organization": organization,
        }
        cached_payload = self._three_stage_payload_cache.get(item_id)
        if isinstance(cached_payload, dict):
            self._apply_three_stage_links(request, cached_payload, cached=True)
            return
        self._pending_three_stage_link_request = request
        # 먼저 본문 한 프레임을 그린 뒤 디스크 3단비교 또는 API를
        # 처리한다. 저장본문 열기와 링크 보강을 같은 프레임에 묶으면
        # 로컬 캐시가 있어도 사용자는 늦게 열린 것으로 느끼게 된다.
        QTimer.singleShot(30, self._start_pending_three_stage_link_request)

    def _start_pending_three_stage_link_request(self) -> None:
        request = self._pending_three_stage_link_request
        if request is None or self.worker is not None:
            return
        oc = self.oc_provider().strip()
        if not oc:
            self._pending_three_stage_link_request = None
            return
        self._pending_three_stage_link_request = None
        self._three_stage_link_request_in_flight = dict(request)
        # "대통령령" 링크를 자동으로 이어주는 건 사용자가 직접 누른
        # 작업이 아니라 화면 뒤에서 하는 보조 작업이므로, 검색·조회
        # 버튼을 잠그거나 진행바를 띄우지 않는다. 저장된 본문을 열
        # 때마다 이 요청이 몇 초씩 걸리면서 마치 문서 여는 것 자체가
        # 느려진 것처럼 보였다.
        self._start_background_worker(
            ResourceApiWorker(
                "three_stage_links",
                oc=oc,
                target="law",
                item_id=request["item_id"],
                law_name=request["law_name"],
                parent=self,
            )
        )

    def _start_background_worker(self, worker: ResourceApiWorker) -> None:
        if self.worker and self.worker.isRunning():
            return
        self.worker = worker
        worker.succeeded.connect(self._worker_succeeded)
        worker.failed.connect(self._worker_failed)
        worker.finished.connect(self._worker_finished)
        worker.start()

    def _apply_three_stage_links(
        self,
        request: dict[str, str],
        payload: dict,
        *,
        cached: bool = False,
    ) -> None:
        links_by_article = self._three_stage_subordinate_links(
            payload,
            document_level=request["document_level"],
            organization=request.get("organization", ""),
        )
        document_key = request["document_key"]
        state = self._document_states.get(document_key)
        if state is None:
            return
        source_articles = (
            self._current_three_stage_articles
            if document_key == self._active_document_key
            else list(state.get("three_stage_articles", []) or [])
        )
        updated_articles = self._apply_subordinate_links_to_articles(
            [dict(article) for article in source_articles], links_by_article
        )
        state["three_stage_articles"] = updated_articles
        if document_key == self._active_document_key:
            self._set_three_stage_articles(updated_articles)
            self._save_active_document_state()
        snapshot = self._law_render_snapshot_from_state(state)
        # 이 화면이 정말 그 법령의 전문인지 확인하고 나서 저장한다.
        # 조문 하나만 뽑아 둔 조항호목 탭이나 다른 법령의 화면이 그 법령의
        # 저장 파일을 덮으면, 다음부터 즐겨찾기로 열 때마다 엉뚱한 본문이
        # 뜬다. 되돌릴 수 없는 일이라 쓰기 전에 막는다.
        state_row = state.get("row")
        state_id = (
            str(state_row.get("law_id") or state_row.get("id") or "")
            if isinstance(state_row, dict)
            and str(state_row.get("target")) == "law"
            else ""
        )
        save_row = {"target": "law", "id": request["item_id"]}
        if snapshot.get("rendered_html") and state_id == str(
            request["item_id"]
        ):
            # 법령ID가 같아도 화면이 전문이라는 보장은 없다. 조문 하나만
            # 담긴 화면이 전문 저장 파일을 덮으면 다음부터 즐겨찾기로 열
            # 때마다 그 한 조문만 뜬다. 저장해 둔 원문과 견줘 조문이 크게
            # 줄어드는 덮어쓰기는 하지 않는다.
            saved = self.law_cache.load_for_row(save_row)
            covers = self._snapshot_covers_payload(
                str(snapshot.get("rendered_plain_text") or ""),
                saved.get("payload") if isinstance(saved, dict) else None,
            )
            if self._snapshot_belongs_to(snapshot, save_row) and covers:
                self.law_cache.update_snapshot(save_row, snapshot)
        link_count = sum(len(links) for links in links_by_article.values())
        if link_count:
            self.status_label.setText(
                f"{request['law_name']} 하위법령 조문 링크 {link_count}건 표시"
                + (" · 받은 3단비교 자료 재사용" if cached else "")
            )

    def _show_three_stage_links(self, result: object) -> None:
        request = self._three_stage_link_request_in_flight
        self._three_stage_link_request_in_flight = None
        if not isinstance(result, dict) or request is None:
            return
        payload = result.get("payload")
        if not isinstance(payload, dict):
            return
        item_id = str(result.get("item_id") or request.get("item_id") or "")
        if item_id:
            self._three_stage_payload_cache[item_id] = payload
        self._apply_three_stage_links(request, payload)

    def _three_stage_node_html(
        self,
        node: dict,
        *,
        fallback_law_name: str,
        current_law_id: str = "",
        authority_links: dict[str, str] | None = None,
        show_law_name: bool = True,
    ) -> str:
        law_name = json_text(node.get("법령명")) or fallback_law_name
        article_title = json_text(node.get("조제목"))
        article_content = insert_admin_clause_breaks(
            json_text(node.get("조내용"))
        )
        parts = ['<div class="comparison-item">']
        if law_name and show_law_name:
            parts.append(
                '<div class="comparison-law-name">'
                f"{escape(law_name)}</div>"
            )
        if article_title:
            article_link = self._three_stage_reference_link(
                node,
                authority="",
                fallback_law_name=law_name or fallback_law_name,
            )
            if article_link is not None:
                article_title_html = (
                    f'<a href="{escape(article_link["href"], quote=True)}" '
                    f'title="{escape(article_link["tooltip"], quote=True)}">'
                    f"{escape(article_title)}</a>"
                )
            else:
                article_title_html = escape(article_title)
            parts.append(
                '<div class="comparison-article-title">'
                f"{article_title_html}</div>"
            )
        if article_content:
            authority_tokens: dict[str, tuple[str, str]] = {}
            for index, (authority, href) in enumerate(
                sorted(
                    (authority_links or {}).items(),
                    key=lambda item: len(item[0]),
                    reverse=True,
                )
            ):
                if not authority or not href or authority not in article_content:
                    continue
                token = f"THREESTAGEAUTHORITYLINK{index}TOKEN"
                article_content = article_content.replace(authority, token)
                authority_tokens[token] = (authority, href)
            content_html = body_to_html(
                article_content,
                self.detail_highlight_terms,
                current_law_name=law_name,
                current_law_id=current_law_id,
                use_api_links=True,
            )
            for token, (authority, href) in authority_tokens.items():
                content_html = content_html.replace(
                    token,
                    f'<a href="{escape(href, quote=True)}" '
                    'style="color:#006dcc; text-decoration:underline;" '
                    f'title="{escape(authority)} 관련 하위법령 조문을 엽니다.">'
                    f"{escape(authority)}</a>",
                )
            parts.append(
                '<div class="comparison-content">'
                + content_html
                + "</div>"
            )
        else:
            parts.append('<div class="comparison-empty">조문 내용 없음</div>')
            parts.append("</div>")
        return "".join(parts)

    def _link_three_stage_authority_phrases(
        self, content_html: str, rules: list[dict]
    ) -> str:
        """시행령 칸의 부령 문구를, 그 덩어리에 붙인 시행규칙으로만 연결."""
        if not content_html or not rules:
            return content_html
        href = self._inline_subordinate_href(
            [
                link
                for node in rules
                if (
                    link := self._three_stage_reference_link(
                        node,
                        authority="부령",
                        fallback_law_name="시행규칙",
                    )
                )
            ]
        )
        if not href:
            return content_html
        phrases = sorted(
            set(re.findall(r"[가-힣]{2,20}부령|총리령|부령", content_html)),
            key=len,
            reverse=True,
        )
        tokens: list[tuple[str, str]] = []
        for index, authority in enumerate(phrases):
            token = f"THREESTAGEBLOCKAUTH{index}TOKEN"
            content_html = content_html.replace(authority, token)
            tokens.append((token, authority))
        for token, authority in tokens:
            content_html = content_html.replace(
                token,
                f'<a href="{escape(href, quote=True)}" '
                'style="color:#006dcc; text-decoration:underline;" '
                f'title="{escape(authority)} 관련 하위법령 조문을 엽니다.">'
                f"{escape(authority)}</a>",
            )
        return content_html

    # 하위법령에서 3단비교를 열었을 때 법률 열의 근거 항·호로 이동시키는 닻
    THREE_STAGE_SOURCE_ANCHOR = "thd-source"

    @staticmethod
    def _three_stage_source_label(unit: dict[str, str]) -> str:
        """근거 단위 코드를 본문 표지 표기(``8.``ㆍ``8의2.``ㆍ``②``)로 바꾼다."""
        ho = str(unit.get("source_ho") or "")
        if ho:
            number, branch = int(ho[:4]), int(ho[4:])
            return f"{number}의{branch}." if branch else f"{number}."
        hang = str(unit.get("source_hang") or "")
        if hang:
            number, branch = int(hang[:4]), int(hang[4:])
            if branch or not 1 <= number <= len(CIRCLED_NUMBER_MARKERS):
                return ""
            return CIRCLED_NUMBER_MARKERS[number - 1]
        return ""

    @classmethod
    def _split_comparison_item(cls, item_html: str) -> tuple[str, str]:
        """비교 항목 HTML을 (법령명ㆍ조제목 머리, 본문 안쪽)으로 나눈다."""
        opening = '<div class="comparison-content">'
        index = item_html.find(opening)
        if index < 0:
            return item_html, ""
        head = item_html[:index]
        inner = item_html[index + len(opening) :]
        # 본문 div와 항목 div가 연달아 닫힌다.
        closing = "</div></div>"
        if inner.endswith(closing):
            inner = inner[: -len(closing)]
        return head, inner

    def _comparison_node_fragments(
        self,
        node: dict,
        *,
        fallback_law_name: str,
        show_law_name: bool,
    ) -> list[dict]:
        """조문 HTML을 항 묶음으로 나눠 머리(법령명ㆍ조제목)는 첫 묶음에만."""
        html = self._three_stage_node_html(
            node,
            fallback_law_name=fallback_law_name,
            show_law_name=show_law_name,
        )
        head, inner = self._split_comparison_item(html)
        groups = hang_groups_from_blocks(law_content_blocks(inner))
        fragments: list[dict] = []
        show_head = True
        for group in groups:
            fragments.append(
                {
                    "node": node,
                    "head": head if show_head else "",
                    "blocks": group,
                }
            )
            show_head = False
        return fragments

    @classmethod
    def _fragment_plain_text(cls, fragment: dict) -> str:
        return html_to_plain_text(
            "".join(block["html"] for block in fragment["blocks"])
        )

    def _fragment_cell_html(
        self, fragment: dict, *, link_nodes: list[dict] | None = None
    ) -> str:
        body = "".join(block["html"] for block in fragment["blocks"])
        if link_nodes:
            body = self._link_three_stage_authority_phrases(body, link_nodes)
        return (
            str(fragment.get("head") or "")
            + '<div class="comparison-content">'
            + body
            + "</div>"
        )

    def _stacked_rule_fragments(self, fragments: list[dict]) -> str:
        return "".join(
            self._fragment_cell_html(fragment) for fragment in fragments
        )

    @staticmethod
    def _three_stage_source_inner_label(unit: dict[str, str]) -> str:
        """``제2조제2호다목``의 ``다.``처럼 호 안의 목 표지를 돌려준다."""
        mok = str(unit.get("source_mok") or "")
        return f"{mok}." if mok else ""

    @staticmethod
    def _marker_block_span(
        content_html: str, label: str, start: int, end: int
    ) -> tuple[int, int] | None:
        """주어진 구간에서 표지 줄(여는 div부터 표지 span 끝까지)을 찾는다."""
        if not label:
            return None
        block = re.compile(
            r'<div class="legal-indent[^"]*"[^>]*>'
            r'<span class="bullet-marker"[^>]*>'
            + re.escape(f"{escape(label)}&nbsp;")
            + r"</span>",
            re.S,
        )
        match = block.search(content_html, start, end)
        return match.span() if match else None

    @classmethod
    def _mark_three_stage_source_unit(
        cls, content_html: str, label: str, *, inner_label: str = ""
    ) -> str:
        """법률 열에서 위임 근거가 된 항·호에 닻과 음영을 붙인다.

        모법 조문은 통째로 오기 때문에 시행령 제3조에서 열면 25개 호가
        한꺼번에 보인다. 근거인 제2조제8호가 어디인지 바로 찾도록
        그 표지 줄만 표시한다.
        """
        span = cls._marker_block_span(
            content_html, label, 0, len(content_html)
        )
        if span is None:
            return content_html
        if inner_label:
            # 목은 호마다 가.ㆍ나.ㆍ다.가 되풀이되므로 반드시 그 호 안에서
            # 찾는다. 다음 호(같은 level-1 줄) 앞까지만 훑는다.
            next_ho = re.compile(r'<div class="legal-indent level-1"', re.S)
            following = next_ho.search(content_html, span[1])
            limit = following.start() if following else len(content_html)
            inner_span = cls._marker_block_span(
                content_html, inner_label, span[1], limit
            )
            if inner_span is not None:
                span = inner_span
        start, end = span
        highlighted = content_html[start:end]
        highlighted = highlighted.replace(
            '<span class="bullet-marker" style="',
            '<span class="bullet-marker" style="background:#fdf0bd; ',
            1,
        )
        anchor = f'<a name="{cls.THREE_STAGE_SOURCE_ANCHOR}"></a>'
        highlighted = highlighted.replace(">", f">{anchor}", 1)
        tail = content_html[end:]
        tail = tail.replace(
            '<span class="bullet-text" style="',
            '<span class="bullet-text" style="background:#fdf0bd; ',
            1,
        )
        return content_html[:start] + highlighted + tail

    @classmethod
    def _resolve_three_stage_article_nodes(
        cls,
        articles: list[dict],
        *,
        law_name: str,
        jo: str,
    ) -> tuple[dict, list[dict], list[dict]] | None:
        """현재 문서 조문을 3단비교 응답의 법률·시행령·시행규칙에 연결.

        법제처 API는 위임 관계 하나마다 같은 법률 조문을 통째로 다시
        내려준다. 국토계획법 제2조는 시행령 제2조ㆍ제3조ㆍ제4조ㆍ
        제4조의2ㆍ제4조의3이 각각 별개 항목으로 온다. 처음 만난 항목만
        쓰면 나머지 하위법령이 표에서 통째로 빠지므로, 같은 조문에 달린
        항목을 끝까지 훑어 하위법령 조문을 모은다.
        """
        normalized_name = re.sub(r"\s+", "", law_name)
        is_rule = bool(re.search(r"(?:시행규칙|규칙|부령|총리령)$", law_name.strip()))
        is_decree = law_name.strip().endswith("시행령")

        def child_nodes(article: dict, keys: tuple[str, ...]) -> list[dict]:
            nodes: list[dict] = []
            for key in keys:
                nodes.extend(cls._three_stage_child_nodes(article.get(key)))
            return nodes

        def belongs_to_current_law(node: dict) -> bool:
            node_name = json_text(node.get("법령명"))
            return (
                not node_name
                or re.sub(r"\s+", "", node_name) == normalized_name
            )

        base_article: dict | None = None
        decree_nodes: list[dict] = []
        rule_nodes: list[dict] = []
        matched_decrees: list[dict] = []
        matched_rules: list[dict] = []

        for article in articles:
            article_decrees = child_nodes(
                article, ("시행령조문", "시행령조문목록")
            )
            article_rules = child_nodes(
                article, ("시행규칙조문", "시행규칙조문목록")
            )

            if not (is_rule or is_decree):
                if cls._three_stage_article_code(article) != jo:
                    continue
                if base_article is None:
                    base_article = article
                decree_nodes.extend(article_decrees)
                rule_nodes.extend(article_rules)
                continue

            hits = [
                node
                for node in (article_rules if is_rule else article_decrees)
                if cls._three_stage_article_code(node) == jo
                and belongs_to_current_law(node)
            ]
            if not hits:
                continue
            if base_article is None:
                base_article = article
            decree_nodes.extend(article_decrees)
            rule_nodes.extend(article_rules)
            if is_rule:
                matched_rules.extend(hits)
            else:
                matched_decrees.extend(hits)

        if base_article is None:
            return None

        decree_nodes = cls._deduplicate_three_stage_nodes(decree_nodes)
        rule_nodes = cls._deduplicate_three_stage_nodes(rule_nodes)

        if not (is_rule or is_decree):
            return base_article, decree_nodes, rule_nodes

        if is_rule:
            matched_rules = cls._deduplicate_three_stage_nodes(matched_rules)
            referenced_decrees: set[str] = set()
            for node in matched_rules:
                referenced_decrees.update(
                    cls._decree_codes_referenced_by_rule(
                        json_text(node.get("조내용"))
                    )
                )
            matched_decrees = [
                node
                for node in decree_nodes
                if not referenced_decrees
                or cls._three_stage_article_code(node) in referenced_decrees
            ]
            return base_article, matched_decrees, matched_rules

        matched_decrees = cls._deduplicate_three_stage_nodes(matched_decrees)
        matched_rules = [
            node
            for node in rule_nodes
            if jo
            in cls._decree_codes_referenced_by_rule(
                json_text(node.get("조내용"))
            )
        ]
        return base_article, matched_decrees, matched_rules

    def _build_three_stage_comparison_html(
        self,
        payload: dict,
        *,
        law_id: str,
        law_name: str,
        jo: str,
        label: str,
    ) -> str:
        service = next(
            (
                value
                for value in payload.values()
                if isinstance(value, dict)
                and (
                    "위임조문삼단비교" in value
                    or "인용조문삼단비교" in value
                )
            ),
            None,
        )
        if not isinstance(service, dict):
            raise ValueError("3단비교 응답 본문을 찾지 못했습니다.")
        comparison = service.get("위임조문삼단비교")
        if not isinstance(comparison, dict):
            comparison = service.get("인용조문삼단비교")
        if not isinstance(comparison, dict):
            raise ValueError("3단비교 조문 목록을 찾지 못했습니다.")

        basic = service.get("기본정보")
        if not isinstance(basic, dict):
            basic = {}
        response_law_name = (
            json_text(basic.get("법령명"))
            or law_name
        )
        articles = [
            node
            for node in json_list(comparison.get("법률조문"))
            if isinstance(node, dict)
            and json_text(node.get("조제목"))
        ]
        resolved = self._resolve_three_stage_article_nodes(
            articles,
            law_name=law_name,
            jo=jo,
        )
        if resolved is None:
            raise ValueError(f"{label}에 연결된 3단비교 조문이 없습니다.")
        base_node, decree_nodes, rule_nodes = resolved
        # 시행령·시행규칙을 기준으로 API를 호출하면 기본정보의 법령명도
        # 현재 하위법령명으로 내려온다. 이를 법률 열의 대체 명칭으로 쓰면
        # 모법 조문 아래에 "… 시행규칙"이 표시된다. 법률조문 노드 또는
        # 기준법령명을 우선하고, 없으면 현재 명칭에서 하위법령 접미어를
        # 제거해 모법명을 만든다.
        base_law_name = (
            json_text(base_node.get("법령명"))
            or json_text(basic.get("기준법령명"))
            or law_base_name(law_name)
            or law_base_name(response_law_name)
            or response_law_name
        )

        def node_links(
            nodes: list[dict], authority: str, fallback_name: str
        ) -> list[dict[str, str]]:
            return [
                link
                for node in nodes
                if (
                    link := self._three_stage_reference_link(
                        node,
                        authority=authority,
                        fallback_law_name=fallback_name,
                    )
                )
            ]

        decree_href = self._inline_subordinate_href(
            node_links(decree_nodes, "대통령령", "시행령")
        )
        base_authority_links = {"대통령령": decree_href} if decree_href else {}

        base_html = self._three_stage_node_html(
            base_node,
            fallback_law_name=base_law_name,
            # 현재 문서가 시행령·시행규칙이면 law_id는 하위법령 ID다.
            # 모법 링크에 잘못 붙이지 않는다.
            current_law_id=(
                law_id
                if re.sub(r"\s+", "", law_name)
                == re.sub(r"\s+", "", base_law_name)
                else ""
            ),
            authority_links=base_authority_links,
        )
        # 하위법령에서 열면 모법 조문이 통째로 오므로, 그 하위법령이
        # 위임 근거로 든 항ㆍ호를 찾아 표시하고 그 자리로 스크롤한다.
        current_nodes = (
            rule_nodes
            if re.search(r"(?:시행규칙|규칙|부령|총리령)$", law_name.strip())
            else decree_nodes
            if law_name.strip().endswith("시행령")
            else []
        )
        base_code = self._three_stage_article_code(base_node)
        for node in current_nodes:
            units = self._law_source_units_referenced_by_decree(
                json_text(node.get("조내용")), base_code
            )
            unit = next(
                (
                    candidate
                    for candidate in units
                    if self._three_stage_source_label(candidate)
                ),
                None,
            )
            if unit is None:
                continue
            marked = self._mark_three_stage_source_unit(
                base_html,
                self._three_stage_source_label(unit),
                inner_label=self._three_stage_source_inner_label(unit),
            )
            if marked != base_html:
                base_html = marked
                break
        # 법률 본문을 항ㆍ호 덩어리로 나누고, 시행령도 항 묶음으로 나눠
        # 각 묶음이 든 법 제○항에 붙인다. 근거를 못 찾은 조문은 첫 줄에 모은다.
        base_head, base_inner = self._split_comparison_item(base_html)
        # 법령명은 열 머리에 한 번만 적고 조제목 바로 위에서는 뺀다.
        base_head = re.sub(
            r'<div class="comparison-law-name">.*?</div>', "", base_head, count=1
        )
        blocks = law_content_blocks(base_inner)
        base_code = self._three_stage_article_code(base_node)

        def column_law_name(nodes: list[dict], fallback_name: str) -> str:
            """그 열을 대표하는 법령명. 열 머리에 한 번만 적는다."""
            for node in nodes:
                name = json_text(node.get("법령명"))
                if name:
                    return name
            return fallback_name

        decree_header = column_law_name(decree_nodes, "시행령")
        rule_header = column_law_name(rule_nodes, "시행규칙")

        fragments_by_row: list[list[dict]] = [[] for _ in blocks]
        for node in decree_nodes:
            node_law_name = json_text(node.get("법령명")) or "시행령"
            last_row_index = 0
            for fragment in self._comparison_node_fragments(
                node,
                fallback_law_name="시행령",
                show_law_name=node_law_name != decree_header,
            ):
                hang, ho, mok = primary_source_unit(
                    self._law_source_units_referenced_by_decree(
                        self._fragment_plain_text(fragment), base_code
                    )
                )
                matched = block_index_for_unit_or_none(
                    blocks, hang, ho, mok
                )
                if matched is None:
                    row_index = last_row_index
                else:
                    row_index = matched
                    last_row_index = row_index
                fragments_by_row[row_index].append(fragment)

        def pairs_for_fragments(
            fragments: list[dict], remaining: list[dict]
        ) -> tuple[list[tuple[str, str]], list[dict]]:
            pairs: list[tuple[str, str]] = []
            leftover = remaining
            for fragment in fragments:
                decree_blocks = fragment["blocks"]
                rule_bins: list[list[dict]] = [[] for _ in decree_blocks]
                still: list[dict] = []
                decree_code = self._three_stage_article_code(fragment["node"])
                head = str(fragment.get("head") or "")
                for rule in leftover:
                    content = self._fragment_plain_text(rule)
                    cited = self._decree_codes_referenced_by_rule(content)
                    if cited and decree_code and decree_code not in cited:
                        still.append(rule)
                        continue
                    units = [
                        unit
                        for unit in self._decree_units_referenced_by_rule(
                            content
                        )
                        if not decree_code
                        or unit.get("article_code") == decree_code
                    ]
                    hang, ho, mok = primary_source_unit(units)
                    if not hang and not ho and not mok:
                        if head:
                            rule_bins[0].append(rule)
                        else:
                            still.append(rule)
                        continue
                    block_index = block_index_for_unit_or_none(
                        decree_blocks, hang, ho, mok
                    )
                    if block_index is None:
                        still.append(rule)
                        continue
                    rule_bins[block_index].append(rule)
                leftover = still
                for block_index, decree_block in enumerate(decree_blocks):
                    block_rules = rule_bins[block_index]
                    decree_cell = (
                        (head if block_index == 0 else "")
                        + '<div class="comparison-content">'
                        + self._link_three_stage_authority_phrases(
                            decree_block["html"],
                            [item["node"] for item in block_rules],
                        )
                        + "</div>"
                    )
                    pairs.append(
                        (
                            decree_cell,
                            self._stacked_rule_fragments(block_rules),
                        )
                    )
            return pairs, leftover

        row_pairs: list[list[tuple[str, str]]] = [[] for _ in blocks]
        remaining_rules: list[dict] = []
        for node in rule_nodes:
            node_law_name = json_text(node.get("법령명")) or "시행규칙"
            remaining_rules.extend(
                self._comparison_node_fragments(
                    node,
                    fallback_law_name="시행규칙",
                    show_law_name=node_law_name != rule_header,
                )
            )
        for index, fragments in enumerate(fragments_by_row):
            pairs, remaining_rules = pairs_for_fragments(
                fragments, remaining_rules
            )
            row_pairs[index] = pairs
        leftover_row = next(
            (
                index
                for index in range(len(row_pairs) - 1, -1, -1)
                if row_pairs[index]
            ),
            0,
        )
        for rule in remaining_rules:
            hang, ho, mok = primary_source_unit(
                self._law_source_units_referenced_by_decree(
                    self._fragment_plain_text(rule), base_code
                )
            )
            matched = block_index_for_unit_or_none(
                blocks, hang, ho, mok
            )
            row_index = leftover_row if matched is None else matched
            rule_html = self._stacked_rule_fragments([rule])
            if row_pairs[row_index]:
                first_decree, first_rule = row_pairs[row_index][0]
                row_pairs[row_index][0] = (first_decree, first_rule + rule_html)
            else:
                row_pairs[row_index] = [("", rule_html)]

        row_html: list[str] = []
        for index, block in enumerate(blocks):
            law_cell = (
                (base_head if index == 0 else "")
                + '<div class="comparison-content">'
                + block["html"]
                + "</div>"
            )
            inner_pairs = row_pairs[index]
            if index == 0 and not decree_nodes:
                inner_pairs = [
                    (
                        (
                            '<div class="comparison-empty">'
                            "연결된 시행령 조문이 없습니다.</div>"
                        ),
                        inner_pairs[0][1] if inner_pairs else "",
                    )
                ]
            if index == 0 and not rule_nodes:
                empty_rule = (
                    '<div class="comparison-empty">'
                    "연결된 시행규칙 조문이 없습니다.</div>"
                )
                if inner_pairs:
                    inner_pairs = [
                        (inner_pairs[0][0], empty_rule),
                        *inner_pairs[1:],
                    ]
                else:
                    inner_pairs = [("", empty_rule)]
            if not inner_pairs:
                inner_pairs = [("", "")]
            span = len(inner_pairs)
            for inner_index, (decree_cell, rule_cell) in enumerate(inner_pairs):
                if inner_index == 0:
                    rowspan = f' rowspan="{span}"' if span > 1 else ""
                    row_html.append(
                        '<tr><td class="comparison-edge"></td>'
                        f'<td class="comparison-cell"{rowspan}>{law_cell}</td>'
                        '<td class="comparison-divider"></td>'
                        f'<td class="comparison-cell">{decree_cell}</td>'
                        '<td class="comparison-divider"></td>'
                        f'<td class="comparison-cell">{rule_cell}</td>'
                        '<td class="comparison-edge"></td></tr>'
                    )
                else:
                    row_html.append(
                        '<tr><td class="comparison-edge"></td>'
                        '<td class="comparison-divider"></td>'
                        f'<td class="comparison-cell">{decree_cell}</td>'
                        '<td class="comparison-divider"></td>'
                        f'<td class="comparison-cell">{rule_cell}</td>'
                        '<td class="comparison-edge"></td></tr>'
                    )
        return "".join(
            (
                "<style>",
                "body { font-family:'Malgun Gothic'; font-weight:400; color:#172033; "
                "line-height:1.35; margin:0; }",
                ".comparison-summary { color:#526176; font-size:12px; "
                "margin:0 0 5px 0; }",
                ".comparison-table { width:100%; border-collapse:collapse; "
                # QTextDocument는 table의 border를 바깥선이 아니라 모든
                # 셀의 격자로 그린다. 바깥선도 아래 셀 규칙으로 따로 만든다.
                "table-layout:fixed; border:none; }",
                ".comparison-table th { background:#173b63; "
                "color:white; border:none; padding:8px; "
                "font-size:14px; }",
                ".comparison-table td { border:none; padding:0; }",
                ".comparison-table td.comparison-cell { width:33.33%; "
                "vertical-align:top; padding:0 3px; }",
                # Qt가 셀의 좌우 border를 사방 테두리로 바꾸므로,
                # 1px 배경 열로 외곽선과 세로 구분선만 직접 만든다.
                ".comparison-edge, .comparison-divider { width:1px; "
                "background:#c7d6e4; }",
                ".comparison-table td.comparison-horizontal-rule { height:1px; "
                "font-size:1px; line-height:1px; padding:0; "
                "background:#c7d6e4; }",
                # 호·목마다 행이 하나씩 생기므로 여기 붙는 여백이 그대로
                # 표 전체 높이가 된다. 칸을 나누는 선만 남기고 최소로 둔다.
                ".comparison-item { border:none; "
                "padding:0 0 3px 0; margin:0 0 3px 0; }",
                ".comparison-law-name { color:#1768aa; font-weight:700; "
                "font-size:12px; margin:0 0 2px 0; }",
                ".comparison-article-title { color:#173b63; font-weight:700; "
                "font-size:13px; margin:0 0 3px 0; }",
                ".comparison-content { font-size:12px; }",
                ".comparison-empty { color:#7a8798; font-size:12px; "
                "padding:4px; }",
                "a { color:#1768aa; font-weight:600; text-decoration:none; }",
                "</style>",
                '<div class="comparison-summary">',
                f"{escape(base_law_name)} {escape(label)} · 위임조문 기준",
                "</div>",
                '<table class="comparison-table" cellspacing="0" cellpadding="0">',
                '<tr><td class="comparison-horizontal-rule" colspan="7"></td></tr>',
                "<tr>"
                '<td class="comparison-edge"></td>'
                f"<th>{escape(base_law_name)}</th>"
                '<td class="comparison-divider"></td>'
                f"<th>{escape(decree_header)}</th>"
                '<td class="comparison-divider"></td>'
                f"<th>{escape(rule_header)}</th>"
                '<td class="comparison-edge"></td>'
                "</tr>",
                "".join(row_html),
                '<tr><td class="comparison-horizontal-rule" '
                'colspan="7"></td></tr>',
                "</table>",
            )
        )

    def _show_three_stage_comparison(
        self, result: object, *, cached: bool = False
    ) -> None:
        if not isinstance(result, dict):
            raise ValueError("3단비교 응답 형식이 올바르지 않습니다.")
        payload = result.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("3단비교 API 결과를 찾지 못했습니다.")
        law_id = str(result.get("item_id") or "")
        law_name = str(result.get("law_name") or "법령")
        jo = str(result.get("jo") or "")
        article = self._pending_three_stage_article
        label = str(article.get("label") or self._law_reference_label(jo))
        html = self._build_three_stage_comparison_html(
            payload,
            law_id=law_id,
            law_name=law_name,
            jo=jo,
            label=label,
        )
        self._three_stage_payload_cache[law_id] = payload
        popup_title = f"{law_name} {label} 3단비교"
        reference_key = f"thdcmp:{law_id}:{jo}"
        self.three_stage_popup.reference_key = reference_key
        self.three_stage_popup.show_content_at(
            popup_title,
            html,
            QCursor.pos(),
            scroll_anchor=(
                self.THREE_STAGE_SOURCE_ANCHOR
                if f'name="{self.THREE_STAGE_SOURCE_ANCHOR}"' in html
                else ""
            ),
        )
        self._remember_three_stage_popup(
            reference_key,
            popup_title,
            html,
            law_name=law_name,
            label=label,
            short_name=self._known_law_short_name(law_name),
        )
        self.status_label.setText(
            f"{popup_title} 표시 완료"
            + (" · 받은 API 자료 재사용" if cached else "")
        )

    def _show_inline_subordinate_menu(self, url: QUrl) -> None:
        encoded_links = query_value(QUrlQuery(url), "data").strip()
        try:
            padding = "=" * (-len(encoded_links) % 4)
            decoded_links = base64.urlsafe_b64decode(
                (encoded_links + padding).encode("ascii")
            ).decode("utf-8")
            options = json.loads(decoded_links)
        except (binascii.Error, UnicodeDecodeError, ValueError):
            options = []
        valid_options = [
            option
            for option in options
            if isinstance(option, dict)
            and option.get("text")
            and option.get("href")
        ] if isinstance(options, list) else []
        if not valid_options:
            QMessageBox.warning(
                self,
                "하위법령 링크 없음",
                "연결된 하위법령 조문을 찾지 못했습니다.\n"
                "옆의 [3단비교] 버튼으로 법률·시행령·시행규칙을 함께 확인해 주세요.",
            )
            return
        if len(valid_options) == 1:
            self._detail_link_clicked(QUrl(str(valid_options[0]["href"])))
            return
        menu = QMenu(self)
        for option in valid_options:
            action = menu.addAction(str(option["text"]))
            action.triggered.connect(
                lambda _checked=False, href=str(option["href"]): (
                    self._detail_link_clicked(QUrl(href))
                )
            )
        menu.exec(QCursor.pos())

    def open_reference_link(self, url: QUrl) -> None:
        """다른 탭이 만든 조문 참조 링크를 이 탭의 조문 팝업으로 연다.

        참조 팝업과 조회 캐시가 모두 이 탭에 있으므로, 키워드검색 탭은
        링크만 넘기고 표시는 여기에 맡긴다. 행정규칙ㆍ자치법규 문서
        링크(doc:)도 본문 화면과 같은 파서로 이 팝업에 연다. 별표·서식은
        조문이 아니라 첨부 파일이라 별표 원문(PDF 미리보기 또는
        kordoc 본문)으로 연다.
        """
        if url.scheme() == "annexref":
            self.open_annex_reference(url)
            return
        if url.scheme() == "doc":
            href = url.toString()
            category, item_id = split_doc_reference(href)
            if category.strip() in ("licbyl", "admbyl", "ordinbyl"):
                self.open_annex_reference(url)
                return
            if is_inquiry_target(category) and item_id:
                self._open_inquiry_reference_popup(category, item_id, href)
                return
            self._open_document_reference_popup(url)
            return
        self._detail_link_clicked(url)

    def open_annex_reference(self, url: QUrl) -> None:
        """별표·별지서식 인용을 찾아 PDF 미리보기 또는 추출 본문으로 연다."""
        query = QUrlQuery(url)
        title = query_value(query, "name").strip()
        category = query_value(query, "category").strip() or "licbyl"
        item_id = query_value(query, "id").strip()
        if url.scheme() == "doc":
            href = url.toString()
            _, _, rest = href.partition(":")
            category, _, item_id = rest.partition(":")
            category = category.strip() or "licbyl"
            item_id = item_id.strip()
        if category not in ("licbyl", "admbyl", "ordinbyl"):
            category = "licbyl"
        if not title and not item_id:
            QMessageBox.warning(
                self, "별표 링크 오류", "열 별표·서식 이름을 확인하지 못했습니다."
            )
            return
        oc = self.oc_provider().strip()
        if not oc:
            prompt_oc_api_key(self)
            return
        related = query_value(query, "related").strip() or annex_related_law_name(
            title
        )
        search_query = related or title or item_id
        search_scope = 2 if related and related != title else 1
        hint = annex_hint_in_query(title)
        popup = self._reference_popup_for_request()
        popup.reference_request = {
            "title": title or "별표·서식",
            "category": category,
            "item_id": item_id,
        }
        self._pending_reference_popup = popup
        popup.show_loading(title or "별표·서식", QCursor.pos())
        running = self._annex_worker
        if running is not None and running.isRunning():
            running.requestInterruption()
            running.wait(200)
        try:
            worker = AnnexReferenceWorker(
                oc=oc,
                category=category,
                query=search_query,
                search_scope=search_scope,
                item_id=item_id,
                hint=hint,
                title=title or "별표·서식",
                parent=self,
            )
            self._annex_worker = worker
            worker.succeeded.connect(self._show_annex_reference)
            worker.failed.connect(self._annex_reference_failed)
            # 끝난 작업을 손에 쥐고 있으면, 다음 클릭에서 이미 지워진
            # 객체를 만지게 된다. 지우기 예약보다 먼저 놓아 준다.
            worker.finished.connect(self._annex_worker_done)
            worker.finished.connect(worker.deleteLater)
            worker.start()
        except Exception as error:  # noqa: BLE001
            # 여기서 터지면 팝업이 "불러오는 중" 그대로 멈춰 버린다.
            self._annex_worker = None
            popup.set_error(f"별표·서식을 여는 데 실패했습니다: {error}")

    def _annex_worker_done(self) -> None:
        """끝난 별표 조회를 손에서 놓는다.

        finished 뒤에는 deleteLater로 C++ 객체가 사라진다. 그대로 들고
        있다가 다음 클릭에서 isRunning()을 부르면 예외가 나고, 그 예외가
        조회 시작을 건너뛰어 팝업이 "불러오는 중"에서 멈춘다.
        """
        if self.sender() is self._annex_worker:
            self._annex_worker = None

    def _annex_reference_failed(self, error: str) -> None:
        if self.sender() is not self._annex_worker:
            return
        self._pending_reference_popup.set_error(
            error or "별표·서식을 찾지 못했습니다."
        )

    def _show_annex_reference(self, result: object) -> None:
        if self.sender() is not self._annex_worker:
            return
        if not isinstance(result, dict):
            self._annex_reference_failed("별표 검색 응답이 올바르지 않습니다.")
            return
        payload = result.get("payload")
        category = str(result.get("category") or "licbyl")
        if not isinstance(payload, dict):
            self._annex_reference_failed("별표 검색 응답이 올바르지 않습니다.")
            return
        try:
            rows, _total = self._parse_resource_rows(payload, category)
        except ValueError as error:
            self._annex_reference_failed(str(error))
            return
        item_id = str(result.get("item_id") or "")
        hint = str(result.get("hint") or "")
        title = str(result.get("title") or "")
        row = self._pick_annex_row(
            rows, item_id=item_id, hint=hint, title=title
        )
        if row is None:
            self._annex_reference_failed(
                f"'{title or item_id}'에 해당하는 별표·서식을 찾지 못했습니다."
            )
            return
        raw = row["raw"] if isinstance(row.get("raw"), dict) else {}
        pdf_url = full_law_url(raw.get("별표서식PDF파일링크"))
        file_url = full_law_url(raw.get("별표서식파일링크"))
        shown = str(row.get("name") or title or "별표·서식")
        if pdf_url:
            self._pending_reference_popup._close_popup()
            self._open_pdf_preview(pdf_url, shown)
            return
        if not file_url:
            self._annex_reference_failed(
                f"{shown}의 원문 파일이 없습니다."
            )
            return
        try:
            data = download_law_file(file_url)
        except Exception as error:  # noqa: BLE001
            self._annex_reference_failed(f"원문 다운로드 실패: {error}")
            return
        parsed = parse_annex_bytes(data)
        if parsed.success and parsed.markdown and not parsed.is_image_based:
            html = (
                "<pre style='white-space:pre-wrap; font-family:inherit; "
                "font-size:10pt;'>"
                f"{escape(parsed.markdown)}</pre>"
            )
            self._pending_reference_popup.show_content_at(
                shown, html, QCursor.pos()
            )
            return
        detail = parsed.error or "별표 원문에서 글을 뽑지 못했습니다."
        if parsed.is_image_based:
            detail = "이미지 기반 파일이라 글자를 뽑지 못했습니다. PDF가 있으면 미리보기로 엽니다."
        self._annex_reference_failed(f"{shown}: {detail}")

    @staticmethod
    def _pick_annex_row(
        rows: list[dict[str, object]],
        *,
        item_id: str,
        hint: str,
        title: str,
    ) -> dict[str, object] | None:
        if item_id:
            for row in rows:
                if str(row.get("id") or "") == item_id:
                    return row
        # 일련번호로 못 찾았으면 이름으로 고르는데, 이동용 껍데기 행은
        # 이름이 그럴듯해도 열면 빈 화면이라 후보에서 뺀다.
        rows = [
            row for row in rows if not is_annex_stub_name(row.get("name") or "")
        ] or rows
        if hint:
            matched = [
                row
                for row in rows
                if isinstance(row.get("raw"), dict)
                and row_matches_annex_hint(row["raw"], hint)
            ]
            if len(matched) == 1:
                return matched[0]
            numbered = [
                row
                for row in rows
                if isinstance(row.get("raw"), dict)
                and str(row["raw"].get("별표번호") or "").strip()
            ]
            if not matched and numbered:
                # 번호를 달고 온 결과 중에 찾는 번호가 없다. 여기서
                # 후보를 도로 넓히면 다른 별표를 열어 버린다.
                return None
            rows = matched or rows
        folded = re.sub(r"\s+", "", title)
        if folded:
            candidates = [
                row
                for row in rows
                if same_annex_number(title, str(row.get("name") or ""))
            ]
            for row in candidates:
                name = re.sub(r"\s+", "", str(row.get("name") or ""))
                if folded in name or name in folded:
                    return row
            # 이름이 그대로 들어 있지 않아도 대개 같은 서식을 조금 다르게
            # 옮겨 적은 것이다. 후보가 여럿이라고 손 놓지 말고 가장 많이
            # 겹치는 것을 고른다. 엉뚱한 것을 열지 않게 문턱을 둔다.
            if candidates:
                scored = [
                    (
                        annex_name_similarity(title, str(row.get("name") or "")),
                        row,
                    )
                    for row in candidates
                ]
                score, best = max(scored, key=lambda item: item[0])
                if score >= 0.55:
                    return best
        return rows[0] if len(rows) == 1 else None

    def _open_inquiry_reference_popup(
        self, target: str, item_id: str, href: str, *, force_api: bool = False
    ) -> None:
        """AI 답의 질의회신 링크를 기관 API 본문으로 연다."""
        agency = AGENCY_BY_TARGET.get(target)
        if agency is None or not item_id:
            QMessageBox.warning(
                self, "문서 링크 오류", "열 수 있는 질의회신 링크가 아닙니다."
            )
            return
        if not agency.detail_available:
            QMessageBox.information(
                self,
                "질의회신 본문 없음",
                f"{agency.name} 질의회신은 법제처 API가 본문을 주지 않습니다.\n"
                "중앙부처 질의회신 탭에서 확인하세요.",
            )
            return
        reference_key = f"doc:{target}:{item_id}"
        title_guess = f"{agency.name} 질의회신"
        if not force_api:
            cached_state = self._reference_popup_states.get(reference_key)
            if cached_state is None:
                cached_state = self._load_reference_cache(reference_key)
            if cached_state is not None:
                popup = self._reference_popup_for_request()
                popup.reference_request = {
                    "href": href,
                    "category": target,
                    "item_id": item_id,
                    "name": title_guess,
                    "reference_key": reference_key,
                    "title": str(cached_state["title"]),
                }
                popup.reference_key = reference_key
                popup.show_content_at(
                    str(cached_state["title"]),
                    str(cached_state["html"]),
                    QCursor.pos(),
                    scroll_position=int(cached_state.get("scroll") or 0),
                )
                self.status_label.setText(
                    f"{cached_state['title']} 저장된 조문 열기 · API 호출 없음"
                )
                return
        oc = self.oc_provider().strip()
        if not oc:
            prompt_oc_api_key(self)
            return
        if self.worker and self.worker.isRunning():
            self.status_label.setText(
                "현재 API 조회가 진행 중입니다 · 완료 후 다시 눌러 주세요."
            )
            return
        popup = self._reference_popup_for_request()
        popup.reference_request = {
            "href": href,
            "category": target,
            "item_id": item_id,
            "name": title_guess,
            "reference_key": reference_key,
            "title": title_guess,
        }
        popup.reference_key = reference_key
        self._pending_reference_popup = popup
        self._pending_reference_key = reference_key
        self._pending_reference_title = title_guess
        popup.show_loading(title_guess, QCursor.pos())
        self._start_worker(
            ResourceApiWorker(
                "inquiry_reference_detail",
                oc=oc,
                target=target,
                item_id=item_id,
                law_name=title_guess,
                parent=self,
            ),
            f"{title_guess} 본문 조회 중...",
        )

    def _inquiry_reference_html(
        self, root: object, target: str
    ) -> tuple[str, str]:
        agency = AGENCY_BY_TARGET.get(target)
        agency_name = agency.name if agency is not None else "중앙부처"
        title = _find_text(root, "안건명") or f"{agency_name} 질의회신"
        metadata = [("조회 기관", agency_name)]
        for label in (
            "법령해석일련번호",
            "안건번호",
            "해석일자",
            "해석기관명",
            "질의기관명",
        ):
            value = _find_text(root, label)
            if value and value.lower() != "null":
                metadata.append((label, value))
        html_parts, _plain = detail_document_header(title, metadata, ())
        for label in ("질의요지", "회답", "이유", "관련법령"):
            value = _find_text(root, label)
            if value and value.lower() != "null":
                html_parts.append(f"<h2>{escape(label)}</h2>")
                html_parts.append(
                    f'<div class="content">{body_to_html(value, ())}</div>'
                )
        return title, "".join(html_parts)

    def _show_inquiry_reference_detail(self, payload: object) -> None:
        if not isinstance(payload, dict):
            raise ValueError("질의회신 본문 응답 형식이 올바르지 않습니다.")
        xml_text = str(payload.get("xml") or "")
        target = str(payload.get("target") or "")
        if not xml_text or not target:
            raise ValueError("질의회신 본문을 찾지 못했습니다.")
        root = ET.fromstring(xml_text)
        title, html = self._inquiry_reference_html(root, target)
        if "질의요지" not in html and "회답" not in html:
            message = "".join(root.itertext()).strip()
            raise ValueError(message or "질의회신 본문을 파싱하지 못했습니다.")
        popup = self._pending_reference_popup
        popup.set_content(title, html)
        popup.reference_request["title"] = title
        reference_key = self._pending_reference_key or str(
            popup.reference_key or ""
        )
        popup.reference_key = reference_key
        item_id = str(payload.get("item_id") or "")
        self._remember_reference_popup(
            {
                "target": target,
                "id": item_id,
                "name": title,
                "label": "질의회신",
            },
            title,
            html,
            "",
            "",
            "",
            "",
            key_override=reference_key,
        )
        self._save_reference_cache(reference_key, title, html)
        self.status_label.setText(f"{title} 조회 완료")

    def _open_document_reference_popup(
        self, url: QUrl, *, force_api: bool = False
    ) -> None:
        """AI 답 등의 행정규칙ㆍ자치법규 링크를 본문과 같은 파서로 연다."""
        href = url.toString()
        _, _, rest = href.partition(":")
        category, _, item_id = rest.partition(":")
        category = category.strip()
        item_id = item_id.strip()
        config = RESOURCE_CATEGORIES.get(category)
        if config is None or "detail_target" not in config or not item_id:
            QMessageBox.warning(
                self, "문서 링크 오류", "열 수 있는 문서 링크가 아닙니다."
            )
            return
        name = query_value(QUrlQuery(url), "name").strip()
        row = {
            "target": category,
            "label": config["label"],
            "id": item_id,
            "name": name,
            "related": "",
            "organization": "",
            "date": "",
            "number": "",
            "effective": "",
            "raw": {},
        }
        reference_key = f"doc:{category}:{item_id}"
        title_guess = name or str(config["label"])
        if not force_api:
            snapshot = self.law_cache.load_snapshot(row)
            if snapshot is not None:
                try:
                    title, html = self._document_reference_html(
                        row, record=snapshot
                    )
                except ValueError:
                    snapshot = None
                else:
                    popup = self._reference_popup_for_request()
                    popup.reference_request = {
                        "href": href,
                        "category": category,
                        "item_id": item_id,
                        "name": name,
                        "reference_key": reference_key,
                        "title": title,
                    }
                    popup.reference_key = reference_key
                    popup.show_content_at(title, html, QCursor.pos())
                    self._remember_reference_popup(
                        {**row, "name": title},
                        title,
                        html,
                        "",
                        "",
                        "",
                        "",
                        key_override=reference_key,
                    )
                    self.status_label.setText(
                        f"{title} 저장된 본문 열기 · API 호출 없음"
                    )
                    return
            cached_state = self._reference_popup_states.get(reference_key)
            if cached_state is None:
                cached_state = self._load_reference_cache(reference_key)
            if cached_state is not None:
                popup = self._reference_popup_for_request()
                popup.reference_request = {
                    "href": href,
                    "category": category,
                    "item_id": item_id,
                    "name": name,
                    "reference_key": reference_key,
                    "title": str(cached_state["title"]),
                }
                popup.reference_key = reference_key
                popup.show_content_at(
                    str(cached_state["title"]),
                    str(cached_state["html"]),
                    QCursor.pos(),
                    scroll_position=int(cached_state.get("scroll") or 0),
                )
                self.status_label.setText(
                    f"{cached_state['title']} 저장된 조문 열기 · API 호출 없음"
                )
                return
        oc = self.oc_provider().strip()
        if not oc:
            prompt_oc_api_key(self)
            return
        if self.worker and self.worker.isRunning():
            self.status_label.setText(
                "현재 API 조회가 진행 중입니다 · 완료 후 다시 눌러 주세요."
            )
            return
        popup = (
            self._pending_reference_popup
            if force_api
            and self._pending_reference_popup.reference_key == reference_key
            else self._reference_popup_for_request()
        )
        popup.reference_request = {
            "href": href,
            "category": category,
            "item_id": item_id,
            "name": name,
            "reference_key": reference_key,
            "title": title_guess,
        }
        popup.reference_key = reference_key
        self._pending_reference_popup = popup
        self._pending_reference_key = reference_key
        self._pending_document_row = row
        self._pending_reference_title = title_guess
        popup.show_loading(title_guess, QCursor.pos())
        self._start_worker(
            ResourceApiWorker(
                "document_reference_detail",
                oc=oc,
                target=category,
                item_id=item_id,
                detail_target=str(config["detail_target"]),
                id_param=str(config["id_param"]),
                law_name=name,
                parent=self,
            ),
            f"{title_guess} 본문 조회 중...",
        )

    def _document_reference_html(
        self,
        row: dict[str, object],
        *,
        payload: dict | None = None,
        record: dict | None = None,
    ) -> tuple[str, str]:
        """본문 화면과 같은 파서로 문서 팝업 HTML을 만든다."""
        target = str(row.get("target") or "")
        original_pending_row = self.pending_row
        self.pending_row = dict(row)
        try:
            if record is not None and target == "admrul":
                sections = self._cached_admrul_sections(record)
                if not sections:
                    raise ValueError("저장된 행정규칙 본문을 찾지 못했습니다.")
                title = str(record.get("name") or row.get("name") or "행정규칙")
                raw = row.get("raw")
                raw = raw if isinstance(raw, dict) else {}
                metadata = [
                    ("행정규칙일련번호", str(row.get("id") or "")),
                    ("발령일자", str(row.get("date") or "")),
                    ("발령번호", str(row.get("number") or "")),
                    ("시행일자", str(row.get("effective") or "")),
                    (
                        "소관부처",
                        str(
                            row.get("organization")
                            or row.get("related")
                            or ""
                        ),
                    ),
                    ("행정규칙종류", json_text(raw.get("행정규칙종류"))),
                ]
            elif payload is not None:
                if target == "admrul":
                    title, metadata, sections = self._parse_admrul_detail(
                        payload
                    )
                elif target == "ordin":
                    title, metadata, sections = self._parse_ordin_detail(
                        payload
                    )
                elif target == "law":
                    title, metadata, sections = self._parse_law_detail(payload)
                else:
                    raise ValueError("이 유형은 본문 조회를 지원하지 않습니다.")
            else:
                raise ValueError("문서 본문을 찾지 못했습니다.")
            html_parts = self._popup_detail_header(title, metadata)
            for label, value in sections:
                value = str(value or "")
                if not value:
                    continue
                html_parts.append(
                    '<div class="popup-section-title">'
                    f"{escape(str(label))}</div>"
                )
                html_parts.append(
                    '<div class="content">'
                    + body_to_html(
                        value,
                        self.detail_highlight_terms,
                        current_law_name=title,
                        current_law_id=(
                            str(row.get("id") or "")
                            if target == "law"
                            else ""
                        ),
                        use_api_links=True,
                        administrative_rule=target == "admrul",
                        administrative_rule_normalized=target == "admrul",
                    )
                    + "</div>"
                )
            return title, "".join(html_parts)
        finally:
            self.pending_row = original_pending_row

    def _show_document_reference_detail(self, payload: object) -> None:
        row = self._pending_document_row
        self._pending_document_row = None
        if not isinstance(payload, dict) or not isinstance(row, dict):
            raise ValueError("문서 본문 응답 형식이 올바르지 않습니다.")
        title, html = self._document_reference_html(row, payload=payload)
        popup = self._pending_reference_popup
        popup.set_content(title, html)
        popup.reference_request["title"] = title
        reference_key = self._pending_reference_key or str(
            popup.reference_key or ""
        )
        popup.reference_key = reference_key
        self._remember_reference_popup(
            {**row, "name": title},
            title,
            html,
            "",
            "",
            "",
            "",
            key_override=reference_key,
        )
        self._save_reference_cache(reference_key, title, html)
        self.status_label.setText(f"{title} 조회 완료")

    def open_three_stage_for_article(
        self,
        *,
        law_id: str,
        jo: str,
        law_name: str,
        label: str = "",
    ) -> None:
        """다른 탭에서 고른 조문의 3단비교를 이 탭의 팝업으로 연다."""
        self._open_three_stage_comparison(
            {
                "law_id": str(law_id or ""),
                "jo": str(jo or ""),
                "law_name": str(law_name or "법령"),
                "label": str(label or ""),
            }
        )

    def _detail_link_clicked(self, url: QUrl) -> None:
        if url.scheme() == "pdfpreview":
            real_url = unquote(url.toString()[len("pdfpreview:") :])
            self._show_pdf_preview(real_url)
            return
        if url.scheme() == "lawsub":
            self._show_inline_subordinate_menu(url)
            return
        if url.scheme() != "lawref":
            if not QDesktopServices.openUrl(url):
                QMessageBox.warning(
                    self, "링크 열기 실패", "외부 링크를 열지 못했습니다."
                )
            return
        query = QUrlQuery(url)
        law_name = query_value(query, "name").strip()
        law_id = query_value(query, "id").strip()
        if not law_name:
            QMessageBox.warning(
                self, "법령명 없음", "링크에서 법령명을 확인하지 못했습니다."
            )
            return
        try:
            jo_number = query_value(query, "jo").strip()
            jo = law_unit_code(
                jo_number, query_value(query, "jo_branch").strip()
            ) if jo_number else ""
            hang_number = query_value(query, "hang").strip()
            hang = law_unit_code(
                hang_number, query_value(query, "hang_branch").strip()
            ) if hang_number else ""
            ho_number = query_value(query, "ho").strip()
            ho = law_unit_code(
                ho_number, query_value(query, "ho_branch").strip()
            ) if ho_number else ""
        except ValueError:
            QMessageBox.warning(
                self, "조문 번호 오류", "링크의 조·항·호 번호가 올바르지 않습니다."
            )
            return
        mok = query_value(query, "mok").strip()
        # 대통령령·부령 위임 링크로 들어온 경우의 출처 조문
        self._pending_delegation_source = {
            "label": query_value(query, "via_label").strip(),
            "name": query_value(query, "via_name").strip(),
            "authority": query_value(query, "via_authority").strip(),
        }
        reference_label = self._law_reference_label(jo, hang, ho, mok)
        self._pending_reference_title = (
            f"{law_name} {reference_label or '본문'}".strip()
        )
        reference_key = self._reference_key(
            law_id, law_name, jo, hang, ho, mok
        )
        cached_state = self._reference_popup_states.get(reference_key)
        if cached_state is None:
            cached_state = self._load_reference_cache(reference_key)
        if cached_state is not None:
            popup = next(
                (
                    candidate
                    for candidate in self._all_reference_popups()
                    if candidate.isVisible()
                    and candidate.reference_key == reference_key
                ),
                None,
            )
            if popup is None:
                popup = self._reference_popup_for_request()
                popup.reference_request = {
                    "law_id": law_id,
                    "law_name": law_name,
                    "jo": jo,
                    "hang": hang,
                    "ho": ho,
                    "mok": mok,
                    "reference_key": reference_key,
                    "title": self._pending_reference_title,
                }
                popup.reference_key = reference_key
                popup.show_content_at(
                    str(cached_state["title"]),
                    str(cached_state["html"]),
                    QCursor.pos(),
                    scroll_position=int(cached_state.get("scroll") or 0),
                )
            elif not popup.pin_button.isChecked():
                popup.reference_request = {
                    "law_id": law_id,
                    "law_name": law_name,
                    "jo": jo,
                    "hang": hang,
                    "ho": ho,
                    "mok": mok,
                    "reference_key": reference_key,
                    "title": self._pending_reference_title,
                }
                popup.show_content_at(
                    str(cached_state["title"]),
                    str(cached_state["html"]),
                    QCursor.pos(),
                    scroll_position=int(cached_state.get("scroll") or 0),
                )
            else:
                popup.dismiss_timer.stop()
                popup.raise_()
                popup.activateWindow()
            self._remember_reference_popup(
                {"id": law_id, "name": law_name},
                str(cached_state["title"]),
                str(cached_state["html"]),
                jo,
                hang,
                ho,
                mok,
            )
            self.status_label.setText(
                f"{self._pending_reference_title} 저장된 조문 열기 · API 호출 없음"
            )
            return

        if self.worker and self.worker.isRunning():
            self.status_label.setText(
                "현재 API 조회가 진행 중입니다 · 완료 후 다시 눌러 주세요."
            )
            return
        oc = self.oc_provider().strip()
        if not oc:
            prompt_oc_api_key(self)
            return

        popup = self._reference_popup_for_request()
        popup.reference_request = {
            "law_id": law_id,
            "law_name": law_name,
            "jo": jo,
            "hang": hang,
            "ho": ho,
            "mok": mok,
            "reference_key": reference_key,
            "title": self._pending_reference_title,
        }
        self._pending_reference_key = reference_key
        popup.reference_key = reference_key
        popup.show_loading(self._pending_reference_title, QCursor.pos())
        self._start_worker(
            ResourceApiWorker(
                "law_reference_detail",
                oc=oc,
                target="law",
                item_id=law_id,
                law_name=law_name,
                jo=jo,
                hang=hang,
                ho=ho,
                mok=mok,
                parent=self,
            ),
            f"{self._pending_reference_title} 조회 중...",
        )

    @staticmethod
    def _law_reference_label(
        jo: str, hang: str = "", ho: str = "", mok: str = ""
    ) -> str:
        def decode(code: str, unit: str) -> str:
            if not code:
                return ""
            main = int(code[:4])
            branch = int(code[4:])
            return f"제{main}{unit}" + (f"의{branch}" if branch else "")

        return "".join(
            (decode(jo, "조"), decode(hang, "항"), decode(ho, "호"), f"{mok}목" if mok else "")
        )

    def _is_reference_favorite(self, request: dict[str, str]) -> bool:
        row = self._law_row(
            str(request.get("law_id") or ""),
            str(request.get("law_name") or ""),
        )
        if row is None:
            return False
        return self.law_cache.is_article_favorite(
            row,
            str(request.get("jo") or ""),
            hang=str(request.get("hang") or ""),
            ho=str(request.get("ho") or ""),
            mok=str(request.get("mok") or ""),
        )

    def _refresh_reference_popup_favorites(self) -> None:
        if not hasattr(self, "reference_popup"):
            return
        for popup in self._all_reference_popups():
            popup._refresh_favorite_button()

    def _toggle_reference_favorite(self, popup: object) -> None:
        if not isinstance(popup, LawReferencePopup):
            return
        request = popup.reference_request
        law_id = str(request.get("law_id") or "")
        jo = str(request.get("jo") or "")
        if not law_id or not jo:
            return
        hang = str(request.get("hang") or "")
        ho = str(request.get("ho") or "")
        mok = str(request.get("mok") or "")
        law_name = str(request.get("law_name") or "")
        unit_label = self._law_reference_label(jo, hang, ho, mok)
        label = f"{law_name} {unit_label}".strip()
        row = self._law_row(law_id, law_name)
        if row is None:
            return
        favorite = self.law_cache.is_article_favorite(
            row, jo, hang=hang, ho=ho, mok=mok
        )
        if favorite:
            if self.law_cache.set_article_favorite(
                row,
                jo,
                label,
                False,
                hang=hang,
                ho=ho,
                mok=mok,
            ):
                self.status_label.setText(f"{label} 즐겨찾기를 해제했습니다.")
            else:
                self.status_label.setText(
                    f"즐겨찾기 해제에 실패했습니다: {self.law_cache.last_error}"
                )
            popup._refresh_favorite_button()
            return
        self.add_article_favorite_by_id(
            law_id,
            jo,
            label,
            law_name,
            hang=hang,
            ho=ho,
            mok=mok,
        )
        pending = self._pending_article_favorite
        if pending is not None and str(pending[0].get("id") or "") == law_id:
            popup.set_favorite_pending()
        else:
            popup._refresh_favorite_button()

    def _all_reference_popups(self) -> list[LawReferencePopup]:
        return [self.reference_popup, *self._extra_reference_popups]

    def _create_reference_popup(self) -> LawReferencePopup:
        popup = LawReferencePopup(self._detail_link_clicked, self)
        popup.resize(self.reference_popup.size())
        popup.favorite_checker = self._is_reference_favorite
        popup.favoriteRequested.connect(self._toggle_reference_favorite)
        popup.hover_guard = (
            lambda popup=popup: self._cursor_over_reference_link(popup)
        )
        popup.browser.verticalScrollBar().valueChanged.connect(
            lambda value, popup=popup: self._reference_popup_scrolled(
                popup, value
            )
        )
        popup.refreshRequested.connect(self._refresh_reference_popup)
        self._extra_reference_popups.append(popup)
        return popup

    def _refresh_reference_popup(self, popup: object) -> None:
        """Refresh a cached reference popup from the law API."""
        if not isinstance(popup, LawReferencePopup):
            return
        request = dict(popup.reference_request)
        if not request:
            return
        if request.get("category"):
            href = str(request.get("href") or "")
            category = str(request.get("category") or "")
            item_id = str(request.get("item_id") or "")
            if is_inquiry_target(category) and item_id:
                self._pending_reference_popup = popup
                self._open_inquiry_reference_popup(
                    category, item_id, href, force_api=True
                )
                return
            if href:
                self._pending_reference_popup = popup
                self._open_document_reference_popup(
                    QUrl(href), force_api=True
                )
            return
        if self.worker and self.worker.isRunning():
            self.status_label.setText(
                "현재 API 조회가 진행 중입니다 · 완료 후 다시 눌러 주세요."
            )
            return
        oc = self.oc_provider().strip()
        if not oc:
            prompt_oc_api_key(self)
            return
        self._pending_reference_popup = popup
        self._pending_reference_key = str(request.get("reference_key") or "")
        self._pending_reference_title = str(request.get("title") or "인용 조문")
        popup.set_loading(
            self._pending_reference_title,
            "저장된 조문을 건너뛰고 API에서 다시 불러오는 중입니다…",
        )
        popup.dismiss_timer.stop()
        self._start_worker(
            ResourceApiWorker(
                "law_reference_detail",
                oc=oc,
                target="law",
                item_id=str(request.get("law_id") or ""),
                law_name=str(request.get("law_name") or ""),
                jo=str(request.get("jo") or ""),
                hang=str(request.get("hang") or ""),
                ho=str(request.get("ho") or ""),
                mok=str(request.get("mok") or ""),
                parent=self,
            ),
            f"{self._pending_reference_title} API 갱신 중...",
        )

    def _reference_popup_scrolled(
        self, popup: LawReferencePopup, value: int
    ) -> None:
        if popup._restoring_scroll or not popup.reference_key:
            return
        state = self._reference_popup_states.get(popup.reference_key)
        if state is not None:
            state["scroll"] = int(value)

    def _cursor_over_reference_link(self, popup: LawReferencePopup) -> bool:
        """현재 팝업을 연 조문 링크 위에 커서가 있으면 팝업을 유지."""
        if not popup.reference_key:
            return False
        browsers = [
            self.detail_view,
            self.three_stage_popup.browser,
            *(candidate.browser for candidate in self._all_reference_popups()),
        ]
        for browser in browsers:
            if not browser.isVisible():
                continue
            viewport = browser.viewport()
            position = viewport.mapFromGlobal(QCursor.pos())
            hit = viewport.rect().adjusted(
                -_LINK_HOVER_SLACK,
                -_LINK_HOVER_SLACK,
                _LINK_HOVER_SLACK,
                _LINK_HOVER_SLACK,
            )
            if not hit.contains(position):
                continue
            href = _browser_href_at(browser, position)
            if href and self._reference_key_from_url(QUrl(href)) == popup.reference_key:
                return True
        return self._cursor_over_chat_link(popup)

    def _chat_reference_labels(self) -> list[QLabel]:
        labels: list[QLabel] = []
        panel = getattr(self, "ai_chat_panel", None)
        if panel is not None:
            labels.extend(panel.findChildren(QLabel))
        window = self.window()
        review = getattr(window, "ai_review_tab", None)
        if review is not None and review is not panel:
            labels.extend(review.findChildren(QLabel))
        return labels

    def _cursor_over_chat_link(self, popup: LawReferencePopup) -> bool:
        """AI 채팅 말풍선의 같은 링크·그 주변이면 팝업을 유지한다."""
        key = popup.reference_key
        if not key:
            return False
        cursor = QCursor.pos()
        for label in self._chat_reference_labels():
            if not label.isVisible() or label.textFormat() != Qt.TextFormat.RichText:
                continue
            local = label.mapFromGlobal(cursor)
            hit = label.rect().adjusted(
                -_LINK_HOVER_SLACK,
                -_LINK_HOVER_SLACK,
                _LINK_HOVER_SLACK,
                _LINK_HOVER_SLACK,
            )
            if not hit.contains(local):
                continue
            html = label.text()
            for href in re.findall(r'href="([^"]+)"', html):
                if self._reference_key_from_url(QUrl(unescape(href))) == key:
                    return True
        return False

    @staticmethod
    def _reference_key(
        law_id: str,
        law_name: str,
        jo: str,
        hang: str,
        ho: str,
        mok: str,
    ) -> str:
        return ":".join((law_id or law_name, jo, hang, ho, mok))

    def _reference_key_from_url(self, url: QUrl) -> str:
        if url.scheme() == "doc":
            category, item_id = split_doc_reference(url.toString())
            if category and item_id:
                return f"doc:{category}:{item_id}"
            return ""
        if url.scheme() != "lawref":
            return ""
        query = QUrlQuery(url)
        try:
            unit_codes: list[str] = []
            for main_name, branch_name in (
                ("jo", "jo_branch"),
                ("hang", "hang_branch"),
                ("ho", "ho_branch"),
            ):
                main = query_value(query, main_name).strip()
                unit_codes.append(
                    law_unit_code(
                        main, query_value(query, branch_name).strip()
                    )
                    if main
                    else ""
                )
        except ValueError:
            return ""
        return self._reference_key(
            query_value(query, "id").strip(),
            query_value(query, "name").strip(),
            unit_codes[0],
            unit_codes[1],
            unit_codes[2],
            query_value(query, "mok").strip(),
        )

    @staticmethod
    def _reference_cache_path(key: str) -> Path:
        readable = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", key).strip("_")
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
        return LAW_REFERENCE_CACHE_DIR / f"{readable[:100] or 'reference'}_{digest}.json"

    def _load_reference_cache(self, key: str) -> dict[str, object] | None:
        path = self._reference_cache_path(key)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if (
            not isinstance(record, dict)
            or record.get("kind") != "law_reference"
            # schema 1은 상·하위 법령 인용을 현재 법령 ID로 잘못 조회해
            # 본문 없는 결과를 저장했으므로 다시 조회한다.
            or record.get("schema") != LAW_REFERENCE_CACHE_SCHEMA
            or record.get("key") != key
            or not isinstance(record.get("title"), str)
            or not isinstance(record.get("html"), str)
        ):
            return None
        try:
            scroll_position = int(record.get("scroll") or 0)
        except (TypeError, ValueError):
            scroll_position = 0
        state = {
            "title": record["title"],
            "html": record["html"],
            "scroll": scroll_position,
        }
        self._reference_popup_states[key] = state
        return state

    def _save_reference_cache(self, key: str, title: str, html: str) -> None:
        try:
            LAW_REFERENCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path = self._reference_cache_path(key)
            temporary_path = path.with_suffix(".json.tmp")
            temporary_path.write_text(
                json.dumps(
                    {
                        "schema": LAW_REFERENCE_CACHE_SCHEMA,
                        "kind": "law_reference",
                        "key": key,
                        "saved_at": datetime.now().astimezone().isoformat(
                            timespec="seconds"
                        ),
                        "title": title,
                        "html": html,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            temporary_path.replace(path)
        except (OSError, TypeError, ValueError):
            pass

    def _reference_popup_for_request(self) -> LawReferencePopup:
        """고정되지 않은 팝업은 재사용하고, 모두 고정됐으면 새 팝업을 생성."""
        for popup in self._all_reference_popups():
            if not popup.pin_button.isChecked():
                self._pending_reference_popup = popup
                return popup
        popup = self._create_reference_popup()
        self._pending_reference_popup = popup
        return popup

    def _reference_popup_for_pinned_history(self) -> LawReferencePopup:
        """고정 모드에서는 화면에 보이는 팝업을 덮어쓰지 않고 새 창을 확보."""
        for popup in self._all_reference_popups():
            if not popup.isVisible() and not popup.pin_button.isChecked():
                self._pending_reference_popup = popup
                return popup
        popup = self._create_reference_popup()
        self._pending_reference_popup = popup
        return popup

    def _place_reference_popup(self, popup: LawReferencePopup) -> None:
        """새 팝업을 기존 고정 팝업과 겹치지 않는 가까운 위치에 배치."""
        pinned = [
            candidate
            for candidate in self._all_reference_popups()
            if candidate is not popup
            and candidate.isVisible()
            and candidate.pin_button.isChecked()
        ]
        if not pinned:
            return
        screen = (
            QApplication.screenAt(popup.frameGeometry().center())
            or QApplication.primaryScreen()
        )
        available = screen.availableGeometry()
        current = popup.frameGeometry()
        gap = 12
        step = popup.width() + gap
        candidates: list[tuple[int, int]] = []
        for distance in range(1, len(pinned) + 3):
            candidates.extend(
                (
                    (current.x() + step * distance, current.y()),
                    (current.x() - step * distance, current.y()),
                )
            )
        for x, y in candidates:
            candidate_rect = QRect(current)
            candidate_rect.moveTo(x, y)
            if not available.contains(candidate_rect):
                continue
            if any(
                candidate_rect.intersects(other.frameGeometry())
                for other in pinned
            ):
                continue
            popup.move(x, y)
            return

        offset = 28 * len(pinned)
        x = max(
            available.left(),
            min(current.x() + offset, available.right() - popup.width() + 1),
        )
        y = max(
            available.top(),
            min(current.y() + offset, available.bottom() - popup.height() + 1),
        )
        popup.move(x, y)

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
            cursor,
            QColor(color_value),
            background=background,
        )

    def _reset_selected_colors(self) -> None:
        cursor = self._selected_detail_cursor()
        if cursor is None:
            return
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        self._clear_cursor_colors(cursor)
        self._restore_memo_markers_for_range(start, end)
        self.detail_view.setTextCursor(cursor)
        self._save_active_document_state()

        row = self._active_cached_law_row()
        saved: bool | None = None
        if row is not None:
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
            self._apply_memo_marker(
                memo_cursor, str(memo.get("text") or "")
            )

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
        self._save_active_document_state()

        row = self._active_cached_law_row()
        saved: bool | None = None
        if row is not None:
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
        self._save_active_document_state()
        formatting_saved = self._persist_active_law_formatting(
            cursor, color, background=background
        )
        if formatting_saved is True:
            status = (
                f"선택한 본문에 {description}을 적용하고 저장본에 보관했습니다."
            )
        elif formatting_saved is False:
            status = (
                f"{description}은 적용했지만 저장하지 못했습니다: "
                f"{self.law_cache.last_error}"
            )
        else:
            status = f"선택한 본문에 {description}을 적용했습니다."
        self.status_label.setText(status)
        self.detail_view.setFocus()

    def _persist_active_law_formatting(
        self,
        cursor: QTextCursor,
        color: QColor,
        *,
        background: bool,
    ) -> bool | None:
        row = self._active_cached_law_row()
        if row is None:
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

    def _active_cached_law_row(self) -> dict[str, object] | None:
        target, separator, identifier = self._active_document_key.partition(":")
        if target not in ("law", "admrul", "ordin") or not separator or not identifier:
            return None
        row = {"target": target, "id": identifier}
        if not self.law_cache.has(row):
            return None
        return row

    @staticmethod
    def _apply_memo_marker(cursor: QTextCursor, text: str) -> None:
        character_format = QTextCharFormat()
        character_format.setBackground(QBrush(Qt.BrushStyle.NoBrush))
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
        record = self.law_cache.load_for_row(row)
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

    def _open_memo_marker_popup(self, index: int) -> None:
        self._edit_selection_memo(
            anchor_rect=self.memo_marker_bar.marker_global_rect(index)
        )

    def _edit_selection_memo(self, anchor_rect: QRect | None = None) -> None:
        row = self._active_cached_law_row()
        if row is None:
            QMessageBox.information(
                self,
                "메모 저장",
                "저장된 법령 본문을 연 뒤 메모할 구간을 선택해 주세요.",
            )
            return
        record = self.law_cache.load_for_row(row)
        if record is None:
            QMessageBox.critical(
                self,
                "메모 열기 실패",
                self.law_cache.last_error or "법령 저장본을 읽지 못했습니다.",
            )
            return
        memos = record.get("memos")
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

        excerpt = cursor.selectedText().replace("\u2029", " ").strip()
        initial_text = (
            str(existing_memo.get("text") or "") if existing_memo else ""
        )
        # 이전에 선택해 둔 메모를 도구모음 버튼으로 다시 열 때 현재
        # 스크롤이 다른 위치에 있을 수 있다. 팝업보다 먼저 메모 문구를
        # 화면에 노출해 어떤 본문의 메모인지 바로 확인하게 한다.
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
            self._save_active_document_state()
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

    def _category_changed(self) -> None:
        self._sync_content_page()
        self._sync_detail_button_visibility()
        if self.is_keyword_category:
            # 키워드검색 화면은 자기 표ㆍ본문을 따로 들고 있어서 목록 검색
            # 상태를 건드리면 안 된다. 돌아왔을 때 보던 결과가 남아 있어야
            # 카테고리를 오가며 비교할 수 있다.
            self.status_label.setText(
                f"{self.category['label']} 화면으로 바꿨습니다."
            )
            return
        is_annex_category = self.category_target in ("licbyl", "admbyl", "ordinbyl")
        self.annex_search_scope.setVisible(is_annex_category)
        if is_annex_category:
            related_label = {
                "licbyl": "해당 법령명",
                "admbyl": "해당 행정규칙명",
                "ordinbyl": "해당 자치법규명",
            }[self.category_target]
            self.annex_search_scope.setItemText(1, related_label)
        self._annex_search_scope_changed()
        self._prepare_preview_for_outer_search()
        self.result_rows.clear()
        self.result_table.setRowCount(0)
        self.result_count.setText("0건")
        self.current_detail_text = ""
        self.copy_button.setEnabled(False)
        self.detail_button.setEnabled(False)
        is_integrated = self.category_target == RESOURCE_ALL_TARGET
        self.result_table.setColumnHidden(1, not is_integrated)
        self.detail_button.setText("본문\n조회")
        if is_integrated:
            self.detail_button.setToolTip("선택한 항목을 엽니다.")
        else:
            is_annex = "detail_target" not in self.category
            self.detail_button.setToolTip(
                "선택한 별표·서식의 다운로드·미리보기 링크를 표시합니다."
                if is_annex
                else "선택한 항목의 본문을 조회합니다."
            )
        self._sync_detail_button_visibility()
        self.status_label.setText(
            f"{self.category['label']} 검색 유형을 선택했습니다."
        )

    def _annex_search_scope_changed(self, *_args: object) -> None:
        if self.category_target not in ("licbyl", "admbyl", "ordinbyl"):
            self.query_input.setPlaceholderText("검색할 키워드를 입력하세요")
            return
        related_name = {
            "licbyl": "법령명",
            "admbyl": "행정규칙명",
            "ordinbyl": "자치법규명",
        }[self.category_target]
        scope = int(self.annex_search_scope.currentData() or 1)
        placeholders = {
            1: "검색할 별표·서식명을 입력하세요",
            2: f"별표·서식을 찾을 {related_name}을 입력하세요",
            3: "별표 본문에서 찾을 단어를 입력하세요",
        }
        self.query_input.setPlaceholderText(placeholders.get(scope, placeholders[1]))

    def _prepare_preview_for_outer_search(self) -> None:
        """본문 탭 상태를 보존하고 바깥 검색용 미리보기를 초기화."""
        self._activate_preview()
        self.detail_search.query_input.clear()
        self.toc_search_input.clear()
        self._replace_detail_content()
        self._populate_toc([])

    def _clear_search_highlighting(self) -> None:
        terms = self.highlight_terms
        if not terms:
            return
        self.highlight_terms = ()
        self.name_delegate.set_terms(())
        self.related_delegate.set_terms(())
        replace_search_term_backgrounds(self.detail_view, ())
        self.result_table.viewport().update()
        self.search_shade_reset_button.setEnabled(False)
        self._save_active_document_state()
        self.status_label.setText("검색어 음영을 초기화했습니다.")

    def _refresh_search_from_api(self) -> None:
        self.start_search(force_api=True)

    def start_search(self, *_args: object, force_api: bool = False) -> None:
        query = self.query_input.text().strip()
        if not query:
            QMessageBox.information(self, "검색어 확인", "검색어를 입력해 주세요.")
            self.query_input.setFocus()
            return

        self.recent_search_manager.add(query)
        self.highlight_terms = search_terms(query)
        self.search_shade_reset_button.setEnabled(bool(self.highlight_terms))
        self.name_delegate.set_terms(self.highlight_terms)
        self.related_delegate.set_terms(self.highlight_terms)
        self.result_table.setRowCount(0)
        self.result_rows.clear()
        self.result_count.setText("0건")
        self._prepare_preview_for_outer_search()
        self.current_detail_text = ""
        self.copy_button.setEnabled(False)
        self.pending_row = None
        search_scope = (
            int(self.annex_search_scope.currentData() or 1)
            if self.category_target in ("licbyl", "admbyl", "ordinbyl")
            else 1
        )
        if not force_api:
            cached = self.search_result_cache.load(
                self.category_target, query, search_scope
            )
            if cached is not None:
                self._show_search_results(cached["payload"])
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
            ResourceApiWorker(
                "resource_search",
                oc=oc,
                target=self.category_target,
                query=query,
                search_scope=search_scope,
                parent=self,
            ),
            f"{self.category['label']}에서 '{query}' 검색 중...",
        )

    def _start_worker(self, worker: ResourceApiWorker, message: str) -> None:
        if self.worker and self.worker.isRunning():
            return
        self.worker = worker
        self.search_button.setEnabled(False)
        self.search_refresh_button.setEnabled(False)
        self.detail_button.setEnabled(False)
        self.query_input.setEnabled(False)
        self.annex_search_scope.setEnabled(False)
        self.category_tabs.setEnabled(False)
        self.detail_search.setEnabled(False)
        self._progress_opacity.setOpacity(1.0)
        self.status_label.setText(message)
        worker.succeeded.connect(self._worker_succeeded)
        worker.failed.connect(self._worker_failed)
        worker.finished.connect(self._worker_finished)
        worker.start()

    def _worker_finished(self) -> None:
        operation = self.worker.operation if self.worker else ""
        self.search_button.setEnabled(True)
        self.search_refresh_button.setEnabled(True)
        self.query_input.setEnabled(True)
        self.annex_search_scope.setEnabled(True)
        self.category_tabs.setEnabled(True)
        self.detail_search.setEnabled(True)
        self._progress_opacity.setOpacity(0.0)
        if self.worker:
            self.worker.deleteLater()
        self.worker = None
        if operation == "resource_search":
            self._selection_changed()
        else:
            row_index = self.result_table.currentRow()
            self.detail_button.setEnabled(
                0 <= row_index < len(self.result_rows)
            )
        if self._pending_three_stage_link_request is not None:
            QTimer.singleShot(0, self._start_pending_three_stage_link_request)
        if self._article_favorite_waiting_for_worker:
            self._article_favorite_waiting_for_worker = False
            QTimer.singleShot(0, self._resume_pending_article_favorite)

    def _worker_succeeded(self, operation: str, payload: object) -> None:
        try:
            if operation == "resource_search":
                self._show_search_results(payload)
                worker = self.worker
                if isinstance(worker, ResourceApiWorker):
                    if self.search_result_cache.save(
                        worker.target,
                        worker.query,
                        worker.search_scope,
                        payload,
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
            elif operation == "law_reference_detail":
                self._show_law_reference_detail(payload)
            elif operation == "document_reference_detail":
                self._show_document_reference_detail(payload)
            elif operation == "inquiry_reference_detail":
                self._show_inquiry_reference_detail(payload)
            elif operation == "three_stage_links":
                self._show_three_stage_links(payload)
            elif operation == "three_stage_comparison":
                self._show_three_stage_comparison(payload)
            else:
                self._show_detail(payload)
        except Exception as exc:
            self._worker_failed(operation, str(exc))

    def _worker_failed(self, operation: str, error: str) -> None:
        action = (
            "검색"
            if operation == "resource_search"
            else "인용 조문 조회"
            if operation == "law_reference_detail"
            else "문서 본문 조회"
            if operation == "document_reference_detail"
            else "질의회신 본문 조회"
            if operation == "inquiry_reference_detail"
            else "하위법령 링크 조회"
            if operation == "three_stage_links"
            else "3단비교 조회"
            if operation == "three_stage_comparison"
            else "본문 조회"
        )
        self.status_label.setText(f"{action}에 실패했습니다.")
        if operation == "law_reference_detail":
            self._pending_reference_popup.set_error(error)
            return
        if operation == "document_reference_detail":
            self._pending_document_row = None
            self._pending_reference_popup.set_error(error)
            return
        if operation == "inquiry_reference_detail":
            self._pending_reference_popup.set_error(error)
            return
        if operation == "three_stage_links":
            self._three_stage_link_request_in_flight = None
            self.status_label.setText(
                "하위법령 조문 링크를 가져오지 못했습니다. "
                "각 조문의 3단비교 버튼은 계속 사용할 수 있습니다."
            )
            return
        if operation == "three_stage_comparison":
            self.three_stage_popup.set_error(error)
            return
        if operation == "resource_detail":
            self._refresh_cache_checkmarks()
            if (
                self._pending_article_favorite is not None
                and not self._article_favorite_waiting_for_worker
            ):
                self._pending_article_favorite = None
                self._pending_favorite_row = None
                self._refresh_reference_popup_favorites()
        QMessageBox.critical(
            self,
            f"{action} 실패",
            f"{action} 중 오류가 발생했습니다.\n\n{error}",
        )

    def _show_law_reference_detail(self, result: object) -> None:
        if not isinstance(result, dict):
            raise ValueError("인용 조문 응답 형식이 올바르지 않습니다.")
        payload = result.get("payload")
        source_row = result.get("row")
        if not isinstance(payload, dict) or not isinstance(source_row, dict):
            raise ValueError("인용 조문 응답에서 법령 정보를 찾지 못했습니다.")

        jo = str(result.get("jo") or "")
        hang = str(result.get("hang") or "")
        ho = str(result.get("ho") or "")
        mok = str(result.get("mok") or "")
        reference_label = self._law_reference_label(jo, hang, ho, mok)
        original_pending_row = self.pending_row
        self.pending_row = dict(source_row)
        try:
            title, metadata, sections = self._parse_law_detail(payload)
        except ValueError:
            # 존재하지 않는 조문을 물으면 API가 본문 없는 응답을 준다.
            # 예외로 끝내지 말고 아래에서 이유를 설명하는 팝업을 만든다.
            title = str(source_row.get("name") or "")
            metadata = [("법령ID", str(source_row.get("id") or ""))]
            sections = []
        finally:
            self.pending_row = original_pending_row

        html_parts = self._popup_detail_header(title, metadata)
        has_body = False
        for label, value in sections:
            value = str(value or "")
            if not value:
                continue
            has_body = True
            html_parts.append(
                '<div class="popup-section-title">'
                f"{escape(str(label))}</div>"
            )
            html_parts.append(
                '<div class="content">'
                + body_to_html(
                    value,
                    self.detail_highlight_terms,
                    current_law_name=title,
                    current_law_id=str(source_row.get("id") or ""),
                    use_api_links=True,
                )
                + "</div>"
            )
        law_label = str(source_row.get("name") or title)
        if not has_body:
            # 해당 법령에 그 조문이 없으면 API가 본문 없이 기본정보만 돌려준다.
            # 빈 팝업 대신 이유를 알려 준다.
            html_parts.append(
                '<div class="content"><p class="paragraph">'
                f"{escape(law_label)}에서 "
                f"{escape(reference_label or '해당 조문')}을(를) 찾지 못했습니다. "
                "인용된 조문이 다른 법령(법률·시행령·시행규칙)에 있을 수 있습니다."
                "</p></div>"
            )
        popup_title = f"{law_label} {reference_label or '본문'}".strip()
        popup_html = "".join(html_parts)
        self._pending_reference_popup.set_content(popup_title, popup_html)
        reference_key = self._remember_reference_popup(
            source_row,
            popup_title,
            popup_html,
            jo,
            hang,
            ho,
            mok,
            key_override=self._pending_reference_key,
        )
        self._pending_reference_popup.reference_key = reference_key
        if has_body:
            # 조문을 못 찾은 응답은 캐시에 남기지 않는다.
            self._save_reference_cache(reference_key, popup_title, popup_html)
        self.status_label.setText(
            f"{popup_title} 조회 완료"
            if has_body
            else f"{popup_title} 조문을 찾지 못했습니다."
        )

    def _remember_reference_popup(
        self,
        source_row: dict,
        title: str,
        html: str,
        jo: str,
        hang: str,
        ho: str,
        mok: str,
        *,
        key_override: str = "",
    ) -> str:
        key = key_override or self._reference_key(
            str(source_row.get("id") or ""),
            str(source_row.get("name") or ""),
            jo,
            hang,
            ho,
            mok,
        )
        previous_state = self._reference_popup_states.get(key, {})
        self._reference_popup_states[key] = {
            "kind": "law_reference",
            "title": title,
            "html": html,
            "scroll": int(previous_state.get("scroll") or 0),
            "request": {
                "law_id": str(source_row.get("id") or ""),
                "law_name": str(source_row.get("name") or ""),
                "jo": jo,
                "hang": hang,
                "ho": ho,
                "mok": mok,
                "reference_key": key,
                "title": title,
            },
        }
        request = self._reference_popup_states[key]["request"]
        history_id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
        self.law_cache.save_snapshot(
            {
                "target": "law_reference",
                "id": history_id,
                "name": title,
                "title": title,
            },
            html=html,
            plain_text=title,
            extra={
                "reference_key": key,
                "reference_request": dict(request),
            },
        )
        index = -1
        for candidate in range(self.reference_tabs.count()):
            if str(self.reference_tabs.tabData(candidate) or "") == key:
                index = candidate
                break
        if index < 0:
            law_name = str(source_row.get("name") or "법령")
            reference_label = self._law_reference_label(jo, hang, ho, mok)
            short_name = law_short_name(
                law_name,
                str(source_row.get("short_name") or "")
                or self._known_law_short_name(law_name),
            )
            tab_title = f"{short_name} {reference_label or '본문'}"
            delegation = self._delegation_tab_title()
            if delegation:
                tab_title = delegation
            index = self.reference_tabs.addTab(tab_title)
            self.reference_tabs.setTabData(index, key)
            self.reference_tabs.setTabToolTip(index, title)
        self.reference_tabs.setCurrentIndex(index)
        return key

    def open_cached_reference_popup(self, record: object) -> None:
        """Restore a saved article/paragraph/item popup without an API call."""
        if not isinstance(record, dict):
            return
        row = record.get("row")
        row = row if isinstance(row, dict) else {}
        title = str(record.get("name") or row.get("title") or "인용 조문")
        html = str(record.get("html") or "")
        if not html:
            return
        request = record.get("reference_request")
        normalized_request = (
            {
                str(request_key): str(request_value or "")
                for request_key, request_value in request.items()
            }
            if isinstance(request, dict)
            else {}
        )
        key = str(record.get("reference_key") or "")
        popup = self._reference_popup_for_request()
        popup.reference_key = key
        popup.reference_request = normalized_request
        self._reference_popup_states[key] = {
            "kind": "law_reference",
            "title": title,
            "html": html,
            "scroll": 0,
            "request": normalized_request,
        }
        popup.show_content_at(title, html, QCursor.pos())
        self.status_label.setText(f"{title} 저장 팝업 열기 · API 호출 없음")

    def _delegation_tab_title(self) -> str:
        """위임 링크로 연 조문의 하단 기록 이름.

        시행령 조문 번호 대신 "국토계획법 제3조의2제2항 대통령령"처럼
        위임한 쪽을 적어야 본문에서 어디를 눌렀는지 알아보기 쉽다.
        """
        source = self._pending_delegation_source or {}
        label = str(source.get("label") or "").strip()
        if not label:
            return ""
        law_name = str(source.get("name") or "").strip()
        authority = str(source.get("authority") or "").strip()
        short_name = law_short_name(
            law_name, self._known_law_short_name(law_name)
        ) if law_name else ""
        return " ".join(
            part for part in (short_name, label, authority) if part
        )

    def _known_law_short_name(self, law_name: str) -> str:
        """이미 받아 둔 검색 결과·현재 문서에서 법제처 공식 약칭을 찾는다."""
        target = re.sub(r"\s+", "", str(law_name or ""))
        if not target:
            return ""
        cached = self._law_short_name_cache.get(target)
        if cached:
            return cached
        candidates = []
        if isinstance(self.pending_row, dict):
            candidates.append(self.pending_row)
        candidates.extend(
            row for row in getattr(self, "result_rows", []) if isinstance(row, dict)
        )
        for row in candidates:
            if re.sub(r"\s+", "", str(row.get("name") or "")) == target:
                short_name = str(row.get("short_name") or "").strip()
                if short_name:
                    self._law_short_name_cache[target] = short_name
                    return short_name
        # 시행령·시행규칙만 못 찾았으면 상위 법률의 약칭에서 유도한다.
        base = law_base_name(law_name)
        if base and base != law_name:
            return self._known_law_short_name(base)
        return ""

    def _remember_three_stage_popup(
        self,
        key: str,
        title: str,
        html: str,
        *,
        law_name: str,
        label: str,
        short_name: str = "",
    ) -> None:
        previous_state = self._reference_popup_states.get(key, {})
        self._reference_popup_states[key] = {
            "kind": "three_stage",
            "title": title,
            "html": html,
            "scroll": int(previous_state.get("scroll") or 0),
        }
        # 인용 조문 팝업과 같은 방식으로 저장내역에도 남긴다. 3단비교는
        # API 한 번에 법령 전체가 오므로 다시 열 때 호출이 필요 없다.
        history_id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
        self.law_cache.save_snapshot(
            {
                "target": "three_stage",
                "id": history_id,
                "name": title,
                "title": title,
            },
            html=html,
            plain_text=title,
            extra={
                "reference_key": key,
                "three_stage_request": {
                    "law_name": law_name,
                    "label": label,
                    "short_name": short_name,
                },
            },
        )
        index = -1
        for candidate in range(self.reference_tabs.count()):
            if str(self.reference_tabs.tabData(candidate) or "") == key:
                index = candidate
                break
        if index < 0:
            # 탭에는 "제3조(국토 이용 및 관리의 기본원칙)"의 조제목을 빼고
            # 조문 번호만 남겨 짧게 적는다.
            short_label = re.sub(r"\s*\(.*\)\s*$", "", str(label or "")).strip()
            index = self.reference_tabs.addTab(
                f"{law_short_name(law_name, short_name)} "
                f"{short_label or '본문'} 3단"
            )
            self.reference_tabs.setTabData(index, key)
        self.reference_tabs.setTabToolTip(index, title)
        self.reference_tabs.setCurrentIndex(index)

    def open_cached_three_stage_popup(self, record: object) -> None:
        """저장해 둔 3단비교표를 API 호출 없이 다시 연다."""
        if not isinstance(record, dict):
            return
        row = record.get("row")
        row = row if isinstance(row, dict) else {}
        title = str(record.get("name") or row.get("title") or "3단비교")
        html = str(record.get("html") or "")
        if not html:
            return
        request = record.get("three_stage_request")
        request = request if isinstance(request, dict) else {}
        key = str(record.get("reference_key") or "")
        self._reference_popup_states[key] = {
            "kind": "three_stage",
            "title": title,
            "html": html,
            "scroll": 0,
        }
        self.three_stage_popup.reference_key = key
        self.three_stage_popup.show_content_at(title, html, QCursor.pos())
        self._remember_three_stage_popup(
            key,
            title,
            html,
            law_name=str(request.get("law_name") or title),
            label=str(request.get("label") or ""),
            short_name=str(request.get("short_name") or ""),
        )
        self.status_label.setText(f"{title} 저장된 표 열기 · API 호출 없음")

    def _reference_history_clicked(self, index: int) -> None:
        if index < 0:
            return
        key = str(self.reference_tabs.tabData(index) or "")
        state = self._reference_popup_states.get(key)
        if not state:
            return
        if state.get("kind") == "three_stage" or key.startswith("thdcmp:"):
            if (
                self.three_stage_popup.isVisible()
                and self.three_stage_popup.reference_key == key
            ):
                self.three_stage_popup.raise_()
                self.three_stage_popup.activateWindow()
                return
            anchor_top_left = self.reference_tabs.mapToGlobal(
                self.reference_tabs.rect().topLeft()
            )
            anchor_rect = QRect(anchor_top_left, self.reference_tabs.size())
            self.three_stage_popup.reference_key = key
            self.three_stage_popup.show_content_above(
                str(state["title"]),
                str(state["html"]),
                anchor_rect,
                scroll_position=int(state.get("scroll") or 0),
            )
            return
        for popup in self._all_reference_popups():
            if popup.isVisible() and popup.reference_key == key:
                popup.raise_()
                popup.activateWindow()
                return
        anchor_top_left = self.reference_tabs.mapToGlobal(
            self.reference_tabs.rect().topLeft()
        )
        anchor_rect = QRect(anchor_top_left, self.reference_tabs.size())
        pinned_mode = any(
            popup.isVisible() and popup.pin_button.isChecked()
            for popup in self._all_reference_popups()
        )
        popup = (
            self._reference_popup_for_pinned_history()
            if pinned_mode
            else self._reference_popup_for_request()
        )
        request = state.get("request")
        popup.reference_request = (
            {
                str(request_key): str(request_value or "")
                for request_key, request_value in request.items()
            }
            if isinstance(request, dict)
            else {}
        )
        popup.reference_key = key
        popup.show_content_above(
            str(state["title"]),
            str(state["html"]),
            anchor_rect,
            scroll_position=int(state.get("scroll") or 0),
        )
        self._place_reference_popup(popup)
        if pinned_mode:
            popup.pin_button.setChecked(True)

    def _close_reference_history(self, index: int) -> None:
        if index < 0:
            return
        key = str(self.reference_tabs.tabData(index) or "")
        self._reference_popup_states.pop(key, None)
        for popup in self._all_reference_popups():
            if popup.reference_key == key:
                popup.reference_key = ""
                popup._close_popup()
        if self.three_stage_popup.reference_key == key:
            self.three_stage_popup.reference_key = ""
            self.three_stage_popup._close_popup()
        self.reference_tabs.removeTab(index)

    def _show_search_results(self, payload: object) -> None:
        if not isinstance(payload, dict):
            raise ValueError("목록 응답 형식이 올바르지 않습니다.")
        rows: list[dict[str, object]] = []
        total_count = 0
        errors: list[str] = []
        if self.category_target == RESOURCE_ALL_TARGET:
            integrated_results = payload.get("integrated_results")
            if not isinstance(integrated_results, dict):
                raise ValueError("통합검색 응답 형식이 올바르지 않습니다.")
            errors.extend(str(error) for error in json_list(payload.get("errors")))
            for target in RESOURCE_CATEGORIES:
                target_payload = integrated_results.get(target)
                if not isinstance(target_payload, dict):
                    continue
                try:
                    target_rows, target_total = self._parse_resource_rows(
                        target_payload, target
                    )
                    rows.extend(target_rows)
                    total_count += target_total
                except Exception as exc:
                    errors.append(f"{RESOURCE_CATEGORIES[target]['label']}: {exc}")
            try:
                keyword_rows, keyword_total = self._parse_keyword_rows(
                    payload.get("keyword_roots"), rows
                )
                rows.extend(keyword_rows)
                total_count += keyword_total
            except Exception as exc:
                errors.append(f"연관검색ㆍ직접검색: {exc}")
            if not integrated_results and errors:
                raise ValueError("\n".join(errors))
        else:
            rows, total_count = self._parse_resource_rows(
                payload, self.category_target
            )

        saved_keys = self.law_cache.saved_keys_for_rows(rows)
        rows.sort(
            key=lambda row: (
                0
                if self.law_cache.key_for_row(row) in saved_keys
                else 1
            )
        )
        self.result_rows = rows
        self.result_filter_input.clear()
        self._sort_column = -1
        self.result_table.horizontalHeader().setSortIndicator(
            -1, Qt.SortOrder.AscendingOrder
        )
        self._render_result_rows()

        resize_adaptive_result_rows(self.result_table)
        self.result_count.setText(f"{total_count}건")
        status = f"검색 완료: 총 {total_count}건 중 {len(rows)}건을 불러왔습니다."
        if errors:
            status += f" 일부 유형 {len(errors)}건은 조회하지 못했습니다."
        self.status_label.setText(status)
        if rows:
            self.result_table.selectRow(0)
        else:
            self._replace_detail_content(text="검색 결과가 없습니다.")

    def _render_result_rows(self) -> None:
        saved_keys = self.law_cache.saved_keys_for_rows(self.result_rows)
        self._updating_cache_checks = True
        try:
            with batch_table_updates(self.result_table):
                self.result_table.setRowCount(len(self.result_rows))
                for row_index, row in enumerate(self.result_rows):
                    self.result_table.setItem(
                        row_index,
                        0,
                        self._cache_item_for_row(row, saved_keys=saved_keys),
                    )
                    values = (
                        str(row["label"]),
                        str(row["id"]),
                        str(row.get("display_name") or row["name"]),
                        str(row["related"]),
                        str(row["date"]),
                        str(row["effective"]),
                    )
                    for column, value in enumerate(values, start=1):
                        item = QTableWidgetItem(" ".join(value.split()))
                        if column in (1, 2, 5, 6):
                            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        if column in (3, 4):
                            item.setToolTip(item.text())
                        if column == 2:
                            item.setForeground(QColor("#1768aa"))
                            font = item.font()
                            font.setWeight(QFont.Weight.DemiBold)
                            item.setFont(font)
                        self.result_table.setItem(row_index, column, item)
        finally:
            self._updating_cache_checks = False

    @staticmethod
    def _law_level_priority(related: str) -> int:
        """관련 법령·기관 이름을 법 → 시행령 → 시행규칙 순으로 정렬하기 위한 우선순위."""
        text = str(related or "").strip()
        if text.endswith("시행규칙"):
            return 2
        if text.endswith("시행령"):
            return 1
        return 0

    def _sort_by_column(self, logical_index: int) -> None:
        if logical_index == 0 or not self.result_rows:
            return
        key_funcs = {
            1: lambda row: str(row.get("label") or ""),
            3: lambda row: str(row.get("name") or ""),
            4: lambda row: (
                self._law_level_priority(str(row.get("related") or "")),
                str(row.get("related") or ""),
            ),
            5: lambda row: str(row.get("date") or ""),
            6: lambda row: str(row.get("effective") or ""),
        }
        key_func = key_funcs.get(logical_index)
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
        resize_adaptive_result_rows(self.result_table)
        self.result_table.horizontalHeader().setSortIndicator(
            logical_index,
            Qt.SortOrder.AscendingOrder
            if self._sort_ascending
            else Qt.SortOrder.DescendingOrder,
        )
        if self.result_rows:
            self.result_table.selectRow(0)

    def _row_is_saved(self, row: dict[str, object]) -> bool:
        target = str(row.get("target") or "")
        return (
            self.law_cache.has(row)
            if target == "law"
            else self.law_cache.has_snapshot(row)
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

    def _is_favorite_at_row(self, row_index: int) -> bool:
        if not (0 <= row_index < len(self.result_rows)):
            return False
        return self.law_cache.is_favorite(self.result_rows[row_index])

    def _toggle_favorite_at_row(self, row_index: int) -> None:
        if not (0 <= row_index < len(self.result_rows)):
            return
        self._toggle_favorite_for_row(
            self.result_rows[row_index], select_row_index=row_index
        )

    def _toggle_favorite_for_row(
        self, row: dict[str, object], *, select_row_index: int = -1
    ) -> None:
        """결과 목록의 별표와 본문 탭의 별표가 함께 쓰는 즐겨찾기 토글."""
        wants_favorite = not self.law_cache.is_favorite(row)
        if wants_favorite and not self._row_is_saved(row):
            if self.worker and self.worker.isRunning():
                self.status_label.setText(
                    "다른 API 요청이 끝난 뒤 즐겨찾기를 설정해 주세요."
                )
                return
            # 저장본이 없으면 먼저 본문을 받아 저장한 뒤 즐겨찾기를 건다.
            self._pending_favorite_row = row
            if select_row_index >= 0:
                self.result_table.selectRow(select_row_index)
            self._request_resource_detail(row, force_api=False)
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
        self._refresh_document_tab_favorites()

    def _law_row(self, law_id: str, name: str = "") -> dict[str, object] | None:
        config = RESOURCE_CATEGORIES.get("law")
        if config is None or "detail_target" not in config:
            return None
        return {
            "target": "law",
            "id": law_id,
            "label": str(config["label"]),
            "name": name or law_id,
        }

    def is_article_favorite_by_id(
        self,
        law_id: str,
        jo: str,
        *,
        hang: str = "",
        ho: str = "",
        mok: str = "",
    ) -> bool:
        """그 법령의 그 조항호목이 이미 즐겨찾기에 있는지 알려 준다."""
        row = self._law_row(law_id)
        if row is None:
            return False
        return self.law_cache.is_article_favorite(
            row, jo, hang=hang, ho=ho, mok=mok
        )

    def add_article_favorite_by_id(
        self,
        law_id: str,
        jo: str,
        label: str,
        name: str = "",
        *,
        hang: str = "",
        ho: str = "",
        mok: str = "",
    ) -> None:
        """인용된 조항호목 하나를 즐겨찾기에 건다.

        조문 즐겨찾기는 그 법령의 저장본 안에 얹힌다. 그래서 저장본이
        없으면 본문을 먼저 받아 저장한 뒤에 걸어야 한다 — 그 대기는
        _finalize_pending_favorite가 이어받는다.
        """
        row = self._law_row(law_id, name)
        if row is None:
            self.status_label.setText("이 항목은 즐겨찾기에 걸 수 없습니다.")
            return
        if self.law_cache.is_article_favorite(
            row, jo, hang=hang, ho=ho, mok=mok
        ):
            self.status_label.setText("이미 즐겨찾기에 있는 조문입니다.")
            return
        if self._row_is_saved(row):
            if self.law_cache.set_article_favorite(
                row,
                jo,
                label,
                True,
                hang=hang,
                ho=ho,
                mok=mok,
            ):
                self.status_label.setText(f"{label}을(를) 즐겨찾기에 걸었습니다.")
            else:
                self.status_label.setText(
                    f"즐겨찾기 설정에 실패했습니다: {self.law_cache.last_error}"
                )
            self._refresh_document_tab_favorites()
            return
        if self.worker and self.worker.isRunning():
            self._pending_article_favorite = (row, jo, hang, ho, mok, label)
            self._pending_favorite_row = row
            self._article_favorite_waiting_for_worker = True
            self.status_label.setText(
                "진행 중인 API 요청이 끝나면 조문 즐겨찾기를 자동으로 추가합니다."
            )
            return
        self._pending_article_favorite = (row, jo, hang, ho, mok, label)
        self._pending_favorite_row = row
        if not self._request_resource_detail(row, force_api=False):
            self._pending_article_favorite = None
            self._pending_favorite_row = None
            self._refresh_reference_popup_favorites()

    def _resume_pending_article_favorite(self) -> None:
        """다른 API 작업 때문에 미뤄 둔 조문 즐겨찾기를 이어서 처리."""
        article = self._pending_article_favorite
        if article is None:
            self._refresh_reference_popup_favorites()
            return
        row = article[0]
        if self._row_is_saved(row):
            self._finalize_pending_favorite(row)
            return
        if self.worker and self.worker.isRunning():
            self._article_favorite_waiting_for_worker = True
            return
        if not self._request_resource_detail(row, force_api=False):
            self._pending_article_favorite = None
            self._pending_favorite_row = None
            self._refresh_reference_popup_favorites()

    def is_favorite_by_id(self, category: str, item_id: str) -> bool:
        """id만으로 이미 즐겨찾기에 걸린 법령인지 알려 준다.

        AI 대화의 즐겨찾기 단추가 "추가"인지 "이미 있음"인지 정하는 데
        쓴다. 눌러 봐야 "이미 즐겨찾기에 있습니다"를 듣는 것보다 낫다.
        """
        config = RESOURCE_CATEGORIES.get(category)
        if config is None or "detail_target" not in config:
            return False
        return bool(
            self.law_cache.is_favorite(
                {
                    "target": category,
                    "id": item_id,
                    "label": str(config["label"]),
                    "name": item_id,
                }
            )
        )

    def add_favorite_by_id(self, category: str, item_id: str, name: str) -> None:
        """검색 결과 목록에 없는 법령도 id만으로 즐겨찾기에 추가한다.

        AI 검토 대화가 검색해서 읽은 법령을 "즐겨찾기에 추가" 단추로 걸 때
        쓴다. 결과 표에 그 행이 있어야 하는 _toggle_favorite_for_row와
        달리, 최소 정보(target·id·label·name)만으로 만든 행을 그대로
        쓴다 — 저장ㆍ즐겨찾기 API는 이 네 값만 있으면 동작한다.
        """
        config = RESOURCE_CATEGORIES.get(category)
        if config is None or "detail_target" not in config:
            self.status_label.setText("이 항목은 즐겨찾기에 걸 수 없습니다.")
            return
        row: dict[str, object] = {
            "target": category,
            "id": item_id,
            "label": str(config["label"]),
            "name": name or item_id,
        }
        if self.law_cache.is_favorite(row):
            self.status_label.setText("이미 즐겨찾기에 있습니다.")
            return
        if self._row_is_saved(row):
            if self.law_cache.set_favorite(row, True):
                self.status_label.setText("즐겨찾기에 추가했습니다.")
            else:
                self.status_label.setText(
                    f"즐겨찾기 설정에 실패했습니다: {self.law_cache.last_error}"
                )
            self._refresh_document_tab_favorites()
            return
        if self.worker and self.worker.isRunning():
            self.status_label.setText(
                "다른 API 요청이 끝난 뒤 즐겨찾기를 추가해 주세요."
            )
            return
        # 저장본이 없으면 먼저 본문을 받아 저장한 뒤 즐겨찾기를 건다.
        # _show_detail이 저장을 마치면 _finalize_pending_favorite가 이어받는다.
        self._pending_favorite_row = row
        self._request_resource_detail(row, force_api=False)

    def _cache_item_for_row(
        self,
        row: dict[str, object],
        *,
        saved_keys: frozenset[str] | None = None,
    ) -> QTableWidgetItem:
        item = QTableWidgetItem()
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        # 저장 열은 체크 기능만 담당한다. 행 선택 배경이 빈 셀에 남아
        # 체크박스 오른쪽이 별도 버튼처럼 보이지 않도록 선택 대상에서 뺀다.
        flags = Qt.ItemFlag.ItemIsEnabled
        cached = (
            self.law_cache.key_for_row(row) in saved_keys
            if saved_keys is not None
            else self._row_is_saved(row)
        )
        flags |= Qt.ItemFlag.ItemIsUserCheckable
        if cached:
            item.setCheckState(Qt.CheckState.Checked)
            item.setToolTip(
                "저장된 본문입니다. 체크를 풀면 저장 본문 파일을 삭제합니다."
            )
        else:
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setToolTip("본문을 처음 열면 실행 폴더에 자동 저장됩니다.")
        item.setFlags(flags)
        return item

    def _refresh_cache_checkmarks(self) -> None:
        if not hasattr(self, "result_table"):
            return
        saved_keys = self.law_cache.saved_keys_for_rows(self.result_rows)
        self._updating_cache_checks = True
        try:
            for row_index, row in enumerate(self.result_rows):
                if row_index >= self.result_table.rowCount():
                    break
                self.result_table.setItem(
                    row_index,
                    0,
                    self._cache_item_for_row(row, saved_keys=saved_keys),
                )
        finally:
            self._updating_cache_checks = False
        self.result_table.viewport().update()

    def _finalize_pending_favorite(self, saved_row: dict[str, object]) -> None:
        pending = self._pending_favorite_row
        if pending is None:
            return
        if str(pending.get("target")) != str(saved_row.get("target")) or str(
            pending.get("id")
        ) != str(saved_row.get("id")):
            return
        self._pending_favorite_row = None
        article = self._pending_article_favorite
        self._pending_article_favorite = None
        if article is not None and str(article[0].get("id")) == str(
            saved_row.get("id")
        ):
            # 조문 즐겨찾기는 그 법령까지 함께 올린다(set_article_favorite).
            _row, jo, hang, ho, mok, label = article
            if self.law_cache.set_article_favorite(
                saved_row,
                jo,
                label,
                True,
                hang=hang,
                ho=ho,
                mok=mok,
            ):
                self.status_label.setText(
                    f"{label}을(를) 즐겨찾기에 걸었습니다."
                )
            else:
                self.status_label.setText(
                    f"즐겨찾기 설정에 실패했습니다: {self.law_cache.last_error}"
                )
        elif not self.law_cache.set_favorite(saved_row, True):
            self.status_label.setText(
                f"즐겨찾기 설정에 실패했습니다: {self.law_cache.last_error}"
            )
        self.result_table.viewport().update()
        self._refresh_document_tab_favorites()

    def _cache_check_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_cache_checks or item.column() != 0:
            return
        row_index = item.row()
        if row_index < 0 or row_index >= len(self.result_rows):
            return
        row = self.result_rows[row_index]
        cached = self._row_is_saved(row)
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
            self._refresh_cache_checkmarks()
            return
        if self.worker and self.worker.isRunning():
            self.status_label.setText(
                "다른 API 요청이 끝난 뒤 저장본 체크를 해제해 주세요."
            )
            self._refresh_cache_checkmarks()
            return
        self.result_table.selectRow(row_index)
        if not self._request_resource_detail(row, force_api=False):
            self._refresh_cache_checkmarks()

    def _parse_resource_rows(
        self, payload: dict, target: str
    ) -> tuple[list[dict[str, object]], int]:
        config = RESOURCE_CATEGORIES[target]
        search_root = payload.get(str(config["root"]))
        if not isinstance(search_root, dict):
            raise ValueError(
                f"응답에서 {config['root']} 항목을 찾지 못했습니다."
            )
        raw_items = json_list(search_root.get(str(config["item"])))
        rows: list[dict[str, object]] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            related_field = str(config.get("related", ""))
            organization = json_text(raw.get(str(config["organization"]), ""))
            related = json_text(raw.get(related_field, "")) if related_field else organization
            row = {
                "target": target,
                "label": str(config["label"]),
                "id": json_text(raw.get(str(config["id"]), "")),
                "name": json_text(raw.get(str(config["name"]), "")),
                "related": related,
                "organization": organization,
                "date": self._display_date(json_text(raw.get(str(config["date"]), ""))),
                "number": json_text(raw.get(str(config["number"]), "")),
                "effective": self._display_date(
                    json_text(raw.get(str(config.get("effective", "")), ""))
                ),
                # 법제처가 정한 공식 약칭(없는 법령은 빈 값).
                "short_name": json_text(raw.get("법령약칭명", "")),
                "raw": raw,
            }
            if row["short_name"] and row["name"]:
                self._law_short_name_cache[
                    re.sub(r"\s+", "", str(row["name"]))
                ] = str(row["short_name"])
            if row["id"] or row["name"]:
                rows.append(row)
        try:
            total_count = int(search_root.get("totalCnt", len(rows)))
        except (TypeError, ValueError):
            total_count = len(rows)
        return rows, total_count

    @staticmethod
    def _keyword_result_number(value: str) -> str:
        return str(int(value)) if value.isdigit() else value

    @classmethod
    def _keyword_result_provision(cls, node: object) -> str:
        """키워드검색 XML 한 건의 조문 표기를 단독 검색과 같게 만든다."""
        item_tag = str(getattr(node, "tag", "")).rsplit("}", 1)[-1]
        is_annex = "별표서식" in item_tag
        if is_annex:
            number = cls._keyword_result_number(_find_text(node, "별표서식번호"))
            branch = cls._keyword_result_number(
                _find_text(node, "별표서식가지번호")
            )
            title = _find_text(node, "별표서식제목")
            prefix = f"별표·서식 {number}" if number else "별표·서식"
        else:
            number = cls._keyword_result_number(_find_text(node, "조문번호"))
            branch = cls._keyword_result_number(_find_text(node, "조문가지번호"))
            title = _find_text(node, "조문제목")
            prefix = f"제{number}조" if number else "조문"
        if branch and branch != "0":
            prefix += f"의{branch}"
        return f"{prefix} {title}".strip()

    def _parse_keyword_rows(
        self, roots: object, _existing: list[dict[str, object]]
    ) -> tuple[list[dict[str, object]], int]:
        """연관검색ㆍ직접검색 응답을 통합검색 목록의 행으로 옮긴다.

        두 API의 조문 단위 결과를 단독 연관검색ㆍ직접검색과 같은 건수로
        보존한다. 같은 법령이 목록검색에 있거나 여러 조문이 검색되어도
        각각 별도 검색결과이므로 버리지 않는다. 별표ㆍ서식 항목은 이
        응답만으로 본문을 열 수 있는 일련번호를 얻지 못해 제외한다.
        """
        if not isinstance(roots, list) or not roots:
            return [], 0
        rows: list[dict[str, object]] = []
        for entry in roots:
            try:
                agency, root = entry
            except (TypeError, ValueError):
                continue
            label = KEYWORD_CATEGORY_LABELS.get(
                KEYWORD_RELATED_TARGET
                if agency.target == "aiRltLs"
                else KEYWORD_DIRECT_TARGET,
                str(agency.name),
            )
            for node in root.iter():
                if "id" not in node.attrib:
                    continue
                item_tag = str(node.tag).rsplit("}", 1)[-1]
                if "별표서식" in item_tag:
                    continue
                is_admin = item_tag.startswith("행정규칙")
                target = "admrul" if is_admin else "law"
                name = _find_text(node, "행정규칙명" if is_admin else "법령명")
                item_id = _find_text(node, "행정규칙ID" if is_admin else "법령ID")
                if not name or not item_id:
                    continue
                provision = self._keyword_result_provision(node)
                article_number = _find_text(node, "조문번호")
                article_branch = _find_text(node, "조문가지번호")
                keyword_jo = ""
                if article_number.isdigit():
                    keyword_jo = law_unit_code(
                        article_number,
                        article_branch if article_branch.isdigit() else "",
                    )
                organization = _find_text(
                    node, "발령기관명" if is_admin else "소관부처명"
                )
                rows.append(
                    {
                        "target": target,
                        "label": label,
                        "id": item_id,
                        "name": name,
                        # 내부 본문ㆍ저장 경로는 실제 법령명을 계속 쓰고,
                        # 통합 목록의 명칭 열만 조문 단위 결과로 보여 준다.
                        "display_name": (
                            provision
                            if provision not in ("조문", "별표·서식")
                            else name
                        ),
                        "related": name,
                        "organization": organization,
                        "date": self._display_date(
                            _find_text(node, "발령일자" if is_admin else "공포일자")
                        ),
                        "number": _find_text(
                            node, "발령번호" if is_admin else "공포번호"
                        ),
                        "effective": self._display_date(
                            _find_text(node, "시행일자")
                        ),
                        "short_name": "",
                        "keyword_provision": provision,
                        "keyword_jo": keyword_jo,
                        # 키워드 API의 행정규칙ID는 admrul 본문 API가
                        # 요구하는 행정규칙일련번호가 아니다. 본문 조회 전에
                        # 목록에서 일련번호를 해소해야 한다.
                        "resolve_admrul_id": is_admin,
                        "raw": {},
                    }
                )
        return rows, len(rows)

    @staticmethod
    def _display_date(value: str) -> str:
        digits = re.sub(r"\D", "", value)
        if len(digits) >= 8:
            return f"{digits[:4]}.{digits[4:6]}.{digits[6:8]}"
        return value

    def _selection_changed(self) -> None:
        row_index = self.result_table.currentRow()
        has_selection = 0 <= row_index < len(self.result_rows)
        self.detail_button.setEnabled(
            has_selection and not (self.worker and self.worker.isRunning())
        )
        if not has_selection:
            return
        # 본문을 준비하는 데 큰 법령은 100ms 안팎이 든다. 그 일을 클릭과
        # 같은 프레임에서 하면 눌린 행에 파란 띠가 뜨는 것조차 그만큼
        # 늦어 "누르고 한 박자 뒤에 반응한다"고 느끼게 된다. 선택 표시를
        # 먼저 그리게 하고 본문은 바로 다음 차례에 연다. 방향키로 목록을
        # 빠르게 훑을 때는 지나친 행을 건너뛰고 멈춘 행만 실제로 연다.
        self._pending_selection_row = row_index
        if not self._selection_open_scheduled:
            self._selection_open_scheduled = True
            QTimer.singleShot(0, self._open_pending_selection)

    def _open_pending_selection(self) -> None:
        self._selection_open_scheduled = False
        row_index = self._pending_selection_row
        self._pending_selection_row = -1
        if not 0 <= row_index < len(self.result_rows):
            return
        if row_index != self.result_table.currentRow():
            return
        row = self.result_rows[row_index]
        row_config = RESOURCE_CATEGORIES[str(row["target"])]
        has_saved_body = "detail_target" in row_config and (
            self.law_cache.has(row)
            if str(row.get("target") or "") == "law"
            else self.law_cache.has_snapshot(row)
        )
        if "detail_target" not in row_config:
            button_tooltip = "선택한 별표·서식의 다운로드·미리보기 링크를 표시합니다."
        elif has_saved_body:
            button_tooltip = "API 호출 없이 저장된 본문을 엽니다."
        else:
            button_tooltip = "선택한 항목의 본문을 조회합니다."
        self.detail_button.setText("본문\n조회")
        self.detail_button.setToolTip(button_tooltip)
        # 한 번 누른 것만으로는 열지 않는다. 목록을 훑어보려고 눌렀을
        # 뿐인데 저장해 둔 본문이 곧바로 열려 버려, 다음 항목을 보려면
        # 매번 되돌아와야 했다. 여는 것은 두 번 누르기다.
        self._show_preview(row)

    def _show_preview(self, row: dict[str, object]) -> None:
        self._activate_preview()
        is_annex = "detail_target" not in RESOURCE_CATEGORIES[str(row["target"])]
        metadata = [
            ("구분", str(row["label"])),
            ("ID", str(row["id"])),
            ("관련 법령·기관", str(row["related"])),
            ("소관기관", str(row["organization"])),
            ("공포·발령일자", str(row["date"])),
            ("공포·발령번호", str(row["number"])),
            ("시행일자", str(row["effective"])),
        ]
        if is_annex:
            note = (
                "본문 조회를 누르면 원본·PDF 다운로드 링크와 "
                "PDF 미리보기 링크를 표시합니다."
            )
        elif "detail_target" in RESOURCE_CATEGORIES[str(row["target"])]:
            note = (
                "더블클릭하면 본문 API를 호출합니다.\n"
                "저장된 본문이면 API 호출이 아닌 저장된 본문으로 열립니다.\n"
                "저장 체크를 풀면 저장된 본문 파일을 삭제합니다."
            )
        else:
            note = "본문 조회를 누르면 본문 API를 호출합니다."
        self._set_detail_document(
            str(row["name"]), metadata, [("안내", note)]
        )

    def _open_detail_expanded(self, *_args: object) -> None:
        """검색결과 더블클릭: 본문을 열고 바로 크게 보기로 전환한다."""
        row = self.result_table.currentRow()
        if row < 0 or row >= len(self.result_rows):
            return
        self.open_selected_detail()
        self._set_reading_mode(True)

    def open_selected_detail(self, *_args: object) -> None:
        row_index = self.result_table.currentRow()
        if row_index < 0 or row_index >= len(self.result_rows):
            QMessageBox.information(self, "항목 선택", "조회할 항목을 선택해 주세요.")
            return
        self._request_resource_detail(self.result_rows[row_index])

    def _request_resource_detail(
        self, row: dict[str, object], *, force_api: bool = False
    ) -> bool:
        config = RESOURCE_CATEGORIES[str(row["target"])]
        if "detail_target" not in config:
            self._show_annex_links(row)
            return True
        if str(row.get("target") or "") == "law" and not force_api:
            cached_record = self.law_cache.load_for_row(row)
            if cached_record is not None:
                self.open_cached_law(cached_record, clear_highlights=False)
                self._schedule_keyword_article_scroll(row)
                return True
        elif not force_api:
            cached_snapshot = self.law_cache.load_snapshot(row)
            if cached_snapshot is not None:
                self._open_cached_resource_snapshot(row, cached_snapshot)
                return True
        item_id = str(row["id"])
        if not item_id:
            QMessageBox.warning(self, "식별자 없음", "본문 조회 식별자를 찾지 못했습니다.")
            return False
        if force_api:
            # API 갱신을 직접 눌렀을 때는 메모리에 남아 있는 이전
            # 3단비교 결과를 재사용하지 않고 새로 확인한다.
            self._three_stage_payload_cache.pop(item_id, None)
            stale_record = self.law_cache.load_for_row(row)
            if isinstance(stale_record, dict) and "three_stage_payload" in stale_record:
                stale_row = stale_record.get("row")
                stale_payload = stale_record.get("payload")
                if isinstance(stale_row, dict) and isinstance(stale_payload, dict):
                    self.law_cache.save(stale_row, stale_payload)
        oc = self.oc_provider().strip()
        if not oc:
            prompt_oc_api_key(self)
            return False
        self.pending_row = row
        self._start_worker(
            ResourceApiWorker(
                "resource_detail",
                oc=oc,
                target=str(row["target"]),
                item_id=item_id,
                detail_target=str(config["detail_target"]),
                id_param=str(config["id_param"]),
                law_name=str(row.get("name") or ""),
                resolve_admrul_id=bool(row.get("resolve_admrul_id")),
                issue_date=str(row.get("date") or ""),
                issue_number=str(row.get("number") or ""),
                parent=self,
            ),
            (
                f"{row['label']} ID {item_id} 저장본 갱신을 위해 API 재호출 중..."
                if force_api
                else f"{row['label']} ID {item_id} 본문 조회 중..."
            ),
        )
        return True

    def _schedule_keyword_article_scroll(self, row: dict[str, object]) -> None:
        """통합 키워드 결과로 연 법령을 해당 조문 위치에 맞춘다."""
        jo = str(row.get("keyword_jo") or "")
        if str(row.get("target") or "") != "law" or not jo:
            return
        key = f"{row['target']}:{row['id'] or row['name']}"

        def scroll() -> None:
            if self._active_document_key == key:
                self.scroll_to_favorite_article(jo)

        QTimer.singleShot(0, scroll)

    def _open_cached_resource_snapshot(
        self,
        row: dict[str, object],
        record: dict[str, object],
    ) -> None:
        """행정규칙·자치법규 저장 본문을 API 호출 없이 문서 탭으로 엶."""
        self.pending_row = dict(row)
        self._open_document_tab(row, defer_restore=True)
        target = str(row.get("target") or "")
        if target == "admrul":
            cached_sections = self._cached_admrul_sections(record)
            if cached_sections:
                raw = row.get("raw")
                raw = raw if isinstance(raw, dict) else {}
                metadata = [
                    ("행정규칙일련번호", str(row.get("id") or "")),
                    ("발령일자", str(row.get("date") or "")),
                    ("발령번호", str(row.get("number") or "")),
                    ("시행일자", str(row.get("effective") or "")),
                    (
                        "소관부처",
                        str(
                            row.get("organization")
                            or row.get("related")
                            or ""
                        ),
                    ),
                    ("행정규칙종류", json_text(raw.get("행정규칙종류"))),
                ]
                self._set_detail_document(
                    str(record.get("name") or row.get("name") or "행정규칙"),
                    metadata,
                    cached_sections,
                    build_toc=True,
                    administrative_rule=True,
                )
                restored_formats = self._restore_cached_formatting(record)
                restored_memos = self._restore_cached_memos(record)
                self.status_label.setText(
                    f"{row['label']} ID {row['id']} 저장된 본문 열기"
                    " · 원문 문단 구성 자동 보정"
                    + (
                        f" · 색상 서식 {restored_formats}건 복원"
                        if restored_formats
                        else ""
                    )
                    + (
                        f" · 메모 {restored_memos}건 복원"
                        if restored_memos
                        else ""
                    )
                )
                return
        payload = record.get("detail_payload")
        if isinstance(payload, dict) and target in ("admrul", "ordin"):
            if target == "admrul":
                title, metadata, sections = self._parse_admrul_detail(payload)
            else:
                title, metadata, sections = self._parse_ordin_detail(payload)
            self._set_detail_document(
                title,
                metadata,
                sections,
                build_toc=True,
                administrative_rule=target == "admrul",
            )
            restored_formats = self._restore_cached_formatting(record)
            restored_memos = self._restore_cached_memos(record)
            self.status_label.setText(
                f"{row['label']} ID {row['id']} 저장된 본문 열기"
                + (
                    f" · 색상 서식 {restored_formats}건 복원"
                    if restored_formats
                    else ""
                )
                + (
                    f" · 메모 {restored_memos}건 복원"
                    if restored_memos
                    else ""
                )
            )
            return
        state = self._document_states[self._active_document_key]
        state.update(
            {
                "html": str(record.get("html") or ""),
                "plain_text": str(record.get("plain_text") or ""),
                "toc_entries": list(record.get("toc_entries") or []),
                "font_size": float(
                    record.get("font_size") or self.detail_font_size
                ),
                "memos": list(record.get("memos") or []),
                "scroll": 0,
            }
        )
        self._restore_document_state(self._active_document_key)
        self.status_label.setText(
            f"{row['label']} ID {row['id']} 저장된 본문 열기"
        )

    @staticmethod
    def _cached_admrul_sections(
        record: dict[str, object],
    ) -> list[tuple[str, str]]:
        """저장 화면의 평문에서 행정규칙 섹션을 꺼내 문단 구조를 복원."""
        try:
            parse_version = int(record.get("administrative_rule_parse_version") or 0)
        except (TypeError, ValueError):
            parse_version = 0
        stored_sections = record.get("administrative_rule_sections")
        if (
            parse_version >= ADMIN_RULE_PARSE_VERSION
            and isinstance(stored_sections, list)
        ):
            sections = []
            for section in stored_sections:
                if not isinstance(section, dict):
                    continue
                label = str(section.get("label") or "").strip()
                value = str(section.get("value") or "").strip()
                if label in ("조문", "부칙") and value:
                    # 구버전 캐시라도 화면에서 다시 뽑은 평문보다 API 원문
                    # 섹션의 구조가 훨씬 정확하다. 최신 파싱 규칙을 원문
                    # 섹션에 재적용해 장·절·항목 경계를 복구한다.
                    sections.append(
                        (
                            label,
                            # 동일 버전으로 저장된 캐시에도 이전 실행 중
                            # 평탄화된 줄이 남을 수 있다. 파서는 반복 적용해도
                            # 같은 결과가 되도록 관리하므로 항상 재정규화한다.
                            normalize_admin_rule_text(value),
                        )
                    )
            if sections:
                return sections

        # 구버전 저장본은 완성 화면의 평문만 갖고 있다. 지침류 전용
        # 참조번호 병합 규칙을 다시 적용해 잘못 갈라진 줄을 복구한다.
        plain_text = str(record.get("plain_text") or "")
        matches = list(
            re.finditer(r"(?m)^\[([^\]\r\n]+)\]\s*$", plain_text)
        )
        sections: list[tuple[str, str]] = []
        for index, match in enumerate(matches):
            label = match.group(1).strip()
            if label not in ("조문", "부칙"):
                continue
            end = (
                matches[index + 1].start()
                if index + 1 < len(matches)
                else len(plain_text)
            )
            value = plain_text[match.end() : end].strip()
            if value:
                sections.append((label, normalize_admin_rule_text(value)))
        return sections

    def _show_annex_links(self, row: dict[str, object]) -> None:
        self._open_document_tab(row, defer_restore=True)
        self._populate_toc([])
        raw = row["raw"] if isinstance(row.get("raw"), dict) else {}
        file_url = full_law_url(raw.get("별표서식파일링크"))
        pdf_url = full_law_url(raw.get("별표서식PDF파일링크"))
        links = [
            ("원본 첨부파일 다운로드", file_url),
            ("PDF 다운로드", pdf_url),
            (
                "PDF 미리보기",
                f"pdfpreview:{quote(pdf_url, safe='')}" if pdf_url else "",
            ),
        ]
        metadata = [
            ("구분", str(row["label"])),
            ("ID", str(row["id"])),
            ("관련 법령·기관", str(row["related"])),
            ("소관기관", str(row["organization"])),
            ("공포·발령일자", str(row["date"])),
            ("공포·발령번호", str(row["number"])),
            ("별표종류", json_text(raw.get("별표종류", ""))),
        ]
        html_parts, plain_parts = self._detail_header(str(row["name"]), metadata)
        html_parts.append("<h2>별표·서식 링크</h2>")
        available = False
        for label, url in links:
            if not url:
                continue
            available = True
            html_parts.append(
                '<div class="link-item" style="margin:0 0 10px 0;">'
                f'<a href="{escape(url)}">{escape(label)}</a></div>'
            )
            plain_parts.append(f"{label}: {url}")
        if not available:
            html_parts.append('<div class="content">제공된 링크가 없습니다.</div>')
            plain_parts.append("제공된 링크가 없습니다.")
        self._commit_detail(html_parts, plain_parts)
        self._set_three_stage_articles([])
        self._save_active_document_state()
        state = self._document_states.get(
            self._active_document_key, self._empty_document_state()
        )
        status = f"{row['label']} 링크 표시 완료"
        if self.law_cache.save_snapshot(
            dict(row),
            html=str(state.get("html") or ""),
            plain_text=self.current_detail_text,
            extra={
                "toc_entries": list(state.get("toc_entries") or []),
                "font_size": float(
                    state.get("font_size") or self.detail_font_size
                ),
                "memos": list(state.get("memos") or []),
            },
        ):
            status += " · 실행 폴더에 저장됨"
            self._refresh_cache_checkmarks()
            self._finalize_pending_favorite(dict(row))
        else:
            status += f" · 저장 실패: {self.law_cache.last_error}"
        self.status_label.setText(status)

    def _show_detail(self, payload: object, *, save_cache: bool = True) -> None:
        if not isinstance(payload, dict) or not self.pending_row:
            raise ValueError("본문 응답 형식이 올바르지 않습니다.")
        target = str(self.pending_row["target"])
        if target == "law":
            title, metadata, sections = self._parse_law_detail(payload)
        elif target == "admrul":
            title, metadata, sections = self._parse_admrul_detail(payload)
        elif target == "ordin":
            title, metadata, sections = self._parse_ordin_detail(payload)
        else:
            raise ValueError("이 유형은 본문 조회를 지원하지 않습니다.")
        self._open_document_tab(self.pending_row, defer_restore=True)
        self._set_detail_document(
            title,
            metadata,
            sections,
            build_toc=True,
            administrative_rule=target == "admrul",
        )
        status = (
            f"{self.pending_row['label']} ID {self.pending_row['id']} 본문 조회 완료"
        )
        if target == "law" and save_cache:
            # 지금 화면이 정말 이 행의 것일 때만 화면까지 함께 저장한다.
            # 어긋나면 원문만 저장하고 화면은 다음에 열 때 다시 그린다.
            fresh_snapshot = self._active_law_render_snapshot()
            if not self._snapshot_belongs_to(
                fresh_snapshot, dict(self.pending_row)
            ):
                fresh_snapshot = {}
            if self.law_cache.save(
                dict(self.pending_row),
                payload,
                snapshot=fresh_snapshot,
            ):
                status += " · 실행 폴더에 저장됨"
            else:
                status += f" · 저장 실패: {self.law_cache.last_error}"
        elif target in ("admrul", "ordin") and save_cache:
            self._save_active_document_state()
            state = self._document_states.get(
                self._active_document_key, self._empty_document_state()
            )
            extra = {
                "toc_entries": list(state.get("toc_entries") or []),
                "font_size": float(
                    state.get("font_size") or self.detail_font_size
                ),
                "memos": list(state.get("memos") or []),
            }
            if target == "admrul":
                # QTextDocument에서 다시 뽑은 평문은 문단 경계를 잃을 수
                # 있으므로, 수립지침류는 정규화된 원문 섹션도 함께 보관한다.
                extra.update(
                    {
                        "administrative_rule_parse_version": (
                            ADMIN_RULE_PARSE_VERSION
                        ),
                        "administrative_rule_sections": [
                            {"label": str(label), "value": str(value)}
                            for label, value in sections
                            if str(value or "")
                        ],
                    }
                )
            if self.law_cache.save_snapshot(
                dict(self.pending_row),
                html=str(state.get("html") or ""),
                plain_text=self.current_detail_text,
                extra=extra,
            ):
                status += " · 실행 폴더에 저장됨"
            else:
                status += f" · 저장 실패: {self.law_cache.last_error}"
        self.status_label.setText(status)
        self._finalize_pending_favorite(dict(self.pending_row))
        self._schedule_keyword_article_scroll(self.pending_row)

    # 저장 화면이 그 법령 "전문"인지 재는 최소 기준. 조문 수가 이보다
    # 적은 법령은 애초에 비교가 의미 없어 통과시킨다.
    _SNAPSHOT_ARTICLE_FLOOR = 4
    # 전문이라면 조문 대부분이 들어 있다. 절반은 아주 너그러운 선으로,
    # 멀쩡한 화면을 잘못 버리지 않으면서 조문 한두 개짜리 화면은 확실히
    # 걸러낸다.
    _SNAPSHOT_COVERAGE_RATIO = 0.5

    @staticmethod
    def _article_labels(text: str) -> set[str]:
        """본문에서 조 번호 표지만 모은다. 가지번호(제3조의2)도 구분한다."""
        return set(re.findall(r"제\d+조(?:의\d+)?", str(text or "")))

    @classmethod
    def _payload_article_labels(cls, payload: object) -> set[str]:
        """저장된 법령 원문 JSON이 담고 있는 조 번호."""
        if not isinstance(payload, dict):
            return set()
        law = payload.get("법령", payload)
        if not isinstance(law, dict):
            return set()
        units = law.get("조문", {})
        units = units.get("조문단위") if isinstance(units, dict) else units
        labels: set[str] = set()
        for unit in json_list(units):
            if not isinstance(unit, dict):
                continue
            labels |= cls._article_labels(json_text(unit.get("조문내용")))
        return labels

    @classmethod
    def _snapshot_covers_payload(
        cls, plain_text: str, payload: object
    ) -> bool:
        """저장 화면이 원문의 조문을 대부분 담고 있는지 본다.

        3단비교 링크 보강이 조문 하나짜리 화면을 법령 전문 저장 파일에
        덮어쓴 적이 있다. 그러면 첫 줄은 여전히 법령 이름이라
        ``_snapshot_matches_row``를 통과하고, 즐겨찾기로 열 때마다
        제1조만 뜬 채 스스로 낫지 않았다. 조문 수까지 봐야 걸린다.
        """
        expected = cls._payload_article_labels(payload)
        if len(expected) < cls._SNAPSHOT_ARTICLE_FLOOR:
            return True
        covered = cls._article_labels(plain_text) & expected
        return len(covered) >= len(expected) * cls._SNAPSHOT_COVERAGE_RATIO

    @staticmethod
    def _snapshot_matches_row(
        row: dict[str, object], plain_text: str
    ) -> bool:
        """저장해 둔 완성 화면이 정말 이 법령의 것인지 본다.

        완성 화면의 첫 줄은 언제나 법령 제목이다. 예전 판이 다른 법령의
        화면을 이 파일에 써 넣은 적이 있어, 그대로 믿고 그리면 즐겨찾기로
        열 때마다 엉뚱한 본문이 떴다. 어긋나면 원문에서 다시 그린다.
        """
        name = re.sub(r"\s+", "", str(row.get("name") or ""))
        heading = re.sub(
            r"\s+", "", str(plain_text or "").strip().split(chr(10))[0]
        )
        # 첫 줄이 제목이라고 보기 어려울 만큼 짧으면 판단하지 않는다.
        # 애매한 것을 어긋났다고 몰아붙이면 멀쩡한 저장 화면까지 버리고
        # 매번 원문에서 다시 그리게 된다.
        if not name or len(heading) < 6:
            return True
        return name in heading or heading in name

    def _restore_cached_law_render(
        self,
        row: dict[str, object],
        record: dict[str, object],
    ) -> bool:
        """저장해 둔 완성 HTML·목차를 원문 재파싱 없이 복원."""
        try:
            version = int(record.get("render_snapshot_version") or 0)
            source_font_size = float(
                record.get("rendered_font_size") or self.detail_font_size
            )
        except (TypeError, ValueError):
            return False
        html = record.get("rendered_html")
        plain_text = record.get("rendered_plain_text")
        toc_entries = record.get("rendered_toc_entries")
        articles = record.get("rendered_three_stage_articles")
        snapshot_terms = tuple(
            str(term)
            for term in record.get("render_highlight_terms", []) or []
            if str(term)
        )
        if (
            version != LAW_RENDER_SNAPSHOT_VERSION
            or not isinstance(html, str)
            or not html
            or not isinstance(plain_text, str)
            or not isinstance(toc_entries, list)
            or not isinstance(articles, list)
            or snapshot_terms != tuple(self.highlight_terms)
            or not ResourceSearchTab._snapshot_matches_row(row, plain_text)
            or not ResourceSearchTab._snapshot_covers_payload(
                plain_text, record.get("payload")
            )
        ):
            return False

        key = f"{row['target']}:{row['id'] or row['name']}"
        previous_state = self._document_states.get(key)
        had_rendered_document = (
            isinstance(
                previous_state.get("document")
                if isinstance(previous_state, dict)
                else None,
                QTextDocument,
            )
            and bool(
                previous_state.get("plain_text")
                if isinstance(previous_state, dict)
                else ""
            )
        )
        self._open_document_tab(row, defer_restore=True)
        state = self._document_states[self._active_document_key]
        # 검색 결과의 저장 본문을 다시 클릭해도 이미 열어 둔 탭이라면
        # 마지막으로 읽던 위치를 유지한다. 이전에는 저장 HTML을 복원할
        # 때마다 scroll을 0으로 덮어써서 탭을 오갈 때 항상 맨 위로
        # 돌아갔다. 새 탭의 빈 상태는 원래 값이 0이므로 별도 처리가
        # 필요하지 않다.
        preserved_scroll = int(state.get("scroll", 0) or 0)
        state.update(
            {
                "html": html,
                "source_html": html,
                "prefer_source_html": True,
                "plain_text": plain_text,
                "toc_entries": list(toc_entries),
                "font_size": source_font_size,
                "three_stage_articles": [
                    dict(article)
                    for article in articles
                    if isinstance(article, dict)
                ],
                "render_highlight_terms": list(snapshot_terms),
                # 기존 QTextDocument를 재사용하는 빠른 경로에서도 아래 상태가
                # 그대로 사용된다. 여기서 빈 목록을 넣으면 검색 후 크게 보기로
                # 전환할 때 저장 파일의 메모 띠지가 모두 사라진다.
                "memos": self._cached_memos_for_state(record),
                "scroll": preserved_scroll,
            }
        )
        if not had_rendered_document:
            # defer_restore가 탭 간 QTextDocument 공유를 막으려고 먼저
            # 연결한 빈 문서는 렌더링 완료 문서가 아니다. 그대로 두면
            # _restore_document_state가 저장 HTML을 불러오지 않고 빈
            # 문서를 재사용하므로 여기서 실제 복원 대상으로 되돌린다.
            state["document"] = None
        self._restore_document_state(self._active_document_key)
        self._queue_three_stage_link_request(
            str(record.get("name") or row.get("name") or "법령")
        )
        return True

    def open_cached_law(
        self,
        record: dict[str, object],
        *,
        clear_highlights: bool = True,
    ) -> None:
        """열람내역의 로컬 JSON을 API 호출 없이 본문 탭으로 엶."""
        row = record.get("row")
        payload = record.get("payload")
        if not isinstance(row, dict) or not isinstance(payload, dict):
            raise ValueError("저장된 법령 파일에 본문 정보가 없습니다.")
        self.pending_row = dict(row)
        legacy_three_stage = record.get("three_stage_payload")
        if isinstance(legacy_three_stage, dict):
            # 이전 구현이 큰 3단비교 원문을 법률 JSON 안에 합친 경우
            # 첫 화면이 뜬 뒤 제거한다. 본문에 필요한 조문별 연결정보는
            # rendered_three_stage_articles 스냅샷에 따로 남아 있다.
            QTimer.singleShot(
                500,
                lambda saved_row=dict(row): self.law_cache.update_snapshot(
                    saved_row,
                    {},
                    remove=("three_stage_payload",),
                ),
            )
        if clear_highlights:
            self.highlight_terms = ()
        key = f"{row['target']}:{row['id'] or row['name']}"
        state = self._document_states.get(key)
        rendered_plain_text = record.get("rendered_plain_text")
        reuse_current_document = (
            key == self._active_document_key
            and self._document_tab_index(key) >= 0
            and isinstance(state, dict)
            and bool(self.current_detail_text)
            and not list(state.get("render_highlight_terms", []) or [])
            and isinstance(rendered_plain_text, str)
            and rendered_plain_text == str(state.get("plain_text") or "")
        )
        if reuse_current_document:
            # 즐겨찾기 화면을 닫아도 본문 QTextDocument는 그대로 살아 있다.
            # 같은 법령을 다시 열 때 저장 HTML을 setHtml()로 재배치하면 큰 법령일수록
            # 수백 ms가 들고, 숨겨진 페이지의 이전 폭으로 잠시 줄바꿈되는 화면도 보인다.
            self._open_document_tab(row)
            self._queue_three_stage_link_request(
                str(record.get("name") or row.get("name") or "법령")
            )
            self.status_label.setText(
                f"{row.get('name', '법령')} 저장 본문 다시 열기 완료 · 기존 화면 재사용"
            )
            return

        existing_state = self._document_states.get(key)
        had_rendered_document = isinstance(
            existing_state.get("document") if isinstance(existing_state, dict) else None,
            QTextDocument,
        )
        restored_render = self._restore_cached_law_render(row, record)
        if not restored_render:
            self._show_detail(payload, save_cache=False)
            snapshot = self._active_law_render_snapshot()
            if snapshot.get("rendered_html") and self._snapshot_belongs_to(
                snapshot, row
            ):
                self.law_cache.update_snapshot(row, snapshot)
        if had_rendered_document:
            restored_formats = 0
            restored_memos = len(
                list(existing_state.get("memos", []) or [])
            ) if isinstance(existing_state, dict) else 0
        else:
            restored_formats = self._restore_cached_formatting(record)
            restored_memos = self._restore_cached_memos(record)
        self.status_label.setText(
            f"{row.get('name', '법령')} 저장 본문 열기 완료 · API 호출 없음"
            + (
                f" · 색상 서식 {restored_formats}건 복원"
                if restored_formats
                else ""
            )
            + (f" · 메모 {restored_memos}건 복원" if restored_memos else "")
        )

    def open_cached_favorite_article(
        self,
        record: dict[str, object],
        unit: dict[str, object],
    ) -> None:
        """저장 전문에서 선택한 조항호목만 뽑아 본문 화면으로 연다."""
        source_row = record.get("row")
        payload = record.get("payload")
        if not isinstance(source_row, dict) or not isinstance(payload, dict):
            raise ValueError("저장된 법령 본문을 찾지 못했습니다.")
        jo = str(unit.get("jo") or "")
        hang = str(unit.get("hang") or "")
        ho = str(unit.get("ho") or "")
        mok = str(unit.get("mok") or "")
        article_text = extract_law_article(payload, jo, hang, ho, mok)
        if not article_text:
            raise ValueError("저장된 본문에서 선택한 조항호목을 찾지 못했습니다.")
        original_pending_row = self.pending_row
        self.pending_row = dict(source_row)
        try:
            title, metadata, _sections = self._parse_law_detail(payload)
        finally:
            self.pending_row = original_pending_row
        unit_label = self._law_reference_label(jo, hang, ho, mok)
        tab_row = {
            "target": "law_article",
            "id": ":".join(
                (
                    str(source_row.get("id") or ""),
                    jo,
                    hang,
                    ho,
                    mok,
                )
            ),
            "label": "조항호목",
            "name": f"{title} {unit_label}".strip(),
            "source_row": dict(source_row),
            "favorite_unit": dict(unit),
        }
        self._open_document_tab(tab_row, defer_restore=True)
        self._set_detail_document(
            title,
            metadata,
            [("조문내용", article_text)],
            build_toc=True,
        )
        self.status_label.setText(
            f"{tab_row['name']} 저장 본문 열기 완료 · API 호출 없음"
        )

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
        if restored:
            self._save_active_document_state()
        return restored

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
        if restored:
            self._save_active_document_state()
        return restored

    def _parse_law_detail(self, data: dict) -> tuple[str, list, list]:
        law = data.get("법령")
        if not isinstance(law, dict):
            raise ValueError("응답에서 법령 본문을 찾지 못했습니다.")
        info = law.get("기본정보", {})
        if not isinstance(info, dict):
            info = {}
        title = json_text(info.get("법령명_한글")) or str(self.pending_row["name"])
        metadata = [
            ("법령ID", json_text(info.get("법령ID")) or str(self.pending_row["id"])),
            ("공포일자", self._display_date(json_text(info.get("공포일자")))),
            ("공포번호", json_text(info.get("공포번호"))),
            ("시행일자", self._display_date(json_text(info.get("시행일자")))),
            ("소관부처", json_text(info.get("소관부처"))),
        ]
        units = law.get("조문", {})
        units = units.get("조문단위") if isinstance(units, dict) else []
        body_parts: list[str] = []
        for unit in json_list(units):
            if not isinstance(unit, dict):
                continue
            content = json_text(unit.get("조문내용"))
            if content:
                body_parts.append(content)
            for paragraph in json_list(unit.get("항")):
                self._append_law_children(paragraph, body_parts)
        return title, metadata, [("조문", "\n".join(body_parts))]

    def _append_law_children(self, node: object, output: list[str]) -> None:
        if not isinstance(node, dict):
            return
        content = json_text(
            node.get("항내용") or node.get("호내용") or node.get("목내용")
        )
        if content:
            output.append(content)
        for key in ("호", "목"):
            for child in json_list(node.get(key)):
                self._append_law_children(child, output)

    def _parse_admrul_detail(self, data: dict) -> tuple[str, list, list]:
        service = data.get("AdmRulService")
        if not isinstance(service, dict):
            raise ValueError("응답에서 행정규칙 본문을 찾지 못했습니다.")
        info = service.get("행정규칙기본정보", {})
        if not isinstance(info, dict):
            info = {}
        title = json_text(info.get("행정규칙명")) or str(self.pending_row["name"])
        metadata = [
            ("행정규칙일련번호", str(self.pending_row["id"])),
            ("발령일자", self._display_date(json_text(info.get("발령일자")))),
            ("발령번호", json_text(info.get("발령번호"))),
            ("시행일자", self._display_date(json_text(info.get("시행일자")))),
            ("소관부처", json_text(info.get("소관부처명"))),
            ("행정규칙종류", json_text(info.get("행정규칙종류"))),
        ]
        sections = [
            (
                "조문",
                normalize_admin_rule_text(
                    json_text(service.get("조문내용"))
                ),
            )
        ]
        appendix = json_text(service.get("부칙"))
        if appendix:
            sections.append(("부칙", normalize_admin_rule_text(appendix)))
        return title, metadata, sections

    def _parse_ordin_detail(self, data: dict) -> tuple[str, list, list]:
        service = data.get("LawService")
        if not isinstance(service, dict):
            raise ValueError("응답에서 자치법규 본문을 찾지 못했습니다.")
        info = service.get("자치법규기본정보", {})
        if not isinstance(info, dict):
            info = {}
        title = json_text(info.get("자치법규명")) or str(self.pending_row["name"])
        metadata = [
            ("자치법규일련번호", str(self.pending_row["id"])),
            ("지자체", json_text(info.get("지자체기관명"))),
            ("공포일자", self._display_date(json_text(info.get("공포일자")))),
            ("공포번호", json_text(info.get("공포번호"))),
            ("시행일자", self._display_date(json_text(info.get("시행일자")))),
        ]
        articles = service.get("조문", {})
        articles = articles.get("조") if isinstance(articles, dict) else []
        body = "\n".join(
            json_text(article.get("조내용"))
            for article in json_list(articles)
            if isinstance(article, dict) and json_text(article.get("조내용"))
        )
        return title, metadata, [("조문", body)]

    @property
    def detail_highlight_terms(self) -> tuple[str, ...]:
        """본문에 넣을 검색어 음영.

        법령·행정규칙·자치법규는 목록에서 법령을 고른 뒤 전문을 읽는
        방식이라, 검색어가 본문 곳곳에 칠해지면 오히려 읽기 어렵다.
        음영은 검색 결과 목록에만 남기고 본문에는 넣지 않는다.
        """
        return ()

    def _detail_header(self, title: str, metadata: list) -> tuple[list[str], list[str]]:
        return detail_document_header(
            title, metadata, self.detail_highlight_terms
        )

    def _popup_detail_header(self, title: str, metadata: list) -> list[str]:
        """조문 팝업용 작은 제목과 3칸×2줄 기본정보 헤더."""
        html_parts = [
            "<style>",
            "body { font-family:'Malgun Gothic'; font-weight:400; "
            "color:#172033; line-height:1.65; margin:0; }",
            ".popup-law-title { font-family:'Malgun Gothic'; font-size:14px; "
            "font-weight:700; color:#173b63; margin:0 0 7px 0; }",
            ".meta { background:#f3f7fb; border:1px solid #cfdcea; "
            "border-radius:6px; padding:8px 10px; margin-bottom:11px; }",
            ".meta table { width:100%; border-collapse:collapse; "
            "table-layout:fixed; }",
            ".meta td { width:33.33%; color:#172033; font-size:13px; "
            "font-weight:400; padding:4px 6px; white-space:nowrap; }",
            ".meta-label { color:#3d4c60; font-weight:700; "
            "margin-right:5px; }",
            ".popup-section-title { font-family:'Malgun Gothic'; color:#1768aa; "
            "font-size:15px; font-weight:700; border-bottom:1px solid #dbeaf7; "
            "padding-bottom:4px; margin:11px 0 7px 0; }",
            ".content { font-family:'Malgun Gothic'; font-weight:400; "
            "font-size:13px; }",
            ".paragraph { margin:0 0 7px 0; }",
            ".bullet { margin:0 0 5px 0; border-collapse:collapse; }",
            ".bullet-marker { font-weight:400; padding:0; }",
            ".bullet-text { font-weight:400; padding:0; }",
            "a { color:#1768aa; font-weight:600; text-decoration:none; }",
            "</style>",
            '<div class="popup-law-title">'
            f"{highlight_html_text(title, self.detail_highlight_terms)}</div>",
            '<div class="meta"><table cellspacing="0" cellpadding="0">',
        ]
        visible_metadata = [
            (str(label), str(value or ""))
            for label, value in metadata
            if str(value or "")
        ]
        for offset in range(0, len(visible_metadata), 3):
            html_parts.append("<tr>")
            for label, value in visible_metadata[offset : offset + 3]:
                html_parts.append(
                    '<td><span class="meta-label">'
                    f"{escape(label)}</span>"
                    "&nbsp;"
                    f"{highlight_html_text(value, self.detail_highlight_terms)}</td>"
                )
            for _unused in range(3 - len(visible_metadata[offset : offset + 3])):
                html_parts.append("<td></td>")
            html_parts.append("</tr>")
        html_parts.append("</table></div>")
        return html_parts

    def _set_detail_document(
        self,
        title: str,
        metadata: list,
        sections: list,
        *,
        build_toc: bool = False,
        administrative_rule: bool = False,
    ) -> None:
        html_parts, plain_parts = self._detail_header(title, metadata)
        toc_entries: list[tuple[int, str, str]] = []
        is_law_document = (
            build_toc
            and isinstance(self.pending_row, dict)
            and self.pending_row.get("target") in ("law", "law_article")
        )
        current_law_id = (
            str(self.pending_row.get("law_id") or self.pending_row.get("id") or "")
            if is_law_document
            else ""
        )
        for section_index, (label, value) in enumerate(sections):
            value = str(value or "")
            if not value:
                continue
            html_parts.append(f"<h2>{escape(str(label))}</h2>")
            section_html = body_to_html(
                value,
                self.detail_highlight_terms,
                toc_entries=toc_entries if build_toc else None,
                anchor_prefix=f"toc-{section_index}",
                current_law_name=title if is_law_document else "",
                current_law_id=current_law_id,
                use_api_links=True,
                administrative_rule=administrative_rule,
                administrative_rule_normalized=administrative_rule,
            )
            html_parts.append(f'<div class="content">{section_html}</div>')
            plain_parts.extend(("", f"[{label}]", value))
        three_stage_articles: list[dict[str, object]] = []
        if is_law_document and current_law_id:
            for depth, label, anchor in toc_entries:
                if depth != 4:
                    continue
                unit_match = LAW_UNIT_REFERENCE_PATTERN.match(label)
                if unit_match is None:
                    continue
                three_stage_articles.append(
                    {
                        "anchor": anchor,
                        "label": label,
                        "jo": law_unit_code(
                            unit_match.group("jo"),
                            unit_match.group("jo_branch") or "",
                        ),
                        "law_id": current_law_id,
                        "law_name": title,
                    }
                )
        # 3단비교 버튼 자리를 위한 본문 오른쪽 여백을 목차를 채운 뒤에
        # 적용하면, 본문이 일단 여백 없이 넓게 한 번 그려졌다가 여백이
        # 좁아지며 다시 줄바꿈되는 게 화면에 비친다. 화면 갱신을 잠근
        # 채로 내용을 넣고 여백부터 맞춘 뒤, 남은 작업을 끝내고 나서야
        # 다시 그리게 한다.
        self.detail_view.setUpdatesEnabled(False)
        try:
            self._commit_detail(html_parts, plain_parts)
            self._set_three_stage_articles(three_stage_articles)
            self._populate_toc(toc_entries)
        finally:
            self.detail_view.document().size()
            self.detail_view.setUpdatesEnabled(True)
            self.detail_view.viewport().update()
        self._save_active_document_state()
        self._queue_three_stage_link_request(title)

    def _commit_detail(self, html_parts: list[str], plain_parts: list[str]) -> None:
        rendered_html = "".join(html_parts)
        self._replace_detail_content(html=rendered_html)
        state = self._document_states.get(self._active_document_key)
        if isinstance(state, dict):
            state["source_html"] = rendered_html
        self.current_detail_text = "\n".join(plain_parts)
        self.copy_button.setEnabled(bool(self.current_detail_text))

    def copy_detail(self) -> None:
        if not self.current_detail_text:
            return
        QApplication.clipboard().setText(self.current_detail_text)
        self.status_label.setText("본문 정보를 클립보드에 복사했습니다.")
