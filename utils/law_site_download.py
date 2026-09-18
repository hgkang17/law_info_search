"""국가법령정보센터의 저장 창에서 법령·행정규칙·자치법규 전문을 내려받는다.

사이트 저장 창의 파일 형식 기본값은 **HWP**다. 같은 문서라도 HWPX로
받으면 편·장·절 제목의 ``<개정 ...>`` 표기가 빠진다(실측: 국토계획법
장 제목 12개 중 8개 누락, ``<개정`` 338개 → 328개). 두 형식을 서로 다른
엔드포인트가 만들기 때문이므로, 사이트 기본값과 같은 HWP로 받는다.
HWP 선택지가 주는 파일은 이진 형식이 아니라 HWPML(XML 텍스트)이다.

``articles``에 조 번호를 주면 그 조문만 담긴 문서를 받는다. 주지 않으면
전문을 받는다.
"""

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
from collections.abc import Callable, Sequence
from urllib.parse import unquote

import requests

PLAYWRIGHT_VERSION = "1.60.0"
LAW_SITE_ORIGIN = "https://www.law.go.kr"

# 종류별 상세 화면·조문 목록·저장 엔드포인트. 셋 다 저장 창을 같은
# `#bdySaveBtn`으로 열지만 레이어 id와 형식 라디오 id가 다르다.
_KINDS: dict[str, dict[str, object]] = {
    "law": {
        "label": "법령",
        "page": "lsInfoP.do",
        "page_param": "lsId",
        "save": "lsNewHwpSave.do",
        "layers": ("#lsOutPutLayer",),
        "hwp_radio": "#FileSaveHwp1",
    },
    "admrul": {
        "label": "행정규칙",
        "page": "admRulInfoP.do",
        "page_param": "admRulSeq",
        "list": "admRulJoListRInc.do",
        "list_param": "admRulSeq",
        "article_mode": "99",
        "appendix_mode": "2",
        "save": "admRulHwpSave.do",
        "layers": ("#admRulOutPutLayer", "#lsOutPutLayer"),
        "hwp_radio": "#FileSaveHwp",
    },
    "ordin": {
        "label": "자치법규",
        "page": "ordinInfoP.do",
        "page_param": "ordinSeq",
        "list": "ordinJoListRInc_XML.do",
        "list_param": "ordinSeq",
        "article_mode": "99",
        "appendix_mode": "22",
        "save": "ordinHwpSave.do",
        "layers": ("#lsOutPutLayer", "#ordinOutPutLayer"),
        "hwp_radio": "#FileSaveHwp",
    },
}

# 저장 창의 글꼴·줄간격 기본값. 사이트가 보내는 값과 같게 맞춘다.
_SAVE_STYLE = {
    "lsNmFont": "goThic",
    "lsJoSize": "10",
    "lsJoFont": "smyoungjo",
    "spaceCls": "2",
    "fileType": "hwp",
}

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/140 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
}


class _FastDownloadUnavailable(RuntimeError):
    """사이트의 빠른 POST 저장 경로를 쓸 수 없어 브라우저 대체가 필요하다."""


def _kind_spec(kind: str) -> dict[str, object]:
    spec = _KINDS.get(str(kind or "law"))
    if spec is None:
        raise ValueError(f"내려받을 수 없는 종류입니다: {kind}")
    return spec


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


def _verify_hwpml(path: Path) -> None:
    """저장 창의 HWP 선택지가 주는 HWPML(XML) 문서인지 확인한다.

    확장자만 보고 판단하지 않는다. 사이트가 오류 쪽을 보내면 같은 이름의
    HTML이 올 수 있고, HWPX(ZIP)는 장·절 개정 표기가 빠진 다른 문서다.
    """
    if zipfile.is_zipfile(path):
        raise ValueError("내려받은 파일이 HWP가 아니라 HWPX 패키지입니다.")
    head = path.read_bytes()[:4096]
    if not head.lstrip().startswith(b"<?xml"):
        raise ValueError("내려받은 파일이 한글 문서(HWPML)가 아닙니다.")
    try:
        text = head.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("내려받은 한글 문서의 인코딩이 올바르지 않습니다.") from exc
    if "<HWPML" not in text:
        raise ValueError("내려받은 한글 문서에 HWPML 본문이 없습니다.")


def _unique_download_path(directory: Path, suggested_filename: str) -> Path:
    """사이트 파일명을 유지하면서 기존 다운로드를 덮어쓰지 않는다."""
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", suggested_filename).strip(" .")
    if not filename.lower().endswith(".hwp"):
        raise ValueError("사이트가 한글 문서 대신 다른 파일을 보냈습니다.")
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


def _optional_site_input_value(
    page_html: str, element_id: str, default: str = ""
) -> str:
    """있으면 쓰고 없으면 기본값. 화면마다 있는 칸이 다른 자리에 쓴다."""
    try:
        return _site_input_value(page_html, element_id)
    except _FastDownloadUnavailable:
        return default


def _site_page_title(page_html: str) -> str:
    match = re.search(r"<title>(.*?)</title>", page_html, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


# 사이트 본문 화면의 <title>은 ``행정규칙 &gt; 본문 | 국가법령정보센터``
# 처럼 구분만 적고 문서명을 담지 않는다(이름은 자바스크립트가 나중에
# 채운다). 이런 제목으로는 견줄 이름이 없으므로 확인을 건너뛴다. 문서를
# 고르는 열쇠는 주소에 실어 보낸 일련번호이고, 이름 확인은 그 위에 덧댄
# 안전장치일 뿐이다. 예전에는 이 제목을 이름으로 알고 견주다가 행정규칙ㆍ
# 자치법규 다운로드가 늘 "열린 문서명이 화면과 다릅니다"로 끝났다.
_SITE_GENERIC_TITLE = re.compile(
    r"^[^>|]*(?:>|&gt;)\s*본문\s*\|", re.IGNORECASE
)
# 가운뎃점은 자료마다 글자가 다르다(``도시·군``ㆍ``도시ㆍ군``). 한 글자로
# 맞춰 놓고 견주지 않으면 같은 문서가 다른 이름으로 읽힌다.
_MIDDLE_DOTS = re.compile(r"[·ㆍ・･‧∙⋅]")


def _normalized_title(value: str) -> str:
    return _MIDDLE_DOTS.sub("·", re.sub(r"\s+", "", str(value or "")))


def _check_title(expected: str, actual: str) -> None:
    if not expected or not actual:
        return
    if _SITE_GENERIC_TITLE.match(actual.strip()):
        return
    if _normalized_title(expected) not in _normalized_title(actual):
        raise ValueError(f"국가법령정보센터에 열린 문서명이 화면과 다릅니다. (사이트: {actual})")


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
    if not filename.lower().endswith(".hwp"):
        raise _FastDownloadUnavailable("사이트가 한글 문서 대신 다른 파일을 보냈습니다.")
    return filename


def article_code(kind: str, jo: str) -> str:
    """앱의 6자리 조 번호를 저장 요청이 쓰는 조문 코드로 바꾼다.

    ``000100``(제1조)ㆍ``001202``(제12조의2)를 받는다. 행정규칙만 가지번호
    앞에 ``-0000`` 자리가 하나 더 붙는다(실측).
    """
    text = re.sub(r"\D", "", str(jo or ""))
    if len(text) != 6:
        raise ValueError(f"조 번호가 올바르지 않습니다: {jo}")
    number, branch = text[:4], text[4:]
    if str(kind) == "admrul":
        return f"{number}-0000:{branch}"
    return f"{number}:{branch}"


def _selected_articles(kind: str, articles: Sequence[str] | None) -> str:
    """고른 조문들을 ``joNo`` 문자열로 만든다. 없으면 빈 글자."""
    if not articles:
        return ""
    return ",".join(article_code(kind, jo) for jo in articles)


def _article_list(session, spec, item_id: str, mode: str) -> list[dict]:
    """행정규칙·자치법규의 조문/부칙 목록을 받는다."""
    response = session.post(
        f"{LAW_SITE_ORIGIN}/{spec['list']}",
        params={
            str(spec["list_param"]): item_id,
            "mode": mode,
            "timeStamp": int(time.time() * 1000),
        },
        timeout=20,
    )
    response.raise_for_status()
    items = response.json()
    if not isinstance(items, list):
        raise _FastDownloadUnavailable("사이트의 조문 목록 형식이 바뀌었습니다.")
    return [item for item in items if isinstance(item, dict)]


def _build_article_parameter(items: list[dict], *, dashed: bool) -> str:
    """조문 목록을 저장 요청의 ``joNo`` 문자열로 되돌린다.

    목록 한 줄이 파라미터 한 칸이다. 장 제목 줄(``joYn`` 이 Y가 아닌 것)은
    ``chapNo``를 그대로 쓰고, 조문 줄은 조 번호 형식으로 적는다. 이 목록을
    보내지 않으면 사이트가 표지와 부칙만 담은 문서를 준다(실측).
    """
    parts: list[str] = []
    for item in items:
        if str(item.get("cls") or "") != "joNo":
            continue
        if str(item.get("joYn") or "") == "Y":
            number = str(item.get("oriJoNo") or "")
            branch = str(item.get("joBrNo") or "")
            if dashed:
                parts.append(f"{number}-{item.get('dashNo') or '0000'}:{branch}")
            else:
                parts.append(f"{number}:{branch}")
        else:
            parts.append(str(item.get("chapNo") or ""))
    if not parts:
        raise _FastDownloadUnavailable("사이트의 조문 목록이 비어 있습니다.")
    return ",".join(parts)


def _last_appendix(items: list[dict]) -> str:
    """부칙 목록의 마지막 항목. 저장 요청의 ``arSeq``가 이 값이다(실측)."""
    sequences = [
        str(item.get("joNo") or "")
        for item in items
        if str(item.get("cls") or "") == "arSeq" and item.get("joNo")
    ]
    return sequences[-1] if sequences else ""


def _law_save_request(session, item_id, title, effective_date, articles=None):
    """법령: 전문은 ``joAllCheck=Y`` 축약이 통해 목록을 만들지 않는다.

    고른 조문이 있으면 전체 선택을 끄고 ``joNo``에 그 조문만 적는다.
    """
    page = session.get(
        f"{LAW_SITE_ORIGIN}/lsInfoP.do",
        params={"lsId": item_id, "ancYnChk": "0"},
        timeout=15,
    )
    page.raise_for_status()
    html = page.content.decode("utf-8")
    sequence = _site_input_value(html, "lsiSeq")
    _check_title(title, _site_input_value(html, "lsNm"))
    character_class = _site_input_value(html, "lsBdyChrCls")
    site_date = _site_effective_date(html, sequence)
    expected = re.sub(r"\D", "", effective_date or "")
    if expected and expected != site_date:
        raise ValueError("사이트 다운로드의 시행일이 현재 화면과 다릅니다.")

    appendix = session.post(
        f"{LAW_SITE_ORIGIN}/joListRInc.do",
        params={
            "lsiSeq": sequence, "mode": "9", "chapNo": "1", "nwYn": "3",
            "efYd": site_date, "gubun": "save", "ancYnChk": "0",
            "timeStamp": int(time.time() * 1000),
        },
        timeout=15,
    )
    appendix.raise_for_status()
    items = appendix.json()
    if not isinstance(items, list):
        raise _FastDownloadUnavailable("사이트의 부칙 목록 형식이 바뀌었습니다.")
    sequences = list(dict.fromkeys(
        str(item.get("joNo") or "")
        for item in items
        if isinstance(item, dict)
        and item.get("cls") == "arSeq"
        and item.get("joChgYn") == "Y"
        and item.get("joNo")
    ))
    if items and not sequences:
        raise _FastDownloadUnavailable("사이트의 현행 부칙을 구분하지 못했습니다.")

    selected = _selected_articles("law", articles)
    params = {
        "trSeq": sequence, "efDvPop": "", "nwJoYnInfo": "", "efGubun": "",
        "ancYnChk": "0",
    }
    if sequences:
        params["lastCheck"] = "Y"
    data = {
        "lsiSeq": sequence, "chrClsCd": character_class, "outPutTitleYn": "",
        "joAllCheck": "" if selected else "Y", "joNo": selected,
        "onlyEfYd": "", "efLsGubun": "", "efDvPop": "", "nwJoYnInfo": "",
        "arSeqs": ",," + ",".join(f"{s}#" for s in sequences) if sequences else ",",
        "mokChaChk": "N", "bylChaChk": "N",
        "arIds": ",".join(f"check_outPut_{s}" for s in sequences),
        "bylAllSeq": "", "efYd": site_date, "efGubun": "", "test1": "on",
        "joEfOutPutYn": "on", "coverDpYn": "1", **_SAVE_STYLE,
    }
    return params, data, expected


def _admin_rule_save_request(session, item_id, title, effective_date, articles=None):
    page = session.get(
        f"{LAW_SITE_ORIGIN}/admRulInfoP.do",
        params={"admRulSeq": item_id},
        timeout=15,
    )
    page.raise_for_status()
    html = page.content.decode("utf-8")
    # 행정규칙 화면은 서버가 내려주는 HTML에 이름을 전혀 담지 않는다
    # (자바스크립트가 나중에 채운다). 견줄 이름이 없으므로 건너뛰고,
    # 주소에 실은 행정규칙일련번호로 문서를 고른 것을 믿는다.
    _check_title(title, _site_page_title(html))
    spec = _KINDS["admrul"]
    appendix = _article_list(session, spec, item_id, str(spec["appendix_mode"]))
    selected = _selected_articles("admrul", articles)
    if not selected:
        articles_found = _article_list(
            session, spec, item_id, str(spec["article_mode"])
        )
        selected = _build_article_parameter(articles_found, dashed=True)
    data = {
        "admRulSeq": item_id,
        # 법령 화면은 ``lsBdyChrCls``를 숨은 칸에 담아 주지만, 행정규칙
        # 화면은 이 값을 자바스크립트가 본문을 불러온 뒤에 채운다. 서버가
        # 처음 내려주는 HTML에는 없으므로 빈 값으로 보낸다(실측에서 사이트가
        # 그대로 한글 문서를 만들어 준다). 예전에는 이 칸을 못 찾아 빠른
        # 다운로드가 늘 실패하고 브라우저 대체 경로로 넘어갔다.
        "chrClsCd": _optional_site_input_value(html, "lsBdyChrCls"),
        "outPutTitleYn": "",
        "joNo": selected,
        "arSeq": _last_appendix(appendix),
        "mokChaChk": "N", "bylChaChk": "N",
        "allJoChkYn": "N" if articles else "Y",
        "bylAllSeq": "", "test1": "on", **_SAVE_STYLE,
    }
    return {}, data, re.sub(r"\D", "", effective_date or "")


def _ordinance_save_request(session, item_id, title, effective_date, articles=None):
    page = session.get(
        f"{LAW_SITE_ORIGIN}/ordinInfoP.do",
        params={"ordinSeq": item_id},
        timeout=15,
    )
    page.raise_for_status()
    html = page.content.decode("utf-8")
    # 자치법규 화면은 법령의 ``lsNm``처럼 이름을 숨은 칸(``ordinNm``)에 담아
    # 준다. <title>은 구분만 적혀 있어 견줄 것이 없다. 칸이 없는 응답이 와도
    # 다운로드를 막지는 않는다 — 이름 확인은 일련번호 위에 덧댄 안전장치다.
    _check_title(
        title,
        _optional_site_input_value(html, "ordinNm") or _site_page_title(html),
    )
    spec = _KINDS["ordin"]
    appendix = _article_list(session, spec, item_id, str(spec["appendix_mode"]))
    selected = _selected_articles("ordin", articles)
    if not selected:
        articles_found = _article_list(
            session, spec, item_id, str(spec["article_mode"])
        )
        selected = _build_article_parameter(articles_found, dashed=False)
    gubun = _site_input_value(html, "gubun")
    last = _last_appendix(appendix)
    data = {
        "ordinSeq": item_id, "outPutGubun": gubun, "outPutTitleYn": "",
        "gubun": gubun, "joNo": selected,
        # 사이트는 이 값 뒤에 공백 하나를 붙여 보낸다(실측). 그대로 맞춘다.
        "arSeq": f"{last} " if last else "",
        "test1": "on", **_SAVE_STYLE,
    }
    return {}, data, re.sub(r"\D", "", effective_date or "")


_REQUEST_BUILDERS = {
    "law": _law_save_request,
    "admrul": _admin_rule_save_request,
    "ordin": _ordinance_save_request,
}


def _download_direct(
    kind: str,
    item_id: str,
    title: str,
    effective_date: str,
    directory: Path,
    destination_path: Path,
    is_directory: bool,
    progress: Callable[[str], None],
    articles: Sequence[str] | None = None,
) -> Path:
    """화면 렌더링 없이 사이트의 저장 POST 요청을 직접 실행한다."""
    spec = _kind_spec(kind)
    progress("한글 문서 빠른 다운로드 연결 중")
    headers = dict(_BROWSER_HEADERS)
    headers["Referer"] = (
        f"{LAW_SITE_ORIGIN}/{spec['page']}?{spec['page_param']}={item_id}"
    )
    try:
        with requests.Session() as session:
            session.headers.update(headers)
            params, data, expected_date = _REQUEST_BUILDERS[kind](
                session, item_id, title, effective_date, articles
            )
            response = session.post(
                f"{LAW_SITE_ORIGIN}/{spec['save']}",
                params=params,
                data=data,
                timeout=60,
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
                prefix=".law-hwp-", suffix=".part", dir=directory, delete=False
            ) as temporary:
                partial = Path(temporary.name)
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        temporary.write(chunk)
            try:
                _verify_hwpml(partial)
                partial.replace(target)
            except ValueError as exc:
                raise _FastDownloadUnavailable(str(exc)) from exc
            finally:
                partial.unlink(missing_ok=True)
    except requests.RequestException as exc:
        raise _FastDownloadUnavailable(str(exc)) from exc
    progress("한글 문서 저장 완료")
    return target


def _wait_for_site_download(page, context, layer, hwp_radio: str):
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
    radio = layer.locator(hwp_radio)
    radio.evaluate("element => element.click()")
    if not radio.is_checked():
        raise RuntimeError("사이트 저장 창에서 HWP 형식을 선택하지 못했습니다.")
    layer.locator("#aBtnOutPutSave").evaluate("element => element.click()")
    deadline = time.monotonic() + 60
    while not downloads:
        if alerts:
            raise RuntimeError(f"국가법령정보센터 안내: {alerts[-1]}")
        if time.monotonic() >= deadline:
            raise RuntimeError("사이트 저장 버튼을 눌렀지만 60초 동안 다운로드가 시작되지 않았습니다.")
        page.wait_for_timeout(200)
    return downloads[0]


def download_official_law_document(
    kind: str,
    item_id: str,
    title: str,
    effective_date: str,
    destination: str | Path,
    progress: Callable[[str], None] | None = None,
    articles: Sequence[str] | None = None,
) -> Path:
    """공식 사이트의 저장 버튼을 눌러 완성된 파일만 목적지에 둔다.

    ``articles``는 앱의 6자리 조 번호 목록이다. 주면 그 조문만 담긴
    문서를 받는다.
    """
    progress = progress or (lambda _message: None)
    spec = _kind_spec(kind)
    if not re.fullmatch(r"\d{1,16}", str(item_id)):
        raise ValueError(f"{spec['label']} ID가 올바르지 않습니다.")
    destination_path = Path(destination)
    is_directory = destination_path.is_dir() or not destination_path.suffix
    if not is_directory and destination_path.suffix.lower() != ".hwp":
        raise ValueError("저장 경로는 다운로드 폴더 또는 .hwp 파일이어야 합니다.")
    directory = destination_path if is_directory else destination_path.parent
    directory.mkdir(parents=True, exist_ok=True)
    selected = list(articles or [])
    try:
        return _download_direct(
            kind, item_id, title, effective_date, directory, destination_path,
            is_directory, progress, selected,
        )
    except _FastDownloadUnavailable as exc:
        if selected:
            # 브라우저 대체 경로는 저장 창의 조문 체크박스를 다루지 않는다.
            # 고른 조문만 받는 요청은 조용히 전문으로 바뀌면 안 되므로
            # 여기서 끝낸다.
            raise RuntimeError(
                f"고른 조문만 내려받지 못했습니다: {exc}"
            ) from exc
        # 사이트가 POST 형식을 바꾸거나 직접 연결을 일시 차단하면, 이미
        # 검증한 실제 저장 창 조작으로 자동 복구한다.
        progress("빠른 다운로드 연결 실패 · 브라우저로 다시 시도 중")
    sync_playwright = _load_playwright(progress)
    page_url = f"{LAW_SITE_ORIGIN}/{spec['page']}?{spec['page_param']}={item_id}"
    if kind == "law":
        page_url += "&ancYnChk=0"
    with tempfile.TemporaryDirectory(prefix="law-site-download-") as browser_temp:
        with sync_playwright() as playwright:
            browser = _launch_browser(playwright, progress, browser_temp)
            try:
                context = browser.new_context(accept_downloads=True)
                page = context.new_page()
                progress(f"국가법령정보센터 {spec['label']} 본문 여는 중")
                page.goto(page_url, wait_until="domcontentloaded", timeout=45000)
                page.locator("#bdySaveBtn").wait_for(state="visible", timeout=30000)
                _check_title(title, page.title())
                # 사이트의 로딩 마스크가 버튼 위에 남는 때에도 저장 함수를 실행한다.
                page.locator("#bdySaveBtn").evaluate("element => element.click()")
                layer = None
                for selector in spec["layers"]:
                    try:
                        candidate = page.locator(selector)
                        candidate.wait_for(state="visible", timeout=15000)
                        layer = candidate
                        break
                    except Exception:
                        continue
                if layer is None:
                    raise RuntimeError("국가법령정보센터 저장 창을 열지 못했습니다.")
                # 페이지 껍데기와 저장 버튼이 먼저 보이고, 저장 창을 열 때
                # 조문 목록 AJAX 조회가 시작되는 경우가 있다. 사이트의
                # beforeSavePrint()는 arSeq가 하나도 없으면 "법령 본문 목록
                # 조회 후 사용하세요"라는 안내만 띄운다.
                progress("본문 목록 불러오는 중")
                try:
                    page.locator("input[name='arSeq']").first.wait_for(
                        state="attached", timeout=60000
                    )
                except Exception as exc:
                    raise RuntimeError(
                        "국가법령정보센터에서 60초 안에 본문 목록을 불러오지 못했습니다."
                    ) from exc
                progress(f"{spec['label']} 전문 한글 문서 내려받는 중")
                download = _wait_for_site_download(
                    page, context, layer, str(spec["hwp_radio"])
                )
                expected_date = re.sub(r"\D", "", effective_date or "")
                if expected_date and f"({expected_date})" not in download.suggested_filename:
                    raise ValueError("사이트 다운로드의 시행일이 현재 화면과 다릅니다.")
                target = (
                    _unique_download_path(directory, download.suggested_filename)
                    if is_directory else destination_path
                )
                with tempfile.NamedTemporaryFile(
                    prefix=".law-hwp-", suffix=".part", dir=directory, delete=False
                ) as temporary:
                    partial = Path(temporary.name)
                try:
                    download.save_as(partial)
                    failure = download.failure()
                    if failure:
                        raise RuntimeError(f"다운로드 실패: {failure}")
                    _verify_hwpml(partial)
                    partial.replace(target)
                finally:
                    partial.unlink(missing_ok=True)
                progress("한글 문서 저장 완료")
                return target
            finally:
                browser.close()
