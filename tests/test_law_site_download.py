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
    def __init__(self, page):
        self.page = page

    def wait_for(self, **_kwargs):
        pass

    def evaluate(self, _expression):
        self.page.opened = True

    def locator(self, _selector):
        return self

    def click(self):
        assert self.page.opened


class _Download:
    suggested_filename = "행정기본법(법률)(제20824호)(20260319).hwpx"

    def __init__(self, payload: bytes):
        self.payload = payload

    def save_as(self, path):
        Path(path).write_bytes(self.payload)

    def failure(self):
        return None


class _Page:
    def __init__(self, payload: bytes):
        self.download = _Download(payload)
        self.opened = False
        self.url = ""

    def goto(self, url, **_kwargs):
        self.url = url

    def title(self):
        return "법령 > 본문 > 행정기본법 | 국가법령정보센터"

    def locator(self, _selector):
        return _Locator(self)

    @contextmanager
    def expect_download(self, **_kwargs):
        yield type("Event", (), {"value": self.download})()


class _Browser:
    def __init__(self, payload: bytes):
        self.page = _Page(payload)
        self.closed = False

    def new_context(self, **_kwargs):
        return self

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True


def _fake_browser(monkeypatch, payload: bytes) -> _Browser:
    browser = _Browser(payload)

    @contextmanager
    def playwright_context():
        yield object()

    monkeypatch.setattr(site, "_load_playwright", lambda _progress: playwright_context)
    monkeypatch.setattr(site, "_launch_browser", lambda *_args: browser)
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
    assert browser.closed
    assert not list(tmp_path.glob("*.part"))


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
