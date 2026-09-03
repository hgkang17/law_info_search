"""아이콘 경로와 화면에 쓰는 안내 문구."""

from __future__ import annotations

from storage.paths import APP_DIR


SEARCH_API_REFRESH_TOOLTIP = (
    "검색기능에도 API를 호출하기때문에\n"
    "검색결과량이 많을경우 딜레이가 생김,\n"
    "딜레이를 줄이기 위해 한번 검색한 단어는\n"
    "컴퓨터에 저장하여 다음에 검색이 API호출을 하지않아 딜레이를 없앰\n"
    "API갱신 버튼은 컴퓨터에 저장된 검색어가 아니라 API호출을 재시도함"
)


LOGO_PATH = APP_DIR / "molit_law_logo.svg"


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


# LGPL v3ㆍSIL OFL 1.1은 재배포판에 라이선스 사본을 함께 담도록 요구한다.
# 빌드 설정이 이 폴더를 통째로 번들에 넣고, 프로그램 정보 대화상자가
# 여기를 열어 준다.
LICENSE_DIR = APP_DIR / "licenses"


ADMIN_RULE_PARSE_VERSION = 30
