"""console=False로 빌드하면 stdout/stderr가 None이 된다.

그 상태에서 print()나 라이브러리의 경고 출력이 한 번이라도 일어나면
AttributeError로 프로그램이 죽으므로, 시작 전에 빈 장치로 채워 둔다.
"""

# 런타임 전체에서 유지할 표준 스트림이므로 with로 닫으면 안 된다.
# ruff: noqa: SIM115

import os
import sys


def _windows_standard_stream(handle_id: int, mode: str):
    """windowed bootloader가 남긴 Windows 표준 핸들을 Python으로 감싼다."""
    import ctypes
    import msvcrt

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetStdHandle.argtypes = [ctypes.c_ulong]
    kernel32.GetStdHandle.restype = ctypes.c_void_p
    handle = kernel32.GetStdHandle(handle_id)
    invalid_handle = ctypes.c_void_p(-1).value
    if handle in (0, invalid_handle):
        return None
    flags = os.O_RDONLY if "r" in mode else os.O_WRONLY
    fd = msvcrt.open_osfhandle(handle, flags)
    return os.fdopen(
        fd,
        mode,
        encoding="utf-8",
        errors="replace",
        buffering=1,
        closefd=False,
    )


if "--mcp-server" in sys.argv[1:]:
    # console=False onefile을 Codex/Claude가 stdio MCP 자식으로 띄울 때도
    # PyInstaller는 sys.std*를 None으로 만들 수 있다. 부모가 연결해 준
    # 표준 핸들을 다시 감싸 JSONL 통신을 살린다.
    if os.name == "nt":
        sys.stdin = sys.stdin or _windows_standard_stream(-10, "r")
        sys.stdout = sys.stdout or _windows_standard_stream(-11, "w")
        sys.stderr = sys.stderr or _windows_standard_stream(-12, "w")
    else:
        if sys.stdin is None:
            sys.stdin = open(
                0, "r", encoding="utf-8", errors="replace", closefd=False
            )
        if sys.stdout is None:
            sys.stdout = open(
                1,
                "w",
                encoding="utf-8",
                errors="replace",
                buffering=1,
                closefd=False,
            )
        if sys.stderr is None:
            sys.stderr = open(
                2,
                "w",
                encoding="utf-8",
                errors="replace",
                buffering=1,
                closefd=False,
            )
else:
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
