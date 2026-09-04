"""프로그램을 열면 가장 먼저 보이는 시작 화면.

왼쪽 메뉴는 그대로 두고, 오른쪽 칸 한가운데에 검색칸 하나만 둔다. 여기서
넣은 검색어는 법령검색 화면의 통합검색으로 넘어가 결과를 보여 준다. 무엇을
찾을지부터 정하고 화면을 고르던 순서를, 찾을 말부터 넣는 순서로 바꾼다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMovie, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.assets import HOME_ANIMATION_PATH, LOGO_PATH
from ui.widgets import RecentSearchBar


class HomeSearchPage(QWidget):
    """가운데 검색칸 하나만 둔 시작 화면."""

    searchRequested = Signal(str)

    # 넓은 창에서도 검색칸이 화면 끝까지 늘어나지 않게 하는 폭. 글이 한
    # 줄에 너무 길게 늘어지면 어디를 눌러야 하는지 한눈에 안 들어온다.
    CONTENT_WIDTH = 720
    # 창을 좁혀도 검색칸이 한 줄짜리 단추만큼 쪼그라들지 않게 한다.
    MIN_CONTENT_WIDTH = 420
    # 검색칸과 같은 폭 안에 담기는 만큼만 최근 검색어를 보여 준다.
    RECENT_SEARCH_LIMIT = 4

    def __init__(self, recent_search_manager, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("homePage")

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(0)

        content = QWidget()
        content.setObjectName("homeContent")
        content.setMaximumWidth(self.CONTENT_WIDTH)
        content.setMinimumWidth(self.MIN_CONTENT_WIDTH)
        # 남는 자리를 양옆 여백과 나눠 갖되, CONTENT_WIDTH에서 멈춘다.
        content.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(14)

        self.logo_label = QLabel()
        self.logo_label.setObjectName("homeLogo")
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # 움직이는 그림이 있으면 그것을, 없으면 로고를 세운다. 그림 파일이
        # 빠진 배포판에서도 화면이 비지 않게 한다.
        self._movie: QMovie | None = None
        movie = QMovie(str(HOME_ANIMATION_PATH))
        if movie.isValid():
            self._movie = movie
            self.logo_label.setMovie(movie)
            movie.start()
        else:
            logo = QPixmap(str(LOGO_PATH))
            if not logo.isNull():
                self.logo_label.setPixmap(
                    logo.scaled(
                        44,
                        44,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )

        self.title_label = QLabel("무엇을 찾아 드릴까요?")
        self.title_label.setObjectName("homeTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.search_box = QFrame()
        self.search_box.setObjectName("homeSearchBox")
        box_layout = QHBoxLayout(self.search_box)
        box_layout.setContentsMargins(18, 10, 10, 10)
        box_layout.setSpacing(8)

        self.query_input = QLineEdit()
        self.query_input.setObjectName("homeSearchInput")
        self.query_input.setPlaceholderText(
            "찾을 법령ㆍ행정규칙ㆍ자치법규나 조문 내용을 넣으세요"
        )
        self.query_input.setClearButtonEnabled(True)
        self.query_input.returnPressed.connect(self._emit_search)

        self.search_button = QPushButton("검색")
        self.search_button.setObjectName("homeSearchButton")
        self.search_button.setFixedSize(72, 36)
        self.search_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.search_button.clicked.connect(self._emit_search)

        box_layout.addWidget(self.query_input, 1)
        box_layout.addWidget(self.search_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.hint_label = QLabel(
            "법령ㆍ행정규칙ㆍ자치법규와 별표ㆍ서식을 한 번에 찾고, "
            "AI가 고른 조문을 맨 앞에 보여 줍니다."
        )
        self.hint_label.setObjectName("homeHint")
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint_label.setWordWrap(True)

        # 최근 검색어는 검색줄과 같은 것을 쓴다. 누르면 그 자리에서 바로
        # 검색까지 이어지도록 returnPressed를 그대로 활용한다.
        self.recent_search_bar = RecentSearchBar(
            self.query_input,
            recent_search_manager,
            self,
            max_items=self.RECENT_SEARCH_LIMIT,
        )
        self.recent_search_bar.setObjectName("homeRecentSearchBar")

        column.addWidget(self.logo_label)
        column.addWidget(self.title_label)
        column.addSpacing(4)
        column.addWidget(self.search_box)
        column.addWidget(self.hint_label)
        column.addSpacing(6)
        column.addWidget(self.recent_search_bar)

        # 어떤 AI가 결과를 고르는지 밝혀 둔다. 통합검색의 "AI추천"이
        # 어디서 온 것인지 묻는 일이 없도록 화면에 적어 둔다.
        self.credit_label = QLabel(
            "AI : Lawbot, 국가법령정보센터 AI(지능형 법령검색 시스템)"
        )
        self.credit_label.setObjectName("homeCredit")
        self.credit_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.credit_label.setWordWrap(True)
        column.addWidget(self.credit_label)

        # 위쪽 여백을 조금 더 크게 잡아 검색칸이 화면 한가운데보다 살짝
        # 위에 오게 한다. 아래에 최근 검색어가 붙어도 균형이 유지된다.
        root.addStretch(5)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        row.addWidget(content, 6)
        row.addStretch(1)
        root.addLayout(row)
        root.addStretch(6)

    def focus_query(self) -> None:
        """화면이 앞으로 나올 때마다 바로 칠 수 있게 커서를 둔다."""
        self.query_input.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        self.query_input.selectAll()

    def _emit_search(self) -> None:
        query = self.query_input.text().strip()
        if not query:
            self.query_input.setFocus()
            return
        self.searchRequested.emit(query)
