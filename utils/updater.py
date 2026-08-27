"""GitHub Releases 기반의 안전한 자동 업데이트 지원.

네트워크와 파일 처리는 Qt에 의존하지 않게 두어 단위 테스트와 onefile
교체 모드 양쪽에서 같은 검증 코드를 사용한다.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Callable, Protocol
import uuid
from urllib.parse import urlparse

import requests

from storage.paths import APPDATA_CACHE_PARENT
from utils.constants import (
    APP_VERSION,
    GITHUB_REPOSITORY,
    UPDATE_ASSET_NAME,
)


GITHUB_API_VERSION = "2022-11-28"
LATEST_RELEASE_API = (
    f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
)
UPDATE_DIR = APPDATA_CACHE_PARENT / "업데이트"
MAX_RELEASE_NOTES_LENGTH = 12_000
MAX_CHECKSUM_BYTES = 16_384
MAX_UPDATE_BYTES = 500 * 1024 * 1024


class UpdateError(RuntimeError):
    """업데이트를 안전하게 계속할 수 없을 때 발생한다."""


class UpdateCancelled(UpdateError):
    """사용자가 다운로드를 취소했다."""


class _Response(Protocol):
    status_code: int
    content: bytes
    headers: dict[str, str]

    def json(self) -> object: ...

    def raise_for_status(self) -> None: ...

    def iter_content(self, chunk_size: int) -> object: ...

    def __enter__(self): ...

    def __exit__(self, exc_type, exc, traceback): ...


class _Session(Protocol):
    def get(self, url: str, **kwargs) -> _Response: ...


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag_name: str
    name: str
    notes: str
    page_url: str
    download_url: str
    asset_name: str
    asset_size: int
    sha256: str


_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*)(?:[-+].*)?$", re.IGNORECASE)
_SHA256_RE = re.compile(r"\b([0-9a-fA-F]{64})\b")


def version_parts(value: str) -> tuple[int, ...]:
    """v2.1.0 같은 태그를 비교 가능한 정수 튜플로 바꾼다."""
    match = _VERSION_RE.fullmatch(value.strip())
    if match is None:
        raise UpdateError(f"올바르지 않은 릴리스 버전입니다: {value!r}")
    parts = tuple(int(part) for part in match.group(1).split("."))
    while len(parts) > 1 and parts[-1] == 0:
        parts = parts[:-1]
    return parts


def is_newer_version(candidate: str, current: str = APP_VERSION) -> bool:
    return version_parts(candidate) > version_parts(current)


def _request_headers(*, binary: bool = False) -> dict[str, str]:
    return {
        "Accept": (
            "application/octet-stream"
            if binary
            else "application/vnd.github+json"
        ),
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
        # HTTP 헤더는 latin-1로 인코딩되므로 한글 프로그램명은 넣지 않는다.
        "User-Agent": f"law_info_search/{APP_VERSION}",
    }


def _validate_github_download_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise UpdateError("GitHub가 아닌 주소의 업데이트 파일은 받지 않습니다.")
    return value


def _response_json(response: _Response) -> dict[str, object]:
    try:
        payload = response.json()
    except (TypeError, ValueError) as error:
        raise UpdateError("GitHub 릴리스 응답을 해석할 수 없습니다.") from error
    if not isinstance(payload, dict):
        raise UpdateError("GitHub 릴리스 응답 형식이 올바르지 않습니다.")
    return payload


def _find_asset(
    assets: object, name: str
) -> tuple[str, int] | None:
    if not isinstance(assets, list):
        return None
    for asset in assets:
        if not isinstance(asset, dict) or asset.get("name") != name:
            continue
        url = str(asset.get("browser_download_url") or "")
        try:
            size = int(asset.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        if not url or size <= 0:
            return None
        return _validate_github_download_url(url), size
    return None


def _read_checksum(
    session: _Session,
    url: str,
    *,
    timeout: tuple[float, float],
) -> str:
    try:
        response = session.get(
            url,
            headers=_request_headers(binary=True),
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        raise UpdateError("업데이트 검증 파일을 받지 못했습니다.") from error
    content = response.content
    if len(content) > MAX_CHECKSUM_BYTES:
        raise UpdateError("업데이트 검증 파일이 비정상적으로 큽니다.")
    match = _SHA256_RE.search(content.decode("ascii", errors="ignore"))
    if match is None:
        raise UpdateError("업데이트 SHA-256 값을 읽을 수 없습니다.")
    return match.group(1).lower()


def fetch_latest_release(
    *,
    session: _Session = requests,
    timeout: tuple[float, float] = (5.0, 15.0),
) -> ReleaseInfo:
    """최신 정식 릴리스와 필수 EXE·SHA-256 자산을 조회한다."""
    try:
        response = session.get(
            LATEST_RELEASE_API,
            headers=_request_headers(),
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        status = getattr(getattr(error, "response", None), "status_code", None)
        if status == 404:
            raise UpdateError(
                "공개된 GitHub 정식 릴리스를 찾지 못했습니다."
            ) from error
        raise UpdateError("GitHub에서 최신 버전을 확인하지 못했습니다.") from error

    payload = _response_json(response)
    tag_name = str(payload.get("tag_name") or "").strip()
    version_parts(tag_name)

    executable = _find_asset(payload.get("assets"), UPDATE_ASSET_NAME)
    if executable is None:
        raise UpdateError(
            f"릴리스에 {UPDATE_ASSET_NAME} 파일이 없습니다."
        )
    download_url, asset_size = executable
    if asset_size > MAX_UPDATE_BYTES:
        raise UpdateError("업데이트 파일 크기가 허용 범위를 넘습니다.")

    checksum_name = f"{UPDATE_ASSET_NAME}.sha256"
    checksum_asset = _find_asset(payload.get("assets"), checksum_name)
    if checksum_asset is None:
        raise UpdateError(
            f"릴리스에 필수 검증 파일 {checksum_name}이 없습니다."
        )
    checksum_url, _checksum_size = checksum_asset
    sha256 = _read_checksum(session, checksum_url, timeout=timeout)

    version = tag_name.lstrip("vV")
    return ReleaseInfo(
        version=version,
        tag_name=tag_name,
        name=str(payload.get("name") or tag_name).strip(),
        notes=str(payload.get("body") or "")[:MAX_RELEASE_NOTES_LENGTH],
        page_url=str(payload.get("html_url") or "").strip(),
        download_url=download_url,
        asset_name=UPDATE_ASSET_NAME,
        asset_size=asset_size,
        sha256=sha256,
    )


def staged_update_path(release: ReleaseInfo) -> Path:
    safe_version = re.sub(r"[^0-9A-Za-z._-]", "_", release.version)
    return UPDATE_DIR / f"{safe_version}-{release.asset_name}"


def download_release(
    release: ReleaseInfo,
    destination: Path,
    *,
    session: _Session = requests,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    timeout: tuple[float, float] = (5.0, 30.0),
) -> Path:
    """릴리스 EXE를 임시 파일로 받은 뒤 크기와 SHA-256을 검증한다."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f"{destination.name}.part")
    digest = hashlib.sha256()
    received = 0
    try:
        with session.get(
            release.download_url,
            headers=_request_headers(binary=True),
            stream=True,
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            with partial.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if cancelled is not None and cancelled():
                        raise UpdateCancelled("업데이트 다운로드를 취소했습니다.")
                    if not chunk:
                        continue
                    received += len(chunk)
                    if received > release.asset_size:
                        raise UpdateError("업데이트 파일 크기가 릴리스 정보와 다릅니다.")
                    output.write(chunk)
                    digest.update(chunk)
                    if progress is not None:
                        progress(received, release.asset_size)
                output.flush()
                os.fsync(output.fileno())

        if received != release.asset_size:
            raise UpdateError("업데이트 파일이 완전히 다운로드되지 않았습니다.")
        if not hmac.compare_digest(digest.hexdigest(), release.sha256):
            raise UpdateError("업데이트 파일의 SHA-256 검증에 실패했습니다.")
        os.replace(partial, destination)
        return destination
    except UpdateError:
        partial.unlink(missing_ok=True)
        raise
    except (OSError, requests.RequestException) as error:
        partial.unlink(missing_ok=True)
        raise UpdateError("업데이트 파일을 저장하지 못했습니다.") from error


def _is_protected_location(path: Path) -> bool:
    """관리자만 쓸 수 있는 자리인지. Windows가 지키는 폴더들이다."""
    try:
        resolved = Path(path).resolve()
    except OSError:
        return False
    parent = resolved.parent
    # 드라이브 최상위(C:\)에 그대로 둔 경우도 일반 사용자는 쓰지 못한다.
    if parent == parent.parent:
        return True
    lowered = str(parent).lower()
    for name in (
        "program files",
        "program files (x86)",
        "programdata",
        "windows",
    ):
        marker = os.sep + name
        if lowered.endswith(marker) or (marker + os.sep) in lowered:
            return True
    return False


def install_location_hint(path: Path) -> str:
    """왜 교체가 막혔는지, 무엇을 하면 되는지 사람 말로 돌려준다."""
    if _is_protected_location(path):
        return (
            "이 폴더는 관리자 권한이 있어야 파일을 바꿀 수 있습니다. "
            "프로그램을 바탕화면이나 문서 폴더로 옮긴 뒤 다시 시도해 주세요."
        )
    return (
        "백신 실시간 검사나 클라우드 동기화 폴더가 파일을 붙잡고 있을 수 "
        "있습니다. 프로그램을 완전히 닫고 다시 시도하거나, 바탕화면이나 "
        "문서 폴더로 옮긴 뒤 시도해 주세요. 디스크 여유 공간도 확인해 "
        "주세요."
    )


def executable_location_is_writable() -> bool:
    """지금 EXE가 있는 폴더에 우리가 파일을 쓸 수 있는지 미리 확인한다.

    76MB를 다 내려받고 나서야 권한이 없다는 것을 아는 일이 없도록,
    업데이트를 시작하기 전에 같은 폴더에 임시 파일을 만들어 본다.
    """
    if not can_self_update():
        return True
    folder = Path(sys.executable).resolve().parent
    probe = folder / f".{uuid.uuid4().hex}.update-probe"
    try:
        probe.touch()
    except OSError:
        return False
    finally:
        probe.unlink(missing_ok=True)
    return True


def can_self_update() -> bool:
    return bool(getattr(sys, "frozen", False) and sys.platform == "win32")


def launch_staged_update(
    staged_executable: Path, tag_name: str, expected_sha256: str
) -> None:
    """내려받은 새 EXE를 교체 도우미 모드로 시작한다."""
    if not can_self_update():
        raise UpdateError("자동 교체는 Windows 배포용 EXE에서만 지원합니다.")
    staged = Path(staged_executable).resolve()
    target = Path(sys.executable).resolve()
    if not staged.is_file() or staged.suffix.lower() != ".exe":
        raise UpdateError("교체할 업데이트 실행 파일을 찾지 못했습니다.")
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.Popen(
            [
                str(staged),
                "--apply-update",
                str(target),
                str(os.getpid()),
                tag_name,
                expected_sha256,
            ],
            cwd=str(target.parent),
            close_fds=True,
            creationflags=creation_flags,
        )
    except OSError as error:
        raise UpdateError("업데이트 교체 프로그램을 시작하지 못했습니다.") from error


def _wait_for_process_exit(pid: int, timeout_seconds: float = 120.0) -> None:
    """Windows 프로세스 핸들을 기다리되 실패하면 파일 잠금 재시도로 넘긴다."""
    if sys.platform != "win32" or pid <= 0:
        return
    try:
        import ctypes

        synchronize = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            return
        try:
            ctypes.windll.kernel32.WaitForSingleObject(
                handle, int(timeout_seconds * 1000)
            )
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except (AttributeError, OSError):
        return


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _discard_candidate(candidate: Path) -> None:
    """실패한 임시 파일을 치운다. 못 치워도 그것 때문에 터지지 않는다.

    백신이 방금 만든 파일을 잡고 있으면 지우는 것마저 실패한다. 여기서
    다시 예외가 나면 정작 사용자가 알아야 할 원래 실패 사유가 가려진다.
    원본 EXE는 손대지 않았으므로 임시 파일이 남아도 프로그램은 멀쩡하다.
    """
    try:
        candidate.unlink(missing_ok=True)
    except OSError:
        pass


def install_staged_executable(
    source: Path, target: Path, expected_sha256: str = ""
) -> None:
    """새 파일을 같은 폴더에 쓴 뒤 원래 EXE와 원자적으로 교체한다."""
    source = Path(source).resolve()
    target = Path(target).resolve()
    if source == target or source.suffix.lower() != ".exe":
        raise UpdateError("업데이트 원본 실행 파일이 올바르지 않습니다.")
    if target.suffix.lower() != ".exe" or not target.is_file():
        raise UpdateError("교체할 기존 실행 파일이 올바르지 않습니다.")

    candidate = target.with_name(f".{target.name}.update-new.exe")
    try:
        if expected_sha256 and not hmac.compare_digest(
            _file_sha256(source), expected_sha256.lower()
        ):
            raise UpdateError("교체 직전 업데이트 파일 검증에 실패했습니다.")
        shutil.copyfile(source, candidate)
        with candidate.open("rb+") as copied:
            copied.flush()
            os.fsync(copied.fileno())
        if expected_sha256 and not hmac.compare_digest(
            _file_sha256(candidate), expected_sha256.lower()
        ):
            raise UpdateError("복사된 업데이트 파일 검증에 실패했습니다.")
        os.replace(candidate, target)
    except UpdateError:
        _discard_candidate(candidate)
        raise
    except OSError as error:
        _discard_candidate(candidate)
        # 이 문구는 교체 도우미가 명령줄 인자로 넘겨 주므로 한 줄로 둔다.
        # 사람이 읽을 안내는 받는 쪽에서 경로를 보고 덧붙인다.
        reason = getattr(error, "strerror", "") or str(error)
        raise UpdateError(
            f"기존 실행 파일을 교체하지 못했습니다: {target} ({reason})"
        ) from error


def apply_update_mode(
    target_text: str,
    old_pid_text: str,
    tag_name: str,
    expected_sha256: str,
) -> int:
    """새 onefile EXE 안에서 실행되는 최소 교체 모드."""
    source = Path(sys.executable).resolve()
    target = Path(target_text).resolve()
    try:
        old_pid = int(old_pid_text)
    except ValueError:
        old_pid = 0
    _wait_for_process_exit(old_pid)

    error_message = ""
    for attempt in range(40):
        try:
            install_staged_executable(source, target, expected_sha256)
            break
        except UpdateError as error:
            error_message = str(error)
            if attempt == 39:
                break
            time.sleep(0.25)
    else:  # pragma: no cover - range는 항상 끝나지만 방어적으로 둔다.
        error_message = "업데이트 파일 교체에 실패했습니다."

    arguments = [str(target)]
    if error_message:
        arguments.extend(["--update-error", error_message])
    else:
        arguments.extend(
            [
                "--updated-version",
                tag_name,
                "--cleanup-update-source",
                str(source),
            ]
        )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.Popen(
            arguments,
            cwd=str(target.parent),
            close_fds=True,
            creationflags=creation_flags,
        )
    except OSError:
        return 2
    return 1 if error_message else 0


def consume_startup_option(arguments: list[str], name: str) -> str:
    """QApplication에 넘기기 전 내부용 옵션 하나를 꺼낸다."""
    try:
        index = arguments.index(name)
    except ValueError:
        return ""
    if index + 1 >= len(arguments):
        arguments.pop(index)
        return ""
    arguments.pop(index)
    return arguments.pop(index)


def cleanup_staged_executable(path_text: str) -> bool:
    if not path_text:
        return True
    path = Path(path_text)
    try:
        if path.parent.resolve() != UPDATE_DIR.resolve() or path.suffix.lower() != ".exe":
            return False
        path.unlink(missing_ok=True)
        return True
    except OSError:
        return False
