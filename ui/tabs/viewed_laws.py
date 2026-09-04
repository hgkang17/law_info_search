"""저장한 본문과 즐겨찾기 목록 화면."""

from __future__ import annotations

from ui.assets import (
    FAVORITE_PLUS_ICON_PATH,
)
from ui.widgets import (
    DropdownComboBox,
    FavoriteCategoryTree,
    FAVORITE_PROJECT_MIME,
)
from storage.cache import LawDocumentCache
from storage.paths import (
    ANNEX_FILE_CACHE_DIR,
    LAW_REFERENCE_CACHE_DIR,
    SEARCH_RESULT_CACHE_DIR,
)
from PySide6.QtCore import QSettings, QSize, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QDesktopServices, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import QAbstractItemView, QCheckBox, QFrame, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QSplitter, QStyle, QTabBar, QTableWidget, QTableWidgetItem, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget
import json
import re
import uuid
from pathlib import Path
from molit_cgm_expc_api import AGENCY_BY_TARGET


class FavoriteProjectTabBar(QTabBar):
    """프로젝트 전환과 즐겨찾기 복사 드롭을 함께 받는 탭 띠."""

    favoriteDropped = Signal(str, object)

    def _drop_project_id(self, position) -> str:
        index = self.tabAt(position)
        project_id = str(self.tabData(index) or "") if index >= 0 else ""
        return (
            ""
            if project_id == ViewedLawsTab.COMMON_FAVORITES_VIEW_ID
            else project_id
        )

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(FAVORITE_PROJECT_MIME):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if (
            event.mimeData().hasFormat(FAVORITE_PROJECT_MIME)
            and self._drop_project_id(event.position().toPoint())
        ):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event) -> None:
        project_id = self._drop_project_id(event.position().toPoint())
        if not project_id or not event.mimeData().hasFormat(FAVORITE_PROJECT_MIME):
            event.ignore()
            return
        try:
            payloads = json.loads(
                bytes(event.mimeData().data(FAVORITE_PROJECT_MIME)).decode("utf-8")
            )
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            event.ignore()
            return
        if not isinstance(payloads, list):
            event.ignore()
            return
        self.favoriteDropped.emit(project_id, payloads)
        event.acceptProposedAction()


class ViewedLawsTab(QWidget):
    """실행 폴더에 저장된 내역을 빠르게 다시 여는 목록."""

    openRequested = Signal(object)
    searchRequested = Signal(str, str)
    allCachesDeleted = Signal()
    FAVORITE_CATEGORIES = (
        ("law", "법령검색"),
        ("article", "조항호목"),
        ("annex", "별표·서식"),
        ("central", "중앙부처\n질의회신"),
        ("expc", "법령해석례"),
        ("prec", "판례검색"),
    )
    FAVORITE_FOLDER_SETTINGS_KEY = "favorite_folder_tree_v2"
    FAVORITE_FOLDER_LEGACY_SETTINGS_KEY = "favorite_folder_tree_v1"
    FAVORITE_PROJECTS_SETTINGS_KEY = "favorite_projects_v1"
    # 처음 만들어 두는 프로젝트 이름. 이름을 붙이기 전이라는 뜻이므로
    # "기본 프로젝트"보다 "제목 없음"이 실제에 가깝다.
    DEFAULT_PROJECT_NAME = "제목 없음"
    LEGACY_DEFAULT_PROJECT_NAME = "기본 프로젝트"
    FAVORITE_ACTIVE_PROJECT_KEY = "favorite_active_project_v1"
    COMMON_FAVORITES_VIEW_ID = "__common_favorites__"
    FAVORITE_UNION_VIEW_KEY = "favorite_union_view_v1"
    FAVORITE_VISIBLE_CATEGORIES_KEY = "favorite_visible_categories"
    FAVORITE_VISIBLE_CATEGORIES_VERSION_KEY = (
        "favorite_visible_categories_version"
    )
    FAVORITE_VISIBLE_CATEGORIES_VERSION = 2
    FAVORITE_KIND_ROLE = int(Qt.ItemDataRole.UserRole) + 1
    # 조문 즐겨찾기 줄이 가리키는 조 번호.
    FAVORITE_ARTICLE_ROLE = int(Qt.ItemDataRole.UserRole) + 4
    FAVORITE_UNIT_ROLE = int(Qt.ItemDataRole.UserRole) + 5
    FAVORITE_PROJECT_IDS_ROLE = int(Qt.ItemDataRole.UserRole) + 6
    FAVORITE_FOLDER_ID_ROLE = int(Qt.ItemDataRole.UserRole) + 2
    FAVORITE_CATEGORY_ROLE = int(Qt.ItemDataRole.UserRole) + 3

    def __init__(
        self,
        law_cache: LawDocumentCache,
        parent=None,
        *,
        favorites_only: bool = False,
        settings: QSettings | None = None,
    ) -> None:
        super().__init__(parent)
        self.law_cache = law_cache
        self.favorites_only = favorites_only
        self.settings = settings
        self.records: list[dict[str, object]] = []
        # 목록을 다시 채우는 중에는 선택 변경으로 본문을 열지 않는다.
        self._populating = False
        self.favorite_category_checks: dict[str, QCheckBox] = {}
        self.favorite_category_cards: dict[str, QFrame] = {}
        self.favorite_projects = self._load_favorite_projects()
        self.active_favorite_project = self._load_active_favorite_project()
        self.union_check: QCheckBox | None = None
        self.union_panel: QWidget | None = None
        self.union_trees: dict[str, FavoriteCategoryTree] = {}
        self.union_cards: dict[str, QWidget] = {}
        self.union_splitter: QSplitter | None = None
        self.union_tree: FavoriteCategoryTree | None = None
        self.favorite_body_splitter: QSplitter | None = None
        self._syncing_union_widths = False
        self.law_cache.set_active_favorite_project(
            self.active_favorite_project
        )

        root = QVBoxLayout(self)
        # 왼쪽ㆍ오른쪽과 같은 12px을 위에도 준다. 저장내역만 0으로 두었더니
        # 안내 카드가 창 천장에 붙어 다른 화면과 시작선이 어긋났다.
        root.setContentsMargins(12, 12, 12, 0)
        root.setSpacing(12)

        # 즐겨찾기 화면은 왼쪽 메뉴에 이미 같은 이름이 있다. 제목 카드를
        # 만들고 내용만 숨기면 흰 테두리 박스가 공통 목록 위에 빈 띠로
        # 남으므로, 이쪽에서는 카드 자체를 두지 않는다.
        self.path_label = None
        if not favorites_only:
            heading = QFrame()
            heading.setObjectName("card")
            heading_layout = QVBoxLayout(heading)
            heading_layout.setContentsMargins(18, 14, 18, 14)
            heading_layout.setSpacing(5)
            title = QLabel("저장내역")
            title.setObjectName("sectionTitle")
            description = QLabel(
                "법령·조문·질의회신·해석례·판례의 저장 본문을 모아 보여줍니다. "
                "저장된 본문은 API를 다시 호출하지 않고 엽니다."
            )
            description.setObjectName("sectionDescription")
            description.setWordWrap(True)
            self.path_label = QLabel(f"저장 위치: {self.law_cache.directory}")
            self.path_label.setObjectName("sectionDescription")
            self.path_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            self.path_label.setWordWrap(True)
            heading_layout.addWidget(title)
            heading_layout.addWidget(description)
            heading_layout.addWidget(self.path_label)
            root.addWidget(heading)

        self.project_tabs: QTabBar | None = None
        if favorites_only:
            project_row = QHBoxLayout()
            project_row.setSpacing(7)
            # 프로젝트는 자주 오가는 자리라 펼쳐서 고르는 콤보보다 탭이 낫다.
            # 목록이 잘릴 일도 없고, 공통 목록에서 끌어다 탭 위에 떨어뜨려
            # 그 프로젝트로 담는 길도 열린다.
            self.project_tabs = FavoriteProjectTabBar()
            self.project_tabs.setObjectName("favoriteProjectTabs")
            self.project_tabs.setExpanding(False)
            self.project_tabs.setDrawBase(False)
            self.project_tabs.setUsesScrollButtons(True)
            self.project_tabs.setElideMode(Qt.TextElideMode.ElideRight)
            self.project_tabs.setAcceptDrops(True)
            # 탭을 끌어 순서를 바꾼다. 자주 쓰는 프로젝트를 앞으로
            # 옮겨 두려면 지금까지는 지우고 다시 만드는 수밖에 없었다.
            self.project_tabs.setMovable(True)
            for project in self.favorite_projects:
                index = self.project_tabs.addTab(str(project["name"]))
                self.project_tabs.setTabData(index, str(project["id"]))
            active_index = self._project_tab_index(self.active_favorite_project)
            self.project_tabs.setCurrentIndex(max(0, active_index))
            self.project_tabs.currentChanged.connect(
                self._favorite_project_changed
            )
            self.project_tabs.setContextMenuPolicy(
                Qt.ContextMenuPolicy.CustomContextMenu
            )
            self.project_tabs.customContextMenuRequested.connect(
                self._show_favorite_project_context_menu
            )
            self.project_tabs.favoriteDropped.connect(
                self._copy_favorites_to_project
            )
            self.project_tabs.tabMoved.connect(self._favorite_project_moved)
            # 탭 위에 커서를 둔 채 F2를 누르면 그 프로젝트 이름을 고친다.
            rename_shortcut = QShortcut(
                QKeySequence(Qt.Key.Key_F2), self
            )
            rename_shortcut.setContext(
                Qt.ShortcutContext.WidgetWithChildrenShortcut
            )
            rename_shortcut.activated.connect(
                self._rename_hovered_favorite_project
            )
            self.project_add_button = QToolButton()
            self.project_add_button.setObjectName("favoriteProjectAddButton")
            self.project_add_button.setFixedSize(32, 32)
            self.project_add_button.setIcon(QIcon(str(FAVORITE_PLUS_ICON_PATH)))
            self.project_add_button.setIconSize(QSize(14, 14))
            self.project_add_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.project_add_button.setToolTip("새 즐겨찾기 프로젝트 만들기")
            self.project_add_button.setAccessibleName("새 프로젝트")
            self.project_add_button.clicked.connect(self._create_favorite_project)
            project_row.addWidget(self.project_tabs, 0, Qt.AlignmentFlag.AlignVCenter)
            project_row.addWidget(
                self.project_add_button, 0, Qt.AlignmentFlag.AlignBottom
            )
            project_row.addStretch(1)
            root.addLayout(project_row)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("저장된 내역 검색")
        self.search_input.setClearButtonEnabled(True)
        self.folder_button = QPushButton("저장 폴더 열기")
        self.folder_button.setObjectName("ghostButton")
        self.folder_button.setFixedSize(176, 38)
        self.clear_cache_button = QPushButton("모든 캐시 삭제")
        self.clear_cache_button.setObjectName("dangerButton")
        self.clear_cache_button.setFixedSize(176, 38)
        self.clear_cache_button.setStyleSheet(
            "QPushButton#dangerButton { color:#a12b2b; background:#fff7f7; "
            "border:1px solid #dfb7b7; border-radius:6px; padding:0 14px; }"
            "QPushButton#dangerButton:hover { background:#fbe9e9; "
            "border-color:#cf8f8f; }"
        )
        self.clear_cache_button.setToolTip(
            "저장 본문, 즐겨찾기, 검색목록 및 인용 조문 캐시를 모두 삭제합니다."
        )
        if favorites_only:
            # 즐겨찾기 화면에서는 검색칸과 폴더 열기가 칸만 차지한다.
            self.search_input.hide()
            self.folder_button.hide()
            self.clear_cache_button.hide()
        else:
            controls = QHBoxLayout()
            controls.setSpacing(8)
            controls.addWidget(self.search_input, 1)
            controls.addWidget(self.folder_button)
            controls.addWidget(self.clear_cache_button)
            root.addLayout(controls)

        self.count_label = QLabel("저장 내역 0건")
        self.count_label.setObjectName("resultTitle")
        if self.favorites_only:
            # 즐겨찾기 화면에서는 건수를 적지 않는다. 바로 아래 목록이
            # 곧 그 수이고, 프로젝트 탭 줄 밑에 한 줄이 더 끼어 목록이
            # 그만큼 내려갔다. 값은 접근성 도구를 위해 남긴다.
            self.count_label.hide()
            count_row = QHBoxLayout()
            count_row.setContentsMargins(0, 0, 0, 0)
            count_row.addStretch()
            self.union_check = QCheckBox("즐겨찾기 모아보기")
            self.union_check.setObjectName("favoriteCategoryCheck")
            self.union_check.setFixedHeight(28)
            self.union_check.setToolTip(
                "모든 프로젝트의 즐겨찾기를 한 목록으로 모아 아래에 보여 줍니다."
            )
            # 지난 실행에서 켜 두었더라도 켤 때마다 꺼 둔다. 모아보기가
            # 열려 있으면 아래 칸이 먼저 보여 지금 프로젝트 목록을 가린다.
            self.union_check.setChecked(False)
            self.union_check.toggled.connect(self._union_favorites_toggled)
            count_row.addWidget(self.union_check, 0, Qt.AlignmentFlag.AlignVCenter)
            visible_categories = self._load_visible_favorite_categories()
            for category, label in self.FAVORITE_CATEGORIES:
                checkbox = QCheckBox(label.replace("\n", " "))
                checkbox.setObjectName("favoriteCategoryCheck")
                checkbox.setFixedHeight(28)
                checkbox.setChecked(category in visible_categories)
                checkbox.toggled.connect(
                    lambda _checked=False, selected_category=category: (
                        self._favorite_category_visibility_changed(
                            selected_category
                        )
                    )
                )
                self.favorite_category_checks[category] = checkbox
                count_row.addWidget(
                    checkbox, 0, Qt.AlignmentFlag.AlignVCenter
                )
            root.addLayout(count_row)
        else:
            root.addWidget(self.count_label)

        self.favorite_cards: QWidget | None = None
        self.favorite_splitter: QSplitter | None = None
        self.favorite_tree: QTreeWidget | None = None
        self.favorite_trees: dict[str, FavoriteCategoryTree] = {}
        self.favorite_category_titles: dict[str, QLabel] = {}
        self.favorite_add_buttons: dict[str, QPushButton] = {}
        self._active_favorite_category = "law"
        self.favorite_folders: list[dict[str, object]] = []
        self._populating_favorite_tree = False
        self._favorite_tree_persist_pending = False
        self.table: QTableWidget | None = None
        if self.favorites_only:
            self.favorite_folders = self._load_favorite_folders()
            cards = QWidget()
            cards.setObjectName("favoriteCards")
            cards_layout = QHBoxLayout(cards)
            cards_layout.setContentsMargins(0, 0, 0, 0)
            cards_layout.setSpacing(0)
            splitter = QSplitter(Qt.Orientation.Horizontal)
            splitter.setChildrenCollapsible(True)
            splitter.setHandleWidth(5)
            for category, label in self.FAVORITE_CATEGORIES:
                card = QFrame()
                card.setObjectName("favoriteCategoryCard")
                card.setMinimumWidth(0)
                card_layout = QVBoxLayout(card)
                card_layout.setContentsMargins(0, 0, 0, 0)
                card_layout.setSpacing(5)
                title_bar = QFrame()
                title_bar.setObjectName("favoriteCategoryTitleBar")
                title_layout = QHBoxLayout(title_bar)
                title_layout.setContentsMargins(8, 5, 8, 5)
                title_layout.setSpacing(4)
                title_layout.addSpacing(22)
                category_title = QLabel(label.replace("\n", " "))
                category_title.setObjectName("favoriteCategoryTitle")
                category_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
                add_folder_button = QPushButton()
                add_folder_button.setObjectName("favoriteAddFolderButton")
                add_folder_button.setFixedSize(28, 28)
                add_folder_button.setIcon(QIcon(str(FAVORITE_PLUS_ICON_PATH)))
                add_folder_button.setIconSize(QSize(12, 12))
                add_folder_button.setCursor(Qt.CursorShape.PointingHandCursor)
                add_folder_button.setToolTip(
                    f"{label.replace(chr(10), ' ')}에 새 폴더 만들기"
                )
                add_folder_button.clicked.connect(
                    lambda _checked=False, selected_category=category: (
                        self._create_favorite_folder(selected_category)
                    )
                )
                title_layout.addWidget(category_title, 1)
                title_layout.addWidget(
                    add_folder_button,
                    0,
                    Qt.AlignmentFlag.AlignVCenter,
                )
                tree = FavoriteCategoryTree(category)
                tree.setObjectName("favoriteCategoryTree")
                tree.setColumnCount(1)
                tree.setHeaderHidden(True)
                tree.setSelectionMode(
                    QAbstractItemView.SelectionMode.ExtendedSelection
                )
                tree.setDragDropMode(
                    QAbstractItemView.DragDropMode.InternalMove
                )
                tree.setDefaultDropAction(Qt.DropAction.MoveAction)
                tree.setDragDropOverwriteMode(False)
                tree.setDropIndicatorShown(True)
                tree.setAlternatingRowColors(False)
                # 폴더 왼쪽에 ▶/▼ 접기·펼치기 버튼을 표시한다.
                # 기존 행 더블클릭 접기·펼치기는 아래 설정으로 유지한다.
                tree.setRootIsDecorated(True)
                tree.setExpandsOnDoubleClick(True)
                tree.setAnimated(True)
                tree.setUniformRowHeights(True)
                tree.setContextMenuPolicy(
                    Qt.ContextMenuPolicy.CustomContextMenu
                )
                tree.customContextMenuRequested.connect(
                    lambda position, selected_category=category: (
                        self._show_favorite_folder_context_menu(
                            selected_category, position
                        )
                    )
                )
                tree.categoryActivated.connect(
                    self._activate_favorite_category
                )
                tree.itemSelectionChanged.connect(
                    lambda category=category: self._favorite_tree_selection_changed(
                        category
                    )
                )
                # 법령 즐겨찾기와 조항호목 즐겨찾기가 같은 화면에 나란히
                # 있으므로 여는 방법도 같아야 한다. 둘 다 두 번 눌러 연다.
                tree.itemDoubleClicked.connect(self._open_favorite_tree_item)
                tree.itemDoubleClicked.connect(
                    self._open_favorite_article_item
                )
                tree.externalFavoritesDropped.connect(
                    self._drop_favorites_on_current_project
                )
                tree.removeRequested.connect(
                    lambda index, selected_category=category: (
                        self._remove_favorite_by_index(
                            selected_category, index
                        )
                    )
                )
                tree.model().rowsMoved.connect(
                    lambda *_args: self._schedule_favorite_tree_persist()
                )
                # QTreeWidget의 기본 드래그앤드롭은 같은 부모 안에서
                # 순서만 바꿀 때는 rowsMoved가 뜨지만, 항목을 다른
                # 폴더 "안으로" 옮길 때(부모가 바뀔 때)는 내부적으로
                # 제거 후 재삽입으로 처리되어 rowsMoved가 발생하지
                # 않는다. 그래서 폴더에 넣어도 저장이 안 되고 재실행
                # 하면 폴더 밖으로 돌아가 있었다. rowsInserted도 함께
                # 감지해야 한다.
                tree.model().rowsInserted.connect(
                    lambda *_args: self._schedule_favorite_tree_persist()
                )
                delete_shortcut = QShortcut(QKeySequence.StandardKey.Delete, tree)
                delete_shortcut.setContext(
                    Qt.ShortcutContext.WidgetShortcut
                )
                delete_shortcut.activated.connect(
                    self._remove_selected_favorite
                )
                card_layout.addWidget(title_bar)
                card_layout.addWidget(tree, 1)
                splitter.addWidget(card)
                self.favorite_category_cards[category] = card
                self.favorite_trees[category] = tree
                self.favorite_category_titles[category] = category_title
                self.favorite_add_buttons[category] = add_folder_button
            self.favorite_cards = cards
            self.favorite_splitter = splitter
            self.favorite_tree = self.favorite_trees["law"]
            cards_layout.addWidget(splitter)
            self.union_panel = QWidget()
            self.union_panel.setObjectName("favoriteUnionPanel")
            union_layout = QVBoxLayout(self.union_panel)
            union_layout.setContentsMargins(0, 6, 0, 0)
            union_layout.setSpacing(4)
            union_label = QLabel("즐겨찾기 모아보기")
            union_label.setObjectName("favoriteUnionLabel")
            self.union_splitter = QSplitter(Qt.Orientation.Horizontal)
            self.union_splitter.setObjectName("favoriteUnionSplitter")
            self.union_splitter.setChildrenCollapsible(True)
            self.union_splitter.setHandleWidth(5)
            for category, _label in self.FAVORITE_CATEGORIES:
                column = QWidget()
                column.setObjectName("favoriteUnionColumn")
                column_layout = QVBoxLayout(column)
                column_layout.setContentsMargins(0, 0, 0, 0)
                column_layout.setSpacing(0)
                tree = self._create_union_tree(category)
                column_layout.addWidget(tree, 1)
                self.union_splitter.addWidget(column)
                self.union_cards[category] = column
                self.union_trees[category] = tree
            self.union_tree = self.union_trees["law"]
            union_layout.addWidget(union_label)
            union_layout.addWidget(self.union_splitter, 1)
            splitter.splitterMoved.connect(self._sync_union_column_widths)
            self.union_splitter.splitterMoved.connect(
                self._copy_union_widths_to_cards
            )
            self.favorite_body_splitter = QSplitter(Qt.Orientation.Vertical)
            self.favorite_body_splitter.setObjectName("favoriteBodySplitter")
            self.favorite_body_splitter.setChildrenCollapsible(False)
            self.favorite_body_splitter.addWidget(cards)
            self.favorite_body_splitter.addWidget(self.union_panel)
            self.favorite_body_splitter.setStretchFactor(0, 3)
            self.favorite_body_splitter.setStretchFactor(1, 1)
            self.union_panel.setVisible(self._is_union_favorites_visible())
            root.addWidget(self.favorite_body_splitter, 1)
            splitter.splitterMoved.connect(self._save_favorite_widths)
            self._apply_favorite_category_visibility()
            QTimer.singleShot(0, self._restore_favorite_widths)
            QTimer.singleShot(0, self._apply_union_splitter_sizes)
        else:
            self.table = QTableWidget(0, 4)
            self.table.setHorizontalHeaderLabels(
                ("구분", "명칭·조문", "시행일", "저장일시")
            )
            self.table.setSelectionBehavior(
                QAbstractItemView.SelectionBehavior.SelectRows
            )
            self.table.setSelectionMode(
                QAbstractItemView.SelectionMode.SingleSelection
            )
            self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.table.setAlternatingRowColors(True)
            self.table.setShowGrid(False)
            self.table.verticalHeader().setVisible(False)
            self.table.verticalHeader().setMinimumSectionSize(28)
            self.table.verticalHeader().setDefaultSectionSize(28)
            header = self.table.horizontalHeader()
            header.setSectionResizeMode(
                0, QHeaderView.ResizeMode.ResizeToContents
            )
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(
                2, QHeaderView.ResizeMode.ResizeToContents
            )
            header.setSectionResizeMode(
                3, QHeaderView.ResizeMode.ResizeToContents
            )
            root.addWidget(self.table, 1)

        # 상태줄 실물은 창에 하나만 둔다. main_window가 use_shared_status로
        # 공용 하단바를 넘겨 주면 이 줄은 숨는다.
        self.status_row = QWidget()
        status_layout = QHBoxLayout(self.status_row)
        status_layout.setContentsMargins(0, 0, 0, 0)
        self.status_label = QLabel(
            "각 검색 화면에서 저장한 본문이 이 목록에 표시됩니다."
        )
        self.status_label.setObjectName("statusLabel")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        root.addWidget(self.status_row)


        self.search_input.textChanged.connect(self._populate)
        if not self.favorites_only:
            self.folder_button.clicked.connect(self.open_folder)
            self.clear_cache_button.clicked.connect(self._confirm_clear_all_caches)
        if self.table is not None:
            self.table.itemSelectionChanged.connect(self._selection_changed)
            self.table.cellDoubleClicked.connect(
                lambda _row, _column: self.open_selected()
            )
        self.law_cache.changed.connect(self.refresh)
        self.refresh()

    def use_shared_status(self, bar) -> None:
        """창 아래 공용 상태줄을 이 화면의 상태 자리로 삼는다."""
        line = bar.line_for(self)
        line.setText(self.status_label.text())
        self.status_row.hide()
        self.status_label = line

    def _load_favorite_projects(self) -> list[dict[str, str]]:
        default = [{"id": "default", "name": self.DEFAULT_PROJECT_NAME}]
        if self.settings is None:
            return default
        raw = self.settings.value(self.FAVORITE_PROJECTS_SETTINGS_KEY, "")
        try:
            parsed = json.loads(str(raw)) if raw else []
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = []
        projects: list[dict[str, str]] = []
        seen: set[str] = set()
        for project in parsed if isinstance(parsed, list) else []:
            if not isinstance(project, dict):
                continue
            project_id = str(project.get("id") or "").strip()
            name = str(project.get("name") or "").strip()
            if not project_id or not name or project_id in seen:
                continue
            # 이름을 따로 바꾸지 않은 첫 프로젝트는 새 이름으로 옮긴다.
            if (
                project_id == "default"
                and name == self.LEGACY_DEFAULT_PROJECT_NAME
            ):
                name = self.DEFAULT_PROJECT_NAME
            seen.add(project_id)
            projects.append({"id": project_id, "name": name})
        if "default" not in seen:
            projects.insert(0, default[0])
        self.settings.setValue(
            self.FAVORITE_PROJECTS_SETTINGS_KEY,
            json.dumps(projects, ensure_ascii=False, separators=(",", ":")),
        )
        return projects

    def _load_active_favorite_project(self) -> str:
        valid = {project["id"] for project in self.favorite_projects}
        if self.settings is None:
            return "default"
        selected = str(
            self.settings.value(self.FAVORITE_ACTIVE_PROJECT_KEY, "default")
            or "default"
        )
        return selected if selected in valid else "default"

    def _save_favorite_projects(self) -> None:
        if self.settings is None:
            return
        self.settings.setValue(
            self.FAVORITE_PROJECTS_SETTINGS_KEY,
            json.dumps(
                self.favorite_projects,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
        self.settings.setValue(
            self.FAVORITE_ACTIVE_PROJECT_KEY, self.active_favorite_project
        )
        self.settings.sync()

    def _project_tab_index(self, project_id: str) -> int:
        """프로젝트 id가 몇 번째 탭인지. 없으면 -1."""
        if self.project_tabs is None:
            return -1
        for index in range(self.project_tabs.count()):
            if str(self.project_tabs.tabData(index) or "") == str(project_id):
                return index
        return -1

    def _current_project_id(self) -> str:
        if self.project_tabs is None:
            return "default"
        data = self.project_tabs.tabData(self.project_tabs.currentIndex())
        return str(data or "default")

    def _current_project_name(self) -> str:
        if self.project_tabs is None:
            return ""
        return self.project_tabs.tabText(self.project_tabs.currentIndex())

    def _is_common_favorite_view(self) -> bool:
        """예전 공통 목록 탭 자리. 지금은 쓰지 않는다."""
        return False

    def _is_union_favorites_visible(self) -> bool:
        return bool(self.union_check is not None and self.union_check.isChecked())

    def _load_union_view(self) -> bool:
        if self.settings is None:
            return False
        return bool(self.settings.value(self.FAVORITE_UNION_VIEW_KEY, False))

    def _save_union_view(self, checked: bool) -> None:
        if self.settings is None:
            return
        self.settings.setValue(self.FAVORITE_UNION_VIEW_KEY, bool(checked))
        self.settings.sync()

    def _union_favorites_toggled(self, checked: bool) -> None:
        self._save_union_view(checked)
        if self.union_panel is not None:
            self.union_panel.setVisible(bool(checked))
        if checked:
            self._apply_union_splitter_sizes()
            self._populate_union_favorites()
            self.status_label.setText(
                "모든 프로젝트의 즐겨찾기입니다. 아래 항목을 위 칸이나 "
                "프로젝트 탭으로 끌어다 놓으면 담을 수 있습니다."
            )
        else:
            for tree in self.union_trees.values():
                tree.clear()

    def _apply_union_splitter_sizes(self) -> None:
        splitter = self.favorite_body_splitter
        if splitter is None or not self._is_union_favorites_visible():
            return
        total = max(splitter.height(), 360)
        bottom = min(240, max(160, total // 3))
        splitter.setSizes([max(200, total - bottom), bottom])

    def _favorite_project_changed(self, _index: int = -1) -> None:
        if self.project_tabs is None:
            return
        project_id = self._current_project_id()
        if (
            not project_id
            or project_id == self.COMMON_FAVORITES_VIEW_ID
        ):
            return
        if project_id == self.active_favorite_project:
            self.refresh()
            return
        if self.favorite_trees:
            self._persist_favorite_tree("현재 프로젝트의 정리를 저장했습니다.")
        self.active_favorite_project = project_id
        self._save_favorite_projects()
        self.law_cache.set_active_favorite_project(project_id)
        self.favorite_folders = self._load_favorite_folders()
        self.refresh()
        self.status_label.setText(
            f"'{self._current_project_name()}' 프로젝트를 열었습니다."
        )

    def _build_favorite_project_context_menu(
        self, index: int
    ) -> QMenu | None:
        if self.project_tabs is None or index < 0:
            return None
        project_id = str(self.project_tabs.tabData(index) or "")
        if not project_id or project_id == self.COMMON_FAVORITES_VIEW_ID:
            return None
        menu = QMenu(self.project_tabs)
        rename_action = menu.addAction("이름 변경")
        delete_action = menu.addAction("프로젝트 삭제")
        delete_action.setEnabled(project_id != "default")
        rename_action.triggered.connect(
            lambda _checked=False, target_index=index: (
                self._rename_favorite_project(target_index)
            )
        )
        delete_action.triggered.connect(
            lambda _checked=False, target_index=index: (
                self._delete_favorite_project(target_index)
            )
        )
        return menu

    def _show_favorite_project_context_menu(self, position) -> None:
        if self.project_tabs is None:
            return
        index = self.project_tabs.tabAt(position)
        menu = self._build_favorite_project_context_menu(index)
        if menu is not None:
            menu.exec(self.project_tabs.mapToGlobal(position))

    def _next_default_project_name(self) -> str:
        """겹치지 않는 ``제목 없음`` 계열 이름을 만든다."""
        taken = {str(project.get("name") or "") for project in self.favorite_projects}
        if self.DEFAULT_PROJECT_NAME not in taken:
            return self.DEFAULT_PROJECT_NAME
        number = 2
        while f"{self.DEFAULT_PROJECT_NAME} {number}" in taken:
            number += 1
        return f"{self.DEFAULT_PROJECT_NAME} {number}"

    def _create_favorite_project(self) -> None:
        """+ 를 누르면 이름을 묻지 않고 바로 만든다.

        이름은 만든 뒤 탭에서 오른쪽 단추 또는 F2로 고친다. 만들 때마다
        대화상자가 뜨면 담을 곳부터 급한 상황에서 손이 한 번 더 간다.
        """
        if self.project_tabs is None:
            return
        name = self._next_default_project_name()
        project_id = uuid.uuid4().hex
        self.favorite_projects.append({"id": project_id, "name": name})
        index = self.project_tabs.addTab(name)
        self.project_tabs.setTabData(index, project_id)
        self._save_favorite_projects()
        self.project_tabs.setCurrentIndex(index)
        self.status_label.setText(
            f"'{name}' 프로젝트를 만들었습니다. "
            "탭에서 오른쪽 단추 또는 F2로 이름을 고칠 수 있습니다."
        )

    def _favorite_project_moved(self, *_args: object) -> None:
        """끌어서 바꾼 탭 순서를 그대로 저장한다."""
        if self.project_tabs is None:
            return
        by_id = {
            str(project.get("id") or ""): project
            for project in self.favorite_projects
        }
        moved: list[dict[str, str]] = []
        for index in range(self.project_tabs.count()):
            project_id = str(self.project_tabs.tabData(index) or "")
            project = by_id.get(project_id)
            if project is not None:
                moved.append(project)
        # 모아보기처럼 프로젝트가 아닌 탭이 섞여 있어도 프로젝트 수는
        # 그대로여야 한다. 어긋나면 저장하지 않고 둔다.
        if len(moved) != len(self.favorite_projects):
            return
        self.favorite_projects = moved
        self._save_favorite_projects()

    def _rename_hovered_favorite_project(self) -> None:
        """F2. 커서가 얹힌 탭을, 없으면 지금 보고 있는 탭을 고친다."""
        if self.project_tabs is None:
            return
        position = self.project_tabs.mapFromGlobal(QCursor.pos())
        index = (
            self.project_tabs.tabAt(position)
            if self.project_tabs.rect().contains(position)
            else -1
        )
        self._rename_favorite_project(
            index if index >= 0 else self.project_tabs.currentIndex()
        )

    def _rename_favorite_project(self, index: int | None = None) -> None:
        if self.project_tabs is None:
            return
        target_index = (
            self.project_tabs.currentIndex() if index is None else int(index)
        )
        project_id = str(self.project_tabs.tabData(target_index) or "")
        if not project_id or project_id == self.COMMON_FAVORITES_VIEW_ID:
            return
        current = self.project_tabs.tabText(target_index)
        name, accepted = QInputDialog.getText(
            self,
            "즐겨찾기 프로젝트 이름 변경",
            "새 프로젝트 이름:",
            text=current,
        )
        name = name.strip()
        if not accepted or not name or name == current:
            return
        for project in self.favorite_projects:
            if project["id"] == project_id:
                project["name"] = name
                break
        self.project_tabs.setTabText(target_index, name)
        self._save_favorite_projects()

    def _delete_favorite_project(self, index: int | None = None) -> None:
        if self.project_tabs is None:
            return
        target_index = (
            self.project_tabs.currentIndex() if index is None else int(index)
        )
        project_id = str(self.project_tabs.tabData(target_index) or "")
        if not project_id or project_id == self.COMMON_FAVORITES_VIEW_ID:
            return
        if project_id == "default":
            QMessageBox.information(
                self,
                "프로젝트 삭제",
                f"'{self.DEFAULT_PROJECT_NAME}' 프로젝트는 삭제할 수 없습니다.",
            )
            return
        name = self.project_tabs.tabText(target_index)
        answer = QMessageBox.question(
            self,
            "즐겨찾기 프로젝트 삭제",
            f"'{name}' 프로젝트를 삭제할까요?\n"
            "저장된 본문과 다른 프로젝트의 즐겨찾기는 유지됩니다.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.law_cache.remove_favorite_project(project_id)
        self.favorite_projects = [
            project
            for project in self.favorite_projects
            if project["id"] != project_id
        ]
        was_active = project_id == self.active_favorite_project
        if target_index >= 0:
            self.project_tabs.removeTab(target_index)
        if was_active:
            self.active_favorite_project = "default"
            self.law_cache.set_active_favorite_project("default")
        self._save_favorite_projects()
        if was_active:
            self.project_tabs.setCurrentIndex(
                max(0, self._project_tab_index("default"))
            )
        else:
            self.refresh()

    def _favorite_folder_settings_key(self) -> str:
        return (
            f"{self.FAVORITE_FOLDER_SETTINGS_KEY}/"
            f"{self.active_favorite_project}"
        )

    def _load_visible_favorite_categories(self) -> set[str]:
        """지난에 선택한 즐겨찾기 카드. 저장값이 없으면 모두 보인다."""
        all_categories = {
            category for category, _label in self.FAVORITE_CATEGORIES
        }
        if self.settings is None or not self.settings.contains(
            self.FAVORITE_VISIBLE_CATEGORIES_KEY
        ):
            return all_categories
        raw = self.settings.value(self.FAVORITE_VISIBLE_CATEGORIES_KEY, "")
        try:
            values = json.loads(str(raw or "[]"))
        except ValueError:
            return all_categories
        if not isinstance(values, list):
            return all_categories
        visible = {
            str(value) for value in values if str(value) in all_categories
        }
        version = int(
            self.settings.value(
                self.FAVORITE_VISIBLE_CATEGORIES_VERSION_KEY, 0
            )
            or 0
        )
        if version < self.FAVORITE_VISIBLE_CATEGORIES_VERSION:
            visible.add("article")
            self.settings.setValue(
                self.FAVORITE_VISIBLE_CATEGORIES_KEY,
                json.dumps(sorted(visible), ensure_ascii=False),
            )
            self.settings.setValue(
                self.FAVORITE_VISIBLE_CATEGORIES_VERSION_KEY,
                self.FAVORITE_VISIBLE_CATEGORIES_VERSION,
            )
            self.settings.sync()
        return visible

    def _favorite_category_visibility_changed(self, _category: str = "") -> None:
        self._apply_favorite_category_visibility()
        if self.settings is None:
            return
        visible = [
            category
            for category, _label in self.FAVORITE_CATEGORIES
            if self.favorite_category_checks[category].isChecked()
        ]
        self.settings.setValue(
            self.FAVORITE_VISIBLE_CATEGORIES_KEY,
            json.dumps(visible, ensure_ascii=False),
        )
        self.settings.setValue(
            self.FAVORITE_VISIBLE_CATEGORIES_VERSION_KEY,
            self.FAVORITE_VISIBLE_CATEGORIES_VERSION,
        )
        self.settings.sync()

    def _apply_favorite_category_visibility(self) -> None:
        """체크한 구분의 카드만 표시하고 숨긴 카드는 폭도 제거."""
        if not self.favorite_category_cards:
            return
        visible_categories: list[str] = []
        for category, _label in self.FAVORITE_CATEGORIES:
            visible = self.favorite_category_checks[category].isChecked()
            self.favorite_category_cards[category].setVisible(visible)
            union_card = self.union_cards.get(category)
            if union_card is not None:
                union_card.setVisible(visible)
            if visible:
                visible_categories.append(category)
        if self._active_favorite_category not in visible_categories:
            if visible_categories:
                self._active_favorite_category = visible_categories[0]
                self.favorite_tree = self.favorite_trees[visible_categories[0]]
            else:
                self.favorite_tree = None
        QTimer.singleShot(0, self._sync_union_column_widths)

    @staticmethod
    def _display_date(value: object) -> str:
        text = str(value or "").strip()
        digits = re.sub(r"\D", "", text)
        if len(digits) == 8:
            return f"{digits[:4]}.{digits[4:6]}.{digits[6:]}"
        return text

    @staticmethod
    def _display_timestamp(value: object) -> str:
        text = str(value or "").strip()
        return text.replace("T", " ")[:16]

    @staticmethod
    def _record_type(record: dict[str, object]) -> str:
        row = record.get("row")
        row = row if isinstance(row, dict) else {}
        if record.get("kind") != "detail_snapshot":
            return "법령"
        target = str(row.get("target") or "")
        labels = {
            "ai_search": "키워드 직접검색",
            "ai_related": "키워드 연관법령",
            "expc": "법령해석례",
            "prec": "판례",
            "admrul": "행정규칙",
            "law_reference": "인용 조문",
            "three_stage": "3단비교",
            "ordin": "자치법규",
            "licbyl": "법령 별표·서식",
            "admbyl": "행정규칙 별표·서식",
            "ordinbyl": "자치법규 별표·서식",
        }
        if target in labels:
            return labels[target]
        if row.get("agency"):
            return "중앙부처 질의회신"
        return "저장 본문"

    @classmethod
    def _record_name(cls, record: dict[str, object]) -> str:
        row = record.get("row")
        row = row if isinstance(row, dict) else {}
        name = str(
            record.get("name")
            or row.get("title")
            or row.get("name")
            or "본문"
        )
        if record.get("kind") == "detail_snapshot":
            provision = str(row.get("provision") or "").strip()
            target = str(row.get("target") or "")
            if provision and target in ("ai_search", "ai_related"):
                law_name = name.replace(provision, "", 1).strip(" ·")
                return f"{provision} · {law_name}" if law_name else provision
            if provision and provision not in name:
                return f"{name} · {provision}"
        return name

    @staticmethod
    def _favorite_category(record: dict[str, object]) -> str:
        row = record.get("row")
        row = row if isinstance(row, dict) else {}
        target = str(row.get("target") or "")
        item_kind = str(row.get("kind") or "").replace("·", "")
        if target in ("licbyl", "admbyl", "ordinbyl") or "별표서식" in item_kind:
            return "annex"
        if target in ("ai_search", "ai_related"):
            # 지능형 검색 결과의 법령 조문은 이제 법령검색 화면과 같은
            # 조문 즐겨찾기로 들어간다. 예전 판이 남긴 저장본만 여기로
            # 오므로 법령 칸에 함께 둔다.
            return "law"
        if target == "expc":
            return "expc"
        if target == "prec":
            return "prec"
        if target in AGENCY_BY_TARGET or row.get("agency"):
            return "central"
        return "law"

    @classmethod
    def _default_favorite_folders(cls) -> list[dict[str, object]]:
        return [
            {
                "id": category,
                "name": label.replace("\n", " "),
                "category": category,
                "children": [],
            }
            for category, label in cls.FAVORITE_CATEGORIES
        ]

    def _load_favorite_folders(self) -> list[dict[str, object]]:
        raw: object = ""
        if self.settings is not None:
            raw = self.settings.value(
                self._favorite_folder_settings_key(), ""
            )
            if not raw and self.active_favorite_project == "default":
                # 프로젝트 기능 도입 전의 정리 상태는 기본 프로젝트로 옮긴다.
                raw = self.settings.value(
                    self.FAVORITE_FOLDER_SETTINGS_KEY, ""
                )
            if not raw and self.active_favorite_project == "default":
                raw = self.settings.value(
                    self.FAVORITE_FOLDER_LEGACY_SETTINGS_KEY, ""
                )
        try:
            parsed = json.loads(str(raw)) if raw else []
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = []
        seen: set[str] = set()

        def clean(nodes: object) -> list[dict[str, object]]:
            cleaned: list[dict[str, object]] = []
            if not isinstance(nodes, list):
                return cleaned
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                folder_id = str(node.get("id") or "").strip()
                name = str(node.get("name") or "").strip()
                if not folder_id or not name or folder_id in seen:
                    continue
                seen.add(folder_id)
                cleaned.append(
                    {
                        "id": folder_id,
                        "name": name,
                        "category": str(node.get("category") or ""),
                        "children": clean(node.get("children")),
                    }
                )
            return cleaned

        legacy_folders = clean(parsed)
        fixed_folders = self._default_favorite_folders()
        fixed_by_category = {
            str(folder["category"]): folder for folder in fixed_folders
        }
        valid_categories = set(fixed_by_category)

        record_category_counts: dict[str, dict[str, int]] = {}
        for record in self.law_cache.favorite_entries():
            folder_id = str(record.get("favorite_folder") or "")
            if not folder_id:
                continue
            category = self._favorite_category(record)
            counts = record_category_counts.setdefault(folder_id, {})
            counts[category] = counts.get(category, 0) + 1

        def subtree_category_counts(
            folder: dict[str, object],
        ) -> dict[str, int]:
            counts = dict(record_category_counts.get(str(folder["id"]), {}))
            children = folder.get("children")
            for child in children if isinstance(children, list) else []:
                if not isinstance(child, dict):
                    continue
                for category, count in subtree_category_counts(child).items():
                    counts[category] = counts.get(category, 0) + count
            return counts

        def migrate_custom_folder(
            folder: dict[str, object], category: str
        ) -> dict[str, object]:
            children = folder.get("children")
            child_folders = children if isinstance(children, list) else []
            return {
                "id": str(folder["id"]),
                "name": str(folder["name"]),
                "category": category,
                "children": [
                    migrate_custom_folder(child, category)
                    for child in child_folders
                    if isinstance(child, dict)
                ],
            }

        for folder in legacy_folders:
            folder_id = str(folder.get("id") or "")
            saved_category = str(folder.get("category") or "")
            root_category = (
                folder_id
                if folder_id in valid_categories
                else saved_category
                if saved_category in valid_categories
                else ""
            )
            if root_category:
                children = folder.get("children")
                child_folders = children if isinstance(children, list) else []
                for child in child_folders:
                    if not isinstance(child, dict):
                        continue
                    child_category = root_category
                    counts = subtree_category_counts(child)
                    if root_category == "law" and counts.get("annex", 0) > counts.get("law", 0):
                        # 5개 구분 버전에서 법령검색으로 합쳐졌던 별표·서식
                        # 사용자 폴더를 원래 여섯 번째 고정 구분으로 복구한다.
                        child_category = "annex"
                    fixed_by_category[child_category]["children"].append(
                        migrate_custom_folder(child, child_category)
                    )
                continue
            counts = subtree_category_counts(folder)
            category = (
                max(counts, key=counts.get) if counts else "law"
            )
            fixed_by_category[category]["children"].append(
                migrate_custom_folder(folder, category)
            )

        self._save_favorite_folders(fixed_folders)
        return fixed_folders

    def _save_favorite_folders(
        self, folders: list[dict[str, object]]
    ) -> None:
        self.favorite_folders = folders
        if self.settings is None:
            return
        self.settings.setValue(
            self._favorite_folder_settings_key(),
            json.dumps(folders, ensure_ascii=False, separators=(",", ":")),
        )
        self.settings.sync()

    def _favorite_folder_item(
        self, folder: dict[str, object]
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem((str(folder.get("name") or "폴더"), "폴더", ""))
        item.setData(0, self.FAVORITE_KIND_ROLE, "folder")
        item.setData(
            0, self.FAVORITE_FOLDER_ID_ROLE, str(folder.get("id") or "")
        )
        item.setData(
            0, self.FAVORITE_CATEGORY_ROLE, str(folder.get("category") or "")
        )
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
            | Qt.ItemFlag.ItemIsDropEnabled
        )
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        item.setForeground(0, QColor("#173b63"))
        item.setIcon(
            0, self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        )
        item.setToolTip(0, "폴더를 선택한 뒤 새 폴더를 만들면 하위 폴더가 됩니다.")
        return item

    def _favorite_category_item(
        self, category: str, label: str
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem((label.replace("\n", " "), "고정 구분", ""))
        item.setData(0, self.FAVORITE_KIND_ROLE, "category")
        item.setData(0, self.FAVORITE_FOLDER_ID_ROLE, category)
        item.setData(0, self.FAVORITE_CATEGORY_ROLE, category)
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDropEnabled
        )
        font = item.font(0)
        font.setBold(True)
        font.setPointSize(max(font.pointSize(), 10))
        item.setFont(0, font)
        item.setForeground(0, QColor("#173b63"))
        item.setBackground(0, QColor("#eaf2f9"))
        item.setToolTip(
            0,
            "고정 구분입니다. 이름을 바꾸거나 삭제할 수 없으며 "
            "이 안에 사용자 폴더를 만들 수 있습니다.",
        )
        return item

    def _populate_favorite_tree(
        self, records: list[dict[str, object]]
    ) -> None:
        if not self.favorite_trees:
            return
        query_active = bool(self.search_input.text().strip())
        # 드래그 저장이나 다른 화면의 별표 변경으로 목록을 다시 그려도
        # 사용자가 접어 둔 폴더까지 전부 열리지 않게 현재 상태를 먼저 잡는다.
        expanded_folder_ids: dict[str, set[str]] = {}
        tree_had_items: dict[str, bool] = {}
        for category, tree in self.favorite_trees.items():
            tree_had_items[category] = tree.topLevelItemCount() > 0
            expanded: set[str] = set()

            def remember_expanded(item: QTreeWidgetItem) -> None:
                if (
                    item.data(0, self.FAVORITE_KIND_ROLE) == "folder"
                    and item.isExpanded()
                ):
                    folder_id = str(
                        item.data(0, self.FAVORITE_FOLDER_ID_ROLE) or ""
                    )
                    if folder_id:
                        expanded.add(folder_id)
                for child_index in range(item.childCount()):
                    remember_expanded(item.child(child_index))

            for item_index in range(tree.topLevelItemCount()):
                remember_expanded(tree.topLevelItem(item_index))
            expanded_folder_ids[category] = expanded
        self._populating_favorite_tree = True
        for tree in self.favorite_trees.values():
            tree.blockSignals(True)
        try:
            for tree in self.favorite_trees.values():
                tree.clear()
            folder_items: dict[str, dict[str, QTreeWidgetItem]] = {
                category: {} for category, _label in self.FAVORITE_CATEGORIES
            }

            def add_folders(
                folders: list[dict[str, object]],
                category: str,
                parent: QTreeWidgetItem | None = None,
            ) -> None:
                tree = self.favorite_trees[category]
                for folder in folders:
                    folder["category"] = category
                    item = self._favorite_folder_item(folder)
                    if parent is None:
                        tree.addTopLevelItem(item)
                    else:
                        parent.addChild(item)
                    folder_id = str(folder.get("id") or "")
                    folder_items[category][folder_id] = item
                    children = folder.get("children")
                    add_folders(
                        children if isinstance(children, list) else [],
                        category,
                        item,
                    )

            saved_roots = {
                str(folder.get("category") or folder.get("id") or ""): folder
                for folder in self.favorite_folders
                if isinstance(folder, dict)
            }
            normalized_roots = self._default_favorite_folders()
            for root_folder in normalized_roots:
                category = str(root_folder["category"])
                saved_root = saved_roots.get(category)
                if isinstance(saved_root, dict):
                    saved_children = saved_root.get("children")
                    root_folder["children"] = (
                        saved_children
                        if isinstance(saved_children, list)
                        else []
                    )
                children = root_folder.get("children")
                add_folders(
                    children if isinstance(children, list) else [],
                    category,
                )
            self.favorite_folders = normalized_roots

            category_counts = {
                category: 0 for category, _label in self.FAVORITE_CATEGORIES
            }

            def stored_order(entry: object) -> int:
                try:
                    return (
                        int(entry.get("favorite_order", 1_000_000_000))
                        if isinstance(entry, dict)
                        else 1_000_000_000
                    )
                except (TypeError, ValueError):
                    return 1_000_000_000

            for record in records:
                folder_id = str(record.get("favorite_folder") or "")
                category = self._favorite_category(record)
                tree = self.favorite_trees[category]
                category_counts[category] += 1
                name = self._record_name(record)
                item = QTreeWidgetItem((name,))
                item.setData(0, Qt.ItemDataRole.UserRole, record.get("path"))
                item.setData(0, self.FAVORITE_KIND_ROLE, "record")
                item.setData(0, self.FAVORITE_CATEGORY_ROLE, category)
                item.setData(
                    0,
                    self.FAVORITE_PROJECT_IDS_ROLE,
                    list(record.get("favorite_project_ids") or []),
                )
                item.setChildIndicatorPolicy(
                    QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator
                )
                item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsDragEnabled
                )
                item.setToolTip(
                    0,
                    f"{name}\n구분: {self._record_type(record)}\n"
                    f"저장일시: {self._display_timestamp(record.get('saved_at'))}",
                )
                parent = folder_items[category].get(folder_id)
                if parent is None:
                    tree.addTopLevelItem(item)
                else:
                    parent.addChild(item)
                article_tree = self.favorite_trees["article"]
                law_name = self._record_name(record)
                article_entries = record.get("favorite_articles") or []
                article_entries = sorted(
                    article_entries if isinstance(article_entries, list) else [],
                    key=stored_order,
                )
                for entry in article_entries:
                    if not isinstance(entry, dict):
                        continue
                    jo = str(entry.get("jo") or "").strip()
                    if not jo:
                        continue
                    article_label = (
                        str(entry.get("label") or "").strip()
                        or f"제{jo}조"
                    )
                    article_caption = self._article_favorite_caption(
                        law_name, article_label
                    )
                    article_item = QTreeWidgetItem((article_caption,))
                    article_item.setData(
                        0, Qt.ItemDataRole.UserRole, record.get("path")
                    )
                    article_item.setData(
                        0, self.FAVORITE_KIND_ROLE, "article"
                    )
                    article_item.setData(
                        0, self.FAVORITE_ARTICLE_ROLE, jo
                    )
                    article_item.setData(
                        0,
                        self.FAVORITE_UNIT_ROLE,
                        {
                            "jo": jo,
                            "hang": str(entry.get("hang") or ""),
                            "ho": str(entry.get("ho") or ""),
                            "mok": str(entry.get("mok") or ""),
                            "label": article_label,
                        },
                    )
                    article_item.setData(
                        0, self.FAVORITE_CATEGORY_ROLE, "article"
                    )
                    article_item.setData(
                        0,
                        self.FAVORITE_PROJECT_IDS_ROLE,
                        list(entry.get("favorite_project_ids") or []),
                    )
                    article_item.setToolTip(
                        0,
                        f"{article_caption}\n"
                        "누르면 해당 조항호목을 열고, 별표를 누르면 해제합니다.",
                    )
                    article_item.setFlags(
                        Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsSelectable
                        | Qt.ItemFlag.ItemIsDragEnabled
                    )
                    article_parent = folder_items["article"].get(
                        str(entry.get("favorite_folder") or "")
                    )
                    if article_parent is None:
                        article_tree.addTopLevelItem(article_item)
                    else:
                        article_parent.addChild(article_item)
                    category_counts["article"] += 1
            for category, label in self.FAVORITE_CATEGORIES:
                tree = self.favorite_trees[category]
                if query_active or not tree_had_items[category]:
                    tree.expandAll()
                else:
                    expanded = expanded_folder_ids[category]
                    for folder_id, item in folder_items[category].items():
                        item.setExpanded(folder_id in expanded)
                tree.setProperty("favoriteRemoveEnabled", True)
                tree.setDragEnabled(not query_active)
                tree.setAcceptDrops(not query_active)
                tree.setDragDropMode(
                    QAbstractItemView.DragDropMode.InternalMove
                )
                tree.viewport().update()
                self.favorite_category_titles[category].setText(
                    label.replace("\n", " ")
                )
                self.favorite_add_buttons[category].setVisible(True)
                self.favorite_add_buttons[category].setEnabled(not query_active)
        finally:
            for tree in self.favorite_trees.values():
                tree.blockSignals(False)
            self._populating_favorite_tree = False

    def _create_union_tree(self, category: str) -> FavoriteCategoryTree:
        tree = FavoriteCategoryTree(category)
        tree.setObjectName("favoriteCategoryTree")
        tree.setColumnCount(1)
        tree.setHeaderHidden(True)
        tree.setRootIsDecorated(False)
        tree.setUniformRowHeights(True)
        tree.setProperty("favoriteRemoveEnabled", False)
        tree.setDragEnabled(True)
        tree.setAcceptDrops(False)
        tree.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree.customContextMenuRequested.connect(
            self._show_union_favorite_context_menu
        )
        tree.itemDoubleClicked.connect(self._open_favorite_tree_item)
        tree.itemDoubleClicked.connect(self._open_favorite_article_item)
        return tree

    def _populate_union_favorites(self) -> None:
        """위 칸은 현재 프로젝트, 아래 칸은 구분별로 합집합만 채운다."""
        if not self.union_trees:
            return
        if not self._is_union_favorites_visible():
            for tree in self.union_trees.values():
                tree.clear()
            return
        query = self.search_input.text().strip().casefold()
        for tree in self.union_trees.values():
            tree.blockSignals(True)
            tree.clear()
        try:
            for record in self.law_cache.all_project_favorite_entries():
                name = self._record_name(record)
                category = self._favorite_category(record)
                tree = self.union_trees.get(category)
                if tree is None:
                    continue
                if query and query not in name.casefold():
                    pass
                else:
                    item = QTreeWidgetItem((name,))
                    item.setData(0, Qt.ItemDataRole.UserRole, record.get("path"))
                    item.setData(0, self.FAVORITE_KIND_ROLE, "record")
                    item.setData(0, self.FAVORITE_CATEGORY_ROLE, category)
                    item.setData(
                        0,
                        self.FAVORITE_PROJECT_IDS_ROLE,
                        list(record.get("favorite_project_ids") or []),
                    )
                    item.setFlags(
                        Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsSelectable
                        | Qt.ItemFlag.ItemIsDragEnabled
                    )
                    item.setToolTip(
                        0,
                        f"{name}\n구분: {self._record_type(record)}\n"
                        f"저장일시: {self._display_timestamp(record.get('saved_at'))}",
                    )
                    tree.addTopLevelItem(item)
                article_tree = self.union_trees.get("article")
                if article_tree is None:
                    continue
                article_entries = record.get("favorite_articles") or []
                if not isinstance(article_entries, list):
                    continue
                for entry in article_entries:
                    if not isinstance(entry, dict):
                        continue
                    jo = str(entry.get("jo") or "").strip()
                    if not jo:
                        continue
                    article_label = (
                        str(entry.get("label") or "").strip() or f"제{jo}조"
                    )
                    article_text = self._article_favorite_caption(
                        name, article_label
                    )
                    if query and query not in article_text.casefold():
                        continue
                    article_item = QTreeWidgetItem((article_text,))
                    article_item.setData(
                        0, Qt.ItemDataRole.UserRole, record.get("path")
                    )
                    article_item.setData(0, self.FAVORITE_KIND_ROLE, "article")
                    article_item.setData(0, self.FAVORITE_ARTICLE_ROLE, jo)
                    article_item.setData(
                        0,
                        self.FAVORITE_UNIT_ROLE,
                        {
                            "jo": jo,
                            "hang": str(entry.get("hang") or ""),
                            "ho": str(entry.get("ho") or ""),
                            "mok": str(entry.get("mok") or ""),
                            "label": article_label,
                        },
                    )
                    article_item.setData(0, self.FAVORITE_CATEGORY_ROLE, "article")
                    article_item.setData(
                        0,
                        self.FAVORITE_PROJECT_IDS_ROLE,
                        list(entry.get("favorite_project_ids") or []),
                    )
                    article_item.setFlags(
                        Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsSelectable
                        | Qt.ItemFlag.ItemIsDragEnabled
                    )
                    article_item.setToolTip(0, article_text)
                    article_tree.addTopLevelItem(article_item)
            for tree in self.union_trees.values():
                tree.setProperty("favoriteRemoveEnabled", False)
                tree.viewport().update()
        finally:
            for tree in self.union_trees.values():
                tree.blockSignals(False)

    def _show_union_favorite_context_menu(self, position) -> None:
        tree = self.sender()
        if not isinstance(tree, FavoriteCategoryTree):
            tree = self.union_tree
        if tree is None:
            return
        item = tree.itemAt(position)
        if item is None or item.data(0, self.FAVORITE_KIND_ROLE) not in (
            "record",
            "article",
        ):
            return
        menu = QMenu(tree)
        project_menu = menu.addMenu("프로젝트에 추가")
        existing_ids = {
            str(value)
            for value in list(item.data(0, self.FAVORITE_PROJECT_IDS_ROLE) or [])
        }
        for project in self.favorite_projects:
            project_id = str(project["id"])
            action = project_menu.addAction(str(project["name"]))
            action.setEnabled(project_id not in existing_ids)
            action.triggered.connect(
                lambda _checked=False, selected_item=item, target_id=project_id: (
                    self._copy_favorite_item_to_project(selected_item, target_id)
                )
            )
        menu.exec(tree.viewport().mapToGlobal(position))

    def _activate_favorite_category(self, category: str) -> None:
        tree = self.favorite_trees.get(category)
        if tree is None:
            return
        self._active_favorite_category = category
        self.favorite_tree = tree
        for other_category, other_tree in self.favorite_trees.items():
            if other_category == category or not other_tree.selectedItems():
                continue
            other_tree.blockSignals(True)
            other_tree.clearSelection()
            other_tree.setCurrentItem(None)
            other_tree.blockSignals(False)
        self._favorite_tree_selection_changed(category)

    def _favorite_tree_selection_changed(self, category: str = "") -> None:
        if category and not self._populating_favorite_tree:
            self._active_favorite_category = category
            self.favorite_tree = self.favorite_trees.get(category)
            for other_category, other_tree in self.favorite_trees.items():
                if other_category == category or not other_tree.selectedItems():
                    continue
                other_tree.blockSignals(True)
                other_tree.clearSelection()
                other_tree.setCurrentItem(None)
                other_tree.blockSignals(False)
        searching = bool(self.search_input.text().strip())
        for button in self.favorite_add_buttons.values():
            button.setEnabled(not searching)
        # 즐겨찾기는 폴더를 열고 정리하는 화면이라 한 번 누르는 것만으로
        # 본문을 열지 않는다. 여는 것은 더블클릭으로.

    def _show_favorite_folder_context_menu(
        self, category: str, position: object
    ) -> None:
        tree = self.favorite_trees.get(category)
        if tree is None:
            return
        item = tree.itemAt(position)
        if item is None:
            return
        kind = item.data(0, self.FAVORITE_KIND_ROLE)
        if kind not in ("folder", "record"):
            return
        self._activate_favorite_category(category)
        tree.setCurrentItem(item)
        menu = QMenu(tree)
        if kind == "folder":
            if self.search_input.text().strip():
                return
            rename_action = menu.addAction("이름 변경")
            delete_action = menu.addAction("삭제")
            rename_action.triggered.connect(self._rename_favorite_folder)
            delete_action.triggered.connect(self._delete_favorite_folder)
        else:
            search_request = self._favorite_search_request(item)
            if search_request is not None:
                target, name = search_request
                search_action = menu.addAction("검색목록으로 이동")
                search_action.triggered.connect(
                    lambda _checked=False, selected_target=target, selected_name=name: (
                        self.searchRequested.emit(selected_target, selected_name)
                    )
                )
                menu.addSeparator()
            remove_action = menu.addAction("즐겨찾기 해제")
            remove_action.triggered.connect(self._remove_selected_favorite)
        menu.exec(tree.viewport().mapToGlobal(position))

    def _copy_favorite_item_to_project(
        self, item: QTreeWidgetItem, project_id: str
    ) -> bool:
        path = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        kind = str(item.data(0, self.FAVORITE_KIND_ROLE) or "")
        payload: dict[str, object] = {"path": path, "kind": kind}
        if kind == "article":
            unit = item.data(0, self.FAVORITE_UNIT_ROLE)
            if isinstance(unit, dict):
                payload["unit"] = dict(unit)
        return self._copy_favorites_to_project(project_id, [payload]) > 0

    def _copy_favorites_to_project(
        self, project_id: str, payloads: object
    ) -> int:
        project_name = next(
            (
                str(project["name"])
                for project in self.favorite_projects
                if str(project["id"]) == str(project_id)
            ),
            "",
        )
        if not project_name or not isinstance(payloads, list):
            return 0
        copied = 0
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            path = str(payload.get("path") or "")
            record = self.law_cache.load(path)
            row = record.get("row") if isinstance(record, dict) else None
            if not isinstance(row, dict):
                continue
            unit = payload.get("unit")
            kwargs = dict(unit) if isinstance(unit, dict) else {}
            kwargs.pop("label", None)
            if self.law_cache.add_favorite_to_project(
                row, project_id, **kwargs
            ):
                copied += 1
        if copied:
            message = (
                f"'{project_name}' 프로젝트에 즐겨찾기 {copied}개를 담았습니다."
            )
            self.refresh()
            self.status_label.setText(message)
        else:
            self.status_label.setText(
                self.law_cache.last_error
                or "프로젝트에 담을 즐겨찾기를 찾지 못했습니다."
            )
        return copied

    def _drop_favorites_on_current_project(self, payloads: object) -> None:
        """모아보기에서 위 칸으로 끌어 오면 지금 프로젝트에 담는다."""
        project_id = self._current_project_id()
        if not project_id:
            return
        self._copy_favorites_to_project(project_id, payloads)

    @staticmethod
    def _article_favorite_caption(law_name: str, article_label: str) -> str:
        law_name = str(law_name or "").strip()
        article_label = str(article_label or "").strip()
        if law_name and article_label:
            return f"{law_name} · {article_label}"
        return law_name or article_label

    def _favorite_search_request(
        self, item: QTreeWidgetItem
    ) -> tuple[str, str] | None:
        """Return the resource-search target and title for a favorite item."""
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path:
            return None
        record = self.law_cache.load(str(path))
        if not isinstance(record, dict):
            return None
        row = record.get("row")
        row = row if isinstance(row, dict) else {}
        raw_target = str(row.get("target") or "law")
        if raw_target not in ("law", "admrul"):
            return None
        name = str(
            row.get("title")
            or row.get("name")
            or record.get("name")
            or item.text(0)
        ).strip()
        return (raw_target, name) if name else None

    def _create_favorite_folder(self, category: str = "") -> None:
        if self.search_input.text().strip():
            self.status_label.setText("검색어를 지운 뒤 폴더를 편집해 주세요.")
            return
        if category:
            self._activate_favorite_category(category)
        name, accepted = QInputDialog.getText(
            self, "새 즐겨찾기 폴더", "폴더 이름:"
        )
        name = name.strip()
        if not accepted or not name:
            return
        tree = self.favorite_tree
        if tree is None:
            return
        selected = tree.currentItem()
        kind = (
            selected.data(0, self.FAVORITE_KIND_ROLE)
            if selected is not None
            else ""
        )
        if kind != "folder":
            selected = None
        category = self._active_favorite_category
        folder = {
            "id": uuid.uuid4().hex,
            "name": name,
            "category": category,
            "children": [],
        }
        item = self._favorite_folder_item(folder)
        if selected is None:
            tree.addTopLevelItem(item)
        else:
            selected.addChild(item)
            selected.setExpanded(True)
        tree.setCurrentItem(item)
        self._persist_favorite_tree("새 즐겨찾기 폴더를 만들었습니다.")

    def _rename_favorite_folder(self) -> None:
        tree = self.favorite_tree
        item = tree.currentItem() if tree is not None else None
        if (
            item is None
            or item.data(0, self.FAVORITE_KIND_ROLE) != "folder"
            or self.search_input.text().strip()
        ):
            return
        name, accepted = QInputDialog.getText(
            self, "즐겨찾기 폴더 이름 변경", "새 폴더 이름:", text=item.text(0)
        )
        name = name.strip()
        if not accepted or not name or name == item.text(0):
            return
        item.setText(0, name)
        self._persist_favorite_tree("폴더 이름을 변경했습니다.")

    def _delete_favorite_folder(self) -> None:
        tree = self.favorite_tree
        item = tree.currentItem() if tree is not None else None
        if (
            tree is None
            or item is None
            or item.data(0, self.FAVORITE_KIND_ROLE) != "folder"
            or self.search_input.text().strip()
        ):
            return
        answer = QMessageBox.question(
            self,
            "즐겨찾기 폴더 삭제",
            f"'{item.text(0)}' 폴더를 삭제할까요?\n"
            "안의 즐겨찾기와 하위 폴더는 현재 구분의 상위 위치로 이동합니다.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        parent = item.parent()
        if parent is not None:
            insert_at = parent.indexOfChild(item)
            moved: list[QTreeWidgetItem] = []
            while item.childCount():
                moved.append(item.takeChild(0))
            parent.takeChild(insert_at)
            for offset, child in enumerate(moved):
                parent.insertChild(insert_at + offset, child)
            parent.setExpanded(True)
            tree.setCurrentItem(parent)
        else:
            insert_at = tree.indexOfTopLevelItem(item)
            moved = []
            while item.childCount():
                moved.append(item.takeChild(0))
            tree.takeTopLevelItem(insert_at)
            for offset, child in enumerate(moved):
                tree.insertTopLevelItem(insert_at + offset, child)
            tree.setCurrentItem(moved[0] if moved else None)
        self._persist_favorite_tree("폴더를 삭제하고 내용은 다른 폴더로 옮겼습니다.")

    def _remove_selected_favorite(self) -> None:
        if self._is_common_favorite_view():
            return
        tree = self.favorite_tree
        item = tree.currentItem() if tree is not None else None
        path = (
            item.data(0, Qt.ItemDataRole.UserRole)
            if item is not None
            and item.data(0, self.FAVORITE_KIND_ROLE) == "record"
            else None
        )
        if path:
            self._remove_favorite_path(str(path))

    def _remove_favorite_by_index(self, category: str, index: object) -> None:
        """즐겨찾기 항목의 × 버튼 클릭으로 바로 해제."""
        if self._is_common_favorite_view():
            return
        tree = self.favorite_trees.get(category)
        if tree is None:
            return
        item = tree.itemFromIndex(index)
        if item is None:
            return
        kind = item.data(0, self.FAVORITE_KIND_ROLE)
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path:
            return
        if kind == "article":
            unit = item.data(0, self.FAVORITE_UNIT_ROLE)
            if isinstance(unit, dict):
                QTimer.singleShot(
                    0,
                    lambda selected_path=str(path), selected_unit=dict(unit): (
                        self._remove_article_favorite(selected_path, selected_unit)
                    ),
                )
            return
        if kind != "record":
            return
        # 모델 이벤트 처리가 끝난 뒤 목록을 갱신해 클릭 중인 항목이
        # 즉시 사라져도 안전하게 처리한다.
        QTimer.singleShot(
            0,
            lambda selected_path=str(path): self._remove_favorite_path(
                selected_path
            ),
        )

    def _remove_article_favorite(
        self, path: str, unit: dict[str, object]
    ) -> None:
        record = self.law_cache.load(path)
        row = record.get("row") if isinstance(record, dict) else None
        if not isinstance(row, dict):
            self.status_label.setText("조항호목 즐겨찾기를 해제하지 못했습니다.")
            return
        label = str(unit.get("label") or "")
        if self.law_cache.set_article_favorite(
            row,
            str(unit.get("jo") or ""),
            label,
            False,
            hang=str(unit.get("hang") or ""),
            ho=str(unit.get("ho") or ""),
            mok=str(unit.get("mok") or ""),
        ):
            self.status_label.setText(f"{label} 즐겨찾기를 해제했습니다.")
        else:
            self.status_label.setText(
                f"즐겨찾기 해제에 실패했습니다: {self.law_cache.last_error}"
            )

    def _schedule_favorite_tree_persist(self) -> None:
        if (
            self._is_common_favorite_view()
            or self._populating_favorite_tree
            or self._favorite_tree_persist_pending
        ):
            return
        self._favorite_tree_persist_pending = True
        QTimer.singleShot(0, self._persist_scheduled_favorite_tree)

    def _persist_scheduled_favorite_tree(self) -> None:
        self._favorite_tree_persist_pending = False
        self._persist_favorite_tree("즐겨찾기 폴더와 표시 순서를 저장했습니다.")

    def _persist_favorite_tree(
        self, success_message: str, *, force: bool = False
    ) -> None:
        if (
            (self._is_common_favorite_view() and not force)
            or not self.favorite_trees
            or self._populating_favorite_tree
        ):
            return
        folders: list[dict[str, object]] = []
        layout: list[tuple[object, str, int]] = []
        article_layout: list[
            tuple[object, dict[str, object], str, int]
        ] = []

        self._populating_favorite_tree = True

        def read_folder(
            item: QTreeWidgetItem, category: str
        ) -> dict[str, object]:
            folder_id = str(item.data(0, self.FAVORITE_FOLDER_ID_ROLE) or "")
            children: list[dict[str, object]] = []
            record_order = 0
            for index in range(item.childCount()):
                child = item.child(index)
                if child.data(0, self.FAVORITE_KIND_ROLE) == "folder":
                    children.append(read_folder(child, category))
                    continue
                path = child.data(0, Qt.ItemDataRole.UserRole)
                if path:
                    if child.data(0, self.FAVORITE_KIND_ROLE) == "article":
                        unit = child.data(0, self.FAVORITE_UNIT_ROLE)
                        if isinstance(unit, dict):
                            article_layout.append(
                                (path, dict(unit), folder_id, record_order)
                            )
                    else:
                        layout.append((path, folder_id, record_order))
                    record_order += 1
            return {
                "id": folder_id,
                "name": item.text(0).strip(),
                "category": category,
                "children": children,
            }

        try:
            for category, label in self.FAVORITE_CATEGORIES:
                tree = self.favorite_trees[category]
                children: list[dict[str, object]] = []
                record_order = 0
                for index in range(tree.topLevelItemCount()):
                    child = tree.topLevelItem(index)
                    if child.data(0, self.FAVORITE_KIND_ROLE) == "folder":
                        children.append(read_folder(child, category))
                        continue
                    path = child.data(0, Qt.ItemDataRole.UserRole)
                    if path:
                        if child.data(0, self.FAVORITE_KIND_ROLE) == "article":
                            unit = child.data(0, self.FAVORITE_UNIT_ROLE)
                            if isinstance(unit, dict):
                                article_layout.append(
                                    (path, dict(unit), "", record_order)
                                )
                        else:
                            layout.append((path, category, record_order))
                        record_order += 1
                folders.append(
                    {
                        "id": category,
                        "name": label.replace("\n", " "),
                        "category": category,
                        "children": children,
                    }
                )
        finally:
            self._populating_favorite_tree = False
        self._save_favorite_folders(folders)
        article_saved = self.law_cache.set_article_favorite_layout(
            article_layout
        )
        if article_saved and self.law_cache.set_favorite_layout(layout):
            self.status_label.setText(success_message)
        else:
            self.status_label.setText(
                f"즐겨찾기 폴더 저장에 실패했습니다: {self.law_cache.last_error}"
            )

    def refresh(self) -> None:
        # 목록은 이름ㆍ구분ㆍ날짜ㆍ즐겨찾기 표시만 쓴다. 본문까지 들어
        # 있는 기록을 읽으면 저장 건수에 비례해 창 여는 시간이 늘어난다.
        # 실제로 열 때는 ``_open_path``가 그 파일만 다시 읽는다.
        self.records = (
            self.law_cache.favorite_entries()
            if self.favorites_only
            else self.law_cache.list_entries()
        )
        self._populate()
        if self.law_cache.last_error:
            self.status_label.setText(
                f"저장 목록을 읽지 못했습니다: {self.law_cache.last_error}"
            )
        elif self._is_union_favorites_visible():
            self.status_label.setText(
                "모든 프로젝트의 즐겨찾기입니다. 아래 항목을 위 칸이나 "
                "프로젝트 탭으로 끌어다 놓으면 담을 수 있습니다."
            )
        elif self.records and self.favorites_only:
            self.status_label.setText(
                "항목을 더블클릭하면 저장 본문을 즉시 엽니다(API 호출 없음)."
            )
        elif self.records:
            self.status_label.setText(
                "목록에서 항목을 누르면 저장 본문을 바로 엽니다(API 호출 없음)."
            )
        elif self.favorites_only:
            self.status_label.setText(
                "각 검색 화면의 제목 왼쪽 별을 눌러 즐겨찾기에 추가할 수 있습니다."
            )
        else:
            self.status_label.setText(
                "각 검색 화면에서 본문을 저장하면 이 목록에 표시됩니다."
            )

    def _populate(self) -> None:
        self._populating = True
        try:
            self._populate_records()
        finally:
            self._populating = False

    def _populate_records(self) -> None:
        query = self.search_input.text().strip().casefold()
        visible_records = []
        for record in self.records:
            record_type = self._record_type(record)
            record_name = self._record_name(record)
            if not query or query in f"{record_type} {record_name}".casefold():
                visible_records.append(record)
        if self.favorites_only:
            self._populate_favorite_tree(visible_records)
            self.count_label.setText(f"즐겨찾기 {len(visible_records)}건")
            self._favorite_tree_selection_changed()
            self._populate_union_favorites()
            return

        if self.table is None:
            return
        self.table.setRowCount(len(visible_records))
        for row_index, record in enumerate(visible_records):
            row = record.get("row")
            row = row if isinstance(row, dict) else {}
            type_item = QTableWidgetItem(self._record_type(record))
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            name_item = QTableWidgetItem(self._record_name(record))
            name_item.setData(Qt.ItemDataRole.UserRole, record.get("path"))
            effective_item = QTableWidgetItem(
                self._display_date(
                    record.get("effective_date")
                    or row.get("date")
                    or row.get("effective")
                )
            )
            saved_item = QTableWidgetItem(
                self._display_timestamp(record.get("saved_at"))
            )
            effective_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            saved_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row_index, 0, type_item)
            self.table.setItem(row_index, 1, name_item)
            self.table.setItem(row_index, 2, effective_item)
            self.table.setItem(row_index, 3, saved_item)
        self.count_label.setText(f"저장 내역 {len(visible_records)}건")
        if visible_records:
            self.table.selectRow(0)
    def _restore_favorite_widths(self) -> None:
        if self.favorite_splitter is None:
            return
        values: object = (
            self.settings.value("favorite_card_widths", [])
            if self.settings is not None
            else []
        )
        if isinstance(values, str):
            values = [part for part in values.split(",") if part.strip()]
        try:
            sizes = [int(value) for value in list(values or [])]
        except (TypeError, ValueError):
            sizes = []
        if (
            len(sizes) == len(self.FAVORITE_CATEGORIES)
            and all(size >= 0 for size in sizes)
            and sum(sizes) > 0
        ):
            self.favorite_splitter.setSizes(sizes)
        else:
            self.favorite_splitter.setSizes(
                [200] * len(self.FAVORITE_CATEGORIES)
            )
        self._sync_union_column_widths()

    def _sync_union_column_widths(self, *_args: object) -> None:
        if (
            self._syncing_union_widths
            or self.union_splitter is None
            or self.favorite_splitter is None
        ):
            return
        self._syncing_union_widths = True
        try:
            self.union_splitter.setSizes(self.favorite_splitter.sizes())
        finally:
            self._syncing_union_widths = False

    def _copy_union_widths_to_cards(self, *_args: object) -> None:
        if (
            self._syncing_union_widths
            or self.union_splitter is None
            or self.favorite_splitter is None
        ):
            return
        self._syncing_union_widths = True
        try:
            self.favorite_splitter.setSizes(self.union_splitter.sizes())
            self._save_favorite_widths()
        finally:
            self._syncing_union_widths = False

    def _save_favorite_widths(self, *_args: object) -> None:
        if self.favorite_splitter is None or self.settings is None:
            return
        self.settings.setValue(
            "favorite_card_widths", self.favorite_splitter.sizes()
        )
        self.settings.sync()
    def _remove_favorite_path(self, path: str) -> None:
        record = self.law_cache.load(path)
        if record is None:
            self.status_label.setText(
                "즐겨찾기 해제에 실패했습니다: "
                f"{self.law_cache.last_error or '저장 본문을 찾지 못했습니다.'}"
            )
            return
        row = record.get("row")
        if not isinstance(row, dict):
            self.status_label.setText(
                "즐겨찾기 해제에 실패했습니다: 저장 정보가 올바르지 않습니다."
            )
            return
        if self.law_cache.set_favorite(row, False):
            self.status_label.setText("즐겨찾기에서 빼습니다.")
        else:
            self.status_label.setText(
                f"즐겨찾기 해제에 실패했습니다: {self.law_cache.last_error}"
            )

    def _selection_changed(self) -> None:
        # 저장 본문은 로컬 파일이라 즉시 열 수 있다. 안내 문구를 보여 주고
        # 더블클릭을 기다리는 대신, 고르는 즉시 본문을 띄운다.
        if not self._populating:
            self.open_selected()

    def open_selected(self) -> None:
        path = None
        if self.favorites_only:
            item = (
                self.favorite_tree.currentItem()
                if self.favorite_tree is not None
                else None
            )
            if (
                item is not None
                and item.data(0, self.FAVORITE_KIND_ROLE) == "record"
            ):
                path = item.data(0, Qt.ItemDataRole.UserRole)
        elif self.table is not None:
            row_index = self.table.currentRow()
            item = self.table.item(row_index, 1) if row_index >= 0 else None
            path = (
                item.data(Qt.ItemDataRole.UserRole)
                if item is not None
                else None
            )
        if not path:
            return
        self._open_path(path)

    def _add_article_children(
        self, item: QTreeWidgetItem, record: dict[str, object]
    ) -> None:
        """법령 밑에 조문 즐겨찾기를 딸린 줄로 단다.

        조문은 따로 저장하지 않고 그 법령의 저장 파일 안에 얹혀 있다.
        그래서 목록에서도 법령 밑에 붙는다 — 열면 그 법령 본문이 뜬다.
        """
        entries = record.get("favorite_articles")
        if not isinstance(entries, list) or not entries:
            return
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            jo = str(entry.get("jo") or "").strip()
            if not jo:
                continue
            label = str(entry.get("label") or "") or f"제{jo}조"
            child = QTreeWidgetItem((label,))
            child.setData(0, Qt.ItemDataRole.UserRole, record.get("path"))
            child.setData(0, self.FAVORITE_KIND_ROLE, "article")
            child.setData(0, self.FAVORITE_ARTICLE_ROLE, jo)
            child.setData(
                0,
                self.FAVORITE_UNIT_ROLE,
                {
                    "jo": jo,
                    "hang": str(entry.get("hang") or ""),
                    "ho": str(entry.get("ho") or ""),
                    "mok": str(entry.get("mok") or ""),
                    "label": label,
                },
            )
            child.setToolTip(
                0, f"{label} · 누르면 열고, 별표를 누르면 해제합니다."
            )
            child.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            )
            item.addChild(child)
        item.setChildIndicatorPolicy(
            QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicatorWhenChildless
        )

    def _open_favorite_tree_item(
        self, item: QTreeWidgetItem, _column: int = 0
    ) -> None:
        if item.data(0, self.FAVORITE_KIND_ROLE) == "record":
            path = item.data(0, Qt.ItemDataRole.UserRole)
            if path:
                self._open_path(path)

    def _open_favorite_article_item(
        self, item: QTreeWidgetItem, _column: int = 0
    ) -> None:
        """조항호목 즐겨찾기를 두 번 누르면 저장 위치를 연다.

        한 번 누르면 열리게 두었더니 옆의 법령 즐겨찾기와 손이 달라져,
        고르려고 누른 것이 그냥 열려 버렸다.
        """
        if self._populating or item.data(
            0, self.FAVORITE_KIND_ROLE
        ) != "article":
            return
        path = item.data(0, Qt.ItemDataRole.UserRole)
        jo = str(item.data(0, self.FAVORITE_ARTICLE_ROLE) or "").strip()
        if path and jo:
            unit = item.data(0, self.FAVORITE_UNIT_ROLE)
            self._open_path(
                path,
                article_jo=jo,
                article_unit=dict(unit) if isinstance(unit, dict) else None,
            )
    def _open_path(
        self,
        path: object,
        *,
        article_jo: str = "",
        article_unit: dict[str, object] | None = None,
    ) -> None:
        record = self.law_cache.load(str(path))
        if record is None:
            QMessageBox.critical(
                self,
                "저장 본문 열기 실패",
                self.law_cache.last_error or "저장 파일을 읽지 못했습니다.",
            )
            return
        if article_jo:
            record = dict(record)
            record["favorite_article_jo"] = article_jo
            if article_unit is not None:
                record["favorite_article_unit"] = dict(article_unit)
        self.openRequested.emit(record)

    def open_folder(self) -> None:
        try:
            self.law_cache.directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(self, "저장 폴더 열기 실패", str(exc))
            return
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.law_cache.directory.resolve()))
        )

    @staticmethod
    def _delete_cache_files(directories: tuple[Path, ...]) -> tuple[int, list[str]]:
        deleted = 0
        errors: list[str] = []
        for directory in directories:
            try:
                root = directory.resolve()
            except OSError as exc:
                errors.append(f"{directory}: {exc}")
                continue
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                try:
                    resolved = path.resolve()
                    if root not in resolved.parents:
                        continue
                    resolved.unlink()
                    deleted += 1
                except OSError as exc:
                    errors.append(f"{path.name}: {exc}")
        return deleted, errors

    def _confirm_clear_all_caches(self) -> None:
        answer = QMessageBox.warning(
            self,
            "모든 캐시 삭제",
            "저장된 본문, 즐겨찾기, 검색목록과 인용 조문 캐시를 모두 삭제합니다.\n"
            "삭제한 내용은 복구할 수 없으며, 필요할 때 API로 다시 조회해야 합니다.\n\n"
            "계속하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        deleted, errors = self._delete_cache_files(
            (
                Path(self.law_cache.directory),
                LAW_REFERENCE_CACHE_DIR,
                SEARCH_RESULT_CACHE_DIR,
                ANNEX_FILE_CACHE_DIR,
            )
        )
        self.law_cache.changed.emit()
        self.allCachesDeleted.emit()
        self.refresh()
        if errors:
            QMessageBox.warning(
                self,
                "일부 캐시 삭제 실패",
                f"{deleted}개 파일을 삭제했지만 일부 파일은 삭제하지 못했습니다.\n\n"
                + "\n".join(errors[:8]),
            )
            return
        self.status_label.setText(f"모든 캐시를 삭제했습니다 · {deleted}개 파일")
