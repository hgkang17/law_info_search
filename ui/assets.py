"""아이콘 경로와 화면에 쓰는 안내 문구."""

from __future__ import annotations

from base64 import b64encode
from functools import lru_cache
from pathlib import Path
import re

from storage.paths import APP_DIR


@lru_cache(maxsize=32)
def icon_data_uri(path: Path) -> str:
    """아이콘 파일을 본문 HTML에 그대로 담는 data: 주소로 바꾼다.

    본문 HTML은 저장본으로 남고 다음 실행에서 그대로 다시 열린다.
    거기에 ``file:`` 경로를 심으면 onefile EXE가 실행마다 다른 임시
    폴더에 풀리므로, 저장본을 다시 열 때 그림이 사라지고 점선 네모만
    남았다. 그림을 주소 안에 담으면 경로와 무관하게 늘 보인다.
    """
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return Path(path).as_uri()
    kind = "image/svg+xml" if str(path).lower().endswith(".svg") else "image/png"
    return f"data:{kind};base64," + b64encode(raw).decode("ascii")


# 저장본에 남은 옛 ``file:`` 아이콘 주소를 지금 실행의 data: 주소로
# 바꿀 때 쓴다. 파일 이름만 보고 찾으므로 어느 폴더에서 저장했든 걸린다.
_INLINE_ICON_FILES = (
    "annex_expand.svg",
    "annex_collapse.svg",
    "annex_hwp.svg",
    "annex_pdf.svg",
)
_INLINE_ICON_PATTERN = re.compile(
    r"file:/+[^\"'>\s]*?/(" + "|".join(
        name.replace(".", r"\.") for name in _INLINE_ICON_FILES
    ) + r")",
    re.IGNORECASE,
)


def normalize_inline_icon_sources(html: str) -> str:
    """저장본의 옛 아이콘 주소를 지금 실행에서 볼 수 있는 주소로 고친다."""
    if not html or "file:" not in html:
        return html

    def replace(match: re.Match[str]) -> str:
        return icon_data_uri(APP_DIR / match.group(1).lower())

    return _INLINE_ICON_PATTERN.sub(replace, html)


SEARCH_API_REFRESH_TOOLTIP = (
    "검색기능에도 API를 호출하기때문에\n"
    "검색결과량이 많을경우 딜레이가 생김,\n"
    "딜레이를 줄이기 위해 한번 검색한 단어는\n"
    "컴퓨터에 저장하여 다음에 검색이 API호출을 하지않아 딜레이를 없앰\n"
    "API갱신 버튼은 컴퓨터에 저장된 검색어가 아니라 API호출을 재시도함"
)


LOGO_PATH = APP_DIR / "molit_law_logo.svg"


# 시작 화면 한가운데에서 도는 짧은 그림. 돋보기가 문서를 훑으며 글줄이
# 물드는 모습으로, 이 프로그램이 무엇을 하는지 한눈에 보여 준다.
HOME_ANIMATION_PATH = APP_DIR / "home_search.gif"


# API 인증키 발급 안내. 물음표 단추가 기본 웹 브라우저로 연다.
# onefile EXE에서는 APP_DIR이 실행 중 풀린 임시 폴더를 가리킨다.
MANUAL_DIR = APP_DIR / "메뉴얼"
API_KEY_MANUAL_PATH = MANUAL_DIR / "API인증키 발급안내.html"
GEMINI_KEY_MANUAL_PATH = MANUAL_DIR / "제미나이 API 발급안내.html"


CHECK_ICON_PATH = APP_DIR / "checkbox_check.svg"


SPIN_UP_ICON_PATH = APP_DIR / "spin_up.svg"


SPIN_DOWN_ICON_PATH = APP_DIR / "spin_down.svg"


FAVORITE_PLUS_ICON_PATH = APP_DIR / "favorite_plus.svg"


# 본문 하단 별표ㆍ서식 목록에서 원본(HWP)ㆍPDF 내려받기를 나타내는 표시.
# 한글과컴퓨터ㆍAdobe의 실제 상표를 쓰지 않고 문서 모양으로만 그렸다.
ANNEX_HWP_ICON_PATH = APP_DIR / "annex_hwp.svg"


ANNEX_PDF_ICON_PATH = APP_DIR / "annex_pdf.svg"


# 별표 목록 왼쪽에서 펼치고 접는 표시. 글자 +ㆍ−는 본문 글씨와 섞여
# 눌러야 할 자리로 보이지 않았다.
ANNEX_EXPAND_ICON_PATH = APP_DIR / "annex_expand.svg"


ANNEX_COLLAPSE_ICON_PATH = APP_DIR / "annex_collapse.svg"


# 닫기(×) 표시. 플랫폼 표준 아이콘은 네모 상자 안에 X가 든 모양이라
# 얇은 선으로 그린 것을 따로 둔다.
CLOSE_MARK_ICON_PATH = APP_DIR / "close_mark.svg"

HIGHLIGHTER_ICON_PATH = APP_DIR / "highlighter.svg"


# LGPL v3ㆍSIL OFL 1.1은 재배포판에 라이선스 사본을 함께 담도록 요구한다.
# 빌드 설정이 이 폴더를 통째로 번들에 넣고, 프로그램 정보 대화상자가
# 여기를 열어 준다.
LICENSE_DIR = APP_DIR / "licenses"


ADMIN_RULE_PARSE_VERSION = 30
