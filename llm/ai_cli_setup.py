"""AI CLI 설치 여부 확인과 npm 전역 설치.

화면에서는 이 함수를 작업 스레드에서 부른다. npm 설치는 네트워크와 디스크를
쓰는 느린 작업이므로 GUI 스레드에서 직접 실행하면 안 된다.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

from .desktop_mcp import clean_child_environment, cli_argv, no_window_creation_flags


@dataclass(frozen=True)
class AiCliSpec:
    """설치 여부를 확인할 CLI의 실행 명령과 npm 패키지."""

    label: str
    command: str
    npm_package: str
    login_status_args: tuple[str, ...]
    login_args: tuple[str, ...]


CLAUDE_CLI = AiCliSpec(
    label="Claude Code CLI",
    command="claude",
    npm_package="@anthropic-ai/claude-code",
    login_status_args=("auth", "status"),
    login_args=("auth", "login"),
)
CODEX_CLI = AiCliSpec(
    label="Codex CLI",
    command="codex",
    npm_package="@openai/codex",
    login_status_args=("login", "status"),
    login_args=("login",),
)

class AiCliSetupError(RuntimeError):
    """AI CLI 확인 또는 설치 실패를 사용자 문구로 전달한다."""


def _run_cli(
    command: str, *args: str, timeout: int
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cli_argv(command) + list(args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=clean_child_environment(),
        creationflags=no_window_creation_flags(),
        timeout=timeout,
        check=False,
    )


def _result_text(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stdout or result.stderr or "").strip()


def _is_host_bundled_cli(spec: AiCliSpec, resolved: str) -> bool:
    """IDE가 자기 프로세스 PATH에만 넣은 실행 파일은 전역 설치로 세지 않는다."""
    normalized = resolved.replace("/", "\\").casefold()
    return (
        spec == CODEX_CLI
        and "\\.vscode\\extensions\\openai.chatgpt-" in normalized
    )


def cli_version(spec: AiCliSpec) -> str | None:
    """PATH에서 실행 가능한 지정 CLI 버전을 돌려준다."""
    resolved = shutil.which(spec.command)
    if not resolved or _is_host_bundled_cli(spec, resolved):
        return None
    try:
        result = _run_cli(spec.command, "--version", timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return _result_text(result) or "설치됨"


def cli_login_status(spec: AiCliSpec) -> tuple[bool | None, str]:
    """CLI의 저장된 로그인 상태와 짧은 인증 방법을 돌려준다."""
    try:
        result = _run_cli(
            spec.command,
            *spec.login_status_args,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return None, str(error)

    detail = _result_text(result)
    if spec == CLAUDE_CLI and detail:
        try:
            payload = json.loads(detail)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and isinstance(
            payload.get("loggedIn"), bool
        ):
            if not payload["loggedIn"]:
                return False, ""
            method = str(payload.get("authMethod") or "").strip()
            subscription = str(payload.get("subscriptionType") or "").strip()
            labels = [
                value
                for value in (
                    method,
                    f"Claude {subscription.title()}" if subscription else "",
                )
                if value
            ]
            return True, " · ".join(labels)

    lowered = detail.casefold()
    if result.returncode == 0 and "not logged in" not in lowered:
        prefix = "Logged in using "
        if spec == CODEX_CLI and detail.casefold().startswith(prefix.casefold()):
            detail = detail[len(prefix) :]
        return True, detail
    if any(
        marker in lowered
        for marker in ("not logged in", "login required", "authentication required")
    ):
        return False, ""
    return None, detail


def launch_cli_login(spec: AiCliSpec) -> None:
    """공식 CLI 로그인 절차를 띄워 기본 브라우저에서 인증하게 한다."""
    try:
        subprocess.Popen(
            cli_argv(spec.command) + list(spec.login_args),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=clean_child_environment(),
            creationflags=no_window_creation_flags(),
        )
    except OSError as error:
        raise AiCliSetupError(
            f"{spec.label} 로그인 화면을 열지 못했습니다: {error}"
        ) from error


def npm_available() -> bool:
    """npm이 PATH에서 실제로 실행되는지 확인한다."""
    if not shutil.which("npm"):
        return False
    try:
        return _run_cli("npm", "--version", timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def install_cli(spec: AiCliSpec) -> str:
    """npm 전역 설치를 실행하고 설치된 CLI 버전을 확인한다."""
    if not npm_available():
        raise AiCliSetupError(
            "npm을 찾지 못했습니다. 먼저 Node.js를 설치한 뒤 다시 눌러 주세요."
        )
    try:
        result = _run_cli(
            "npm",
            "install",
            "-g",
            spec.npm_package,
            timeout=600,
        )
    except subprocess.TimeoutExpired as error:
        raise AiCliSetupError(
            f"{spec.label} 설치가 10분 안에 끝나지 않았습니다. "
            "인터넷 연결을 확인해 주세요."
        ) from error
    except OSError as error:
        raise AiCliSetupError(f"npm을 실행하지 못했습니다: {error}") from error

    if result.returncode != 0:
        detail = _result_text(result)
        if len(detail) > 800:
            detail = detail[-800:]
        raise AiCliSetupError(
            f"{spec.label} 설치에 실패했습니다."
            + (f"\n{detail}" if detail else "")
        )

    version = cli_version(spec)
    if version is None:
        raise AiCliSetupError(
            f"npm 설치는 끝났지만 {spec.command} 명령을 찾지 못했습니다. "
            "프로그램을 다시 시작한 뒤 AI 연결을 눌러 주세요."
        )
    return version


def ensure_cli(
    spec: AiCliSpec,
    progress: Callable[[str], None] | None = None,
) -> tuple[str, bool]:
    """지정 CLI를 확인하고 없으면 npm으로 설치한다.

    반환값은 ``(버전 문구, 이번 호출에서 설치했는지)``이다.
    """
    if progress:
        progress(f"{spec.label} 설치 여부를 확인하는 중…")
    version = cli_version(spec)
    if version is not None:
        return version, False

    if not npm_available():
        raise AiCliSetupError(
            f"{spec.label}와 npm을 찾지 못했습니다. "
            "먼저 Node.js를 설치한 뒤 다시 눌러 주세요."
        )
    if progress:
        progress(f"{spec.label}가 없어 npm으로 설치하는 중…")
    return install_cli(spec), True

