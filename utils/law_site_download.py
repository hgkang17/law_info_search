"""국가법령정보센터의 저장 창에서 법령 전문 HWPX를 내려받는다."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from collections.abc import Callable
from urllib.parse import unquote

import requests

PLAYWRIGHT_VERSION = "1.60.0"
LAW_SITE_URL = "https://www.law.go.kr/lsInfoP.do"
LAW_SITE_ORIGIN = "https://www.law.go.kr"
_REQUIRED_HWPX_MEMBERS = {
    "mimetype",
    "version.xml",
    "Contents/header.xml",
    "Contents/section0.xml",
    "Contents/content.hpf",
    "META-INF/container.xml",
}


class _FastDownloadUnavailable(RuntimeError):
    """사이트의 빠른 POST 저장 경로를 쓸 수 없어 브라우저 대체가 필요하다."""


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


def _unique_download_path(directory: Path, suggested_filename: str) -> Path:
    """사이트 파일명을 유지하면서 기존 다운로드를 덮어쓰지 않는다."""
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", suggested_filename).strip(" .")
    if not filename.lower().endswith(".hwpx"):
        raise ValueError("사이트가 HWPX 대신 다른 파일을 보냈습니다.")
    base = Path(filename)
    candidate = directory / filename
    index = 1
    while candidate.exists():
        candidate = directory / f"{base.stem} ({index}){base.suffix}"
        index += 1
    return candidate


def _site_input_value(page_html: str, element_id: str) -> str:
    match = re.search(
        rf'<input\b(?=[^>]*\bid=["\']{re.escape(element_id)}["\'])'
        rf'(?=[^>]*\bvalue=["\']([^"\']*)["\'])[^>]*>',
        page_html,
        re.IGNORECASE,
    )
    if not match:
        raise _FastDownloadUnavailable(f"사이트 응답에서 {element_id} 값을 찾지 못했습니다.")
    return match.group(1)


def _site_effective_date(page_html: str, law_sequence: str) -> str:
    match = re.search(
        rf"lsPopViewAll2\(\s*'{re.escape(law_sequence)}'\s*,\s*'[^']*'\s*,"
        rf"\s*'[^']*'\s*,\s*'(\d{{8}})'",
        page_html,
    )
    if not match:
        raise _FastDownloadUnavailable("사이트 응답에서 현행 시행일을 찾지 못했습니다.")
    return match.group(1)


def _response_filename(content_disposition: str) -> str:
    extended = re.search(r"filename\*=UTF-8''([^;]+)", content_disposition, re.IGNORECASE)
    if extended:
        filename = unquote(extended.group(1))
    else:
        quoted = re.search(r'filename="([^"]+)"', content_disposition, re.IGNORECASE)
        plain = re.search(r"filename=([^;]+)", content_disposition, re.IGNORECASE)
        filename = (quoted or plain).group(1).strip(" \"") if (quoted or plain) else ""
        try:
            filename = filename.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    filename = Path(filename.replace("\\", "/")).name.strip()
    if not filename:
        raise _FastDownloadUnavailable("사이트가 다운로드 파일명을 보내지 않았습니다.")
    if not filename.lower().endswith(".hwpx"):
        raise _FastDownloadUnavailable("사이트가 HWPX 대신 다른 파일을 보냈습니다.")
    return filename


def _download_hwpx_direct(
    law_id: str,
    title: str,
    effective_date: str,
    directory: Path,
    destination_path: Path,
    is_directory: bool,
    progress: Callable[[str], None],
) -> Path:
    """화면 렌더링 없이 사이트의 HWPX POST 저장 요청을 직접 실행한다."""
    progress("한글 문서 빠른 다운로드 연결 중")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/140 Safari/537.36"
        ),
        "Referer": f"{LAW_SITE_URL}?lsId={law_id}&ancYnChk=0",
        "X-Requested-With": "XMLHttpRequest",
    }
    try:
        with requests.Session() as session:
            session.headers.update(headers)
            page_response = session.get(
                LAW_SITE_URL,
                params={"lsId": law_id, "ancYnChk": "0"},
                timeout=15,
            )
            page_response.raise_for_status()
            page_html = page_response.content.decode("utf-8")
            law_sequence = _site_input_value(page_html, "lsiSeq")
            site_title = _site_input_value(page_html, "lsNm")
            character_class = _site_input_value(page_html, "lsBdyChrCls")
            site_date = _site_effective_date(page_html, law_sequence)
            if title and re.sub(r"\s+", "", title) not in re.sub(r"\s+", "", site_title):
                raise ValueError(
                    f"국가법령정보센터에 열린 법령명이 화면과 다릅니다. (사이트: {site_title})"
                )
            expected_date = re.sub(r"\D", "", effective_date or "")
            if expected_date and expected_date != site_date:
                raise ValueError("사이트 다운로드의 시행일이 현재 화면과 다릅니다.")

            appendix_response = session.post(
                f"{LAW_SITE_ORIGIN}/joListRInc.do",
                params={
                    "lsiSeq": law_sequence,
                    "mode": "9",
                    "chapNo": "1",
                    "nwYn": "3",
                    "efYd": site_date,
                    "gubun": "save",
                    "ancYnChk": "0",
                    "timeStamp": int(time.time() * 1000),
                },
                timeout=15,
            )
            appendix_response.raise_for_status()
            appendix_items = appendix_response.json()
            if not isinstance(appendix_items, list):
                raise _FastDownloadUnavailable("사이트의 부칙 목록 형식이 바뀌었습니다.")
            appendix_sequences = list(dict.fromkeys(
                str(item.get("joNo") or "")
                for item in appendix_items
                if isinstance(item, dict)
                and item.get("cls") == "arSeq"
                and item.get("joChgYn") == "Y"
                and item.get("joNo")
            ))
            if appendix_items and not appendix_sequences:
                raise _FastDownloadUnavailable(
                    "사이트의 현행 부칙을 구분하지 못했습니다."
                )
            appendix_values = ",," + ",".join(
                f"{sequence}#" for sequence in appendix_sequences
            ) if appendix_sequences else ","
            save_params = {
                "trSeq": law_sequence,
                "efDvPop": "",
                "nwJoYnInfo": "",
                "efGubun": "",
                "ancYnChk": "0",
            }
            if appendix_sequences:
                save_params["lastCheck"] = "Y"
            response = session.post(
                f"{LAW_SITE_ORIGIN}/lsHwpxSave.do",
                params=save_params,
                data={
                    "lsiSeq": law_sequence,
                    "chrClsCd": character_class,
                    "outPutTitleYn": "",
                    "joAllCheck": "Y",
                    "onlyEfYd": "",
                    "efLsGubun": "",
                    "efDvPop": "",
                    "nwJoYnInfo": "",
                    "arSeqs": appendix_values,
                    "mokChaChk": "N",
                    "bylChaChk": "N",
                    "arIds": ",".join(
                        f"check_outPut_{sequence}" for sequence in appendix_sequences
                    ),
                    "bylAllSeq": "",
                    "efYd": site_date,
                    "efGubun": "",
                    "test1": "on",
                    "joEfOutPutYn": "on",
                    "coverDpYn": "1",
                    "lsNmFont": "goThic",
                    "lsJoSize": "10",
                    "lsJoFont": "smyoungjo",
                    "spaceCls": "2",
                    "fileType": "hwpx",
                },
                timeout=30,
                stream=True,
            )
            response.raise_for_status()
            suggested_filename = _response_filename(
                response.headers.get("Content-Disposition", "")
            )
            if expected_date and f"({expected_date})" not in suggested_filename:
                raise ValueError("사이트 다운로드의 시행일이 현재 화면과 다릅니다.")
            target = (
                _unique_download_path(directory, suggested_filename)
                if is_directory else destination_path
            )
            with tempfile.NamedTemporaryFile(
                prefix=".law-hwpx-", suffix=".part", dir=directory, delete=False
            ) as temporary:
                partial = Path(temporary.name)
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        temporary.write(chunk)
            try:
                _verify_hwpx(partial)
                partial.replace(target)
            except ValueError as exc:
                raise _FastDownloadUnavailable(str(exc)) from exc
            finally:
                partial.unlink(missing_ok=True)
    except requests.RequestException as exc:
        raise _FastDownloadUnavailable(str(exc)) from exc
    progress("한글 문서 저장 완료")
    return target


def _wait_for_site_download(page, context, layer):
    """저장 결과가 현재 페이지나 새 창에서 생겨도 다운로드를 잡는다."""
    downloads = []
    alerts = []

    def on_dialog(dialog) -> None:
        if dialog.type == "confirm":
            dialog.accept()
        else:
            alerts.append(dialog.message)
            dialog.dismiss()

    def attach_page(opened) -> None:
        opened.on("download", lambda download: downloads.append(download))
        opened.on("dialog", on_dialog)

    context.on("page", attach_page)
    attach_page(page)
    # 사이트의 저장 창은 화면 밖에 놓일 수 있다. 실제 input을 선택하고
    # 저장 링크의 click을 DOM에서 실행해야 Playwright의 좌표 클릭이 막히지 않는다.
    radio = layer.locator("#FileSaveHwpx1")
    radio.evaluate("element => element.click()")
    if not radio.is_checked():
        raise RuntimeError("사이트 저장 창에서 HWPX 형식을 선택하지 못했습니다.")
    layer.locator("#aBtnOutPutSave").evaluate("element => element.click()")
    deadline = time.monotonic() + 60
    while not downloads:
        if alerts:
            raise RuntimeError(f"국가법령정보센터 안내: {alerts[-1]}")
        if time.monotonic() >= deadline:
            raise RuntimeError("사이트 저장 버튼을 눌렀지만 60초 동안 다운로드가 시작되지 않았습니다.")
        page.wait_for_timeout(200)
    return downloads[0]


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
    destination_path = Path(destination)
    is_directory = destination_path.is_dir() or not destination_path.suffix
    if not is_directory and destination_path.suffix.lower() != ".hwpx":
        raise ValueError("저장 경로는 다운로드 폴더 또는 .hwpx 파일이어야 합니다.")
    directory = destination_path if is_directory else destination_path.parent
    directory.mkdir(parents=True, exist_ok=True)
    try:
        return _download_hwpx_direct(
            law_id, title, effective_date, directory, destination_path,
            is_directory, progress,
        )
    except _FastDownloadUnavailable:
        # 사이트가 POST 형식을 바꾸거나 직접 연결을 일시 차단하면, 이미
        # 검증한 실제 저장 창 조작으로 자동 복구한다.
        progress("빠른 다운로드 연결 실패 · 브라우저로 다시 시도 중")
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
                site_title = page.title()
                if title and re.sub(r"\s+", "", title) not in re.sub(r"\s+", "", site_title):
                    raise ValueError(f"국가법령정보센터에 열린 법령명이 화면과 다릅니다. (사이트: {site_title})")
                # 사이트의 로딩 마스크가 버튼 위에 남는 때에도 저장 함수를 실행한다.
                page.locator("#bdySaveBtn").evaluate("element => element.click()")
                layer = page.locator("#lsOutPutLayer")
                layer.wait_for(state="visible", timeout=30000)
                # 페이지 껍데기와 저장 버튼이 먼저 보이고, 저장 창을 열 때
                # 조문 목록 AJAX 조회가 시작되는 경우가 있다. 사이트의
                # beforeSavePrint()는 arSeq가 하나도 없으면 "법령 본문 목록
                # 조회 후 사용하세요"라는 안내만 띄운다.
                progress("법령 본문 목록 불러오는 중")
                try:
                    page.locator("input[name='arSeq']").first.wait_for(
                        state="attached", timeout=60000
                    )
                except Exception as exc:
                    raise RuntimeError(
                        "국가법령정보센터에서 60초 안에 법령 본문 목록을 불러오지 못했습니다."
                    ) from exc
                progress("법령 전문 HWPX 내려받는 중")
                download = _wait_for_site_download(page, context, layer)
                expected_date = re.sub(r"\D", "", effective_date or "")
                if expected_date and f"({expected_date})" not in download.suggested_filename:
                    raise ValueError("사이트 다운로드의 시행일이 현재 화면과 다릅니다.")
                target = (
                    _unique_download_path(directory, download.suggested_filename)
                    if is_directory else destination_path
                )
                with tempfile.NamedTemporaryFile(
                    prefix=".law-hwpx-", suffix=".part", dir=directory, delete=False
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
