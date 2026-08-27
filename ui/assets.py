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


CHECK_ICON_PATH = APP_DIR / "checkbox_check.svg"


SPIN_UP_ICON_PATH = APP_DIR / "spin_up.svg"


SPIN_DOWN_ICON_PATH = APP_DIR / "spin_down.svg"


FAVORITE_PLUS_ICON_PATH = APP_DIR / "favorite_plus.svg"


# LGPL v3ㆍSIL OFL 1.1은 재배포판에 라이선스 사본을 함께 담도록 요구한다.
# 빌드 설정이 이 폴더를 통째로 번들에 넣고, 프로그램 정보 대화상자가
# 여기를 열어 준다.
LICENSE_DIR = APP_DIR / "licenses"


ADMIN_RULE_PARSE_VERSION = 29
