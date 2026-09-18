"""사이트가 무엇을 보내든 완성된 HWP(HWPML)만 저장 경로에 둔다."""

from __future__ import annotations

import builtins
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from utils import law_site_download as site


def _hwpml_bytes() -> bytes:
    return (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<HWPML Version="2.8"><BODY><SECTION/></BODY></HWPML>'
    )


def _hwpx_bytes() -> bytes:
    """장·절 개정 표기가 빠지는 HWPX. 저장 경로에 두면 안 된다."""
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w") as package:
        package.writestr("mimetype", b"application/hwp+zip")
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
        elif self.selector == "#FileSaveHwp1":
            self.page.selected_hwp = True
        elif self.selector == "#aBtnOutPutSave":
            assert self.page.opened and self.page.selected_hwp and self.page.body_list_ready
            self.page.emit_download()

    def locator(self, selector):
        return _Locator(self.page, selector)

    def is_checked(self):
        return self.page.selected_hwp


class _Download:
    suggested_filename = "행정기본법(법률)(제20824호)(20260319).hwp"

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
        self.selected_hwp = False
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
        site, "_download_direct",
        lambda *_args: (_ for _ in ()).throw(site._FastDownloadUnavailable("fallback")),
    )
    return browser


# ---------------------------------------------------------------- 브라우저 대체


def test_browser_download_is_verified_then_saved_with_selected_name(tmp_path, monkeypatch):
    browser = _fake_browser(monkeypatch, _hwpml_bytes())
    target = tmp_path / "선택한 이름.hwp"

    saved = site.download_official_law_document(
        "law", "014041", "행정기본법", "20260319", target
    )

    assert saved == target
    assert target.read_bytes() == _hwpml_bytes()
    assert "lsId=014041" in browser.page.url
    assert browser.page.body_list_ready
    assert browser.page.selected_hwp
    assert browser.closed
    assert not list(tmp_path.glob("*.part"))


def test_download_directory_keeps_site_filename_and_existing_file(tmp_path, monkeypatch):
    _fake_browser(monkeypatch, _hwpml_bytes())
    original = tmp_path / _Download.suggested_filename
    original.write_bytes(b"already downloaded")

    saved = site.download_official_law_document(
        "law", "014041", "행정기본법", "20260319", tmp_path
    )

    assert saved.name.endswith(" (1).hwp")
    assert saved.read_bytes() == _hwpml_bytes()
    assert original.read_bytes() == b"already downloaded"


def test_download_started_in_new_window_is_saved(tmp_path, monkeypatch):
    _fake_browser(monkeypatch, _hwpml_bytes(), popup=True)

    saved = site.download_official_law_document(
        "law", "014041", "행정기본법", "20260319", tmp_path
    )

    assert saved.read_bytes() == _hwpml_bytes()


def test_hwpx_package_is_rejected_and_existing_document_kept(tmp_path, monkeypatch):
    """HWPX는 편·장·절 제목의 개정 표기가 빠진 다른 문서다."""
    _fake_browser(monkeypatch, _hwpx_bytes())
    target = tmp_path / "existing.hwp"
    target.write_bytes(b"original")

    with pytest.raises(ValueError, match="HWPX"):
        site.download_official_law_document(
            "law", "014041", "행정기본법", "20260319", target
        )

    assert target.read_bytes() == b"original"
    assert not list(tmp_path.glob("*.part"))


def test_different_effective_date_does_not_replace_existing_document(tmp_path, monkeypatch):
    _fake_browser(monkeypatch, _hwpml_bytes())
    target = tmp_path / "existing.hwp"
    target.write_bytes(b"original")

    with pytest.raises(ValueError, match="시행일"):
        site.download_official_law_document(
            "law", "014041", "행정기본법", "20250101", target
        )

    assert target.read_bytes() == b"original"


# ------------------------------------------------------------------- 빠른 경로


class _Response:
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


def _save_headers(filename: str) -> dict[str, str]:
    return {"Content-Disposition": f'attachment; filename="{filename}"'}


def _install_session(monkeypatch, session_factory):
    monkeypatch.setattr(site.requests, "Session", session_factory)
    monkeypatch.setattr(
        site, "_load_playwright",
        lambda *_args: pytest.fail("빠른 경로가 브라우저를 열었습니다."),
    )


def test_law_fast_download_uses_hwp_endpoint_with_current_appendix(tmp_path, monkeypatch):
    page_html = (
        '<input id="lsiSeq" value="269955">'
        '<input id="lsNm" value="행정기본법">'
        '<input id="lsBdyChrCls" value="010202">'
        "<script>lsPopViewAll2('269955', '', '', '20260319', '', '', '010202', '0');</script>"
    ).encode("utf-8")
    posted = []

    class Session:
        def __init__(self):
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def get(self, *_args, **_kwargs):
            return _Response(page_html)

        def post(self, url, **kwargs):
            posted.append((url, kwargs))
            if url.endswith("joListRInc.do"):
                return _Response(items=[
                    {"cls": "arSeq", "joNo": 11517575, "joChgYn": "N"},
                    {"cls": "arSeq", "joNo": 11517581, "joChgYn": "Y"},
                ])
            return _Response(
                _hwpml_bytes(),
                headers=_save_headers("행정기본법(법률)(제20824호)(20260319).hwp"),
            )

    _install_session(monkeypatch, Session)

    saved = site.download_official_law_document(
        "law", "014041", "행정기본법", "20260319", tmp_path
    )

    assert saved.read_bytes() == _hwpml_bytes()
    save_url, save_kwargs = posted[-1]
    assert save_url.endswith("lsNewHwpSave.do")
    data = save_kwargs["data"]
    assert data["fileType"] == "hwp"
    assert data["joAllCheck"] == "Y"
    assert data["arSeqs"] == ",,11517581#"
    assert data["arIds"] == "check_outPut_11517581"


def test_admin_rule_fast_download_rebuilds_article_list(tmp_path, monkeypatch):
    page_html = (
        "<title>행정규칙 &gt; 시험 규정 | 국가법령정보센터</title>"
        '<input id="lsBdyChrCls" value="010202">'
    ).encode("utf-8")
    posted = []

    class Session:
        def __init__(self):
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def get(self, *_args, **_kwargs):
            return _Response(page_html)

        def post(self, url, **kwargs):
            posted.append((url, kwargs))
            if url.endswith("admRulJoListRInc.do"):
                if kwargs["params"]["mode"] == "99":
                    return _Response(items=[
                        {"cls": "joNo", "joYn": "N", "chapNo": "00000100000000000000"},
                        {"cls": "joNo", "joYn": "Y", "oriJoNo": "0001",
                         "dashNo": "0000", "joBrNo": "00"},
                        {"cls": "joNo", "joYn": "Y", "oriJoNo": "0002",
                         "dashNo": "0000", "joBrNo": "00"},
                    ])
                return _Response(items=[
                    {"cls": "arSeq", "joNo": "2780313"},
                    {"cls": "arSeq", "joNo": "2780315"},
                ])
            return _Response(
                _hwpml_bytes(),
                headers=_save_headers("시험 규정(국토교통부훈령)(제1962호)(20260701).hwp"),
            )

    _install_session(monkeypatch, Session)

    saved = site.download_official_law_document(
        "admrul", "2100000281150", "시험 규정", "20260701", tmp_path
    )

    assert saved.read_bytes() == _hwpml_bytes()
    save_url, save_kwargs = posted[-1]
    assert save_url.endswith("admRulHwpSave.do")
    data = save_kwargs["data"]
    assert data["joNo"] == "00000100000000000000,0001-0000:00,0002-0000:00"
    assert data["arSeq"] == "2780315"
    assert data["allJoChkYn"] == "Y"
    assert data["fileType"] == "hwp"


def test_ordinance_fast_download_rebuilds_article_list(tmp_path, monkeypatch):
    page_html = (
        "<title>자치법규 &gt; 본문 | 국가법령정보센터</title>"
        # 실제 화면은 문서명을 이 숨은 칸에 담아 준다(<title>에는 없다).
        '<input id="ordinNm" value="시험 조례">'
        '<input id="gubun" value="KLAW">'
    ).encode("utf-8")
    posted = []

    class Session:
        def __init__(self):
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def get(self, *_args, **_kwargs):
            return _Response(page_html)

        def post(self, url, **kwargs):
            posted.append((url, kwargs))
            if url.endswith("ordinJoListRInc_XML.do"):
                if kwargs["params"]["mode"] == "99":
                    return _Response(items=[
                        {"cls": "joNo", "joYn": "N", "chapNo": "00000100000000000000"},
                        {"cls": "joNo", "joYn": "Y", "oriJoNo": "0001", "joBrNo": "00"},
                    ])
                return _Response(items=[{"cls": "arSeq", "joNo": "9997369"}])
            return _Response(
                _hwpml_bytes(),
                headers=_save_headers("시험 조례(서울특별시조례)(제10139호)(20260713).hwp"),
            )

    _install_session(monkeypatch, Session)

    saved = site.download_official_law_document(
        "ordin", "2149501", "시험 조례", "20260713", tmp_path
    )

    assert saved.read_bytes() == _hwpml_bytes()
    save_url, save_kwargs = posted[-1]
    assert save_url.endswith("ordinHwpSave.do")
    data = save_kwargs["data"]
    assert data["joNo"] == "00000100000000000000,0001:00"
    # 사이트는 이 값 뒤에 공백 하나를 붙여 보낸다.
    assert data["arSeq"] == "9997369 "
    assert data["gubun"] == "KLAW"


# -------------------------------------------------------------- 조각 함수 단위


def test_article_parameter_uses_chapter_code_for_headings():
    items = [
        {"cls": "joNo", "joYn": "N", "chapNo": "00000100000000000000"},
        {"cls": "joNo", "joYn": "Y", "oriJoNo": "0001", "joBrNo": "00"},
        {"cls": "arSeq", "joNo": "999"},
    ]

    assert site._build_article_parameter(items, dashed=False) == (
        "00000100000000000000,0001:00"
    )


def test_empty_article_list_falls_back_to_browser():
    with pytest.raises(site._FastDownloadUnavailable):
        site._build_article_parameter([{"cls": "arSeq", "joNo": "1"}], dashed=False)


def test_unknown_kind_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        site.download_official_law_document("prec", "1", "판례", "", tmp_path)


def test_article_code_matches_each_kind_of_save_request():
    """행정규칙만 가지번호 앞에 ``-0000`` 자리가 하나 더 붙는다(실측)."""
    assert site.article_code("law", "000100") == "0001:00"
    assert site.article_code("ordin", "001202") == "0012:02"
    assert site.article_code("admrul", "000100") == "0001-0000:00"

    with pytest.raises(ValueError):
        site.article_code("law", "1")


def test_selected_articles_turn_off_whole_document_for_a_law(tmp_path, monkeypatch):
    page_html = (
        '<input id="lsiSeq" value="269955">'
        '<input id="lsNm" value="행정기본법">'
        '<input id="lsBdyChrCls" value="010202">'
        "<script>lsPopViewAll2('269955', '', '', '20260319', '', '', '010202', '0');</script>"
    ).encode("utf-8")
    posted = []

    class Session:
        def __init__(self):
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def get(self, *_args, **_kwargs):
            return _Response(page_html)

        def post(self, url, **kwargs):
            posted.append((url, kwargs))
            if url.endswith("joListRInc.do"):
                return _Response(items=[
                    {"cls": "arSeq", "joNo": 11517581, "joChgYn": "Y"},
                ])
            return _Response(
                _hwpml_bytes(),
                headers=_save_headers("행정기본법(법률)(제20824호)(20260319).hwp"),
            )

    _install_session(monkeypatch, Session)

    site.download_official_law_document(
        "law", "014041", "행정기본법", "20260319", tmp_path,
        articles=["000100", "000200"],
    )

    data = posted[-1][1]["data"]
    assert data["joAllCheck"] == ""
    assert data["joNo"] == "0001:00,0002:00"


def test_selected_articles_never_fall_back_to_the_whole_document(tmp_path, monkeypatch):
    """브라우저 대체 경로는 조문 체크박스를 다루지 않는다."""
    monkeypatch.setattr(
        site, "_download_direct",
        lambda *_args: (_ for _ in ()).throw(site._FastDownloadUnavailable("끊김")),
    )
    monkeypatch.setattr(
        site, "_load_playwright",
        lambda *_args: pytest.fail("고른 조문 요청이 전문 경로로 넘어갔습니다."),
    )

    with pytest.raises(RuntimeError, match="고른 조문"):
        site.download_official_law_document(
            "law", "014041", "행정기본법", "20260319", tmp_path,
            articles=["000100"],
        )


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
