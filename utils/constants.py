"""화면 표시에 쓰는 글꼴·서식 상수."""

from __future__ import annotations

# 화면 UI(메뉴ㆍ단추ㆍ표) 글꼴. 본문 글꼴과 따로 두지만 지금은 같은
# 맑은고딕을 쓴다. Pretendard와 Segoe UI를 차례로 시험해 봤다가 되돌렸다.
# Segoe UI는 한글 글리프가 없어 한글만 대체 글꼴로 넘어가는 탓에 한 화면에
# 두 글꼴이 섞였다.
FONT_FAMILY = "Malgun Gothic"
UI_FONT_FAMILIES = ("Malgun Gothic", "맑은 고딕")
# 화면 글자 크기(px). pt로 두면 화면 배율에 따라 반올림이 갈려 위젯마다
# 크기가 미세하게 달라진다.
UI_FONT_PIXEL_SIZE = 14
# 스타일시트에 그대로 넣을 수 있는 형태.
UI_FONT_CSS_FAMILY = '"Malgun Gothic", "맑은 고딕"' 
# 본문(법령ㆍ행정규칙 조문) 글꼴. 화면 UI 글꼴과 따로 두어 여기만 바꾸면
# 본문 전체가 함께 바뀐다. 맑은 고딕으로 옮겼다가 실제 화면을 보고 굴림
# 9pt로 되돌렸다. 본문 위 글꼴 칸에서 사용자가 다른 글꼴을 고를 수 있고,
# 고른 값은 설정에 남는다.
DETAIL_FONT_FAMILY = "Gulim"
# 본문 HTML(QTextDocument)용 글꼴 목록. 글꼴이 없는 환경을 위해 대체 글꼴을
# 함께 적는다. 위 DETAIL_FONT_FAMILY와 같은 글꼴을 첫머리에 둔다.
DETAIL_FONT_CSS_FAMILY = "'Gulim', '굴림', 'Malgun Gothic', '맑은 고딕'"
# 위 목록과 같은 차례를 QFont에도 그대로 준다. 목록을 지정하지 않으면
# 위젯이 앱 기본 글꼴의 목록을 상속해 본문 글꼴이 화면 UI 글꼴로 덮인다.
DETAIL_FONT_FAMILIES = ("Gulim", "굴림", "Malgun Gothic", "맑은 고딕")
# 본문을 처음 열 때의 글자 크기(pt). 사용자가 본문 위에서 조절하면 그 값이
# 설정에 남아 다음부터는 그쪽을 쓴다.
DEFAULT_DETAIL_FONT_POINT = 9.0
# 본문 머리줄의 글꼴ㆍ크기ㆍ색상ㆍ초기화ㆍ메모 도구 실제 높이. Qt QSS의
# min-height는 테두리를 제외한 값이라 위젯과 부모 영역은 30px로 맞춘다.
DETAIL_HEADER_CONTROL_HEIGHT = 30
# 기본 본문 글꼴을 바꿀 때 기존 자동 저장값을 한 번만 새 기본값으로 옮긴다.
# 사용자가 마이그레이션 뒤 직접 고른 글꼴과 크기는 다시 덮지 않는다.
DETAIL_FONT_DEFAULTS_VERSION = 1

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
