"""프로그램 정보와 오픈소스 라이선스 고지 대화상자.

배포판의 소스는 공개 저장소에서 제공한다. 재배포 조건이 붙은 구성 요소
(LGPL v3인 Qt/PySide6, SIL OFL 1.1인 Pretendard 글꼴)와 프로그램 자체
MIT 라이선스는 여기에서 라이선스와 원본 입수 경로를 명시한다.
"""

from __future__ import annotations

from html import escape

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from storage.paths import CACHE_ROOT
from ui.assets import LICENSE_DIR
from utils.constants import (
    APP_TITLE,
    APP_VERSION,
    AUTHOR_NAME,
    CONTACT_EMAIL,
    COPYRIGHT_YEAR,
    FONT_FAMILY,
)


# 배포는 실행 파일 하나로 묶는 방식(onefile)이라 Qt 라이브러리가 exe 안에
# 들어간다. 공개 소스와 빌드 설정으로 수정한 Qt를 사용해 다시 빌드할 수
# 있고, 배포에 사용한 정확한 Qt 대응 소스도 요청할 수 있음을 밝힌다.
LICENSE_NOTICES = (
    {
        "role": "UI 라이브러리",
        "name": "Qt for Python (PySide6)",
        "holder": "The Qt Company Ltd. 및 Qt 기여자",
        "license": "GNU Lesser General Public License v3 (LGPL v3)",
        "note": (
            "Qt 라이브러리는 이 실행 파일 안에 담겨 배포됩니다. LGPL v3에 "
            "따라 프로그램 소스와 빌드 설정을 공개하며, 배포에 사용한 "
            "Qt/PySide6 대응 소스와 수정한 Qt로 다시 빌드하는 데 필요한 "
            "정보는 위 연락처로 요청할 수 있습니다."
        ),
        "links": (
            ("라이선스 전문", "https://www.gnu.org/licenses/lgpl-3.0.html"),
            (
                "Qt for Python 소스",
                "https://download.qt.io/official_releases/QtForPython/",
            ),
        ),
    },
    {
        # 저작권 표시는 번들한 글꼴 파일의 name 테이블에 적힌 값을 그대로
        # 옮긴다. 파생 원본인 Adobe Source의 표시까지는 동봉한 라이선스
        # 원문에 들어 있다.
        "role": "사용폰트",
        "name": "Pretendard",
        "holder": (
            "Copyright © 2023 Kil Hyung-jin "
            "(Reserved Font Name 'Pretendard')"
        ),
        "license": "SIL Open Font License 1.1",
        "note": (
            "화면 표시용 글꼴로 원본 그대로 담았습니다. 글꼴 파일을 "
            "고치지 않았으므로 예약 글꼴 이름(Reserved Font Name)을 "
            "그대로 씁니다."
        ),
        "links": (
            ("글꼴 배포처", "https://github.com/orioncactus/pretendard"),
            ("라이선스 전문", "https://openfontlicense.org/documents/OFL.txt"),
        ),
    },
    {
        "role": "PDF/HWP 분석",
        "name": "kordoc",
        "holder": "Copyright (c) 2025 Chris",
        "license": "MIT License",
        "note": (
            "별표·서식 HWP/HWPX/PDF를 Markdown으로 바꿀 때 로컬 Node "
            "패키지로 사용합니다. 실행 파일 안에는 넣지 않고, 개발 "
            "환경의 kordoc_parser에서 npm install로 받아 둡니다."
        ),
        "links": (
            ("소스", "https://github.com/chrisryugj/kordoc"),
            ("라이선스 전문", "https://opensource.org/licenses/MIT"),
        ),
    },
    {
        "role": "법령 AI 도구",
        "name": "korean-law-mcp",
        "holder": "Copyright (c) 2025 Chris",
        "license": "MIT License",
        "note": (
            "조문 영향 맵·판례 생사 확인·조례 정비 레이더 등 일부 도구의 "
            "구성·처리 순서·출력 문구를 파이썬으로 다시 구현했습니다. "
            "원본 TypeScript는 실행 파일에 넣지 않았습니다."
        ),
        "links": (
            ("소스", "https://github.com/chrisryugj/korean-law-mcp"),
            ("라이선스 전문", "https://opensource.org/licenses/MIT"),
        ),
    },
    {
        "role": "프로그램 소스",
        "name": "law_search_AI",
        "holder": "Copyright (c) 2026 hgkang",
        "license": "MIT License",
        "note": (
            "프로그램 자체 소스와 PyInstaller 빌드 설정은 공개 GitHub "
            "저장소에서 같은 Release 태그 기준으로 제공합니다."
        ),
        "links": (
            ("소스", "https://github.com/hgkang17/law_info_search"),
            ("라이선스 전문", "https://opensource.org/licenses/MIT"),
        ),
    },
)

DATA_SOURCE_NOTICE = (
    "이 프로그램이 보여 주는 법령·행정규칙·자치법규·판례·법령해석례와 "
    "중앙부처 질의회신 자료는 <b>법제처 국가법령정보 공동활용(OPEN API)</b>에서 "
    "받아 온 것입니다. 자료의 저작권과 최종 유권해석 권한은 각 제공기관에 "
    "있습니다."
)

DISCLAIMER_NOTICE = (
    "이 프로그램의 조회 결과는 참고용이며 법적 효력을 갖지 않습니다. "
    "실제 업무에 적용하기 전에는 반드시 국가법령정보센터의 원문을 "
    "확인하시기 바랍니다."
)

BACKUP_NOTICE = (
    "한 번 호출한 API 법령정보는 <b>위 저장 위치</b>에 남겨 둡니다. "
    "언제든 삭제할 수 있습니다. 같은 자료를 다시 받을 때 API를 반복 "
    "호출하지 않아 대기 시간을 줄이기 위한 것입니다."
)


# QTextDocument는 클래스 선택자를 문단 서식에 적용하지 않으므로,
# 본문 렌더링과 마찬가지로 서식은 인라인 style로 직접 붙인다.
_LABEL_STYLE = (
    'style="color:#3d4c60; font-weight:700; padding-right:14px; '
    'white-space:nowrap; vertical-align:top;"'
)
_HEADING_STYLE = (
    'style="font-size:15px; font-weight:700; color:#1768aa; '
    'margin:22px 0 8px 0;"'
)


def _notice_html() -> str:
    sections: list[str] = []
    sections.append(
        '<div style="font-size:18px; font-weight:700; color:#173b63; '
        f'margin:0 0 12px 0;">{escape(APP_TITLE)} '
        '<span style="font-size:13px; font-weight:400; color:#5a6b80;">'
        f"v{escape(APP_VERSION)}</span></div>"
    )
    sections.append(
        '<table cellspacing="0" cellpadding="0">'
        f"<tr><td {_LABEL_STYLE}>제작자</td>"
        f'<td style="vertical-align:top;">{escape(AUTHOR_NAME)}</td></tr>'
        # 메일 주소는 눌러도 메일 프로그램이 뜨지 않게 글자로만 둔다.
        f"<tr><td {_LABEL_STYLE}>문의</td>"
        '<td style="vertical-align:top;">'
        f"{escape(CONTACT_EMAIL)}</td></tr>"
        f"<tr><td {_LABEL_STYLE}>자료 출처</td>"
        '<td style="vertical-align:top;">'
        '<a href="https://open.law.go.kr">'
        "법제처 국가법령정보 공동활용 (open.law.go.kr)</a></td></tr>"
        # 메모ㆍ즐겨찾기가 이 폴더에 들어 있어 백업하려면 자리를 알아야
        # 한다. exe를 쓰기 막힌 자리에 두면 사용자 폴더로 물러나므로
        # 실제 자리를 그때그때 읽어서 보여 준다.
        f"<tr><td {_LABEL_STYLE}>저장 위치</td>"
        '<td style="vertical-align:top;">'
        f"{escape(str(CACHE_ROOT))}</td></tr>"
        "</table>"
    )
    sections.append(
        f'<div style="margin:14px 0 0 0;">{DATA_SOURCE_NOTICE}</div>'
    )
    sections.append(
        '<div style="margin:10px 0 0 0; color:#8a4b2a;">'
        f"{DISCLAIMER_NOTICE}</div>"
    )
    sections.append(f'<div style="margin:10px 0 0 0;">{BACKUP_NOTICE}</div>')

    sections.append(f"<div {_HEADING_STYLE}>사용한 오픈소스</div>")
    for notice in LICENSE_NOTICES:
        links = " · ".join(
            f'<a href="{escape(url)}">{escape(text)}</a>'
            for text, url in notice["links"]
        )
        # 바깥 div에 margin을 줘도 QTextDocument가 중첩 블록의 여백을
        # 문단 간격으로 반영하지 않아 항목끼리 붙는다. 첫 줄에 직접 준다.
        sections.append(
            "<div>"
            '<div style="font-weight:700; color:#173b63; margin:16px 0 0 0;">'
            f'<span style="font-weight:600; color:#5a6b80;">'
            f'{escape(notice["role"])}</span>'
            f' · {escape(notice["name"])}</div>'
            f'<div style="color:#3d4c60;">{escape(notice["holder"])}</div>'
            f'<div style="color:#3d4c60;">{escape(notice["license"])}</div>'
            f'<div style="margin:3px 0;">{notice["note"]}</div>'
            f'<div style="color:#3d4c60;">{links}</div>'
            "</div>"
        )
    body = "".join(sections)
    return (
        "<style>"
        f"body {{ font-family:'{FONT_FAMILY}'; font-size:13px; "
        "color:#172033; line-height:1.7; }}"
        "a { color:#1768aa; text-decoration:none; }"
        "</style>"
        f"{body}"
    )


class LicenseTextDialog(QDialog):
    """동봉한 라이선스 원문을 프로그램 안에서 그대로 보여 준다.

    실행 파일 하나로 묶어 배포하면 라이선스 사본이 임시 폴더에 풀리기
    때문에, 파일 탐색기로 넘기는 대신 여기에서 바로 읽게 한다. LGPLㆍOFL이
    요구하는 "사용자가 쉽게 확인할 수 있는 형태"를 이 창이 채운다.
    """

    TITLES = {
        "LICENSE.LGPLv3.txt": "GNU Lesser General Public License v3",
        "LICENSE.GPLv3.txt": "GNU General Public License v3",
        "LICENSE.Pretendard-OFL.txt": "SIL Open Font License 1.1 (Pretendard)",
        "LICENSE.kordoc-MIT.txt": "MIT License (kordoc)",
        "LICENSE.korean-law-mcp-MIT.txt": "MIT License (korean-law-mcp)",
        "LICENSE.project-MIT.txt": "MIT License (law_search_AI)",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("라이선스 원문")
        self.setObjectName("licenseTextDialog")
        self.setMinimumSize(600, 480)
        self.resize(720, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        self.selector = QComboBox()
        self.selector.setObjectName("licenseSelector")
        for file_name, title in self.TITLES.items():
            if (LICENSE_DIR / file_name).is_file():
                self.selector.addItem(title, file_name)
        self.selector.currentIndexChanged.connect(self._load_selected)

        self.viewer = QPlainTextEdit()
        self.viewer.setObjectName("licenseViewer")
        self.viewer.setReadOnly(True)
        # 원문은 고정폭으로 줄을 맞춰 쓴 문서라 줄바꿈을 넣지 않는다.
        self.viewer.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        close_button = QPushButton("닫기")
        close_button.setObjectName("licenseCloseButton")
        close_button.setFixedWidth(84)
        close_button.setDefault(True)
        close_button.clicked.connect(self.accept)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addStretch(1)
        footer.addWidget(close_button)

        layout.addWidget(self.selector)
        layout.addWidget(self.viewer, 1)
        layout.addLayout(footer)
        self._load_selected()

    def _load_selected(self) -> None:
        file_name = self.selector.currentData()
        if not file_name:
            self.viewer.setPlainText(
                "라이선스 원문 파일을 찾지 못했습니다."
            )
            return
        path = LICENSE_DIR / str(file_name)
        try:
            self.viewer.setPlainText(path.read_text(encoding="utf-8"))
        except OSError as error:
            self.viewer.setPlainText(f"원문을 읽지 못했습니다: {error}")
        self.viewer.moveCursor(QTextCursor.MoveOperation.Start)


class AboutDialog(QDialog):
    """프로그램 정보ㆍ자료 출처ㆍ오픈소스 라이선스를 한 화면에 보여 준다."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("프로그램 정보")
        self.setObjectName("aboutDialog")
        self.setMinimumSize(520, 430)
        self.resize(560, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(12)

        self.browser = QTextBrowser()
        self.browser.setObjectName("aboutBrowser")
        self.browser.setOpenLinks(False)
        self.browser.setOpenExternalLinks(False)
        self.browser.anchorClicked.connect(self._open_link)
        self.browser.setHtml(_notice_html())
        layout.addWidget(self.browser, 1)

        copyright_label = QLabel(
            f"Copyright (c) {COPYRIGHT_YEAR} {AUTHOR_NAME}. "
            "위에 밝힌 오픈소스는 각 라이선스를 따릅니다."
        )
        copyright_label.setObjectName("aboutCopyright")
        copyright_label.setWordWrap(True)

        self.cache_button = QPushButton("저장 폴더 열기")
        self.cache_button.setObjectName("aboutCacheButton")
        self.cache_button.setToolTip(str(CACHE_ROOT))
        self.cache_button.clicked.connect(self._open_cache_dir)

        self.license_button = QPushButton("라이선스 원문 보기")
        self.license_button.setObjectName("aboutLicenseButton")
        self.license_button.setToolTip(
            "동봉한 LGPL v3ㆍGPL v3ㆍOFL 1.1 원문을 그대로 봅니다."
        )
        self.license_button.clicked.connect(self._show_license_text)
        # 개발 중에는 저장소 안에, 배포판에서는 번들 안에 들어 있다.
        self.license_button.setEnabled(LICENSE_DIR.is_dir())

        close_button = QPushButton("닫기")
        close_button.setObjectName("aboutCloseButton")
        close_button.setFixedWidth(84)
        close_button.setDefault(True)
        close_button.clicked.connect(self.accept)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(12)
        footer.addWidget(copyright_label, 1)
        footer.addWidget(self.cache_button, 0, Qt.AlignmentFlag.AlignBottom)
        footer.addWidget(self.license_button, 0, Qt.AlignmentFlag.AlignBottom)
        footer.addWidget(close_button, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(footer)

    def _open_cache_dir(self) -> None:
        # 아직 아무것도 저장하지 않았으면 폴더가 없어 탐색기가 뜨지 않는다.
        try:
            CACHE_ROOT.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(CACHE_ROOT)))

    def _show_license_text(self) -> None:
        LicenseTextDialog(self).exec()

    def _open_link(self, url: QUrl) -> None:
        # 대화상자 안에서 문서가 바뀌면 라이선스 고지가 사라지므로,
        # 링크는 항상 기본 브라우저ㆍ메일 프로그램으로 넘긴다.
        QDesktopServices.openUrl(url)
