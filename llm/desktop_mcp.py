"""Claude/Codex가 이 프로그램의 법령 MCP 서버를 띄우는 방법.

소스 실행 중에는 현재 파이썬으로 ``mcp_server.server`` 모듈을 실행한다.
PyInstaller onefile 배포본에서는 같은 실행 파일을 ``--mcp-server`` 모드로
다시 띄운다. 이 한 곳에서 명령을 만들면 Claude Code와 Codex app-server가
항상 같은 법령 도구를 사용한다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class McpLaunchSpec:
    command: str
    args: tuple[str, ...]
    cwd: str


def law_mcp_launch_spec() -> McpLaunchSpec:
    """현재 실행 형태에 맞는 법령 MCP 서버 명령을 돌려준다."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        return McpLaunchSpec(str(exe), ("--mcp-server",), str(exe.parent))
    project_root = Path(__file__).resolve().parent.parent
    return McpLaunchSpec(
        sys.executable,
        ("-m", "mcp_server.server"),
        str(project_root),
    )


def mcp_server_child_env() -> dict[str, str]:
    """onefile 부모 exe가 물려 준 추출 폴더를 자식이 재사용하지 않게 한다.

    PyInstaller 6.9부터 같은 exe를 다시 띄우면 기본이 '일꾼 프로세스'다.
    그러면 Claude가 띄운 ``--mcp-server``가 도구 목록을 못 내고, 모델은
    ``mcp__law-search__*``가 없다고 답한다. 새 인스턴스로 풀어야 한다.
    """
    return {"PYINSTALLER_RESET_ENVIRONMENT": "1"}


def write_mcp_config_file(config: dict[str, object]) -> str:
    """MCP 설정을 임시 파일로 남긴다. JSON을 명령줄에 실으면 안 된다."""
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        suffix=".json",
        prefix="law_mcp_",
        delete=False,
    )
    try:
        json.dump(config, handle, ensure_ascii=False, separators=(",", ":"))
    finally:
        handle.close()
    return handle.name


def cli_argv(command: str) -> list[str]:
    """PATH의 CLI를 Windows 배치 파일까지 실행 가능한 argv로 바꾼다."""
    resolved = shutil.which(command)
    if not resolved:
        return [command]
    if os.name == "nt" and Path(resolved).suffix.lower() in {".cmd", ".bat"}:
        # ``cmd /c C:\Program Files\...\npm.cmd``는 공백 앞에서 잘릴 수 있다.
        # CALL을 별도 인자로 두면 subprocess가 배치 파일 경로를 정상 인용하고,
        # 뒤에 붙는 CLI 인자도 그대로 전달한다.
        return [
            os.environ.get("COMSPEC", "cmd.exe"),
            "/d",
            "/s",
            "/c",
            "call",
            resolved,
        ]
    return [resolved]


def clean_child_environment() -> dict[str, str]:
    """호스트 파이썬·PyInstaller 변수가 CLI 자식에 섞이지 않게 한다."""
    env = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP"):
        env.pop(name, None)
    for name in list(env):
        if name.startswith("_PYI_") or name.startswith("_MEIPASS"):
            env.pop(name, None)
    return env


def no_window_creation_flags() -> int:
    """Windows GUI 앱에서 CLI 콘솔 창이 번쩍이지 않게 한다."""
    if os.name == "nt":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0



def stop_process_tree(process: subprocess.Popen[str]) -> None:
    """Windows에서 gemini.cmd가 띄운 node 자식까지 함께 끝낸다.

    ``Popen.kill()``은 cmd만 죽이고 node가 stdout 파이프를 붙잡은 채로
    남는 경우가 있다. 그러면 제한 시간이 지나도 '찾는 중'이 풀리지 않는다.
    """
    if process.poll() is not None:
        return
    pid = getattr(process, "pid", None)
    if os.name == "nt" and pid:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            creationflags=no_window_creation_flags(),
            check=False,
        )
    try:
        process.kill()
    except OSError:
        pass
