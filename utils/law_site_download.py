"""국가법령정보센터의 저장 창에서 법령 전문 HWPX를 내려받는다."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Callable

PLAYWRIGHT_VERSION = "1.60.0"
LAW_SITE_URL = "https://www.law.go.kr/lsInfoP.do"
_REQUIRED_HWPX_MEMBERS = {
    "mimetype",
    "version.xml",
    "Contents/header.xml",
    "Contents/section0.xml",
    "Contents/content.hpf",
    "META-INF/container.xml",
}


def _browser_candidates() -> list[Path]:
    """참고 플러그인처럼 설치된 Chrome을 우선하고 Edge도 찾는다."""
    names = ("chrome.exe", "msedge.exe")
    found: dict[str, list[Path]] = {name: [] for name in names}
    if sys.platform == "win32":
        try:
            import winreg

            for name in names:
                for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                    try:
                        key_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name}"
                        with winreg.OpenKey(hive, key_path) as key:
                            registered = str(winreg.QueryValueEx(key, None)[0]).strip('"')
                            found[name].append(Path(registered))
                    except OSError:
                        pass
        except ImportError:
            pass
    for base_name in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
        base = os.environ.get(base_name)
        if not base:
            continue
        found["chrome.exe"].append(Path(base) / "Google/Chrome/Application/chrome.exe")
        found["msedge.exe"].append(Path(base) / "Microsoft/Edge/Application/msedge.exe")
    candidates = [path for name in names for path in found[name] if path.is_file()]
    return list(dict.fromkeys(candidates))


def _run_hidden(command: list[str], timeout: int = 240, env: dict[str, str] | None = None) -> None:
    options = {"capture_output": True, "text": True, "timeout": timeout, "env": env}
    if sys.platform == "win32":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    result = subprocess.run(command, **options)
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        raise RuntimeError(detail[-1] if detail else f"설치 종료 코드 {result.returncode}")


def _load_playwright(progress: Callable[[str], None]):
    try:
        from playwright.sync_api import sync_playwright

        return sync_playwright
    except ImportError:
        if getattr(sys, "frozen", False):
            raise RuntimeError("배포 실행 파일에 Playwright가 포함되지 않았습니다.") from None
        progress("Playwright 설치 중")
        _run_hidden([sys.executable, "-m", "pip", "install", f"playwright=={PLAYWRIGHT_VERSION}"])
        importlib.invalidate_caches()
        from playwright.sync_api import sync_playwright

        return sync_playwright


def _launch_browser(playwright, progress: Callable[[str], None], downloads_path: str):
    for executable in _browser_candidates():
        try:
            progress(f"{executable.name} 백그라운드 실행 중")
            return playwright.chromium.launch(
                headless=True,
                executable_path=str(executable),
                chromium_sandbox=False,
                downloads_path=downloads_path,
            )
        except Exception:
            # 설치된 브라우저가 손상되었거나 Playwright와 맞지 않으면 다음 후보를 쓴다.
            continue
    if not Path(playwright.chromium.executable_path).is_file():
        progress("Playwright Chromium 설치 중")
        if getattr(sys, "frozen", False):
            # onefile EXE는 `python -m playwright`를 실행할 수 없다. 번들된
            # Playwright의 Node 드라이버 CLI로 사용자 프로필에 설치한다.
            from playwright._impl._driver import compute_driver_executable, get_driver_env

            node, cli = compute_driver_executable()
            _run_hidden([node, cli, "install", "chromium"], timeout=360, env=get_driver_env())
        else:
            _run_hidden([sys.executable, "-m", "playwright", "install", "chromium"], timeout=360)
    progress("Playwright Chromium 백그라운드 실행 중")
    return playwright.chromium.launch(
        headless=True, chromium_sandbox=False, downloads_path=downloads_path
    )


def _verify_hwpx(path: Path) -> None:
    if not zipfile.is_zipfile(path):
        raise ValueError("내려받은 파일이 HWPX 패키지가 아닙니다.")
    with zipfile.ZipFile(path) as archive:
        if not _REQUIRED_HWPX_MEMBERS <= set(archive.namelist()):
            raise ValueError("내려받은 HWPX의 필수 문서 파일이 빠졌습니다.")
        if archive.read("mimetype") != b"application/hwp+zip":
            raise ValueError("내려받은 파일의 HWPX 형식이 올바르지 않습니다.")
        if archive.testzip() is not None:
            raise ValueError("내려받은 HWPX 압축 파일이 손상되었습니다.")


def download_official_law_hwpx(
    law_id: str,
    title: str,
    effective_date: str,
    destination: str | Path,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """공식 사이트의 저장 버튼을 눌러 완성된 파일만 목적지에 둔다."""
    progress = progress or (lambda _message: None)
    if not re.fullmatch(r"\d{1,12}", str(law_id)):
        raise ValueError("법령 ID가 올바르지 않습니다.")
    target = Path(destination)
    if target.suffix.lower() != ".hwpx":
        raise ValueError("저장 경로는 .hwpx 파일이어야 합니다.")
    target.parent.mkdir(parents=True, exist_ok=True)
    sync_playwright = _load_playwright(progress)
    with tempfile.TemporaryDirectory(prefix="law-site-download-") as browser_temp:
        with sync_playwright() as playwright:
            browser = _launch_browser(playwright, progress, browser_temp)
            try:
                context = browser.new_context(accept_downloads=True)
                page = context.new_page()
                progress("국가법령정보센터 본문 여는 중")
                page.goto(
                    f"{LAW_SITE_URL}?lsId={law_id}&ancYnChk=0",
                    wait_until="domcontentloaded",
                    timeout=45000,
                )
                page.locator("#bdySaveBtn").wait_for(state="visible", timeout=30000)
                if title and re.sub(r"\s+", "", title) not in re.sub(r"\s+", "", page.title()):
                    raise ValueError("국가법령정보센터에 열린 법령명이 화면과 다릅니다.")
                # 사이트의 로딩 마스크가 버튼 위에 남는 때에도 저장 함수를 실행한다.
                page.locator("#bdySaveBtn").evaluate("element => element.click()")
                layer = page.locator("#lsOutPutLayer")
                layer.wait_for(state="visible", timeout=30000)
                layer.locator("label[for='FileSaveHwpx1']").click()
                progress("법령 전문 HWPX 내려받는 중")
                with page.expect_download(timeout=90000) as event:
                    layer.locator("#aBtnOutPutSave").click()
                download = event.value
                expected_date = re.sub(r"\D", "", effective_date or "")
                if expected_date and f"({expected_date})" not in download.suggested_filename:
                    raise ValueError("사이트 다운로드의 시행일이 현재 화면과 다릅니다.")
                if not download.suggested_filename.lower().endswith(".hwpx"):
                    raise ValueError("사이트가 HWPX 대신 다른 파일을 보냈습니다.")
                with tempfile.NamedTemporaryFile(
                    prefix=".law-hwpx-", suffix=".part", dir=target.parent, delete=False
                ) as temporary:
                    partial = Path(temporary.name)
                try:
                    download.save_as(partial)
                    failure = download.failure()
                    if failure:
                        raise RuntimeError(f"다운로드 실패: {failure}")
                    _verify_hwpx(partial)
                    partial.replace(target)
                finally:
                    partial.unlink(missing_ok=True)
                progress("한글 문서 저장 완료")
                return target
            finally:
                browser.close()
