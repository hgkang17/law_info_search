"""화면 표시에 쓰는 글꼴·서식 상수."""

from __future__ import annotations

FONT_FAMILY = "Malgun Gothic"
# 본문(법령ㆍ행정규칙 조문) 글꼴. 화면 UI 글꼴과 따로 두어 여기만 바꾸면
# 본문 전체가 함께 바뀐다.
DETAIL_FONT_FAMILY = "돋움"
# 본문 HTML(QTextDocument)용 글꼴 목록. 돋움이 없는 환경을 위해 대체 글꼴을
# 함께 적는다. 위 DETAIL_FONT_FAMILY와 같은 글꼴을 첫머리에 둔다.
DETAIL_FONT_CSS_FAMILY = "'돋움', 'Dotum', 'Malgun Gothic'"

APP_TITLE = "국가법령정보 통합검색"
APP_VERSION = "1.3.3"
AUTHOR_NAME = "hgkang"
COPYRIGHT_YEAR = "2026"
CONTACT_EMAIL = "hgkang17@naver.com"

# 공개 GitHub 저장소의 정식 Release만 자동 업데이트 대상으로 삼는다.
# 배포 자산 이름은 사용자가 EXE 이름을 바꾸어도 영향을 받지 않도록
# 실제 프로그램 표시 이름과 분리한 고정 ASCII 이름을 사용한다.
# GitHub은 Release 자산 이름에서 한글과 공백을 잘라내므로(예: "국가법령정보
# 통합검색.exe" -> "default.exe") 자산 이름에 한글이나 공백을 쓰지 않는다.
GITHUB_REPOSITORY = "hgkang17/law_info_search"
UPDATE_ASSET_NAME = "law_info_search.exe"
