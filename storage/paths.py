"""프로그램이 파일을 저장하는 위치.

이 폴더에 들어가는 것은 캐시만이 아니다. 저장한 본문에 사용자가 직접
붙인 메모와 즐겨찾기 구성(폴더ㆍ순서)이 같은 json에 함께 들어간다. 이
둘은 API로 다시 받아 올 수 없으므로, 폴더를 지우거나 옮기는 코드를 쓸
때는 캐시가 아니라 사용자 자료로 다룬다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# storage/paths.py 기준으로 한 단계 위가 프로그램 폴더다.
APP_DIR = Path(__file__).resolve().parent.parent

RUNTIME_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else APP_DIR
)

CACHE_FOLDER_NAME = "# law 캐시"

# 저장 자리는 exe 위치와 상관없이 항상 사용자 폴더 하나로 고정한다.
#
# exe 옆에 두면 두 가지가 깨진다. C:\ 루트나 Program Files는 Windows가
# 쓰기를 막아 폴더가 아예 만들어지지 않고, 쓸 수 있는 자리라도 exe를 다른
# 폴더로 옮기면 그 자리에 빈 폴더가 새로 생겨 그때까지 쌓은 메모와
# 즐겨찾기가 사라진 것처럼 보인다. 자리를 하나로 묶으면 둘 다 없어진다.
#
# 대신 사용자 눈에 띄지 않는 곳이라, 프로그램 정보 대화상자가 실제 자리와
# "저장 폴더 열기" 단추, 폴더째 복사해 두라는 안내를 함께 보여 준다.
APPDATA_CACHE_PARENT = (
    Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    / "국가법령정보 통합검색"
)

# 예전 판이 exe 옆에 만들어 두었을 수 있는 자리. 마이그레이션이 읽는다.
PORTABLE_CACHE_ROOT = RUNTIME_DIR / CACHE_FOLDER_NAME

CACHE_ROOT = APPDATA_CACHE_PARENT / CACHE_FOLDER_NAME


LAW_CACHE_DIR = CACHE_ROOT / "저장내역"


LAW_REFERENCE_CACHE_DIR = CACHE_ROOT / "조문"


LAW_REFERENCE_CACHE_SCHEMA = 2


SEARCH_RESULT_CACHE_DIR = CACHE_ROOT / "검색목록"


# AI가 부르는 법령검색 도구의 응답을 담아 두는 자리.
#
# 화면이 쓰는 위 캐시들과 따로 두는 이유는 두 가지다. 담기는 값이
# 응답 JSON이 아니라 모델에게 넘길 완성된 글이고, MCP 서버가 질문마다
# 새 프로세스로 뜨는 탓에 메모리에 들고 있을 수가 없어 파일로만 이어진다.
AI_TOOL_SEARCH_CACHE_DIR = CACHE_ROOT / "AI도구" / "검색"
AI_TOOL_BODY_CACHE_DIR = CACHE_ROOT / "AI도구" / "본문"


# 별표ㆍ서식 첨부 파일(PDF·HWP)을 받아 둔 자리.
#
# 위 캐시들과 달리 JSON이 아니라 파일 원본이 그대로 들어간다. 한 건이
# 수 MB라 무한정 쌓이면 안 되므로 총량 상한을 두고 오래된 것부터 지운다.
# 사용자가 붙인 자료가 아니라 다시 받으면 그만인 순수 캐시다.
ANNEX_FILE_CACHE_DIR = CACHE_ROOT / "별표파일"

# 별표 캐시 총량 상한. 넘으면 오래 안 쓴 것부터 지운다.
ANNEX_FILE_CACHE_MAX_BYTES = 300 * 1024 * 1024


LAW_RENDER_SNAPSHOT_VERSION = 10


# 예전 판으로 쓰던 사용자의 저장 자료가 사라져 보이지 않도록, 이전 이름의
# 폴더가 남아 있으면 새 자리로 옮긴다. 오래된 이름부터 두 세대를 받는다.
_LEGACY_CACHE_DIRS = (
    (RUNTIME_DIR / "저장된_법령", LAW_CACHE_DIR),
    (RUNTIME_DIR / "조문_캐시", LAW_REFERENCE_CACHE_DIR),
    (RUNTIME_DIR / "검색목록_캐시", SEARCH_RESULT_CACHE_DIR),
    (RUNTIME_DIR / "# law 캐시_저장내역", LAW_CACHE_DIR),
    (RUNTIME_DIR / "# law 캐시_조문", LAW_REFERENCE_CACHE_DIR),
    (RUNTIME_DIR / "# law 캐시_검색목록", SEARCH_RESULT_CACHE_DIR),
)


def _move_files(source_dir: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for source in source_dir.iterdir():
        if not source.is_file():
            continue
        destination = target_dir / source.name
        # 새 자리에 같은 이름이 이미 있으면 그쪽이 최신이다.
        if destination.exists():
            source.unlink()
            continue
        source.replace(destination)
    # 옮기지 못한 것이 남아 있으면 폴더를 지우지 않는다.
    if not any(source_dir.iterdir()):
        source_dir.rmdir()


def migrate_legacy_cache_dirs() -> None:
    """예전 자리에 있던 저장 자료를 지금 쓰는 자리로 옮긴다.

    메모와 즐겨찾기가 이 파일들 안에 들어 있어 다시 만들 수 없으므로,
    옮기다 실패하면 원본을 그대로 둔다. 프로그램은 떠야 하니 오류는
    삼키되, 지우는 쪽으로는 절대 기울지 않는다.
    """
    for legacy_dir, target_dir in _LEGACY_CACHE_DIRS:
        try:
            if not legacy_dir.is_dir():
                continue
            _move_files(legacy_dir, target_dir)
        except OSError:
            continue

    # 예전 판은 exe 옆에 저장했다. 그 자리에 남은 메모ㆍ즐겨찾기를 가져온다.
    if not PORTABLE_CACHE_ROOT.is_dir():
        return
    try:
        for source_dir in PORTABLE_CACHE_ROOT.iterdir():
            if source_dir.is_dir():
                _move_files(source_dir, CACHE_ROOT / source_dir.name)
        if not any(PORTABLE_CACHE_ROOT.iterdir()):
            PORTABLE_CACHE_ROOT.rmdir()
    except OSError:
        # 읽지도 지우지도 못하면 원본을 남긴다. 사용자가 직접 복사할 수
        # 있도록 프로그램 정보 대화상자가 두 자리를 모두 알려 준다.
        pass


def ensure_cache_dirs() -> None:
    """저장 폴더를 미리 만들어 둔다. 실패해도 프로그램은 뜬다."""
    for directory in (
        LAW_CACHE_DIR,
        LAW_REFERENCE_CACHE_DIR,
        SEARCH_RESULT_CACHE_DIR,
        ANNEX_FILE_CACHE_DIR,
    ):
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
