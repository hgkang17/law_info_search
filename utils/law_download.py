"""법제처 첨부 파일을 HTTPS로만 받는다. Qt를 쓰지 않는다.

별표 원문 파싱(MCP/Gemini)과 화면 PDF 미리보기가 같은 허용 목록을
쓰게 하려고 다운로드 경로를 여기로 모았다. workers.download_worker는
이 모듈을 감싼 QThread일 뿐이다.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

import requests

from storage.paths import ANNEX_FILE_CACHE_DIR, ANNEX_FILE_CACHE_MAX_BYTES

_ALLOWED_DOMAIN = "law.go.kr"
_MAX_REDIRECTS = 5
_MAX_FILE_BYTES = 50 * 1024 * 1024
REQUEST_HEADERS = {
    "Referer": "https://www.law.go.kr/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Python requests",
}


def is_allowed_law_file_url(url: str) -> bool:
    """Allow HTTPS resources hosted by law.go.kr or its subdomains only."""
    try:
        parsed = urlsplit(str(url).strip())
        hostname = (parsed.hostname or "").rstrip(".").lower()
        port = parsed.port
    except (TypeError, ValueError):
        return False
    return bool(
        parsed.scheme.lower() == "https"
        and hostname
        and (hostname == _ALLOWED_DOMAIN or hostname.endswith("." + _ALLOWED_DOMAIN))
        and parsed.username is None
        and parsed.password is None
        and port in (None, 443)
    )


is_allowed_law_pdf_url = is_allowed_law_file_url


def _cache_path(url: str) -> Path:
    key = hashlib.sha256(str(url).strip().encode("utf-8")).hexdigest()
    return ANNEX_FILE_CACHE_DIR / f"{key}.bin"


def _read_cached(url: str) -> bytes | None:
    """받아 둔 파일이 있으면 읽는다. 없거나 읽히지 않으면 None."""
    path = _cache_path(url)
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if not data:
        return None
    try:
        # 마지막으로 쓴 때를 지금으로 올려 두면, 자리가 모자랄 때
        # 오래 안 본 것부터 지울 수 있다.
        os.utime(path, None)
    except OSError:
        pass
    return data


def _write_cached(url: str, data: bytes) -> None:
    """받은 파일을 캐시에 둔다. 실패해도 조용히 넘어간다 — 캐시일 뿐이다."""
    if not data:
        return
    path = _cache_path(url)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # 쓰다 만 파일을 다음에 읽어 깨진 PDF를 보여 주지 않도록,
        # 임시 이름으로 다 쓴 뒤 한 번에 갈아 끼운다.
        handle, temporary = tempfile.mkstemp(dir=str(path.parent))
        try:
            with os.fdopen(handle, "wb") as file:
                file.write(data)
            os.replace(temporary, path)
        except OSError:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            return
    except OSError:
        return
    _prune_cache()


def _prune_cache() -> None:
    """총량 상한을 넘으면 오래 안 쓴 것부터 지운다."""
    try:
        entries = [
            (item.stat().st_mtime, item.stat().st_size, item)
            for item in ANNEX_FILE_CACHE_DIR.iterdir()
            if item.is_file()
        ]
    except OSError:
        return
    total = sum(size for _mtime, size, _item in entries)
    if total <= ANNEX_FILE_CACHE_MAX_BYTES:
        return
    for _mtime, size, item in sorted(entries):
        try:
            item.unlink()
        except OSError:
            continue
        total -= size
        if total <= ANNEX_FILE_CACHE_MAX_BYTES:
            return


def clear_annex_file_cache() -> int:
    """받아 둔 별표 파일을 모두 지운다. 지운 개수를 돌려준다."""
    removed = 0
    try:
        items = list(ANNEX_FILE_CACHE_DIR.iterdir())
    except OSError:
        return 0
    for item in items:
        if not item.is_file():
            continue
        try:
            item.unlink()
        except OSError:
            continue
        removed += 1
    return removed


def download_law_file(url: str, *, use_cache: bool = True) -> bytes:
    """Download a law.go.kr file without following a redirect off-site.

    같은 별표를 다시 열 때마다 법제처를 부르면 느리고 헛되다. 받은
    파일은 캐시에 두고, 다음부터는 거기서 읽는다.
    """
    if use_cache:
        cached = _read_cached(url)
        if cached is not None:
            return cached
    current_url = str(url).strip()
    for _redirect in range(_MAX_REDIRECTS + 1):
        if not is_allowed_law_file_url(current_url):
            raise ValueError("공식 law.go.kr HTTPS 주소의 파일만 열 수 있습니다.")
        response = requests.get(
            current_url,
            timeout=(5, 20),
            allow_redirects=False,
            stream=True,
            headers=REQUEST_HEADERS,
        )
        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location", "")
            response.close()
            if not location:
                raise ValueError("파일 리디렉션 주소가 없습니다.")
            current_url = urljoin(current_url, location)
            continue
        response.raise_for_status()
        declared_size = int(response.headers.get("Content-Length", "0") or 0)
        if declared_size > _MAX_FILE_BYTES:
            response.close()
            raise ValueError("파일 크기가 50MB 제한을 초과합니다.")
        chunks: list[bytes] = []
        received = 0
        try:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                received += len(chunk)
                if received > _MAX_FILE_BYTES:
                    raise ValueError("파일 크기가 50MB 제한을 초과합니다.")
                chunks.append(chunk)
        finally:
            response.close()
        data = b"".join(chunks)
        if use_cache:
            _write_cached(url, data)
        return data
    raise ValueError("파일 리디렉션이 너무 많습니다.")


download_law_pdf = download_law_file


_ORDINANCE_ANNEX_PREVIEW_ENDPOINT = (
    "https://www.law.go.kr/LSW/ordinBylContentsInfoR.do"
)
_VIEWER_IFRAME_PATTERN = re.compile(
    r'<iframe\b[^>]*\bsrc\s*=\s*["\'](?P<src>[^"\']+)',
    re.IGNORECASE,
)


def download_ordinance_annex_pages(
    preview_url: str, *, max_pages: int = 30
) -> tuple[list[bytes], int]:
    """법제처 자치법규 별표 뷰어의 변환 이미지를 내려받는다.

    자치법규 별표는 본문 API에서 PDF를 주지 않고 HWP 원본만 준다.
    법제처 화면도 같은 원본을 Synap 뷰어용 PNG로 변환하므로, 그 공식
    변환 응답을 받아 기존 앱 안 미리보기에서 사용한다.
    """
    parsed = urlsplit(str(preview_url or "").strip())
    if (
        not is_allowed_law_file_url(preview_url)
        or parsed.path != "/LSW/ordinBylContentsInfoR.do"
    ):
        raise ValueError("공식 자치법규 별표 미리보기 주소만 열 수 있습니다.")
    params = {
        key: values[-1]
        for key, values in parse_qs(parsed.query, keep_blank_values=True).items()
        if values
    }
    required = ("bylSeq", "ordinId", "ordinSeq", "bylFlSeq")
    if any(not str(params.get(key) or "").isdigit() for key in required):
        raise ValueError("자치법규 별표 미리보기 식별자가 올바르지 않습니다.")

    response = requests.post(
        _ORDINANCE_ANNEX_PREVIEW_ENDPOINT,
        data=params,
        timeout=(5, 30),
        headers=REQUEST_HEADERS,
    )
    response.raise_for_status()
    if len(response.content) > 2 * 1024 * 1024:
        raise ValueError("자치법규 별표 뷰어 응답이 허용 크기를 초과했습니다.")
    match = _VIEWER_IFRAME_PATTERN.search(response.text)
    if match is None:
        raise ValueError("자치법규 별표 변환 화면을 찾지 못했습니다.")
    viewer_url = urljoin(
        _ORDINANCE_ANNEX_PREVIEW_ENDPOINT,
        html.unescape(match.group("src")),
    )
    viewer_parts = urlsplit(viewer_url)
    if not is_allowed_law_file_url(viewer_url):
        raise ValueError("자치법규 별표 뷰어 주소가 공식 사이트가 아닙니다.")
    viewer_query = parse_qs(viewer_parts.query)
    context_path = str((viewer_query.get("contextPath") or [""])[-1])
    key = str((viewer_query.get("key") or [params["bylFlSeq"]])[-1])
    if (
        not key.isdigit()
        or not context_path.startswith("/viewer/")
        or ".." in context_path.split("/")
    ):
        raise ValueError("자치법규 별표 변환 경로가 올바르지 않습니다.")
    viewer_base = urljoin("https://www.law.go.kr", context_path.rstrip("/"))
    status_url = f"{viewer_base}/status/{key}.js"
    try:
        status = json.loads(download_law_file(status_url).decode("utf-8"))
        total = int(status.get("pageNum") or 0)
    except (UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("자치법규 별표 쪽수 정보를 읽지 못했습니다.") from exc
    if total <= 0:
        raise ValueError("자치법규 별표에 표시할 쪽이 없습니다.")

    limit = max(1, min(int(max_pages), total))
    pages: list[bytes] = []
    for index in range(limit):
        page_url = (
            f"{viewer_base}/thumbnail/{index}.png?dpi=M&withXml=false"
        )
        data = download_law_file(page_url)
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError(f"자치법규 별표 {index + 1}쪽 이미지가 올바르지 않습니다.")
        pages.append(data)
    return pages, total
