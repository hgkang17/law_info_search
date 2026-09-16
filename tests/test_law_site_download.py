"""사이트가 blob 다운로드를 보내더라도 HWPX만 완성 경로에 둔다."""

from __future__ import annotations

import builtins
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from utils import law_site_download as site


def _hwpx_bytes() -> bytes:
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w") as package:
        for name in sorted(site._REQUIRED_HWPX_MEMBERS):
            package.writestr(
                name,
                b"application/hwp+zip" if name == "mimetype" else b"<document/>"
            )
    return stream.getvalue()


class _Locator:
    def __init__(self, page, selector=""):
        self.page = page
        self.selector = selector

    def wait_for(self, **_kwargs):
        if self.selector == "input[name='arSeq']":
            assert self.page.opened
            self.page.body_list_ready = True

    @property
    def first(self):
        return self

    def evaluate(self, _expression):
        if self.selector == "#bdySaveBtn":
            self.page.opened = True
        elif self.selector == "#FileSaveHwpx1":
            self.page.selected_hwpx = True
        elif self.selector == "#aBtnOutPutSave":
            assert self.page.opened and self.page.selected_hwpx and self.page.body_list_ready
            self.page.emit_download()

    def locator(self, selector):
        return _Locator(self.page, selector)

    def is_checked(self):
        return self.page.selected_hwpx


class _Download:
    suggested_filename = "행정기본법(법률)(제20824호)(20260319).hwpx"

    def __init__(self, payload: bytes):
        self.payload = payload

    def save_as(self, path):
        Path(path).write_bytes(self.payload)

    def failure(self):
        return None


class _Page:
    def __init__(self, payload: bytes, context=None, popup=False):
        self.download = _Download(payload)
        self.opened = False
        self.selected_hwpx = False
        self.body_list_ready = False
        self.url = ""
        self.listeners = {}
        self.context = context
        self.popup = popup

    def goto(self, url, **_kwargs):
        self.url = url

    def title(self):
        return "법령 > 본문 > 행정기본법 | 국가법령정보센터"

    def locator(self, selector):
        return _Locator(self, selector)

    def on(self, event, callback):
        self.listeners[event] = callback

    def emit_download(self):
        if self.popup:
            new_page = _Page(self.download.payload)
            self.context.listeners["page"](new_page)
            new_page.emit_download()
        else:
            self.listeners["download"](self.download)

    def wait_for_timeout(self, _milliseconds):
        pass


class _Browser:
    def __init__(self, payload: bytes, popup=False):
        self.page = _Page(payload, self, popup)
        self.closed = False
        self.listeners = {}

    def new_context(self, **_kwargs):
        return self

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True

    def on(self, event, callback):
        self.listeners[event] = callback


def _fake_browser(monkeypatch, payload: bytes, popup=False) -> _Browser:
    browser = _Browser(payload, popup)

    @contextmanager
    def playwright_context():
        yield object()

    monkeypatch.setattr(site, "_load_playwright", lambda _progress: playwright_context)
    monkeypatch.setattr(site, "_launch_browser", lambda *_args: browser)
    monkeypatch.setattr(
        site, "_download_hwpx_direct",
        lambda *_args: (_ for _ in ()).throw(site._FastDownloadUnavailable("fallback")),
    )
    return browser


def test_blob_download_is_verified_then_saved_with_selected_name(tmp_path, monkeypatch):
    browser = _fake_browser(monkeypatch, _hwpx_bytes())
    target = tmp_path / "선택한 이름.hwpx"
    saved = site.download_official_law_hwpx(
        "014041", "행정기본법", "20260319", target
    )

    assert saved == target
    assert target.read_bytes() == _hwpx_bytes()
    assert "lsId=014041" in browser.page.url
    assert browser.page.body_list_ready
    assert browser.closed
    assert not list(tmp_path.glob("*.part"))


def test_download_directory_keeps_site_filename_and_existing_file(tmp_path, monkeypatch):
    _fake_browser(monkeypatch, _hwpx_bytes())
    original = tmp_path / _Download.suggested_filename
    original.write_bytes(b"already downloaded")

    saved = site.download_official_law_hwpx(
        "014041", "행정기본법", "20260319", tmp_path
    )

    assert saved.name.endswith(" (1).hwpx")
    assert saved.read_bytes() == _hwpx_bytes()
    assert original.read_bytes() == b"already downloaded"


def test_download_started_in_new_window_is_saved(tmp_path, monkeypatch):
    _fake_browser(monkeypatch, _hwpx_bytes(), popup=True)

    saved = site.download_official_law_hwpx(
        "014041", "행정기본법", "20260319", tmp_path
    )

    assert saved.read_bytes() == _hwpx_bytes()


def test_fast_post_download_skips_browser_and_includes_current_appendix(tmp_path, monkeypatch):
    page_html = b"""
        <input id="lsiSeq" value="269955">
        <input id="lsNm" value="\xed\x96\x89\xec\xa0\x95\xea\xb8\xb0\xeb\xb3\xb8\xeb\xb2\x95">
        <input id="lsBdyChrCls" value="010202">
        <script>lsPopViewAll2('269955', '', '', '20260319', '', '', '010202', '0');</script>
    """
    posted = []

    class Response:
        def __init__(self, content=b"", *, items=None, headers=None):
            self.content = content
            self._items = items
            self.headers = headers or {}

        def raise_for_status(self):
            pass

        def json(self):
            return self._items

        def iter_content(self, chunk_size):
            yield self.content

    class Session:
        def __init__(self):
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def get(self, *_args, **_kwargs):
            return Response(page_html)

        def post(self, url, **kwargs):
            posted.append((url, kwargs))
            if url.endswith("joListRInc.do"):
                return Response(items=[
                    {"cls": "arSeq", "joNo": 11517575, "joChgYn": "N"},
                    {"cls": "arSeq", "joNo": 11517581, "joChgYn": "Y"},
                ])
            return Response(
                _hwpx_bytes(),
                headers={
                    "Content-Disposition":
                    'attachment; filename="행정기본법(법률)(제20824호)(20260319).hwpx"'
                },
            )

    monkeypatch.setattr(site.requests, "Session", Session)
    monkeypatch.setattr(
        site, "_load_playwright", lambda *_args: pytest.fail("빠른 경로가 브라우저를 열었습니다.")
    )

    saved = site.download_official_law_hwpx(
        "014041", "행정기본법", "20260319", tmp_path
    )

    assert saved.read_bytes() == _hwpx_bytes()
    save_data = posted[-1][1]["data"]
    assert save_data["joAllCheck"] == "Y"
    assert save_data["arSeqs"] == ",,11517581#"
    assert save_data["arIds"] == "check_outPut_11517581"


def test_mislabeled_or_corrupt_file_preserves_existing_document(tmp_path, monkeypatch):
    _fake_browser(monkeypatch, b"<?xml version='1.0'?><HWPML></HWPML>")
    target = tmp_path / "existing.hwpx"
    target.write_bytes(b"original")

    with pytest.raises(ValueError, match="HWPX"):
        site.download_official_law_hwpx("014041", "행정기본법", "20260319", target)

    assert target.read_bytes() == b"original"
    assert not list(tmp_path.glob("*.part"))


def test_different_effective_date_does_not_replace_existing_document(tmp_path, monkeypatch):
    _fake_browser(monkeypatch, _hwpx_bytes())
    target = tmp_path / "existing.hwpx"
    target.write_bytes(b"original")

    with pytest.raises(ValueError, match="시행일"):
        site.download_official_law_hwpx("014041", "행정기본법", "20250101", target)

    assert target.read_bytes() == b"original"


def test_missing_playwright_is_installed_with_pinned_version(monkeypatch):
    original_import = builtins.__import__
    attempted = []
    marker = object()

    def fake_import(name, *args, **kwargs):
        if name == "playwright.sync_api":
            attempted.append(name)
            if len(attempted) == 1:
                raise ImportError("not installed")
            return SimpleNamespace(sync_playwright=marker)
        return original_import(name, *args, **kwargs)

    commands = []
    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(site, "_run_hidden", lambda command: commands.append(command))
    monkeypatch.delattr(site.sys, "frozen", raising=False)

    assert site._load_playwright(lambda _message: None) is marker
    assert commands == [
        [site.sys.executable, "-m", "pip", "install", f"playwright=={site.PLAYWRIGHT_VERSION}"]
    ]
