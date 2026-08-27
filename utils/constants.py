"""화면 표시에 쓰는 글꼴·서식 상수."""

from __future__ import annotations

FONT_FAMILY = "Malgun Gothic"
DETAIL_FONT_FAMILY = FONT_FAMILY

APP_TITLE = "국가법령정보 통합검색"
APP_VERSION = "1.0.0"
AUTHOR_NAME = "hgkang"
COPYRIGHT_YEAR = "2026"
CONTACT_EMAIL = "hakang17@naver.com"

# 공개 GitHub 저장소의 정식 Release만 자동 업데이트 대상으로 삼는다.
# 배포 자산 이름은 사용자가 EXE 이름을 바꾸어도 영향을 받지 않도록
# 실제 프로그램 표시 이름과 분리한 고정 ASCII 이름을 사용한다.
# GitHub은 Release 자산 이름에서 한글과 공백을 잘라내므로(예: "국가법령정보
# 통합검색.exe" -> "default.exe") 자산 이름에 한글이나 공백을 쓰지 않는다.
GITHUB_REPOSITORY = "hgkang17/law_info_search"
UPDATE_ASSET_NAME = "law_info_search.exe"
