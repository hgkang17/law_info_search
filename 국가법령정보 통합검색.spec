# -*- mode: python ; coding: utf-8 -*-
"""국가법령정보 통합검색 실행 파일 빌드 설정.

storage/paths.py가 sys.frozen을 보고 캐시 폴더를 exe 옆에 만들므로,
번들에는 화면에 필요한 자산(아이콘 SVG·Pretendard 글꼴)과 재배포에
필요한 라이선스 사본만 담는다.

배포 편의를 위해 한 파일(onefile)로 묶는다. onefile은 Qt DLL을 실행 파일
안에 넣으므로 LGPL v3 제4조 (d)(1)의 공유 라이브러리 방식이 아니라,
제4조 (d)(0)의 소스 제공 방식에 맞춰 배포한다. GitHub Release에는 동일
태그의 프로그램 소스ㆍ빌드 정보ㆍQt/PySide6 대응 소스 제공 안내를 함께
두고, 프로그램 정보 화면에서도 라이선스와 요청 경로를 표시한다.
"""

# 판올림 때마다 파일 이름이 바뀌면 바로가기가 끊기므로 버전은 넣지 않는다.
# 버전은 프로그램 정보 대화상자에서 보여 준다(utils/constants.py).
APP_NAME = "국가법령정보 통합검색"

datas = [
    ("molit_law_logo.svg", "."),
    # LGPL v3ㆍOFL 1.1이 요구하는 라이선스 사본. ui/assets.py의
    # LICENSE_DIR이 이 위치를 가리킨다.
    ("licenses/LICENSE.LGPLv3.txt", "licenses"),
    ("licenses/LICENSE.GPLv3.txt", "licenses"),
    ("licenses/LICENSE.Pretendard-OFL.txt", "licenses"),
    ("licenses/LICENSE.kordoc-MIT.txt", "licenses"),
    ("licenses/LICENSE.korean-law-mcp-MIT.txt", "licenses"),
    ("licenses/LICENSE.project-MIT.txt", "licenses"),
    # 인증키 발급 안내(물음표 단추). HTML과 그림이 같은 폴더에 있어야
    # 브라우저가 그림을 찾는다.
    ("메뉴얼/API인증키 발급안내.html", "메뉴얼"),
    ("메뉴얼/1. 로그인.webp", "메뉴얼"),
    ("메뉴얼/2. 사용자 가입.webp", "메뉴얼"),
    ("메뉴얼/3. 신청.webp", "메뉴얼"),
    ("메뉴얼/4. 입력.webp", "메뉴얼"),
    # 제미나이 API 키 발급 안내. HTML이 그림을 파일 이름으로만 가리키므로
    # 그림이 하나라도 빠지면 그 자리가 깨져 보인다.
    ("메뉴얼/제미나이 API 발급안내.html", "메뉴얼"),
    ("메뉴얼/Gemini 1. API 키 화면.webp", "메뉴얼"),
    ("메뉴얼/Gemini 2. 새 키 만들기.webp", "메뉴얼"),
    ("메뉴얼/Gemini 3. 생성된 키.webp", "메뉴얼"),
    ("메뉴얼/Gemini 4. 키복사.webp", "메뉴얼"),
    ("메뉴얼/Gemini 5. 프로그램 입력.webp", "메뉴얼"),
    ("checkbox_check.svg", "."),
    ("favorite_plus.svg", "."),
    ("spin_up.svg", "."),
    ("spin_down.svg", "."),
    ("annex_hwp.svg", "."),
    ("annex_pdf.svg", "."),
    ("close_mark.svg", "."),
    ("fonts/PretendardVariable.ttf", "fonts"),
    ("fonts/Pretendard-Thin.ttf", "fonts"),
    ("fonts/Pretendard-ExtraLight.ttf", "fonts"),
    ("fonts/Pretendard-Light.ttf", "fonts"),
    ("fonts/Pretendard-Regular.ttf", "fonts"),
    ("fonts/Pretendard-Medium.ttf", "fonts"),
    ("fonts/Pretendard-SemiBold.ttf", "fonts"),
    ("fonts/Pretendard-Bold.ttf", "fonts"),
    ("fonts/Pretendard-ExtraBold.ttf", "fonts"),
    ("fonts/Pretendard-Black.ttf", "fonts"),
]

analysis = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    # SVG 아이콘과 별표·서식 PDF 미리보기는 실행 중에야 쓰이므로
    # PyInstaller가 정적 분석만으로는 놓칠 수 있다.
    hiddenimports=[
        "PySide6.QtSvg",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtNetwork",
        # 화면 프로그램이 Claude/Codex에게 같은 exe를 --mcp-server로
        # 다시 띄운다. 정적 분석이 이 분기를 놓치면 도구 서버가 통째로
        # 빠지고, 모델은 mcp__law-search__*가 없다고 답한다.
        "mcp.server.fastmcp",
        "mcp.server.stdio",
        "mcp_server.server",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["build_rthook_stdio.py"],
    # 쓰지 않는 Qt 모듈을 빼 실행 파일 크기를 줄인다.
    excludes=[
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuick3D",
        "PySide6.Qt3DCore",
        "PySide6.QtMultimedia",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "tkinter",
        "matplotlib",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    # 콘솔 창 없이 뜨는 화면 프로그램이다.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="molit_law_logo.ico",
)
