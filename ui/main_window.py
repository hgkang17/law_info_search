"""프로그램 본 창. 좌측 메뉴로 각 검색 화면을 오간다."""

from __future__ import annotations

from html import escape
from pathlib import Path
import sys
import time

from PySide6.QtCore import QEvent, QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QStackedWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from molit_cgm_expc_api import (
    AGENCIES,
    AGENCY_BY_TARGET,
    OC_KEY,
    AgencyConfig,
    _find_text,
)
from storage.cache import LawDocumentCache
from storage.paths import (
    LAW_CACHE_DIR,
)
from storage.recent import RecentSearchManager
from ui.about import AboutDialog
from ui.assets import (
    API_KEY_MANUAL_PATH,
    CHECK_ICON_PATH,
    LOGO_PATH,
    SPIN_DOWN_ICON_PATH,
    SPIN_UP_ICON_PATH,
)
from ui.tabs.ai_chat_panel import AiChatPanel, shutdown_ai_background_services
from ui.tabs.ai_search import AiLawSearchTab
from ui.tabs.law_search import LawSearchTab
from ui.tabs.resource_search import ResourceSearchTab
from ui.tabs.viewed_laws import ViewedLawsTab
from ui.theme import (
    apply_dark_title_bar,
    apply_workbench_color_tokens,
    register_bundled_pretendard_fonts,
)
from ui.widgets import (
    CornerCloseTabBar,
    GroupedNavigationList,
    TabClickActivator,
    TabStripScrollArea,
    close_hovered_reference_popup,
)
from utils.constants import APP_VERSION, FONT_FAMILY
from utils.formatting import body_to_html, detail_document_header, law_short_name
from utils.parsing import (
    search_terms,
)
from utils.updater import (
    ReleaseInfo,
    UpdateError,
    can_self_update,
    executable_location_is_writable,
    install_location_hint,
    is_newer_version,
    launch_staged_update,
    staged_update_path,
)
from workers.search_worker import (
    ApiWorker,
)
from workers.update_worker import UpdateCheckWorker, UpdateDownloadWorker


class LawSearchWindow(QMainWindow):
    COMPACT_NAVIGATION_WIDTH = 1100

    def __init__(self) -> None:
        super().__init__()
        register_bundled_pretendard_fonts()
        self.settings = QSettings(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            "CentralLawSearch",
            "CentralAgencyLawInterpretation",
        )
        saved_oc = self._load_saved_api_key()
        self.oc = saved_oc or OC_KEY
        self.has_saved_oc = bool(saved_oc)
        self.recent_search_manager = RecentSearchManager(self.settings, self)
        self.law_cache = LawDocumentCache(LAW_CACHE_DIR, self)
        self._active_document_token = ""
        self._open_document_descriptors: dict[str, dict[str, object]] = {}
        self._open_document_order: list[str] = []
        self._open_document_tab_signature: tuple[tuple[str, str, str], ...] = ()
        self._open_document_refresh_pending = False
        self._update_check_worker: UpdateCheckWorker | None = None
        self._update_download_worker: UpdateDownloadWorker | None = None
        self._update_progress_dialog: QProgressDialog | None = None
        self._update_check_silent = True

        self.setWindowTitle("국가법령정보 통합검색")
        self.setWindowIcon(QIcon(str(LOGO_PATH)))
        self.resize(1440, 860)
        self.setMinimumSize(900, 640)
        self._reading_chrome_expanded = False
        # 스타일시트를 창을 다 만든 뒤에 걸면 Qt가 완성된 위젯 나무 전체를
        # 2천 줄짜리 규칙과 다시 맞춰 본다(창 하나에 66ms). 먼저 걸어 두면
        # 위젯이 만들어질 때 제 몫만 맞춘다. 규칙을 읽는 비용 자체는
        # 0.1ms뿐이라 순서만 바꿔도 된다.
        self._apply_style()
        self._build_ui()
        self.resource_tab.query_input.setFocus()
        self._mouse_back_pressed = False
        # Esc는 포커스가 어디에 있든 같게 동작해야 한다. 조문 팝업이 뜬 직후에는
        # 포커스를 가진 위젯이 없고, 팝업 본문(QTextBrowser)은 Esc를 자체
        # 소비하므로 위젯 단축키로는 잡히지 않는다.
        application = QApplication.instance()
        if application is not None:
            application.installEventFilter(self)
        # 개발ㆍ테스트 창은 짧게 만들고 버리는 경우가 많다. 삭제된 창을
        # singleShot이 뒤늦게 부르지 않도록 배포 EXE에서만 예약한다.
        if can_self_update():
            QTimer.singleShot(2500, self._auto_check_for_updates)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # 본문은 밝은 화면을 유지하고, Windows 제목줄만 어둡게 맞춘다.
        apply_dark_title_bar(self)

    def _load_saved_api_key(self) -> str:
        # API 인증값은 QSettings에 평문으로 저장한다. 이전 버전의 DPAPI
        # 암호문은 더 이상 읽지 않으며 설정에 남지 않도록 정리한다.
        if self.settings.contains("oc_key_protected"):
            self.settings.remove("oc_key_protected")
            self.settings.sync()
        return str(self.settings.value("oc_key", "") or "").strip()

    def _store_api_key(self, value: str) -> None:
        self.settings.remove("oc_key_protected")
        if value:
            self.settings.setValue("oc_key", value)
        else:
            self.settings.remove("oc_key")
        self.settings.sync()

    def _escape_target_tabs(self) -> list:
        tabs = getattr(self, "tabs", None)
        if tabs is None:
            return []
        return [tabs.widget(index) for index in range(tabs.count())]

    def _handle_escape(self) -> bool:
        """Esc 처리. 검색창이 우선이고, 그다음은 커서 아래 조문 팝업."""
        focused = QApplication.focusWidget()
        for tab in self._escape_target_tabs():
            search_bar = getattr(tab, "detail_search", None)
            if search_bar is not None and focused is search_bar.query_input:
                search_bar.cancel_search()
                return True
        for tab in self._escape_target_tabs():
            if close_hovered_reference_popup(tab):
                return True
        return False

    def _handle_mouse_back(self) -> bool:
        """마우스 뒤로가기 버튼으로 현재 크게 보기 화면을 닫는다."""
        current_page = self.tabs.currentWidget()
        if current_page is self.resource_tab and self.resource_tab.is_keyword_category:
            current_page = self.ai_tabs.currentWidget()
        if current_page is None or not getattr(current_page, "_reading_mode", False):
            return False
        current_page._exit_reading_mode()
        return True

    def _refresh_oc_api_settings_button(self) -> None:
        """헤더 단추 글자·색을 키가 있는지로 맞춘다."""
        button = getattr(self, "oc_api_settings_button", None)
        if button is None:
            return
        has_key = bool(self.api_input.text().strip())
        button.setText("API 설정" if has_key else "API 설정 필요")
        button.setProperty("apiConfigured", has_key)
        button.style().unpolish(button)
        button.style().polish(button)

    def open_oc_api_settings(self) -> None:
        """법제처 인증키 입력 창을 연다."""
        self._refresh_oc_api_settings_button()
        self.api_input.setFocus()
        self.oc_api_dialog.exec()
        self._refresh_oc_api_settings_button()

    def apply_reading_mode_chrome(self, expanded: bool) -> None:
        """크게 보기에서도 열린 본문 띠는 남기고 왼쪽 메뉴만 접는다."""
        self._reading_chrome_expanded = expanded
        if hasattr(self, "header_card"):
            self.header_card.setVisible(True)
        self._update_adaptive_navigation()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_adaptive_navigation()

    def _update_adaptive_navigation(self) -> None:
        """좁은 Windows 창에서는 왼쪽 메뉴를 헤더 선택기로 바꾼다."""
        if not hasattr(self, "navigation_card") or not hasattr(
            self, "compact_navigation"
        ):
            return
        compact = self.width() < self.COMPACT_NAVIGATION_WIDTH
        expanded = self._reading_chrome_expanded
        self.navigation_card.setVisible(not compact and not expanded)
        self.compact_navigation.setVisible(compact and not expanded)

    def _compact_navigation_changed(self, index: int) -> None:
        target = self.compact_navigation.itemData(index)
        if target == "favorites":
            self._activate_favorites_page()
        elif target == "ai":
            self._activate_ai_review_page()
        elif target == "viewed":
            self._activate_viewed_laws_page()
        elif isinstance(target, int):
            self.navigation.setCurrentRow(target)

    def _sync_compact_navigation(self, *_args: object) -> None:
        if not hasattr(self, "compact_navigation"):
            return
        if self.favorite_navigation_button.isChecked():
            target: object = "favorites"
        elif self.ai_review_button.isChecked():
            target = "ai"
        elif self.viewed_laws_button.isChecked():
            target = "viewed"
        else:
            target = self.navigation.currentRow()
        index = self.compact_navigation.findData(target)
        if index < 0:
            return
        previous = self.compact_navigation.blockSignals(True)
        self.compact_navigation.setCurrentIndex(index)
        self.compact_navigation.blockSignals(previous)

    def _open_api_manual(self, *_args: object) -> None:
        """인증키 발급 안내를 기본 웹 브라우저로 연다."""
        if not API_KEY_MANUAL_PATH.is_file():
            QMessageBox.warning(
                self,
                "안내 파일 없음",
                "인증키 발급 안내 파일을 찾지 못했습니다.",
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(API_KEY_MANUAL_PATH)))

    def eventFilter(self, watched, event) -> bool:
        event_type = event.type()
        if (
            event_type == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.BackButton
            and self._handle_mouse_back()
        ):
            self._mouse_back_pressed = True
            event.accept()
            return True
        if (
            event_type == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.BackButton
            and self._mouse_back_pressed
        ):
            self._mouse_back_pressed = False
            event.accept()
            return True
        if (
            event_type in (QEvent.Type.KeyPress, QEvent.Type.ShortcutOverride)
            and event.key() == Qt.Key.Key_Escape
            and self._handle_escape()
        ):
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        self.setCentralWidget(central)

        header = QFrame()
        header.setObjectName("headerCard")
        self.header_card = header
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 8, 16, 8)
        header_layout.setSpacing(10)

        logo_label = QLabel()
        logo_label.setObjectName("logoLabel")
        logo_label.setFixedSize(36, 36)
        logo_pixmap = QPixmap(str(LOGO_PATH))
        if not logo_pixmap.isNull():
            logo_label.setPixmap(
                logo_pixmap.scaled(
                    36,
                    36,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

        self.open_documents_widget = QFrame()
        self.open_documents_widget.setObjectName("openDocumentsBar")
        self.open_documents_widget.setFixedHeight(38)
        self.open_documents_layout = QHBoxLayout(self.open_documents_widget)
        self.open_documents_layout.setContentsMargins(0, 0, 0, 0)
        self.open_documents_layout.setSpacing(5)
        self.open_documents_label = QLabel("열린 본문")
        self.open_documents_label.setObjectName("openDocumentsLabel")
        self.open_documents_label.setFixedWidth(58)
        self.open_documents_layout.addWidget(self.open_documents_label)

        # 닫기 × 를 탭 안에 단추로 달면 그만큼 제목 자리가 줄어 글자가
        # 왼쪽으로 밀린다. 모서리에 겹쳐 그려 제목은 가운데 그대로 둔다.
        self.open_document_tabs = CornerCloseTabBar()
        self.open_document_tabs.setObjectName("openDocumentTabs")
        self.open_document_tabs.closable_check = self._open_document_closable
        self.open_document_tabs.tabCloseRequested.connect(
            self._close_open_document_tab
        )
        self.open_document_tabs.setDrawBase(False)
        self.open_document_tabs.setExpanding(False)
        self.open_document_tabs.setMovable(True)
        self.open_document_tabs.setTabsClosable(False)
        self.open_document_tabs.setUsesScrollButtons(False)
        self.open_document_tabs.setElideMode(Qt.TextElideMode.ElideNone)
        self.open_document_tabs.setToolTip(
            "탭을 클릭하면 해당 본문으로 이동하고, 왼쪽 버튼으로 끌면 순서를 "
            "바꿀 수 있습니다. 휠 또는 가운데 버튼 끌기로 좌우 이동합니다."
        )
        # 누르는 순간이 아니라 뗄 때 연다. QTabBar는 누르자마자 현재
        # 탭을 바꿔서, 순서를 바꾸려고 끌기만 해도 그 본문이 열렸다.
        # 같은 탭 위에서 뗐고 그동안 거의 안 움직였을 때만 연다.
        self.open_document_click = TabClickActivator(self.open_document_tabs)
        self.open_document_click.activated.connect(
            self._open_document_tab_activated
        )
        self.open_document_click.settled.connect(
            self._restore_open_document_highlight
        )
        self.open_document_tabs.tabMoved.connect(self._open_document_tab_moved)
        self.open_document_tab_strip = TabStripScrollArea(
            self.open_document_tabs
        )
        self.open_document_tab_strip.setObjectName("openDocumentTabStrip")
        self.open_document_tab_strip.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        self.open_documents_layout.addWidget(self.open_document_tab_strip, 1)

        self.open_documents_empty = QLabel("열린 본문 없음")
        self.open_documents_empty.setObjectName("openDocumentsEmpty")
        self.open_documents_layout.addWidget(self.open_documents_empty, 1)
        header_layout.addWidget(logo_label)

        self.compact_navigation = QComboBox()
        self.compact_navigation.setObjectName("compactNavigation")
        self.compact_navigation.setAccessibleName("화면 선택")
        self.compact_navigation.setToolTip(
            "좁은 창에서 즐겨찾기·법령검색·AI·저장내역 화면을 전환합니다."
        )
        for label, target in (
            ("즐겨찾기", "favorites"),
            ("법령 검색", 1),
            ("중앙부처 질의회신", 2),
            ("법령 해석례", 3),
            ("판례 검색", 4),
            ("AI 에이전트", "ai"),
            ("저장 내역", "viewed"),
        ):
            self.compact_navigation.addItem(label, target)
        self.compact_navigation.setMinimumWidth(142)
        self.compact_navigation.setMaximumWidth(184)
        self.compact_navigation.activated.connect(
            self._compact_navigation_changed
        )
        self.compact_navigation.hide()
        header_layout.addWidget(self.compact_navigation)
        header_layout.addWidget(self.open_documents_widget, 1)

        self.oc_api_dialog = QDialog(self)
        self.oc_api_dialog.setObjectName("ocApiDialog")
        self.oc_api_dialog.setWindowTitle("법제처 API 설정")
        self.oc_api_dialog.setModal(True)
        self.oc_api_dialog.resize(520, 200)
        dialog_layout = QVBoxLayout(self.oc_api_dialog)
        dialog_layout.setContentsMargins(16, 16, 16, 16)
        dialog_layout.setSpacing(12)
        dialog_layout.addWidget(
            QLabel(
                "법제처 국가법령정보 공동활용(OPEN API) 인증키를 입력합니다."
            )
        )

        self.api_input = QLineEdit()
        self.api_input.setObjectName("ocApiKeyInput")
        self.api_input.setPlaceholderText("인증키 입력")
        self.api_input.setClearButtonEnabled(True)
        # 인증키는 화면 공유나 어깨너머로 그대로 노출되므로 기본은 가려 둔다.
        self.api_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_input.setText(self.oc)
        self.api_reveal_button = QPushButton("표시")
        self.api_reveal_button.setCheckable(True)
        self.api_reveal_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.api_reveal_button.setToolTip(
            "인증키를 화면에 보이거나 다시 가립니다."
        )
        self.api_reveal_button.toggled.connect(self._api_reveal_toggled)
        self.save_api_checkbox = QCheckBox("저장")
        self.save_api_checkbox.setToolTip(
            "체크하면 현재 Windows 사용자 설정에 API 인증키를 저장합니다."
        )
        self.save_api_checkbox.setChecked(self.has_saved_oc)
        self.api_input.textChanged.connect(self._api_value_changed)
        self.save_api_checkbox.toggled.connect(self._api_save_toggled)
        self.api_manual_button = QPushButton("?")
        self.api_manual_button.setObjectName("ocApiManualButton")
        self.api_manual_button.setFixedSize(28, 28)
        self.api_manual_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.api_manual_button.setAccessibleName("법제처 API 인증키 발급 안내")
        self.api_manual_button.setToolTip("법제처 API 인증키 발급 방법 보기")
        self.api_manual_button.clicked.connect(self._open_api_manual)

        key_row = QHBoxLayout()
        key_row.setSpacing(8)
        key_row.addWidget(self.api_input, 1)
        key_row.addWidget(self.api_reveal_button)
        key_row.addWidget(self.save_api_checkbox)
        key_row.addWidget(self.api_manual_button)
        dialog_layout.addLayout(key_row)
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_api_button = QPushButton("저장하고 닫기")
        close_api_button.clicked.connect(self.oc_api_dialog.accept)
        close_row.addWidget(close_api_button)
        dialog_layout.addLayout(close_row)

        self.oc_api_settings_button = QPushButton("API 설정")
        self.oc_api_settings_button.setObjectName("ocApiSettingsButton")
        self.oc_api_settings_button.setFixedHeight(28)
        self.oc_api_settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.oc_api_settings_button.setToolTip(
            "법제처 API 인증키를 입력합니다."
        )
        self.oc_api_settings_button.clicked.connect(self.open_oc_api_settings)
        header_layout.addWidget(self.oc_api_settings_button)
        self._refresh_oc_api_settings_button()
        self._header_card = header
        root.addWidget(header)

        self.tabs = QStackedWidget()
        self.tabs.setObjectName("mainPages")
        self.central_tab = LawSearchTab(
            "central",
            lambda: self.api_input.text(),
            self.recent_search_manager,
            self.law_cache,
            self.tabs,
        )
        self.expc_tab = LawSearchTab(
            "expc",
            lambda: self.api_input.text(),
            self.recent_search_manager,
            self.law_cache,
            self.tabs,
        )
        self.prec_tab = LawSearchTab(
            "prec",
            lambda: self.api_input.text(),
            self.recent_search_manager,
            self.law_cache,
            self.tabs,
        )
        self.resource_tab = ResourceSearchTab(
            lambda: self.api_input.text(),
            self.recent_search_manager,
            self.law_cache,
            self.tabs,
            settings=self.settings,
        )
        self.viewed_laws_tab = ViewedLawsTab(self.law_cache, self.tabs)
        self.viewed_laws_tab.openRequested.connect(self._open_viewed_law)
        self.viewed_laws_tab.allCachesDeleted.connect(
            self._clear_runtime_cache_state
        )
        self.favorites_tab = ViewedLawsTab(
            self.law_cache,
            self.tabs,
            favorites_only=True,
            settings=self.settings,
        )
        self.favorites_tab.openRequested.connect(self._open_favorite)
        self.favorites_tab.searchRequested.connect(
            self._search_favorite_in_resource_list
        )
        ai_container = QWidget()
        self.ai_container = ai_container
        ai_layout = QVBoxLayout(ai_container)
        ai_layout.setContentsMargins(0, 0, 0, 0)
        # 연관검색ㆍ직접검색 전환은 법령검색 탭의 카테고리 바가 맡으므로
        # 여기서는 탭바 없는 스택만 둔다.
        self.ai_tabs = QStackedWidget()
        self.ai_tabs.setObjectName("aiSubTabs")
        self.ai_search_tab = AiLawSearchTab(
            "ai_search",
            lambda: self.api_input.text(),
            self.recent_search_manager,
            self.law_cache,
            self.ai_tabs,
        )
        self.ai_related_tab = AiLawSearchTab(
            "ai_related",
            lambda: self.api_input.text(),
            self.recent_search_manager,
            self.law_cache,
            self.ai_tabs,
        )
        # 조문 참조 팝업과 3단비교는 법령검색 탭이 이미 갖고 있으므로
        # 키워드검색 탭은 링크만 넘겨 같은 화면을 재사용한다.
        self.ai_search_tab.reference_tab = self.resource_tab
        self.ai_related_tab.reference_tab = self.resource_tab
        self.ai_tabs.addWidget(self.ai_related_tab)
        self.ai_tabs.addWidget(self.ai_search_tab)
        ai_layout.addWidget(self.ai_tabs)
        # 키워드검색 화면을 법령검색 탭 안으로 넣는다. 왼쪽 주 메뉴에서는
        # 빠지고 카테고리 바의 연관검색ㆍ직접검색으로만 들어간다.
        self.resource_tab.attach_keyword_page(ai_container)
        self.resource_tab._keyword_page_selector = self._select_keyword_page
        # AI 검토 화면은 메뉴 목록이 아니라 별도 단추로 연다. 목록의 줄
        # 번호와 페이지 번호가 1:1로 묶여 있어 중간에 끼우면 기존 이동이
        # 모두 어긋난다.
        # 본문 옆 사이드 패널과 같은 클래스를 쓰지만, 이 독립 화면에는
        # 현재 본문을 자동으로 넣지 않는다. 필요한 법령은 검색 도구로 찾고,
        # 본문을 근거로 삼는 검토는 본문 안의 AI 패널에서만 수행한다.
        self.ai_review_tab = AiChatPanel(
            self.settings, standalone=True, parent=self.tabs
        )
        self.ai_review_tab.oc_provider = lambda: self.oc
        # 즐겨찾기 추가는 실제 검색 결과 테이블ㆍ저장 로직을 가진
        # resource_tab의 것을 그대로 쓴다. id만으로도 저장ㆍ즐겨찾기가
        # 되도록 만들어 둔 메서드라 검색 화면에 그 법령이 없어도 된다.
        self.ai_review_tab.favorite_handler = self.resource_tab.add_favorite_by_id
        self.ai_review_tab.favorite_checker = self.resource_tab.is_favorite_by_id
        self.ai_review_tab.article_favorite_handler = (
            self.resource_tab.add_article_favorite_by_id
        )
        self.ai_review_tab.article_favorite_checker = (
            self.resource_tab.is_article_favorite_by_id
        )
        self.ai_review_tab.reference_handler = self.resource_tab.open_reference_link
        self.ai_review_tab.document_cache = self.law_cache
        # 독립 AI 화면과 본문 안 AI 패널은 같은 저장 채팅을 쓴다. 한쪽에서
        # 이어 쓰거나 지우면 다른 쪽의 목록과 열린 대화도 즉시 맞춘다.
        embedded_chat = self.resource_tab.ai_chat_panel
        self.ai_review_tab.chatHistoryChanged.connect(
            embedded_chat.apply_external_history_change
        )
        embedded_chat.chatHistoryChanged.connect(
            self.ai_review_tab.apply_external_history_change
        )
        self.ai_review_tab.chatHistoryCleared.connect(
            embedded_chat.apply_external_history_clear
        )
        embedded_chat.chatHistoryCleared.connect(
            self.ai_review_tab.apply_external_history_clear
        )
        for page in (
            self.favorites_tab,
            self.resource_tab,
            self.central_tab,
            self.expc_tab,
            self.prec_tab,
            self.viewed_laws_tab,
            self.ai_review_tab,
        ):
            self.tabs.addWidget(page)

        navigation_card = QFrame()
        navigation_card.setObjectName("navigationCard")
        navigation_card.setFixedWidth(136)
        self.navigation_card = navigation_card
        navigation_layout = QVBoxLayout(navigation_card)
        navigation_layout.setContentsMargins(7, 10, 7, 10)
        navigation_layout.setSpacing(4)

        navigation_title = QLabel("MAIN MENU")
        navigation_title.setObjectName("navigationTitle")
        navigation_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.favorite_navigation_button = QPushButton("★\n즐겨찾기")
        self.favorite_navigation_button.setObjectName(
            "favoriteNavigationButton"
        )
        self.favorite_navigation_button.setCheckable(True)
        self.favorite_navigation_button.setFixedHeight(58)
        self.favorite_navigation_button.setToolTip(
            "즐겨찾기로 표시한 저장 본문을 모아 봅니다."
        )

        self.navigation = GroupedNavigationList()
        self.navigation.setObjectName("mainNavigation")
        self.navigation.setAccessibleName("주 메뉴")
        self.navigation.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.navigation.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        # 두 메뉴 묶음 사이와 목록 위·아래에 같은 여백을 분배한다.
        self.navigation.setSpacing(4)
        self.navigation.addItems(
            (
                "★\n즐겨찾기",
                "법령\n검색",
                "중앙부처\n질의회신",
                "법령\n해석례",
                "판례\n검색",
            )
        )
        self.navigation.item(0).setHidden(True)
        for index in range(self.navigation.count()):
            self.navigation.item(index).setTextAlignment(
                Qt.AlignmentFlag.AlignCenter
            )
        self.navigation.set_group_ranges([(1, 1), (2, 4)])
        self.viewed_laws_button = QPushButton("저장\n내역")
        self.viewed_laws_button.setObjectName("viewedLawsNavigationButton")
        self.viewed_laws_button.setCheckable(True)
        self.viewed_laws_button.setFixedHeight(58)
        self.viewed_laws_button.setToolTip(
            "저장된 법령·조문·질의회신·해석례·판례를 API 호출 없이 엽니다."
        )
        self.favorite_navigation_button.clicked.connect(
            self._activate_favorites_page
        )
        self.navigation.currentRowChanged.connect(
            self._main_navigation_changed
        )
        self.viewed_laws_button.clicked.connect(
            self._activate_viewed_laws_page
        )
        self.ai_review_button = QPushButton("AI\n에이전트")
        self.ai_review_button.setObjectName("aiReviewNavigationButton")
        self.ai_review_button.setCheckable(True)
        self.ai_review_button.setFixedHeight(58)
        self.ai_review_button.setToolTip(
            "AI 에이전트에게 법령 검토를 요청합니다. 필요한 법령은 AI가 직접 검색합니다."
        )
        self.ai_review_button.clicked.connect(self._activate_ai_review_page)
        navigation_layout.addWidget(navigation_title)
        navigation_layout.addWidget(self.favorite_navigation_button)
        navigation_layout.addSpacing(8)
        navigation_layout.addWidget(self.navigation, 1)
        navigation_layout.addSpacing(8)
        navigation_layout.addWidget(self.ai_review_button)
        navigation_layout.addWidget(self.viewed_laws_button)
        self.navigation.setCurrentRow(1)

        body_layout = QHBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(12)
        body_layout.addWidget(navigation_card)
        body_layout.addWidget(self.tabs, 1)
        root.addLayout(body_layout, 1)

        # 오픈소스 고지는 배포 조건이라 화면 어딘가에서 항상 닿을 수
        # 있어야 한다. 본문을 가리지 않도록 창 오른쪽 아래에만 둔다.
        self.about_button = QPushButton("프로그램 정보ㆍ라이선스")
        self.about_button.setObjectName("aboutLinkButton")
        self.about_button.setFlat(True)
        self.about_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.about_button.setToolTip(
            "버전ㆍ자료 출처ㆍ사용한 오픈소스 라이선스를 확인합니다."
        )
        self.about_button.clicked.connect(self._show_about_dialog)

        self.update_button = QPushButton("업데이트 확인")
        self.update_button.setObjectName("updateLinkButton")
        self.update_button.setFlat(True)
        self.update_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_button.setToolTip(
            f"현재 버전 {APP_VERSION} · GitHub Releases에서 최신 버전을 확인합니다."
        )
        self.update_button.clicked.connect(self._manual_check_for_updates)

        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(10)
        footer_layout.addStretch(1)
        footer_layout.addWidget(self.update_button)
        footer_layout.addWidget(self.about_button)
        root.addLayout(footer_layout)

        self._bind_open_document_tracking()
        self._refresh_open_documents()
        self.tabs.currentChanged.connect(self._sync_compact_navigation)
        self._sync_compact_navigation()
        self._update_adaptive_navigation()

    def _bind_open_document_tracking(self) -> None:
        """각 검색 화면의 본문 변화가 전역 본문 표시줄에 반영되게 한다."""
        self.tabs.currentChanged.connect(self._schedule_open_documents_refresh)
        self.ai_tabs.currentChanged.connect(self._schedule_open_documents_refresh)
        for tab in (
            self.resource_tab,
            self.ai_search_tab,
            self.ai_related_tab,
            self.central_tab,
            self.expc_tab,
            self.prec_tab,
        ):
            view = getattr(tab, "detail_view", None)
            if view is not None:
                view.textChanged.connect(self._schedule_open_documents_refresh)
        self.resource_tab.document_tabs.currentChanged.connect(
            self._schedule_open_documents_refresh
        )
        self.resource_tab.document_tabs.tabCloseRequested.connect(
            lambda _index: QTimer.singleShot(
                0, self._schedule_open_documents_refresh
            )
        )

    def _schedule_open_documents_refresh(self, *_args: object) -> None:
        if self._open_document_refresh_pending:
            return
        self._open_document_refresh_pending = True
        QTimer.singleShot(0, self._refresh_open_documents)

    @staticmethod
    def _document_title(row: dict[str, object], fallback: str) -> tuple[str, str]:
        full = str(row.get("name") or row.get("title") or fallback).strip()
        official_short = str(
            row.get("short_name")
            or row.get("법령약칭명")
            or row.get("자치법규약칭명")
            or ""
        ).strip()
        short = law_short_name(full, official_short)
        provision = str(row.get("provision") or "").strip()
        if provision and provision not in short:
            short = f"{short} {provision}"
        return short, full

    @staticmethod
    def _two_line_open_document_title(value: str) -> str:
        """제목을 생략하지 않고 읽기 좋은 두 줄로 나눈다."""
        title = " ".join(value.split())
        if len(title) <= 8:
            return title
        midpoint = len(title) / 2
        spaces = [
            index for index, character in enumerate(title) if character == " "
        ]
        split_at = (
            min(spaces, key=lambda index: abs(index - midpoint))
            if spaces
            else max(1, round(midpoint))
        )
        return f"{title[:split_at].rstrip()}\n{title[split_at:].lstrip()}"

    def _collect_open_documents(self) -> list[dict[str, object]]:
        documents: list[dict[str, object]] = []
        resource = self.resource_tab
        for key, state in resource._document_states.items():
            if key == "__preview__" or not isinstance(state, dict):
                continue
            row = state.get("row")
            if not isinstance(row, dict):
                continue
            text = str(state.get("plain_text") or "")
            if key == resource._active_document_key:
                text = resource.current_detail_text or text
            if not text.strip():
                continue
            short, full = self._document_title(row, "법령 본문")
            documents.append(
                {
                    "token": f"resource:{key}",
                    "source": "resource",
                    "key": key,
                    "short": short,
                    "full": full,
                    "text": text,
                    "view": resource.detail_view,
                }
            )

        for source, tab, fallback in (
            ("ai_related", self.ai_related_tab, "연관법령"),
            ("ai_search", self.ai_search_tab, "직접검색"),
            ("central", self.central_tab, "중앙부처 질의회신"),
            ("expc", self.expc_tab, "법령해석례"),
            ("prec", self.prec_tab, "판례"),
        ):
            row = getattr(tab, "_active_detail_row", None)
            text = str(getattr(tab, "current_detail_text", "") or "")
            if not isinstance(row, dict) or not text.strip():
                continue
            short, full = self._document_title(row, fallback)
            identity = str(
                row.get("id")
                or row.get("source_id")
                or row.get("name")
                or row.get("title")
                or fallback
            )
            documents.append(
                {
                    "token": f"{source}:{identity}",
                    "source": source,
                    "key": identity,
                    "short": short,
                    "full": full,
                    "text": text,
                    "view": tab.detail_view,
                }
            )
        return documents

    def _visible_document_token(
        self, documents: list[dict[str, object]]
    ) -> str:
        current = self.tabs.currentWidget()
        source = ""
        key = ""
        if current is self.resource_tab and self.resource_tab.is_keyword_category:
            source = (
                "ai_related"
                if self.ai_tabs.currentWidget() is self.ai_related_tab
                else "ai_search"
            )
        elif current is self.resource_tab:
            source = "resource"
            key = self.resource_tab._active_document_key
        elif current is self.central_tab:
            source = "central"
        elif current is self.expc_tab:
            source = "expc"
        elif current is self.prec_tab:
            source = "prec"
        for document in documents:
            if document["source"] != source:
                continue
            if source == "resource" and document["key"] != key:
                continue
            return str(document["token"])
        return ""

    def _set_active_document_token(self, token: str) -> None:
        if not token or token == self._active_document_token:
            return
        self._active_document_token = token

    def _open_document_tab_activated(self, index: int) -> None:
        """탭을 눌렀다 뗐다. 이미 보고 있던 본문이어도 다시 연다.

        크게 보기에서 빠져나온 뒤 같은 본문을 다시 누르면 아무 일도
        일어나지 않던 문제가 있어, 같은 탭도 그대로 연다.
        """
        token = str(self.open_document_tabs.tabData(index) or "")
        if token:
            self._activate_open_document(token)

    def _restore_open_document_highlight(self) -> None:
        """열지 않고 끝난 누름(끌기 등)의 강조 표시를 되돌린다."""
        for index in range(self.open_document_tabs.count()):
            if (
                str(self.open_document_tabs.tabData(index) or "")
                == self._active_document_token
            ):
                self.open_document_tabs.blockSignals(True)
                self.open_document_tabs.setCurrentIndex(index)
                self.open_document_tabs.blockSignals(False)
                return

    def _open_document_tab_moved(self, _source: int, _target: int) -> None:
        """사용자가 끈 현재 탭 순서를 다음 화면 갱신에서도 유지한다."""
        self._open_document_order = [
            str(self.open_document_tabs.tabData(index) or "")
            for index in range(self.open_document_tabs.count())
            if self.open_document_tabs.tabData(index)
        ]

    def _refresh_open_documents(self) -> None:
        self._open_document_refresh_pending = False
        documents = self._collect_open_documents()
        visible_token = self._visible_document_token(documents)
        known_tokens = {str(item["token"]) for item in documents}
        if visible_token:
            self._set_active_document_token(visible_token)
        elif self._active_document_token not in known_tokens:
            self._active_document_token = (
                str(documents[0]["token"]) if documents else ""
            )

        # 선택한 탭을 맨 앞으로 보내지 않는다. 기존 순서는 그대로 두고
        # 새로 열린 본문만 끝에 붙인다.
        self._open_document_order = [
            token for token in self._open_document_order if token in known_tokens
        ]
        for document in documents:
            token = str(document["token"])
            if token not in self._open_document_order:
                self._open_document_order.append(token)
        order = {
            token: position
            for position, token in enumerate(self._open_document_order)
        }
        documents.sort(key=lambda item: order[str(item["token"])])
        self._open_document_descriptors = {
            str(item["token"]): item for item in documents
        }

        tab_signature = tuple(
            (
                str(document["token"]),
                self._two_line_open_document_title(str(document["short"])),
                str(document["full"]),
            )
            for document in documents
        )
        active_index = next(
            (
                index
                for index, document in enumerate(documents)
                if document["token"] == self._active_document_token
            ),
            -1,
        )
        if tab_signature == self._open_document_tab_signature:
            if (
                active_index >= 0
                and self.open_document_tabs.currentIndex() != active_index
            ):
                self.open_document_tabs.blockSignals(True)
                self.open_document_tabs.setCurrentIndex(active_index)
                self.open_document_tabs.blockSignals(False)
                self.open_document_tab_strip.ensure_visible(
                    self.open_document_tabs.tabRect(active_index)
                )
            return

        self.open_document_tabs.blockSignals(True)
        while self.open_document_tabs.count():
            self.open_document_tabs.removeTab(
                self.open_document_tabs.count() - 1
            )
        for document in documents:
            token = str(document["token"])
            index = self.open_document_tabs.addTab(
                self._two_line_open_document_title(
                    str(document["short"])
                )
            )
            self.open_document_tabs.setTabData(index, token)
            self.open_document_tabs.setTabToolTip(
                index,
                f"{document['full']}\n클릭하면 이 본문으로 이동합니다. "
                "끌어서 순서를 바꿀 수 있습니다.",
            )
            if token == self._active_document_token:
                active_index = index
        self._open_document_tab_signature = tab_signature
        if active_index >= 0:
            self.open_document_tabs.setCurrentIndex(active_index)
        self.open_document_tabs.blockSignals(False)

        self.open_document_tab_strip.setVisible(bool(documents))
        self.open_documents_empty.setVisible(not documents)
        if documents:
            self.open_document_tab_strip.refresh()
            if active_index >= 0:
                self.open_document_tab_strip.ensure_visible(
                    self.open_document_tabs.tabRect(active_index)
                )

    def _open_document_descriptor_at(self, index: int) -> dict[str, object] | None:
        token = str(self.open_document_tabs.tabData(index) or "")
        document = self._open_document_descriptors.get(token)
        return document if isinstance(document, dict) else None

    # 표시줄에서 직접 닫을 수 있는 항목. 법령 본문은 화면 안 탭을 지우고,
    # 질의회신ㆍ해석례ㆍ판례는 화면에 붙은 본문 칸을 비운다. 연관검색ㆍ
    # 직접검색은 검색어를 바꾸면 결과가 통째로 바뀌는 화면이라 뺀다.
    _CLOSABLE_DOCUMENT_TABS = {
        "central": "central_tab",
        "expc": "expc_tab",
        "prec": "prec_tab",
    }

    def _open_document_closable(self, index: int) -> bool:
        """표시줄에서 닫을 수 있는 항목인지 알려 준다."""
        document = self._open_document_descriptor_at(index)
        if not document:
            return False
        source = str(document.get("source"))
        return source == "resource" or source in self._CLOSABLE_DOCUMENT_TABS

    def _close_open_document_tab(self, index: int) -> None:
        document = self._open_document_descriptor_at(index)
        if document is None:
            return
        source = str(document.get("source"))
        if source == "resource":
            self.resource_tab._close_document_tab_by_key(str(document["key"]))
            return
        attribute = self._CLOSABLE_DOCUMENT_TABS.get(source)
        if attribute is None:
            return
        tab = getattr(self, attribute, None)
        close = getattr(tab, "close_open_document", None)
        if close is None:
            return
        close()
        # 본문 탭 쪽은 자기 화면이 알아서 갱신을 예약한다. 이쪽은
        # 표시줄만 바뀌므로 여기서 직접 예약한다.
        self._schedule_open_documents_refresh()

    def _activate_open_document(self, token: str) -> None:
        document = self._open_document_descriptors.get(token)
        if document is None:
            return
        source = str(document["source"])
        if source == "resource":
            # 자리를 옮기기 전에 지금 어디였는지 붙들어 둔다.
            existing_restorer = getattr(
                self.resource_tab, "_reading_mode_exit_callback", None
            )
            restorer = (
                existing_restorer
                if self.resource_tab._reading_mode and existing_restorer is not None
                else self._current_page_restorer()
            )
            self.navigation.setCurrentRow(1)
            index = self.resource_tab._document_tab_index(str(document["key"]))
            if index >= 0:
                self.resource_tab.document_tabs.setCurrentIndex(index)
                self.resource_tab._activate_document_tab(index)
                self.resource_tab._reading_mode_exit_callback = restorer
                self.resource_tab._set_reading_mode(True)
        elif source in {"ai_related", "ai_search"}:
            self._show_keyword_category(source)
        else:
            row = {"central": 2, "expc": 3, "prec": 4}.get(source)
            if row is not None:
                self.navigation.setCurrentRow(row)
        self._set_active_document_token(token)
        self._schedule_open_documents_refresh()

    def _current_page_restorer(self):
        """지금 보고 있는 왼쪽 메뉴 자리로 되돌아가는 함수를 만들어 둔다.

        본문을 크게 보기로 열면 화면이 통째로 본문으로 바뀐다. ◀로
        빠져나올 때 늘 즐겨찾기로 가 버리면, AI 에이전트에서 본문을 연
        사람은 자기가 있던 자리를 잃는다. 그래서 들어가기 전에 어디에
        있었는지를 함수로 붙들어 둔다.
        """
        if self.favorite_navigation_button.isChecked():
            return self._activate_favorites_page
        if self.viewed_laws_button.isChecked():
            return self._activate_viewed_laws_page
        if self.ai_review_button.isChecked():
            return self._activate_ai_review_page
        row = self.navigation.currentRow()
        if row < 0:
            return None

        def restore(*_args: object, row: int = row) -> None:
            self.navigation.setCurrentRow(row)
            self._main_navigation_changed(row)

        return restore

    def _show_about_dialog(self) -> None:
        AboutDialog(self).exec()

    def _auto_check_for_updates(self) -> None:
        if not can_self_update():
            return
        try:
            last_check = float(
                self.settings.value("updates/last_check_epoch", 0) or 0
            )
        except (TypeError, ValueError):
            last_check = 0
        now = time.time()
        if now - last_check < 6 * 60 * 60:
            return
        self.settings.setValue("updates/last_check_epoch", now)
        self._start_update_check(silent=True)

    def _manual_check_for_updates(self, *_args: object) -> None:
        if not can_self_update():
            QMessageBox.information(
                self,
                "업데이트 확인",
                "자동 업데이트는 Windows 배포용 EXE에서 실행할 때 사용할 수 있습니다.",
            )
            return
        self._start_update_check(silent=False)

    def _start_update_check(self, *, silent: bool) -> None:
        running = self._update_check_worker
        if running is not None and running.isRunning():
            if not silent:
                QMessageBox.information(
                    self, "업데이트 확인", "이미 최신 버전을 확인하고 있습니다."
                )
            return
        self._update_check_silent = silent
        self.update_button.setEnabled(False)
        self.update_button.setText("확인 중…")
        worker = UpdateCheckWorker(self)
        self._update_check_worker = worker
        worker.resultReady.connect(self._update_check_result)
        worker.failed.connect(self._update_check_failed)
        worker.finished.connect(self._update_check_finished)
        worker.start()

    def _update_check_result(self, value: object) -> None:
        if not isinstance(value, ReleaseInfo):
            self._update_check_failed("릴리스 정보 형식이 올바르지 않습니다.")
            return
        try:
            newer = is_newer_version(value.version, APP_VERSION)
        except UpdateError as error:
            self._update_check_failed(str(error))
            return
        if not newer:
            if not self._update_check_silent:
                QMessageBox.information(
                    self,
                    "업데이트 확인",
                    f"현재 {APP_VERSION} 버전이 최신입니다.",
                )
            return

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("새 업데이트")
        box.setText(
            f"새 버전 {value.version}을 사용할 수 있습니다.\n"
            f"현재 버전: {APP_VERSION}"
        )
        box.setInformativeText(
            "지금 업데이트하면 파일을 안전하게 확인한 뒤 프로그램을 다시 시작합니다."
        )
        if value.notes.strip():
            box.setDetailedText(value.notes.strip())
        confirm_button = box.addButton("확인", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(confirm_button)
        self._localize_message_box(box)
        box.exec()
        if box.clickedButton() is confirm_button:
            self._start_update_download(value)

    @staticmethod
    def _localize_message_box(box: QMessageBox, minimum_width: int = 380) -> None:
        """상세 보기 단추를 한글로 바꾸고 단추 글자가 잘리지 않게 넓힌다.

        setDetailedText가 만드는 단추는 Qt가 직접 붙이는 것이라 우리가 이름을
        정할 수 없고, 번역 파일 없이는 "Show Details..."로 나온다. 역할이
        ActionRole인 단추가 그것 하나뿐이라 그것을 찾아 이름을 바꾼다.

        QMessageBox는 글의 폭에만 맞춰 창을 잡아서, 단추가 늘어나면 이름이
        잘린다. 눈에 보이지 않는 빈 칸을 격자 맨 아래에 깔아 최소 폭을 준다.
        """
        for button in box.buttons():
            if box.buttonRole(button) == QMessageBox.ButtonRole.ActionRole:
                button.setText("자세히")
        layout = box.layout()
        if layout is not None:
            layout.addItem(
                QSpacerItem(
                    minimum_width,
                    0,
                    QSizePolicy.Policy.Minimum,
                    QSizePolicy.Policy.Expanding,
                ),
                layout.rowCount(),
                0,
                1,
                layout.columnCount(),
            )

    def _update_check_failed(self, message: str) -> None:
        if not self._update_check_silent:
            QMessageBox.warning(self, "업데이트 확인 실패", message)

    def _update_check_finished(self) -> None:
        worker = self._update_check_worker
        self._update_check_worker = None
        self.update_button.setEnabled(True)
        self.update_button.setText("업데이트 확인")
        if worker is not None:
            worker.deleteLater()

    def _start_update_download(self, release: ReleaseInfo) -> None:
        running = self._update_download_worker
        if running is not None and running.isRunning():
            return
        # 76MB를 다 받고 나서야 권한이 없다는 것을 알면 시간만 버린다.
        # 프로그램이 있는 자리에 파일을 쓸 수 있는지 먼저 확인한다.
        if not executable_location_is_writable():
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("업데이트할 수 없음")
            box.setText(
                "지금 자리에서는 프로그램 파일을 바꿀 수 없어 업데이트를 "
                "시작하지 않았습니다."
            )
            box.setInformativeText(
                f"위치: {Path(sys.executable).parent}"
                f"{chr(10)}{chr(10)}"
                f"{install_location_hint(Path(sys.executable))}"
            )
            box.addButton("확인", QMessageBox.ButtonRole.AcceptRole)
            self._localize_message_box(box)
            box.exec()
            return
        destination = staged_update_path(release)
        dialog = QProgressDialog(
            "업데이트 파일을 다운로드하고 있습니다.",
            "취소",
            0,
            release.asset_size,
            self,
        )
        dialog.setObjectName("updateProgressDialog")
        dialog.setWindowTitle(f"{release.version} 업데이트")
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)

        worker = UpdateDownloadWorker(release, destination, self)
        self._update_download_worker = worker
        self._update_progress_dialog = dialog
        worker.progressChanged.connect(dialog.setValue)
        worker.resultReady.connect(
            lambda path: self._update_download_ready(path, release)
        )
        worker.failed.connect(self._update_download_failed)
        worker.cancelled.connect(self._update_download_cancelled)
        worker.finished.connect(self._update_download_finished)
        dialog.canceled.connect(worker.cancel)
        dialog.show()
        worker.start()

    def _close_update_progress(self) -> None:
        dialog = self._update_progress_dialog
        self._update_progress_dialog = None
        if dialog is not None:
            dialog.close()
            dialog.deleteLater()

    def _update_download_ready(
        self, path: str, release: ReleaseInfo
    ) -> None:
        self._close_update_progress()
        try:
            launch_staged_update(path, release.tag_name, release.sha256)
        except UpdateError as error:
            QMessageBox.critical(self, "업데이트 실패", str(error))
            return
        QApplication.quit()

    def _update_download_failed(self, message: str) -> None:
        self._close_update_progress()
        QMessageBox.warning(self, "업데이트 실패", message)

    def _update_download_cancelled(self) -> None:
        self._close_update_progress()

    def _update_download_finished(self) -> None:
        worker = self._update_download_worker
        self._update_download_worker = None
        if worker is not None:
            worker.deleteLater()

    def _select_keyword_page(self, target: str) -> None:
        """카테고리 바가 고른 연관검색ㆍ직접검색 화면을 띄운다."""
        self.ai_tabs.setCurrentWidget(
            self.ai_related_tab if target == "ai_related" else self.ai_search_tab
        )

    def _show_keyword_category(self, target: str) -> None:
        """법령검색 탭으로 옮기고 연관검색ㆍ직접검색 카테고리를 고른다."""
        # 같은 메인 페이지 안에서는 navigation 신호가 다시 나지 않는다.
        # 이때 다른 키워드 화면의 크게 보기 상태를 남겨 두면 공용 메뉴와
        # 카테고리 바가 숨은 채 새 화면만 바뀌어 서로 겹친다.
        if self.resource_tab.category_target != target:
            self._reset_reading_modes_for_page_change()
        self.navigation.setCurrentRow(1)
        self.resource_tab.select_category(target)

    def _reset_reading_modes_for_page_change(self) -> None:
        """메인 화면을 바꿀 때 다른 탭에 남은 크게 보기 상태를 정리한다.

        크게 보기는 창 공용 머리말과 왼쪽 메뉴를 숨긴다. 다른 본문 화면이
        그 공용 영역을 다시 보인 뒤 예전 탭으로 돌아오면, 탭의 내부 플래그만
        True인 채 남아 카테고리 바와 본문 카드가 서로 다른 상태로 겹칠 수
        있다. 메인 메뉴 이동은 명시적인 화면 전환이므로 모든 크게 보기를
        정상 화면으로 돌리고, 예전 화면으로 되돌리는 콜백도 버린다.
        """
        reading_tabs = (
            self.resource_tab,
            self.ai_related_tab,
            self.ai_search_tab,
            self.central_tab,
            self.expc_tab,
            self.prec_tab,
        )
        for tab in reading_tabs:
            if hasattr(tab, "_reading_mode_exit_callback"):
                tab._reading_mode_exit_callback = None
        for tab in reading_tabs:
            if getattr(tab, "_reading_mode", False):
                tab._set_reading_mode(False)

    def _main_navigation_changed(self, row: int) -> None:
        if row < 0:
            return
        self._reset_reading_modes_for_page_change()
        self.favorite_navigation_button.setChecked(False)
        self.viewed_laws_button.setChecked(False)
        self.ai_review_button.setChecked(False)
        self.tabs.setCurrentIndex(row)
        self._sync_compact_navigation()

    def _activate_ai_review_page(self, *_args: object) -> None:
        self._reset_reading_modes_for_page_change()
        self.navigation.blockSignals(True)
        self.navigation.setCurrentRow(-1)
        self.navigation.clearSelection()
        self.navigation.blockSignals(False)
        self.favorite_navigation_button.setChecked(False)
        self.viewed_laws_button.setChecked(False)
        self.ai_review_button.setChecked(True)
        self.tabs.setCurrentIndex(6)
        self._sync_compact_navigation()

    def closeEvent(self, event) -> None:
        # 답을 받는 도중 창을 닫으면 스레드가 남아 프로그램이 끝나지 않는다.
        if self._update_check_worker is not None:
            self._update_check_worker.requestInterruption()
            self._update_check_worker.wait(16_000)
        if self._update_download_worker is not None:
            self._update_download_worker.cancel()
            self._update_download_worker.wait(31_000)
        self.ai_review_tab.shutdown()
        self.resource_tab.ai_chat_panel.shutdown()
        self.central_tab.shutdown()
        self.expc_tab.shutdown()
        self.prec_tab.shutdown()
        self.ai_related_tab.shutdown()
        self.ai_search_tab.shutdown()
        shutdown_ai_background_services()
        super().closeEvent(event)

    def _activate_favorites_page(self, *_args: object) -> None:
        self._reset_reading_modes_for_page_change()
        self.navigation.blockSignals(True)
        self.navigation.setCurrentRow(-1)
        self.navigation.clearSelection()
        self.navigation.blockSignals(False)
        self.favorite_navigation_button.setChecked(True)
        self.viewed_laws_button.setChecked(False)
        self.ai_review_button.setChecked(False)
        self.tabs.setCurrentIndex(0)
        self._sync_compact_navigation()

    def _activate_viewed_laws_page(self, *_args: object) -> None:
        self._reset_reading_modes_for_page_change()
        self.navigation.blockSignals(True)
        self.navigation.setCurrentRow(-1)
        self.navigation.clearSelection()
        self.navigation.blockSignals(False)
        self.favorite_navigation_button.setChecked(False)
        self.viewed_laws_button.setChecked(True)
        self.ai_review_button.setChecked(False)
        self.tabs.setCurrentIndex(5)
        self._sync_compact_navigation()

    def _search_favorite_in_resource_list(
        self, target: str, name: str
    ) -> None:
        """Move a favorite to its law/admin-rule search result list."""
        self.navigation.setCurrentRow(1)
        self.resource_tab.search_resource_name(target, name)

    def _clear_runtime_cache_state(self) -> None:
        """Forget in-memory copies after all local cache files are removed."""
        self.resource_tab._reference_popup_states.clear()
        self.resource_tab._three_stage_payload_cache.clear()

    def _route_saved_record(
        self,
        record: object,
        *,
        reading_mode: bool = False,
    ) -> object | None:
        """저장된 항목을 알맞은 검색 탭으로 라우팅해 열고, 열린 탭 인스턴스를 반환."""
        if not isinstance(record, dict):
            return None

        # 어느 화면에서 열었든 ◀로는 그 화면으로 되돌아가야 한다.
        # 크게 보기로 열 때만 쓰므로 그때만 붙들어 둔다.
        exit_callback = (
            self._current_page_restorer() if reading_mode else None
        )

        def prepare(tab: object) -> object:
            if reading_mode:
                tab._reading_mode_exit_callback = exit_callback
                tab._set_reading_mode(True)
                self._settle_reading_layout(tab)
            return tab

        try:
            row = record.get("row")
            if not isinstance(row, dict):
                raise ValueError("저장 파일에 항목 정보가 없습니다.")
            if record.get("kind") != "detail_snapshot":
                self.navigation.setCurrentRow(1)
                self.resource_tab.ensure_body_page_for_target(
                    str(row.get("target") or "law")
                )
                tab = prepare(self.resource_tab)
                article_jo = str(
                    record.get("favorite_article_jo") or ""
                ).strip()
                article_unit = record.get("favorite_article_unit")
                if article_jo and isinstance(article_unit, dict):
                    tab.open_cached_favorite_article(record, article_unit)
                else:
                    tab.open_cached_law(record)
                    if article_jo:
                        QTimer.singleShot(
                            0,
                            lambda selected_jo=article_jo: (
                                tab.scroll_to_favorite_article(selected_jo)
                            ),
                        )
                return tab

            target = str(row.get("target") or "")
            if target == "law_reference":
                # 저장내역 화면을 유지한 채 그 위에 인용 조문 팝업만 연다.
                self.resource_tab.open_cached_reference_popup(record)
                return self.resource_tab
            if target == "three_stage":
                # 3단비교표도 같은 방식으로 팝업만 다시 띄운다.
                self.resource_tab.open_cached_three_stage_popup(record)
                return self.resource_tab
            if target in ("admrul", "ordin", "licbyl", "admbyl", "ordinbyl"):
                self.navigation.setCurrentRow(1)
                self.resource_tab.ensure_body_page_for_target(target)
                tab = prepare(self.resource_tab)
                tab._open_cached_resource_snapshot(row, record)
                return tab
            if target == "ai_search":
                self._show_keyword_category("ai_search")
                tab = prepare(self.ai_search_tab)
                tab.open_cached_snapshot(record)
                return tab
            if target == "ai_related":
                self._show_keyword_category("ai_related")
                tab = prepare(self.ai_related_tab)
                tab.open_cached_snapshot(record)
                return tab
            if target == "expc":
                self.navigation.setCurrentRow(3)
                tab = prepare(self.expc_tab)
                tab.open_cached_snapshot(record)
                return tab
            if target == "prec":
                self.navigation.setCurrentRow(4)
                tab = prepare(self.prec_tab)
                tab.open_cached_snapshot(record)
                return tab
            if target in AGENCY_BY_TARGET or row.get("agency"):
                self.navigation.setCurrentRow(2)
                tab = prepare(self.central_tab)
                tab.open_cached_snapshot(record)
                return tab
            raise ValueError("저장 본문을 열 검색 화면을 확인하지 못했습니다.")
        except (ValueError, TypeError) as exc:
            QMessageBox.critical(self, "저장 본문 열기 실패", str(exc))
            return None

    def _settle_reading_layout(self, tab: object) -> None:
        """크게보기의 최종 폭을 본문 HTML 배치 전에 확정한다."""
        central = self.centralWidget()
        previous_width = -1
        for _ in range(4):
            # 숨긴 헤더·탐색 영역과 QStackedWidget 전환에서 연쇄적으로 생긴
            # LayoutRequest만 처리한다. 업데이트가 잠긴 동안이라 중간 화면은 그리지 않는다.
            QApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
            if central is not None and central.layout() is not None:
                central.layout().activate()
            root_layout = getattr(tab, "root_layout", None)
            if root_layout is not None:
                root_layout.activate()
            detail_view = getattr(tab, "detail_view", None)
            if detail_view is None:
                continue
            width = detail_view.viewport().width()
            if width > 0 and width == previous_width:
                break
            previous_width = width

    def _open_viewed_law(self, record: object) -> None:
        self._route_saved_record(record, reading_mode=True)

    def _open_favorite(self, record: object) -> None:
        # 대상 검색 화면에서 좁은 폭으로 먼저 그린 뒤 크게보기로
        # 넓히면 한 프레임 동안 줄바꿈이 튄다. 화면 갱신을 잠근 채
        # 크게보기 폭을 먼저 확정하고 저장본문을 한 번만 그린다.
        self.setUpdatesEnabled(False)
        tab = None
        try:
            tab = self._route_saved_record(record, reading_mode=True)
            if tab is not None:
                # 목차 패널처럼 본문을 넣은 뒤에 나타나는 영역까지 반영한 최종 폭을
                # 화면 잠금을 풀기 전에 한 번 더 확정한다.
                self._settle_reading_layout(tab)
            if tab is not None and hasattr(tab, "detail_view"):
                tab.detail_view.document().size()
        finally:
            self.setUpdatesEnabled(True)
            self.update()

    def _apply_style(self) -> None:
        self.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.Normal))
        style_sheet = """
            /* 모든 화면의 스크롤바를 본문보다 한 단계 조용하게 맞춘다. */
            QScrollBar:vertical {
                width: 10px;
                margin: 2px 1px;
                background: transparent;
                border: none;
            }
            QScrollBar::handle:vertical {
                min-height: 32px;
                background: #b8b8b8;
                border: none;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover { background: #969696; }
            QScrollBar:horizontal {
                height: 10px;
                margin: 1px 2px;
                background: transparent;
                border: none;
            }
            QScrollBar::handle:horizontal {
                min-width: 32px;
                background: #b8b8b8;
                border: none;
                border-radius: 4px;
            }
            QScrollBar::handle:horizontal:hover { background: #969696; }
            QScrollBar::add-line,
            QScrollBar::sub-line {
                width: 0px;
                height: 0px;
                border: none;
                background: transparent;
            }
            QScrollBar::add-page,
            QScrollBar::sub-page { background: transparent; }

            /* 목록의 ⋯ 버튼에서 열리는 메뉴를 하나의 작은 팝업으로 통일. */
            QMenu {
                background: #ffffff;
                color: #25282d;
                border: 1px solid #d8dadd;
                border-radius: 10px;
                padding: 7px 5px;
            }
            QMenu::item {
                min-width: 150px;
                min-height: 26px;
                padding: 3px 28px 3px 30px;
                border-radius: 6px;
            }
            QMenu::item:selected {
                background: #f0f1f2;
                color: #17191c;
            }
            QMenu::separator {
                height: 1px;
                margin: 6px 8px;
                background: #e2e3e5;
            }
            QMenu::icon { padding-left: 5px; }
            QMenu#aiChatHistoryPopup {
                padding: 3px 4px;
                border-radius: 8px;
            }
            QMenu#aiChatHistoryPopup::item {
                min-width: 105px;
                min-height: 22px;
                padding: 1px 12px;
                border-radius: 5px;
            }
            QMenu#aiChatHistoryPopup::separator {
                margin: 3px 7px;
            }
            QMainWindow, QWidget {
                background: #f3f6f9;
                color: #172033;
                font-family: "Malgun Gothic";
                font-weight: 400;
            }
            QFrame#headerCard {
                background: #173b63;
                border-radius: 12px;
            }
            QFrame#apiCompact {
                background: #244d77;
                border: 1px solid #4c7195;
                border-radius: 8px;
            }
            QLabel#apiKeyLabel {
                background: transparent;
                color: #eaf3fb;
                font-size: 9pt;
                font-weight: 600;
            }
            QLineEdit#ocApiKeyInput {
                min-height: 30px;
                max-height: 30px;
                background: white;
                border: 1px solid #aec4d7;
                border-radius: 6px;
                padding: 0 9px;
                font-size: 9pt;
            }
            QPushButton#apiManualButton {
                /* 전역 QPushButton의 min-height가 이겨서 세로로 늘어난다.
                   작은 동그라미로 두려면 여기서 못 박아야 한다. */
                min-width: 20px;
                max-width: 20px;
                min-height: 20px;
                max-height: 20px;
                background: rgba(255, 255, 255, 0.12);
                border: 1px solid rgba(255, 255, 255, 0.35);
                border-radius: 10px;
                color: #eaf3fb;
                font-size: 11px;
                font-weight: 700;
                padding: 0;
            }
            QPushButton#apiManualButton:hover {
                background: #eaf3fb;
                border-color: #eaf3fb;
                color: #173b63;
            }
            QPushButton#apiRevealButton {
                min-height: 30px;
                max-height: 30px;
                min-width: 38px;
                padding: 0 6px;
                background: #2f5f8d;
                border: 1px solid #4c7195;
                border-radius: 6px;
                color: #eaf3fb;
                font-size: 9pt;
                font-weight: 600;
            }
            QPushButton#apiRevealButton:hover {
                background: #396fa3;
            }
            QPushButton#apiRevealButton:checked {
                background: #eaf3fb;
                border-color: #aec4d7;
                color: #173b63;
            }
            QCheckBox#apiSaveCheck {
                background: transparent;
                color: white;
                font-size: 9pt;
                font-weight: 600;
            }
            QLabel#appSubtitle {
                background: transparent;
                color: #d5e4f3;
                font-size: 12px;
                font-weight: 400;
            }
            QFrame#openDocumentsBar {
                background: transparent;
                border: none;
            }
            QLabel#openDocumentsLabel {
                background: transparent;
                color: #a9c1d3;
                font-size: 11px;
                font-weight: 600;
            }
            QLabel#openDocumentsEmpty {
                background: transparent;
                color: #89a5b9;
                font-size: 11px;
            }
            QTabBar#openDocumentTabs {
                background: transparent;
            }
            QTabBar#openDocumentTabs::tab {
                min-width: 88px;
                max-width: 180px;
                min-height: 34px;
                max-height: 34px;
                padding: 0 8px;
                margin-right: 4px;
                background: #244d67;
                color: #dceaf3;
                border: 1px solid #496b80;
                border-radius: 4px;
                font-size: 11px;
            }
            QTabBar#openDocumentTabs::tab:hover:!selected {
                background: #315f79;
                border-color: #6f96ad;
            }
            QTabBar#openDocumentTabs::tab:selected {
                background: #078c9b;
                border-color: #38bcc8;
                color: white;
                font-weight: 700;
            }
            QLabel#logoLabel {
                background: transparent;
            }
            QFrame#aiChatPanel {
                background: #f7fafd;
                border: 1px solid #cfdcea;
                border-radius: 14px;
            }
            QLabel#aiChatTitle {
                background: transparent;
                color: #173b63;
                font-size: 13px;
                font-weight: 700;
            }
            QPushButton#aiChatClose {
                background: transparent;
                border: none;
                color: #6b7c91;
                font-size: 16px;
            }
            QPushButton#aiChatClose:hover {
                color: #a33;
            }
            /* 말풍선은 ChatListButton이 직접 그린다. 글꼴 지정은
               필요 없고, 최소 크기만 못박아 두면 된다(전역 QPushButton의
               min-height 38px가 폴리시 때 밀고 들어온다). */
            QPushButton#aiChatHistoryToggle {
                min-width: 28px;
                max-width: 28px;
                min-height: 28px;
                max-height: 28px;
                background: transparent;
                border: 1px solid transparent;
                border-radius: 8px;
                padding: 0px;
            }
            QPushButton#aiChatHistoryToggle:hover {
                background: #eaf2f8;
                border-color: #bfd2e2;
            }
            QPushButton#aiChatHistoryToggle[historyVisible="true"] {
                background: #dcecf6;
                border-color: #8fb4ce;
                color: #0a6282;
            }
            QScrollArea#aiChatTranscript {
                background: #ffffff;
                border: none;
                border-radius: 12px;
            }
            QWidget#aiChatConversationPanel {
                background: #ffffff;
                border-radius: 12px;
            }
            QWidget#aiChatTranscriptContent {
                background: #ffffff;
            }
            /* 말 하나하나를 담는 줄. 이름을 안 주면 시스템 기본 회색이
               그대로 나와 채팅마다 회색 네모가 생긴다. */
            QWidget#aiChatRow {
                background: #ffffff;
            }
            QWidget#aiChatRow QLabel {
                background: transparent;
            }
            QLabel#aiChatHint {
                background: transparent;
                color: #5a6b80;
            }
            QFrame#aiChatBubbleUser {
                background: #e3e7eb;
                border-radius: 14px;
            }
            QFrame#aiChatBubbleUser QLabel {
                background: transparent;
                color: #172033;
            }
            QLabel#aiChatErrorText {
                background: transparent;
                color: #a33;
            }
            QPushButton#aiChatCopyLink {
                background: transparent;
                border: none;
                border-radius: 0px;
                color: #8a97a6;
                font-size: 8pt;
                padding: 0px;
                /* 전역 QPushButton은 min-height가 38px다. 8pt 글자 하나에
                   그 높이를 그대로 쓰면 복사 아래로 빈 띠가 남아, 이어지는
                   "사용한 법령 조문"이 멀찍이 떨어져 보였다. */
                min-height: 15px;
                max-height: 15px;
            }
            QPushButton#aiChatCopyLink:hover {
                color: #1768aa;
            }
            QPushButton#aiChatFavoriteButton {
                background: #fff8e6;
                border: 1px solid #f0d78c;
                border-radius: 11px;
                color: #8a6d1f;
                font-size: 8pt;
                padding: 3px 10px;
            }
            QPushButton#aiChatFavoriteButton:hover {
                background: #fdefc8;
            }
            QPushButton#aiChatFavoriteButton:disabled {
                background: #f3f4f6;
                border-color: #dbe0e6;
                color: #9aa3ad;
            }
            QPlainTextEdit#aiChatInput {
                background: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 6px 8px;
            }
            QWidget#aiChatComposerDock {
                background: transparent;
            }
            /* 전역 QComboBox는 38px다. 입력창 안에 들어가는 모델 칸은
               그 절반 높이로 낮춰 입력줄이 두꺼워지지 않게 한다. */
            QFrame#aiChatPanel QComboBox#aiChatModelCombo {
                min-height: 19px;
                max-height: 19px;
                padding: 0 8px;
                border-radius: 5px;
                font-size: 8.5pt;
            }
            QFrame#aiChatPanel QComboBox#aiChatModelCombo::drop-down {
                width: 18px;
            }
            QPushButton#aiChatModelMenuButton {
                background: transparent;
                border: none;
                border-radius: 5px;
                color: #173b63;
                font-size: 8.5pt;
                text-align: left;
                padding: 0px 7px;
                min-height: 26px;
                max-height: 26px;
            }
            QPushButton#aiChatModelMenuButton:hover {
                background: transparent;
                color: #173b63;
            }
            QPushButton#aiChatModelMenuButton:pressed {
                background: transparent;
                color: #173b63;
            }
            QPushButton#aiChatModelMenuButton:focus {
                background: transparent;
                border: none;
                color: #173b63;
            }
            QMenu#aiChatModelMenu {
                padding: 3px;
                border-radius: 7px;
                font-size: 8.5pt;
            }
            QMenu#aiChatModelMenu::item {
                min-height: 20px;
                padding: 1px 9px 1px 7px;
                border-radius: 4px;
                font-size: 8.5pt;
                font-weight: 400;
            }
            QMenu#aiChatModelMenu::item:disabled {
                color: #7a8a9a;
                background: transparent;
                font-size: 8pt;
            }
            QMenu#aiChatModelMenu::item:selected {
                background: #f4f6f8;
                color: #173b63;
            }
            QMenu#aiChatModelMenu::item:selected:disabled {
                background: transparent;
                color: #7a8a9a;
            }
            QFrame#aiChatComposer {
                background: #ffffff;
                border: 1px solid #9fb3c5;
                border-radius: 12px;
            }
            QFrame#aiChatHistoryPanel {
                background: #f5f8fb;
                border: 1px solid #d6e1eb;
                border-radius: 10px;
            }
            QSplitter#aiChatWorkspace::handle {
                width: 5px;
                background: transparent;
            }
            /* 화살표는 SendButton이 직접 그린다. 여기서는 바탕만 준다.
               예전에는 아래쪽에만 padding 2px이 있어 화살표가 위로
               치우쳐 보였다. */
            QPushButton#aiChatSend {
                background: #1768aa;
                color: white;
                border: none;
                border-radius: 9px;
                padding: 0px;
                min-width: 32px;
                max-width: 32px;
                min-height: 32px;
                max-height: 32px;
            }
            QPushButton#aiChatSend:hover { background: #12578e; }
            QPushButton#aiChatSend:disabled { background: #9fb5c8; }
            /* 좁은 본문 옆 패널에서 탭 대신 쓰는 목록. 전역 QComboBox의
               38px를 그대로 쓰면 옆 단추들보다 혼자 높아진다. */
            QFrame#aiChatPanel QComboBox#aiProviderCombo {
                min-height: 27px;
                max-height: 27px;
                padding: 0 6px;
                border-radius: 7px;
                font-weight: 600;
            }
            QTabBar#aiProviderTabs {
                background: transparent;
            }
            QTabBar#aiProviderTabs::tab {
                min-width: 105px;
                min-height: 32px;
                padding: 0 14px;
                margin-right: 3px;
                background: #edf2f6;
                color: #526176;
                border: 1px solid #cfd8e3;
                border-radius: 7px;
                font-weight: 600;
            }
            /* 고른 탭은 왼쪽 메뉴·상단 띠와 같은 남색으로 둔다.
               밝은 파랑(#1768aa)은 이 화면에서 링크와 강조에 쓰는 색이라
               탭까지 그 색이면 주변과 따로 놀았다. */
            QTabBar#aiProviderTabs::tab:selected {
                background: #173b63;
                color: white;
                border-color: #173b63;
            }
            QTabBar#aiProviderTabs::tab:hover:!selected {
                background: #dee7f0;
                color: #173b63;
            }
            QLabel#aiChatHistoryTitle,
            QLabel#aiChatModelLabel {
                background: transparent;
                color: #526176;
                font-weight: 700;
            }
            QListWidget#aiChatHistoryList {
                background: #f7f9fc;
                border: 1px solid #d6e1eb;
                border-radius: 9px;
                padding: 3px;
                outline: none;
            }
            /* 줄을 그리는 것은 얹은 위젯(aiChatHistoryRow) 하나뿐이다.
               항목까지 제 배경을 그리면 고른 줄 안에 네모가 한 겹 더
               비쳐 어색했다. */
            QListWidget#aiChatHistoryList::item {
                /* 상자를 목록 테두리에 바로 붙이면 첫 줄 윗변이 잘린다.
                   위아래로 조금 띄워 줄 사이 간격도 함께 만든다. */
                margin: 2px 1px;
                padding: 0px;
                border: none;
                background: transparent;
            }
            QListWidget#aiChatHistoryList::item:selected {
                background: transparent;
            }
            QWidget#aiChatHistoryRow {
                background: #ffffff;
                border: 1px solid #e2e9f1;
                border-radius: 7px;
                color: #40566b;
            }
            QWidget#aiChatHistoryRow:hover {
                border-color: #c7d8e7;
            }
            QWidget#aiChatHistoryRow[selected="true"] {
                background: #cfe5f6;
                border-color: #79add3;
            }
            QWidget#aiChatHistoryRow[selected="true"] QLabel {
                color: #14496f;
                font-weight: 700;
            }
            QPushButton#aiChatHistoryNew {
                min-width: 30px;
                max-width: 30px;
                min-height: 26px;
                max-height: 26px;
                padding: 0;
                background: #eef4f9;
                border: 1px solid #c7d8e7;
                color: #1768aa;
            }
            QPushButton#aiChatHistoryClear {
                min-height: 26px;
                max-height: 26px;
                padding: 0 9px;
                background: #f7f9fc;
                border: 1px solid #dbe0e6;
                color: #7c8794;
                font-size: 8.5pt;
            }
            QPushButton#aiChatHistoryClear:hover {
                background: #fdeceb;
                border-color: #e4a3a0;
                color: #a12c2a;
            }
            QLabel#aiChatHistoryItemTitle {
                background: transparent;
                color: #40566b;
            }
            /* 줄 오른쪽의 ⋯ 단추. 이름 바꾸기·고정·삭제를 여기 모았다. */
            QPushButton#aiChatHistoryMenu {
                /* 전역 QPushButton은 min-height가 38px이다. 스타일시트가
                   폴리시할 때 그 값을 위젯 최소 높이로 밀어 넣어
                   setFixedSize(18,18)를 무력화하고, 그 바람에 목록 한 줄이
                   48px까지 부풀었다. 여기서 같은 값으로 못박는다. */
                min-width: 24px;
                max-width: 24px;
                min-height: 24px;
                max-height: 24px;
                background: transparent;
                border: none;
                border-radius: 12px;
                padding: 0px;
                color: #8c96a3;
            }
            QPushButton#aiChatHistoryMenu:hover {
                background: #cfe3f5;
                color: #14496f;
            }
            /* Claudeㆍ Codex는 각자 구독이 있어야 답이 온다. 연결
               배지 왼쪽에 조용히 밝혀 둔다. */
            QLabel#aiFreeHint {
                background: transparent;
                color: #2f7d5b;
                font-size: 11px;
                font-weight: 600;
                padding: 0 2px;
            }
            QLabel#aiSubscriptionHint {
                background: transparent;
                color: #8a94a4;
                font-size: 11px;
                padding: 0 2px;
            }
            QLabel#aiEmbeddedAccessHint {
                background: transparent;
                color: #2f7d5b;
                font-size: 9px;
                font-weight: 600;
                padding: 0px;
            }
            QLabel#aiEmbeddedAccessHint[accessType="paid"] {
                color: #7b8797;
                font-weight: 500;
            }
            QLabel#aiCliStatusBadge {
                min-height: 25px;
                max-height: 25px;
                padding: 0 8px;
                background: #eef4f8;
                color: #40566b;
                border: 1px solid #c8d7e3;
                border-radius: 7px;
                font-size: 8.5pt;
                font-weight: 600;
            }
            QLabel#aiCliStatusBadge[connectionState="connected"] {
                background: #e0f4eb;
                color: #176b4b;
                border-color: #83c7ad;
            }
            QLabel#aiCliStatusBadge[connectionState="disconnected"] {
                background: #fde8e7;
                color: #a12c2a;
                border-color: #e4a3a0;
            }
            /* 전역 QPushButton은 min-height 38px라서, 이 단추가 그대로
               쓰면 CLI 줄만 헤더가 4px 높아져 탭을 옮길 때마다 아래
               화면이 통째로 밀린다. 옆 배지와 같은 높이로 못박는다. */
            QFrame#aiChatPanel QPushButton#aiConnectionButton {
                min-height: 27px;
                max-height: 27px;
                padding: 0 10px;
                background: #eef4f8;
                color: #2c4459;
                border: 1px solid #c8d7e3;
                border-radius: 7px;
                font-size: 8.5pt;
                font-weight: 600;
            }
            QFrame#aiChatPanel QPushButton#aiConnectionButton:hover {
                background: #dcecf9;
                border-color: #9cc2dd;
            }
            QFrame#aiChatPanel QPushButton#aiConnectionButton:disabled {
                background: #f3f4f6;
                border-color: #dbe0e6;
                color: #9aa3ad;
            }
            QPushButton#geminiApiSettingsButton {
                min-height: 27px;
                max-height: 27px;
                padding: 0 6px;
                background: #fff4dd;
                color: #835600;
                border: 1px solid #e2bd6f;
                border-radius: 7px;
                font-size: 8.5pt;
                font-weight: 600;
            }
            QPushButton#geminiApiSettingsButton[apiConfigured="true"] {
                background: #e0f4eb;
                color: #176b4b;
                border-color: #83c7ad;
            }
            QDialog#geminiApiDialog {
                background: #ffffff;
            }
            /* 단추를 눌러 초점이 가면 테두리가 1px에서 2px로 굵어지면서
               글자가 들어갈 자리를 뺏어 "무료 한도 안내"처럼 긴 글이
               잘려 보였다. 글자를 한 호 줄이고 좌우 여백도 좁혀 그만한
               여유를 만들어 둔다. */
            QDialog#geminiApiDialog QPushButton {
                font-size: 9pt;
                padding: 0 10px;
            }
            QLabel#geminiApiDialogStatus {
                background: transparent;
                color: #8a4b2a;
                font-size: 11px;
            }
            QLabel#geminiQuotaNotice {
                padding: 8px 10px;
                background: #f3f7fb;
                color: #526176;
                border: 1px solid #d6e1eb;
                border-radius: 7px;
                font-size: 9pt;
            }
            /* 패널 전체를 각지지 않게 하려고 자손 선택자로 한 번에 묶는다.
               #aiChatSend처럼 objectName이 붙은 규칙은 id 선택자라
               이 규칙보다 명시도가 높아 그대로 남는다. */
            QFrame#aiChatPanel QComboBox,
            QFrame#aiChatPanel QLineEdit,
            QFrame#aiChatPanel QPushButton {
                border-radius: 10px;
            }
            QFrame#aiChatPanel QPushButton#aiChatSend {
                border-radius: 10px;
            }
            QWidget#aiChatStatusBar {
                background: transparent;
            }
            /* 답하는 동안 대화창 위에 겹쳐 뜨는 질문 말풍선. 뒤 글이
               비쳐 보이지 않게 바탕을 채우고, 대화 속 말풍선과 같은
               둥근 모서리를 준다. */
            QFrame#aiChatQuestionBanner {
                background: #ffffff;
                border: 1px solid #cfdceb;
                border-radius: 10px;
            }
            QLabel#aiChatQuestionBannerTag {
                background: #ffffff;
                color: #40566b;
                border: 1px solid #cfdceb;
                border-radius: 6px;
                padding: 1px 7px;
                font-size: 11px;
                font-weight: 600;
            }
            QLabel#aiChatQuestionBannerText {
                background: transparent;
                color: #173b63;
                font-size: 11px;
                font-weight: 600;
            }
            /* 상태바 왼쪽 배지. 지금 보고 있는 AI의 상태라는 것을
               한눈에 알 수 있게 이름을 붙여 둔다. */
            QLabel#aiChatStatusProvider {
                background: #eef4f8;
                color: #40566b;
                border: 1px solid #d7e3ec;
                border-radius: 6px;
                padding: 1px 7px;
                font-size: 11px;
                font-weight: 600;
            }
            QLabel#aiChatStatus {
                background: transparent;
                color: #8a4b2a;
                font-size: 11px;
            }
            QPushButton#aboutLinkButton, QPushButton#updateLinkButton {
                background: transparent;
                border: none;
                padding: 0 2px;
                color: #6b7c91;
                font-size: 11px;
                text-decoration: underline;
            }
            QPushButton#aboutLinkButton:hover, QPushButton#updateLinkButton:hover {
                color: #1768aa;
            }
            QDialog#aboutDialog {
                background: #ffffff;
            }
            QTextBrowser#aboutBrowser {
                background: #ffffff;
                border: 1px solid #d6e0ea;
                border-radius: 6px;
                padding: 12px 14px;
            }
            QLabel#aboutCopyright {
                background: transparent;
                color: #6b7c91;
                font-size: 11px;
            }
            QLabel#fieldLabel, QCheckBox {
                background: transparent;
                font-weight: 600;
            }
            QCheckBox {
                spacing: 7px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                background: white;
                border: 1px solid #738398;
                border-radius: 3px;
            }
            QCheckBox::indicator:hover {
                /* 테두리 굵기가 바뀌면 체크박스 폭도 2px 늘어나 오른쪽
                   항목들이 클릭할 때마다 밀린다. 색만 바꿔 크기를 고정한다. */
                border: 1px solid #2679bd;
            }
            QCheckBox::indicator:checked {
                background: #1768aa;
                border: 1px solid #1768aa;
                image: url("__CHECK_ICON__");
            }
            QFrame#card {
                background: white;
                border: 1px solid #dce3ea;
                border-radius: 10px;
            }
            QFrame#lawReferencePopup {
                background: white;
                border: 2px solid #1768aa;
                border-radius: 10px;
            }
            QLabel#referencePopupArrow {
                background: transparent;
                color: #1768aa;
                font-size: 16px;
                font-weight: 700;
            }
            QLabel#referencePopupTitle {
                background: transparent;
                color: #173b63;
                font-size: 10pt;
                font-weight: 700;
            }
            QPushButton#referencePopupRefresh,
            QPushButton#referencePopupFavorite,
            QPushButton#referencePopupPin,
            QPushButton#referencePopupClose {
                min-height: 28px;
                max-height: 28px;
                background: white;
                color: #1768aa;
                border: 1px solid #b9d3ea;
                padding: 0 5px;
                font-size: 9pt;
            }
            QPushButton#referencePopupPin:checked {
                background: #1768aa;
                color: white;
                border-color: #1768aa;
            }
            QPushButton#referencePopupFavorite[favorite="true"] {
                color: #d79a00;
                background: #fff8df;
                border-color: #e5bd57;
            }
            QPushButton#referencePopupClose:hover {
                background: #fbe9e9;
                color: #a12b2b;
                border-color: #e7bcbc;
            }
            QTextBrowser#referencePopupBrowser {
                border: 1px solid #d6e1eb;
                border-radius: 7px;
                padding: 10px;
            }
            QFrame#navigationCard {
                background: #112f4c;
                border: 1px solid white;
                border-radius: 14px;
            }
            QLabel#navigationTitle {
                min-height: 18px;
                background: transparent;
                color: #94acc1;
                font-family: "Pretendard";
                font-size: 12px;
                font-weight: 700;
                letter-spacing: 1px;
            }
            QPushButton#favoriteNavigationButton {
                min-height: 64px;
                max-height: 64px;
                background: #173956;
                color: white;
                border: 1px solid #41627f;
                border-radius: 9px;
                padding: 1px 3px;
                font-family: "Malgun Gothic";
                font-size: 14px;
                font-weight: 700;
            }
            QPushButton#favoriteNavigationButton:hover {
                background: #1e4b73;
                color: white;
                border-color: #315e84;
            }
            QPushButton#favoriteNavigationButton:checked {
                background: #f2f8fc;
                color: #123f65;
                border-color: #f2f8fc;
            }
            QPushButton#favoriteNavigationButton:focus {
                border-color: #9ecbf0;
            }
            QListWidget#mainNavigation {
                background: transparent;
                border: none;
                outline: none;
                padding: 4px 0;
                font-family: "Malgun Gothic";
                font-size: 14px;
                font-weight: 700;
            }
            QListWidget#mainNavigation::item {
                min-height: 60px;
                background: transparent;
                color: #ffffff;
                border: 1px solid transparent;
                border-radius: 9px;
                padding: 1px 3px;
                margin: 2px 0;
            }
            QListWidget#mainNavigation::item:selected {
                background: #f2f8fc;
                color: #123f65;
                border-color: #f2f8fc;
                font-weight: 700;
            }
            QListWidget#mainNavigation::item:hover:!selected {
                background: #1e4b73;
                color: white;
                border-color: #315e84;
            }
            QWidget#favoriteCards {
                background: transparent;
            }
            QLabel#favoriteCategorySelectorLabel {
                background: transparent;
                color: #68788b;
                padding: 0 3px 0 0;
                font-size: 8.5pt;
                font-weight: 600;
            }
            QCheckBox#favoriteCategoryCheck {
                background: transparent;
                color: #40566b;
                spacing: 4px;
                padding: 2px 3px;
                font-size: 8.5pt;
            }
            QFrame#favoriteCategoryCard {
                background: transparent;
                border: none;
            }
            QFrame#favoriteCategoryTitleBar {
                background: #edf4f9;
                border: 1px solid #cbd8e4;
                border-radius: 7px;
                min-height: 38px;
                max-height: 38px;
            }
            QLabel#favoriteCategoryTitle {
                background: transparent;
                color: #173b63;
                border: none;
                font-size: 10pt;
                font-weight: 700;
            }
            QPushButton#favoriteAddFolderButton {
                background: white;
                color: #1768aa;
                border: 1px solid #afc9dc;
                border-radius: 3px;
                min-width: 22px;
                max-width: 22px;
                min-height: 22px;
                max-height: 22px;
                padding: 0px;
                font-size: 13pt;
                font-weight: 700;
            }
            QPushButton#favoriteAddFolderButton:hover {
                background: #dcecf9;
                border-color: #6fa3c9;
            }
            QPushButton#favoriteAddFolderButton:pressed {
                background: #c7e1f4;
            }
            QTreeWidget#favoriteCategoryTree {
                background: #fbfcfe;
                alternate-background-color: #f7f9fb;
                color: #34465a;
                border: 1px solid #cbd8e4;
                border-radius: 7px;
                outline: none;
                padding: 4px;
                show-decoration-selected: 0;
            }
            QTreeWidget#favoriteCategoryTree::branch:!has-children {
                background: transparent;
                border: none;
                image: none;
            }
            QTreeWidget#favoriteCategoryTree::branch:selected:!has-children,
            QTreeWidget#favoriteCategoryTree::branch:hover:!has-children {
                background: transparent;
            }
            QTreeWidget#favoriteCategoryTree::item {
                min-height: 25px;
                padding: 2px 4px;
                border-radius: 5px;
                font-size: 8pt;
            }
            QTreeWidget#favoriteCategoryTree::item:selected {
                background: transparent;
                color: #1768aa;
            }
            QTreeWidget#favoriteCategoryTree::item:hover:!selected {
                background: #eef6fc;
                color: #1768aa;
            }
            QListWidget#favoriteCategoryList {
                background: #fbfcfe;
                border: none;
                border-bottom-left-radius: 8px;
                border-bottom-right-radius: 8px;
                outline: none;
                padding: 5px;
            }
            QListWidget#favoriteCategoryList::item {
                min-height: 19px;
                background: white;
                color: #34465a;
                border: 1px solid #e0e7ee;
                border-radius: 6px;
                padding: 2px 7px;
                font-size: 8pt;
            }
            QListWidget#favoriteCategoryList::item:selected {
                background: #dcecf9;
                color: #1768aa;
                border-color: #8fb9dc;
            }
            QListWidget#favoriteCategoryList::item:hover:!selected {
                background: #eef6fc;
                color: #1768aa;
                border-color: #bfd8eb;
            }
            QListWidget#favoriteCategoryList::item:disabled {
                color: #9aa4b1;
                background: #f7f9fb;
                border-color: #edf1f5;
            }
            QTreeWidget#favoriteTree {
                background: #fbfcfe;
                alternate-background-color: #f5f8fb;
                color: #34465a;
                border: 1px solid #cbd8e4;
                border-radius: 9px;
                outline: none;
                padding: 4px;
            }
            QTreeWidget#favoriteTree::item {
                min-height: 27px;
                padding: 2px 5px;
                border-radius: 5px;
            }
            QTreeWidget#favoriteTree::item:selected {
                background: #dcecf9;
                color: #1768aa;
            }
            QTreeWidget#favoriteTree::item:hover:!selected {
                background: #eef6fc;
                color: #1768aa;
            }
            QTreeWidget#favoriteTree QHeaderView::section {
                background: #edf4f9;
                color: #173b63;
                border: none;
                border-right: 1px solid #d5e1ea;
                border-bottom: 1px solid #cbd8e4;
                padding: 7px 8px;
                font-weight: 700;
            }
            QPushButton#viewedLawsNavigationButton {
                min-height: 64px;
                max-height: 64px;
                background: #c88700;
                color: #2a1c00;
                border: 1px solid #a86f00;
                border-radius: 9px;
                padding: 1px 3px;
                font-family: "Malgun Gothic";
                font-size: 14px;
                font-weight: 700;
            }
            QPushButton#viewedLawsNavigationButton:hover {
                background: #dba000;
                color: #2a1c00;
                border-color: #a86f00;
            }
            QPushButton#viewedLawsNavigationButton:checked {
                background: #f1bf2f;
                color: #2a1c00;
                border-color: #c88700;
            }
            QPushButton#viewedLawsNavigationButton:focus {
                border-color: #7a5400;
            }
            QStackedWidget#mainPages {
                background: #f3f6f9;
                border: none;
            }
            QTabWidget::pane {
                background: #f3f6f9;
                border: 1px solid #dce3ea;
                border-radius: 10px;
                top: -1px;
            }
            QTabBar::tab {
                min-width: 170px;
                min-height: 38px;
                background: #e8edf2;
                color: #526176;
                border: 1px solid #d2dbe4;
                border-bottom: none;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                padding: 0 18px;
                font-weight: 600;
            }
            QTabBar::tab:selected {
                background: white;
                color: #1768aa;
            }
            QTabBar::tab:hover:!selected {
                background: #dde6ee;
            }
            QTabWidget#aiSubTabs::pane {
                background: #f8fbfe;
                border: 1px solid #b9d3ea;
                border-radius: 9px;
                top: -1px;
            }
            QTabWidget#aiSubTabs QTabBar {
                background: transparent;
            }
            QTabWidget#aiSubTabs QTabBar::tab {
                min-width: 120px;
                min-height: 31px;
                background: #eef5fb;
                color: #526176;
                border: 1px solid #b9d3ea;
                border-radius: 7px;
                margin: 4px 5px 4px 0;
                padding: 0 14px;
                font-weight: 600;
            }
            QTabWidget#aiSubTabs QTabBar::tab:selected {
                background: #1768aa;
                color: white;
                border-color: #1768aa;
            }
            QTabWidget#aiSubTabs QTabBar::tab:hover:!selected {
                background: #dcecf9;
                color: #1768aa;
            }
            QWidget#resourceSubTabs {
                background: transparent;
            }
            QFrame#resourceSubTabFrame,
            QFrame#resourceSubTabSingleFrame {
                background: #e9eff5;
                border: 1px solid #d4e0ea;
                border-radius: 11px;
            }
            QPushButton#resourceSubTabSingle,
            QPushButton#resourceSubTabPaired {
                min-width: 76px;
                background: transparent;
                color: #40566b;
                border: none;
                border-radius: 8px;
                padding: 0 14px;
                font-weight: 600;
            }
            QPushButton#resourceSubTabSingle:checked,
            QPushButton#resourceSubTabPaired:checked {
                background: #1976b8;
                color: white;
            }
            QPushButton#resourceSubTabSingle:hover:!checked,
            QPushButton#resourceSubTabPaired:hover:!checked {
                background: #dce7f0;
                color: #155f94;
            }
            QPushButton#resourceSubTabSingle:pressed,
            QPushButton#resourceSubTabPaired:pressed {
                background: #14689f;
                color: white;
            }
            QTabBar#documentTabs {
                background: transparent;
            }
            /* 탭 닫기 × 는 글자처럼 얇게 둔다. 네모 바탕을 깔면 탭
               안에서 그것만 튀어 보인다. 올렸을 때만 붉게 물든다. */
            QPushButton#documentTabClose {
                border: none;
                background: transparent;
                color: #9aa8b5;
                font-size: 13px;
                font-weight: 400;
                padding: 0;
            }
            QPushButton#documentTabClose:hover {
                color: #c0392b;
            }
            QTabBar#documentTabs::tab {
                /* 별표ㆍ닫기 버튼과 두 줄 제목이 함께 들어가는 폭.
                   좁히면 "… 법률 시행규칙"의 뒷부분이 잘려 시행령과
                   구분되지 않는다. */
                min-width: 122px;
                max-width: 178px;
                min-height: 39px;
                background: #edf2f6;
                color: #526176;
                border: 1px solid #cfd8e3;
                border-radius: 6px;
                margin-right: 2px;
                padding: 1px 5px;
                font-size: 8pt;
                font-weight: 400;
            }
            QTabBar#documentTabs::tab:selected {
                background: white;
                color: #1768aa;
                border-color: #8fb9dc;
                font-weight: 600;
            }
            QTabBar#documentTabs::tab:hover:!selected {
                background: #dcecf9;
                color: #1768aa;
            }
            QPushButton#restoreViewButton {
                /* 전역 QPushButton의 min-height:38px, padding:0 14px를
                   덮어써야 ◀ 아이콘이 잘리지 않는다. */
                min-width: 30px;
                max-width: 30px;
                min-height: 30px;
                max-height: 30px;
                padding: 0;
                margin: 0;
                background: #eef3f8;
                border: 1px solid #cfd8e3;
                border-radius: 6px;
            }
            QPushButton#restoreViewButton:hover {
                background: #dce9f5;
                border-color: #8fb9dc;
            }
            QPushButton#restoreViewButton:pressed {
                background: #cadff0;
            }
            QScrollArea#referenceHistoryBar,
            QWidget#referenceHistoryContent {
                background: transparent;
                border: none;
            }
            QFrame#referenceChip {
                background: #f4f7fa;
                border: 1px solid #cfd8e3;
                border-radius: 4px;
            }
            QFrame#referenceChip[chipSelected="true"] {
                background: #e8f1fb;
                border-color: #8fb9dc;
            }
            QFrame#referenceChip:hover {
                background: #edf5fc;
            }
            QFrame#referenceChip[chipDragging="true"] {
                background: #d7e8f8;
                border: 1px solid #5b93c7;
            }
            QLabel#referenceChipText {
                background: transparent;
                border: none;
                color: #526176;
                font-size: 8pt;
                font-weight: 400;
            }
            QFrame#referenceChip[chipSelected="true"] QLabel#referenceChipText {
                color: #1768aa;
                font-weight: 600;
            }
            QPushButton#referenceChipClose {
                /* 전역 QPushButton의 min-height:38px를 덮어써야
                   칩 안에서 정상 크기로 놓인다. */
                min-width: 24px;
                max-width: 24px;
                min-height: 24px;
                max-height: 24px;
                background: transparent;
                border: none;
                border-radius: 12px;
                color: #94a3b5;
                font-family: "Malgun Gothic";
                font-size: 11pt;
                font-weight: 700;
                padding: 0;
                margin: 0;
                text-align: center;
            }
            QPushButton#referenceChipClose:hover {
                background: #dbe6f1;
            }
            QPushButton#referenceChipClose:hover {
                color: #d9534f;
            }
            QLabel#sectionTitle {
                background: transparent;
                font-family: "Malgun Gothic";
                font-size: 16px;
                font-weight: 700;
                color: #172033;
            }
            QLabel#detailSectionTitle {
                background: transparent;
                color: #172033;
                font-family: "Pretendard";
                font-size: 16px;
                font-weight: 700;
            }
            QLabel#countBadge {
                background: #e8f1fb;
                color: #1768aa;
                border-radius: 8px;
                padding: 0 8px;
                min-height: 22px;
                max-height: 22px;
                font-size: 9pt;
                font-weight: 600;
            }
            QPushButton#searchShadeResetButton {
                min-height: 24px;
                max-height: 24px;
                background: #fff8df;
                color: #8a6510;
                border: 1px solid #e5ca73;
                border-radius: 6px;
                padding: 0 7px;
                font-size: 8pt;
                font-weight: 600;
            }
            QPushButton#searchShadeResetButton:hover {
                background: #ffefb8;
                border-color: #d6b748;
            }
            QPushButton#searchShadeResetButton:focus {
                border: 2px solid #2679bd;
            }
            QPushButton#searchShadeResetButton:disabled {
                background: #f4f6f8;
                color: #a8b0ba;
                border-color: #dfe4e9;
            }
            QLabel#fontSizeLabel {
                background: transparent;
                color: #526176;
                font-size: 8pt;
                font-weight: 600;
            }
            QDoubleSpinBox#fontSizeSpin,
            QSpinBox#pdfZoomSpin {
                min-height: 28px;
                max-height: 28px;
                background: white;
                border: 1px solid #cfd8e3;
                border-radius: 6px;
                padding: 0 18px 0 5px;
                font-size: 8pt;
            }
            QDoubleSpinBox#fontSizeSpin::up-button,
            QSpinBox#pdfZoomSpin::up-button {
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 16px;
                background: #f4f7fa;
                border-left: 1px solid #cfd8e3;
                border-bottom: 1px solid #dbe3eb;
                border-top-right-radius: 5px;
            }
            QDoubleSpinBox#fontSizeSpin::down-button,
            QSpinBox#pdfZoomSpin::down-button {
                subcontrol-origin: border;
                subcontrol-position: bottom right;
                width: 16px;
                background: #f4f7fa;
                border-left: 1px solid #cfd8e3;
                border-top: 1px solid #dbe3eb;
                border-bottom-right-radius: 5px;
            }
            QDoubleSpinBox#fontSizeSpin::up-button:hover,
            QDoubleSpinBox#fontSizeSpin::down-button:hover,
            QSpinBox#pdfZoomSpin::up-button:hover,
            QSpinBox#pdfZoomSpin::down-button:hover {
                background: #e8f1fb;
            }
            QDoubleSpinBox#fontSizeSpin::up-arrow,
            QSpinBox#pdfZoomSpin::up-arrow {
                image: url("__SPIN_UP_ICON__");
                width: 8px;
                height: 5px;
            }
            QDoubleSpinBox#fontSizeSpin::down-arrow,
            QSpinBox#pdfZoomSpin::down-arrow {
                image: url("__SPIN_DOWN_ICON__");
                width: 8px;
                height: 5px;
            }
            QDoubleSpinBox#fontSizeSpin:focus,
            QSpinBox#pdfZoomSpin:focus {
                border: 2px solid #2679bd;
            }
            QLabel#mutedText {
                background: transparent;
                color: #6b7789;
            }
            QWidget#dismissibleBanner {
                background: transparent;
            }
            QPushButton#bannerDismissButton {
                min-width: 24px;
                max-width: 24px;
                min-height: 24px;
                max-height: 24px;
                background: transparent;
                color: #8a94a3;
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 0;
                font-size: 10px;
                font-weight: 600;
            }
            QPushButton#bannerDismissButton:hover {
                background: #eef1f4;
                color: #445268;
                border-color: #d6dbe2;
            }
            QPushButton#bannerDismissButton:focus {
                border: 2px solid #2679bd;
            }
            QLineEdit, QComboBox {
                min-height: 38px;
                background: white;
                border: 1px solid #cfd8e3;
                border-radius: 7px;
                padding: 0 11px;
                selection-background-color: #1768aa;
                font-weight: 400;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 2px solid #2679bd;
            }
            QLineEdit#resultFilterInput {
                min-height: 18px;
                max-height: 18px;
                padding: 0 8px;
                border-radius: 5px;
                font-size: 8.5pt;
            }
            QComboBox#resourceSearchScope {
                min-height: 34px;
                padding: 0 4px;
                font-size: 8pt;
            }
            QWidget#recentSearchBar {
                background: transparent;
            }
            QLabel#recentSearchLabel {
                background: transparent;
                color: #445268;
                font-size: 8pt;
                font-weight: 600;
                margin-right: 2px;
            }
            QLabel#recentSearchEmpty {
                background: transparent;
                color: #929dab;
                font-size: 8pt;
            }
            QPushButton#recentSearchButton {
                min-height: 22px;
                max-height: 22px;
                background: white;
                color: #526176;
                border: 1px solid #d5dee8;
                border-radius: 6px;
                padding: 0 4px;
                font-size: 8pt;
                font-weight: 400;
            }
            QPushButton#recentSearchButton:hover {
                background: #e8f1fb;
                color: #1768aa;
                border-color: #b9d3ea;
            }
            QPushButton#recentSearchClearButton {
                min-height: 20px;
                max-height: 20px;
                background: transparent;
                color: #7a8798;
                border: 1px solid #d5dee8;
                border-radius: 5px;
                padding: 0 6px;
                font-size: 8pt;
                font-weight: 500;
            }
            QPushButton#recentSearchClearButton:hover {
                background: #fbe9e9;
                color: #a12b2b;
                border-color: #e7bcbc;
            }
            QWidget#detailSearchBar {
                background: transparent;
            }
            QLabel#detailSearchLabel {
                background: transparent;
                color: #445268;
                font-weight: 600;
            }
            QLineEdit#detailSearchInput {
                min-height: 30px;
                max-height: 30px;
                padding: 0 9px;
                border: 2px solid #d5dee8;
            }
            QLineEdit#detailSearchInput[findActive="true"] {
                background: #fff3bf;
                color: #172033;
                border: 2px solid #e0a000;
            }
            QLabel#detailSearchCount {
                background: #eef3f7;
                color: #526176;
                border-radius: 6px;
                padding: 4px 5px;
            }
            QPushButton {
                min-height: 38px;
                border-radius: 7px;
                padding: 0 14px;
                font-weight: 600;
            }
            QPushButton:focus {
                border: 2px solid #2679bd;
            }
            /* 표준 대화상자(예/아니요, 확인/취소) 단추. 전역 QPushButton은
               테두리가 없어서 폭이 글자폭+안쪽여백으로만 잡히는데, 기본
               단추에는 :focus 테두리 2px이 더 붙어 좌우 4px이 글자 자리에서
               깎이고 글자 끝이 잘린다. 그래서 여백을 넉넉히 잡아 두고,
               포커스일 때는 테두리가 차지하는 만큼 여백을 되돌려 준다. */
            QMessageBox QPushButton,
            QDialogButtonBox QPushButton {
                min-width: 44px;
                padding: 0 20px;
            }
            QMessageBox QPushButton:focus,
            QDialogButtonBox QPushButton:focus {
                padding: 0 16px;
            }
            QPushButton#primaryButton {
                background: #1768aa;
                color: white;
                border: none;
            }
            QPushButton#primaryButton:hover { background: #12578f; }
            QPushButton#primaryButton:focus {
                border: 2px solid #9ecbf0;
            }
            QPushButton#secondaryButton {
                background: #e8f1fb;
                color: #1768aa;
                border: 1px solid #b9d3ea;
            }
            QPushButton#secondaryButton:hover { background: #dbeaf8; }
            QPushButton#secondaryButton:focus {
                border: 2px solid #2679bd;
            }
            QPushButton#readingModeButton {
                min-height: 40px;
                max-height: 40px;
                background: white;
                color: #1768aa;
                border: 1px solid #b9d3ea;
                border-radius: 5px;
                padding: 0 4px;
                font-size: 9pt;
            }
            QPushButton#readingModeButton:hover {
                background: #e8f1fb;
                border-color: #8fb9dc;
            }
            QPushButton#readingModeButton:focus {
                border: 2px solid #2679bd;
            }
            /* 크게 보기에서는 같은 자리가 대화 패널을 여는 단추가 된다.
               하는 일이 달라졌다는 것이 색으로도 보이게 채워서 그린다. */
            QPushButton#readingModeButton[buttonMode="ai"] {
                background: #1768aa;
                border: 1px solid #135b95;
                color: white;
                font-weight: 700;
            }
            QPushButton#readingModeButton[buttonMode="ai"]:hover {
                background: #12578e;
                border-color: #0f4a7b;
            }
            QWidget#colorTools {
                background: transparent;
            }
            QLabel#colorRowLabel {
                background: transparent;
                color: #526176;
                font-size: 7pt;
                font-weight: 600;
            }
            QPushButton#colorResetButton {
                min-height: 18px;
                max-height: 18px;
                background: white;
                color: #526176;
                border: 1px solid #cfd8e3;
                border-radius: 5px;
                padding: 0 5px;
                font-size: 7pt;
                font-weight: 600;
            }
            QPushButton#colorResetButton:hover {
                background: #f2f5f8;
                color: #1768aa;
                border-color: #9ebed8;
            }
            QPushButton#colorResetButton:focus {
                border: 2px solid #2679bd;
            }
            QPushButton#colorModeButton {
                min-height: 32px;
                max-height: 32px;
                background: white;
                color: #526176;
                border: 1px solid #cfd8e3;
                border-radius: 6px;
                padding: 0 5px;
                font-size: 9pt;
            }
            QPushButton#colorModeButton:checked {
                background: #1768aa;
                color: white;
                border-color: #1768aa;
            }
            QPushButton#colorModeButton:hover:!checked {
                background: #e8f1fb;
                color: #1768aa;
                border-color: #b9d3ea;
            }
            QPushButton#memoButton {
                min-height: 40px;
                max-height: 40px;
                background: #fff8dc;
                color: #6b5200;
                border: 1px solid #dccb7a;
                border-radius: 6px;
                padding: 0 4px;
                font-size: 7pt;
            }
            QPushButton#memoButton:hover {
                background: #fff1b8;
                border-color: #c9b24d;
            }
            QPushButton#memoButton:focus {
                border: 2px solid #2679bd;
            }
            QPushButton#resourceDetailButton {
                min-height: 40px;
                max-height: 40px;
                background: #e8f1fb;
                color: #1768aa;
                border: 1px solid #b9d3ea;
                border-radius: 5px;
                padding: 0 4px;
                font-size: 9pt;
            }
            QPushButton#resourceDetailButton:hover {
                background: #dbeaf8;
            }
            QPushButton#resourceDetailButton:focus {
                border: 2px solid #2679bd;
            }
            QPushButton#ghostButton {
                background: white;
                color: #445268;
                border: 1px solid #cfd8e3;
            }
            QPushButton#ghostButton:focus {
                border: 2px solid #2679bd;
            }
            QPushButton#detailSearchButton {
                min-height: 30px;
                max-height: 30px;
                background: white;
                color: #445268;
                border: 1px solid #cfd8e3;
                padding: 0 8px;
            }
            QPushButton#detailSearchButton:hover {
                background: #e8f1fb;
                color: #1768aa;
                border-color: #b9d3ea;
            }
            QPushButton:disabled {
                background: #edf0f3;
                color: #9aa4b1;
                border-color: #dde2e7;
            }
            QWidget#detailBodyContainer {
                background: #ffffff;
            }
            QPushButton#referencePopupRefresh:hover {
                background: #e8f4fc;
                border-color: #6aa7d5;
            }
            QPushButton#referencePopupRefresh:disabled {
                color: #94a3b1;
                background: #eef2f5;
                border-color: #d5dde5;
            }
            QWidget#detailViewRow {
                background: #ffffff;
            }
            QWidget#articleTocPanel {
                background: transparent;
            }
            QLabel#tocSearchLabel {
                background: transparent;
                color: #445268;
                font-weight: 600;
            }
            QLineEdit#tocSearchInput {
                min-height: 30px;
                max-height: 30px;
                padding: 0 8px;
                font-size: 9pt;
            }
            QLabel#tocSearchCount {
                background: #eef3f7;
                color: #526176;
                border-radius: 6px;
                padding: 4px 4px;
                font-size: 9pt;
            }
            QPushButton#tocSearchButton {
                min-height: 28px;
                max-height: 28px;
                background: white;
                color: #445268;
                border: 1px solid #cfd8e3;
                padding: 0 5px;
                font-size: 9pt;
            }
            QPushButton#tocSearchButton:hover {
                background: #e8f1fb;
                color: #1768aa;
                border-color: #b9d3ea;
            }
            QPushButton#threeStageArticleButton {
                min-height: 24px;
                max-height: 24px;
                background: #e8f1fb;
                color: #1768aa;
                border: 1px solid #9fc2df;
                border-radius: 5px;
                padding: 0 1px;
                font-size: 8pt;
                font-weight: 700;
            }
            QPushButton#threeStageArticleButton:hover {
                background: #1768aa;
                color: white;
                border-color: #1768aa;
            }
            QPushButton#tocShadeResetButton {
                min-height: 28px;
                max-height: 28px;
                background: #fff7e6;
                color: #8a5a00;
                border: 1px solid #f0c869;
                border-radius: 6px;
                padding: 0 2px;
                font-size: 7pt;
            }
            QPushButton#tocShadeResetButton:hover {
                background: #ffedc2;
                border-color: #d9a533;
                color: #6b4500;
            }
            QTreeWidget#articleToc {
                background: #f8fbfe;
                alternate-background-color: #f2f7fb;
                border: 1px solid #d5e1eb;
                border-radius: 7px;
                color: #34465a;
                font-size: 9pt;
                outline: none;
            }
            QTreeWidget#articleToc::item {
                min-height: 25px;
                padding: 1px 3px;
            }
            QTreeWidget#articleToc::item:selected {
                background: #dcecf9;
                color: #1768aa;
            }
            QTreeWidget#articleToc QHeaderView::section {
                background: #e8f1f8;
                color: #445268;
                padding: 7px 8px;
                font-size: 9pt;
                font-weight: 700;
            }
            QTableWidget {
                background: white;
                alternate-background-color: #f7f9fb;
                border: 1px solid #e0e6ed;
                border-radius: 7px;
                selection-background-color: #dcecf9;
                selection-color: #172033;
                font-size: 9pt;
            }
            QHeaderView::section {
                background: #eef3f7;
                color: #445268;
                border: none;
                border-bottom: 1px solid #d7e0e8;
                padding: 9px 7px;
                font-weight: 600;
                font-size: 9pt;
            }
            QTextBrowser {
                background: white;
                border: 1px solid #e0e6ed;
                border-radius: 7px;
                padding: 12px;
                selection-background-color: #1768aa;
                font-weight: 400;
            }
            QSplitter::handle {
                background: transparent;
                width: 10px;
            }
            QSplitter::handle:hover {
                background: #d9e9f6;
                border-left: 1px solid #a9c9e3;
                border-right: 1px solid #a9c9e3;
            }
            QSplitter::handle:pressed {
                background: #8fb9dc;
                border-left: 1px solid #4f91c5;
                border-right: 1px solid #4f91c5;
            }
            QProgressBar {
                border: none;
                background: #dce3ea;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background: #1768aa;
                border-radius: 4px;
            }

            /* 2026 legal-workbench visual system ------------------------- */
            QMainWindow, QWidget {
                background: __WB_CANVAS__;
                color: __WB_INK__;
                font-family: "Malgun Gothic";
            }
            QFrame#headerCard {
                background: __WB_NAVY__;
                border: 1px solid #234963;
                border-radius: 6px;
            }
            QLabel#appSubtitle { color: #bfd0dc; }
            QPushButton#aboutLinkButton, QPushButton#updateLinkButton {
                background: transparent;
                border: none;
                padding: 0 2px;
                color: __WB_MUTED__;
                font-size: 11px;
                text-decoration: underline;
            }
            QPushButton#aboutLinkButton:hover, QPushButton#updateLinkButton:hover {
                color: __WB_NAVY__;
            }
            QFrame#apiCompact {
                background: #1d4059;
                border: 1px solid #45667b;
                border-radius: 5px;
            }
            QFrame#navigationCard {
                background: __WB_NAVY__;
                border: 1px solid #234963;
                border-radius: 5px;
            }
            QLabel#navigationTitle {
                color: #9fb5c3;
                font-size: 11px;
                letter-spacing: 1px;
            }
            QPushButton#favoriteNavigationButton,
            QListWidget#mainNavigation::item {
                border-radius: 3px;
            }
            QPushButton#favoriteNavigationButton {
                min-height: 54px;
                max-height: 54px;
                margin-left: 5px;
                margin-right: 5px;
                background: #173956;
                border: 1px solid #41627f;
            }
            QListWidget#mainNavigation::item {
                min-height: 54px;
                margin: 1px 0;
            }
            QPushButton#favoriteNavigationButton:hover,
            QListWidget#mainNavigation::item:hover:!selected {
                background: #204861;
                border-color: #315a70;
            }
            QPushButton#favoriteNavigationButton:checked,
            QListWidget#mainNavigation::item:selected {
                background: #e7f3f4;
                color: #15324b;
                border-left: 4px solid #18a0a8;
                border-top: 1px solid #c9dfe1;
                border-right: 1px solid #c9dfe1;
                border-bottom: 1px solid #c9dfe1;
            }
            QPushButton#aiReviewNavigationButton {
                min-height: 54px;
                max-height: 54px;
                background: #193a52;
                color: #adc0cc;
                border: 1px solid #315269;
                border-radius: 3px;
                padding: 1px 3px;
                font-family: "Malgun Gothic";
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton#aiReviewNavigationButton:hover {
                background: #204861;
                color: #dce7ed;
                border-color: #45677c;
            }
            QPushButton#aiReviewNavigationButton:checked {
                background: #087e8b;
                color: #ffffff;
                border-left: 4px solid #18a0a8;
                border-top: 1px solid #38abb1;
                border-right: 1px solid #38abb1;
                border-bottom: 1px solid #38abb1;
            }
            QPushButton#viewedLawsNavigationButton {
                min-height: 54px;
                max-height: 54px;
                background: #193a52;
                color: #adc0cc;
                border: 1px solid #315269;
                border-radius: 3px;
                font-weight: 600;
            }
            QPushButton#viewedLawsNavigationButton:hover {
                background: #204861;
                color: #dce7ed;
                border-color: #45677c;
            }
            QPushButton#viewedLawsNavigationButton:checked {
                background: #dfeaec;
                color: #29495d;
                border-left: 4px solid #7897a8;
                border-top: 1px solid #b9cbd3;
                border-right: 1px solid #b9cbd3;
                border-bottom: 1px solid #b9cbd3;
            }
            QStackedWidget#mainPages,
            QTabWidget::pane { background: __WB_CANVAS__; }
            QFrame#card {
                background: __WB_SURFACE__;
                border: 1px solid __WB_BORDER__;
                border-radius: 5px;
            }
            QLineEdit, QComboBox,
            QDoubleSpinBox#fontSizeSpin,
            QSpinBox#pdfZoomSpin {
                border-color: #bfcdd6;
                border-radius: 4px;
                selection-background-color: __WB_ACCENT__;
            }
            QLineEdit:focus, QComboBox:focus,
            QDoubleSpinBox#fontSizeSpin:focus,
            QSpinBox#pdfZoomSpin:focus {
                border: 2px solid __WB_ACCENT__;
            }
            QPushButton { border-radius: 4px; }
            QPushButton:focus { border: 2px solid __WB_FOCUS__; }
            QListWidget#mainNavigation:focus {
                border: 2px solid __WB_FOCUS__;
            }
            QPushButton#primaryButton {
                background: __WB_ACCENT__;
                border: 1px solid __WB_ACCENT__;
            }
            QPushButton#primaryButton:hover { background: __WB_ACCENT_HOVER__; }
            QPushButton#secondaryButton,
            QPushButton#resourceDetailButton {
                background: #e5f2f3;
                color: #086975;
                border-color: #a8cdd0;
            }
            QPushButton#secondaryButton:hover,
            QPushButton#resourceDetailButton:hover {
                background: #d2e9eb;
            }
            QLabel#sectionTitle, QLabel#detailSectionTitle {
                color: #15324b;
                font-family: "Pretendard", "Malgun Gothic";
            }
            QLabel#countBadge {
                background: #dceff0;
                color: #086975;
            }
            QPushButton#ocApiSettingsButton {
                min-height: 28px;
                max-height: 28px;
                padding: 0 10px;
                background: #fff4dd;
                color: #835600;
                border: 1px solid #e2bd6f;
                border-radius: 7px;
                font-size: 8.5pt;
                font-weight: 600;
            }
            QPushButton#ocApiSettingsButton[apiConfigured="true"] {
                background: #e0f4eb;
                color: #176b4b;
                border-color: #83c7ad;
            }
            QDialog#ocApiDialog {
                background: #ffffff;
            }
            QLineEdit#ocApiKeyInput {
                min-height: 30px;
                max-height: 30px;
                background: white;
                border: 1px solid #aec4d7;
                border-radius: 6px;
                padding: 0 9px;
                font-size: 9pt;
            }
            QPushButton#ocApiManualButton {
                min-width: 28px;
                max-width: 28px;
                min-height: 28px;
                max-height: 28px;
                padding: 0;
                border-radius: 14px;
                border: 1px solid #aec4d7;
                background: #eef3f7;
                color: #17324b;
                font-weight: 700;
            }
            QPushButton#ocApiManualButton:hover {
                background: #17607f;
                border-color: #17607f;
                color: white;
            }
            QTableWidget {
                alternate-background-color: #f5f8f9;
                border-color: #d5dfe5;
                border-radius: 3px;
                gridline-color: #e4eaee;
                selection-background-color: #d8ecee;
                selection-color: #172b3a;
            }
            QHeaderView::section {
                background: #e8eef1;
                color: #314b5e;
                border-bottom: 1px solid #c5d2d9;
                border-right: 1px solid #d5dfe5;
            }
            QTextBrowser {
                background: #ffffff;
                border-color: #d5dfe5;
                border-radius: 3px;
                selection-background-color: #087e8b;
            }
            QTextBrowser QWidget {
                background: #ffffff;
            }
            QSplitter::handle:hover {
                background: #d6e8e9;
                border-color: #8dbdc1;
            }
            QSplitter::handle:pressed {
                background: #62aeb3;
                border-color: #087e8b;
            }
            QTabBar::tab {
                border-radius: 3px;
                background: #e5ecef;
            }
            QTabBar::tab:selected {
                color: #087e8b;
                border-top: 3px solid #087e8b;
            }
            QTabWidget#aiSubTabs QTabBar::tab:selected,
            QPushButton#resourceSubTabSingle:checked,
            QPushButton#resourceSubTabPaired:checked,
            QPushButton#colorModeButton:checked {
                background: #087e8b;
                border-color: #087e8b;
            }
            QFrame#resourceSubTabFrame,
            QFrame#resourceSubTabSingleFrame {
                border-radius: 4px;
                background: #e5ecef;
            }
            QTabBar#documentTabs::tab:selected {
                color: #087e8b;
                border-color: #80b8bc;
                border-top: 3px solid #087e8b;
            }
            QPushButton#threeStageArticleButton {
                background: #e3f1f2;
                color: #08727d;
                border-color: #8fc1c5;
            }
            QPushButton#threeStageArticleButton:hover {
                background: #087e8b;
                border-color: #087e8b;
            }
            QProgressBar::chunk { background: #087e8b; }
            """
        self.setStyleSheet(
            apply_workbench_color_tokens(style_sheet)
            .replace("__CHECK_ICON__", CHECK_ICON_PATH.as_posix())
            .replace("__SPIN_UP_ICON__", SPIN_UP_ICON_PATH.as_posix())
            .replace("__SPIN_DOWN_ICON__", SPIN_DOWN_ICON_PATH.as_posix())
        )

    def _api_value_changed(self, value: str) -> None:
        self.oc = value.strip()
        self._refresh_oc_api_settings_button()
        if self.save_api_checkbox.isChecked():
            try:
                self._store_api_key(self.oc)
            except (OSError, RuntimeError, ValueError):
                self.save_api_checkbox.setChecked(False)

    def _api_reveal_toggled(self, checked: bool) -> None:
        """인증키를 잠깐 보이게 하거나 다시 가린다."""
        self.api_input.setEchoMode(
            QLineEdit.EchoMode.Normal
            if checked
            else QLineEdit.EchoMode.Password
        )
        self.api_reveal_button.setText("숨김" if checked else "표시")

    def _api_save_toggled(self, checked: bool) -> None:
        self.oc = self.api_input.text().strip()
        try:
            self._store_api_key(self.oc if checked else "")
        except (OSError, RuntimeError, ValueError):
            self.save_api_checkbox.setChecked(False)

    def start_search(self) -> None:
        query = self.query_input.text().strip()
        if not query:
            QMessageBox.information(self, "검색어 확인", "검색어를 입력해 주세요.")
            self.query_input.setFocus()
            return
        self.oc = self.api_input.text().strip()
        if not self.oc:
            self.open_oc_api_settings()
            return

        self.highlight_terms = search_terms(query)
        self.title_highlight_delegate.set_terms(self.highlight_terms)
        self.result_table.viewport().update()
        self.result_table.setRowCount(0)
        self.result_rows.clear()
        self.result_count.setText("0건")
        self.detail_view.clear()
        self.current_detail_text = ""
        self.copy_button.setEnabled(False)
        selected_target = str(self.agency_combo.currentData())
        if selected_target == "__all__":
            agencies = AGENCIES
            agency_label = "전체 기관"
        else:
            agencies = (AGENCY_BY_TARGET[selected_target],)
            agency_label = agencies[0].name
        self._start_worker(
            ApiWorker(
                "search",
                oc=self.oc,
                query=query,
                search_scope=int(self.scope_combo.currentData()),
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
        if busy:
            self.detail_button.setEnabled(False)
        else:
            self._selection_changed()
        self.query_input.setEnabled(not busy)
        self.scope_combo.setEnabled(not busy)
        self.agency_combo.setEnabled(not busy)
        self.api_input.setEnabled(not busy)
        self.save_api_checkbox.setEnabled(not busy)
        self.progress.setVisible(busy)
        if message:
            self.status_label.setText(message)

    def _worker_finished(self) -> None:
        self._set_busy(False)
        if self.worker:
            self.worker.deleteLater()
        self.worker = None

    def _worker_succeeded(self, operation: str, root: object) -> None:
        try:
            if operation == "search":
                self._show_search_results(root)
            else:
                self._show_detail(root)
        except Exception as exc:
            self._worker_failed(operation, str(exc))

    def _worker_failed(self, operation: str, error: str) -> None:
        action = "검색" if operation == "search" else "본문 조회"
        self.status_label.setText(f"{action}에 실패했습니다.")
        QMessageBox.critical(
            self,
            f"{action} 실패",
            f"{action} 중 오류가 발생했습니다.\n\n{error}",
        )

    def _show_search_results(self, payload: object) -> None:
        roots = payload["roots"]
        request_errors = list(payload["errors"])
        rows: list[dict[str, str]] = []
        total_count = 0
        response_errors: list[tuple[AgencyConfig, str]] = []
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
                if tag_name != "cgmexpc" or "id" not in node.attrib:
                    continue
                item_id = _find_text(node, "법령해석일련번호")
                title = _find_text(node, "안건명")
                if not item_id and not title:
                    continue
                rows.append(
                    {
                        "agency": agency.name,
                        "target": agency.target,
                        "detail_available": agency.detail_available,
                        "id": item_id,
                        "title": title,
                        "case_number": _find_text(node, "안건번호"),
                        "date": _find_text(node, "해석일자"),
                        "inquiry_org": _find_text(node, "질의기관명"),
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

        self.result_rows = rows
        self.result_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = (
                row["agency"],
                row["id"],
                row["title"],
                row["case_number"],
                row["date"],
                row["inquiry_org"],
            )
            for column, value in enumerate(values):
                display_value = " ".join(value.split()) if column == 2 else value
                item = QTableWidgetItem(display_value)
                if column == 2:
                    item.setToolTip(display_value)
                if column in (0, 1, 3, 4, 5):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if column == 1:
                    item.setForeground(QColor("#1768aa"))
                    font = item.font()
                    font.setFamily(FONT_FAMILY)
                    font.setWeight(QFont.Weight.DemiBold)
                    item.setFont(font)
                elif column == 2:
                    font = item.font()
                    font.setFamily(FONT_FAMILY)
                    font.setWeight(QFont.Weight.Medium)
                    item.setFont(font)
                self.result_table.setItem(row_index, column, item)

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
            self.result_table.selectRow(0)
        else:
            self.detail_view.setPlainText("검색 결과가 없습니다.")

    def _selection_changed(self) -> None:
        row = self.result_table.currentRow()
        has_selection = 0 <= row < len(self.result_rows)
        detail_available = bool(
            has_selection and self.result_rows[row]["detail_available"]
        )
        self.detail_button.setEnabled(
            detail_available and not (self.worker and self.worker.isRunning())
        )
        if has_selection and not detail_available:
            self.detail_button.setToolTip(
                f"{self.result_rows[row]['agency']}는 본문 조회 API를 제공하지 않습니다."
            )
        else:
            self.detail_button.setToolTip("")

    def _open_detail_expanded(self, *_args: object) -> None:
        """검색결과 더블클릭: 본문을 열고 바로 크게 보기로 전환한다."""
        row = self.result_table.currentRow()
        if row < 0 or row >= len(self.result_rows):
            return
        self.open_selected_detail()
        self._set_reading_mode(True)

    def open_selected_detail(self, *_args: object) -> None:
        row = self.result_table.currentRow()
        if row < 0 or row >= len(self.result_rows):
            QMessageBox.information(self, "항목 선택", "조회할 항목을 선택해 주세요.")
            return
        selected = self.result_rows[row]
        if not selected["detail_available"]:
            QMessageBox.information(
                self,
                "본문 조회 미제공",
                f"{selected['agency']}는 본문 조회 API를 제공하지 않습니다.",
            )
            return
        item_id = selected["id"]
        agency = AGENCY_BY_TARGET[selected["target"]]
        self._start_worker(
            ApiWorker(
                "detail",
                oc=self.oc,
                item_id=item_id,
                agency=agency,
                parent=self,
            ),
            f"{agency.name} ID {item_id} 본문 조회 중...",
        )

    def _show_detail(self, payload: object) -> None:
        root = payload["root"]
        agency = payload["agency"]
        title = _find_text(root, "안건명") or f"{agency.name} 법령해석"
        item_id = _find_text(root, "법령해석일련번호")
        if not item_id and not _find_text(root, "질의요지"):
            message = "".join(root.itertext()).strip()
            raise ValueError(message or "본문 응답을 파싱하지 못했습니다.")

        metadata = [("조회 기관", agency.name)]
        for label in (
            "법령해석일련번호",
            "안건번호",
            "해석일자",
            "해석기관명",
            "질의기관명",
            "대분류",
            "중분류",
            "소분류",
        ):
            value = _find_text(root, label)
            if value:
                metadata.append((label, value))

        sections = []
        for label in ("질의요지", "회답", "이유", "관련법령"):
            value = _find_text(root, label)
            if value:
                sections.append((label, value))

        html_parts, plain_parts = detail_document_header(
            title, metadata, self.highlight_terms
        )

        for label, value in sections:
            html_parts.append(f"<h2>{escape(label)}</h2>")
            html_parts.append(
                f'<div class="content">'
                f"{body_to_html(value, self.highlight_terms)}</div>"
            )
            plain_parts.extend(("", f"[{label}]", value))

        self.detail_view.setHtml("".join(html_parts))
        self.current_detail_text = "\n".join(plain_parts)
        self.copy_button.setEnabled(True)
        self.status_label.setText(
            f"{agency.name} ID {item_id} 본문 조회 완료"
        )

    def copy_detail(self) -> None:
        if not self.current_detail_text:
            return
        QApplication.clipboard().setText(self.current_detail_text)
        self.status_label.setText("본문을 클립보드에 복사했습니다.")
