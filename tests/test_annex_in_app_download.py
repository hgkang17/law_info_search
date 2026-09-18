"""별표ㆍ서식 원본을 브라우저 없이 프로그램 안에서 받는 경로 회귀 시험."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings, QUrl

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab
from utils.law_download import (
    _header_file_name,
    _suffix_for,
    _unique_path,
    safe_file_name,
    save_law_file,
)


ANNEX_ENTRY = {
    "label": "별표 1",
    "title": "건축물의 종류",
    "file_url": "https://www.law.go.kr/LSW/flDownload.do?flSeq=1",
    "pdf_url": "https://www.law.go.kr/LSW/flDownload.do?flSeq=2",
}


def test_header_file_name_reads_the_site_encodings() -> None:
    # 퍼센트 인코딩(UTF-8)
    assert _header_file_name(
        'attachment; filename="%EB%B3%84%ED%91%9C.hwp"'
    ) == "별표.hwp"
    # RFC 5987 확장 형식
    assert _header_file_name(
        "attachment; filename*=UTF-8''%EB%B3%84%ED%91%9C1.hwp"
    ) == "별표1.hwp"
    # 헤더에 쉼표를 그대로 못 싣는 서버가 세디유로 바꿔 보낸 것을 되돌린다.
    assert _header_file_name(
        'attachment; filename="%EC%A2%85%EB%A5%98%C2%B8%20%EA%B1%B4%EC%B6%95.hwp"'
    ) == "종류, 건축.hwp"
    assert _header_file_name("") == ""


def test_suffix_comes_from_the_bytes_when_the_name_has_none() -> None:
    # 법제처는 Content-Type을 옥텟 스트림으로만 줄 때가 있어 첫 바이트로 가린다.
    assert _suffix_for(b"%PDF-1.7", "application/octet-stream", "별표") == ".pdf"
    assert (
        _suffix_for(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "", "별표") == ".hwp"
    )
    assert _suffix_for(b"PK\x03\x04", "", "별표") == ".hwpx"
    # 이름에 이미 확장자가 있으면 그대로 둔다.
    assert _suffix_for(b"\x00\x00", "", "별표.pdf") == ".pdf"


def test_saved_name_drops_path_characters_and_never_overwrites(tmp_path) -> None:
    assert safe_file_name("[별표 1] 용도/구분: 표") == "[별표 1] 용도 구분 표"
    assert safe_file_name("   ") == "별표서식"

    first = tmp_path / "별표.hwp"
    first.write_bytes(b"x")
    assert _unique_path(tmp_path, "별표", ".hwp").name == "별표 (2).hwp"


def test_save_law_file_refuses_addresses_off_the_official_site(tmp_path) -> None:
    with pytest.raises(ValueError):
        save_law_file("https://example.com/a.hwp", tmp_path)
    with pytest.raises(ValueError):
        save_law_file("http://www.law.go.kr/LSW/flDownload.do", tmp_path)


def _tab(tmp_path) -> ResourceSearchTab:
    settings = QSettings(
        str(tmp_path / "annex.ini"), QSettings.Format.IniFormat
    )
    return ResourceSearchTab(
        lambda: "",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )


def test_annex_icons_link_to_the_in_app_download(qtbot_app, tmp_path) -> None:
    """원본ㆍPDF 표시는 바깥 브라우저가 아니라 자체 주소로 걸린다."""
    tab = _tab(tmp_path)
    try:
        html_parts: list[str] = []
        plain_parts: list[str] = []
        tab._append_law_annex_section(html_parts, plain_parts, [dict(ANNEX_ENTRY)])
        html = "".join(html_parts)
        assert 'href="annexsave:0"' in html
        assert 'href="annexsavepdf:0"' in html
        # 링크 주소를 그대로 걸면 Qt가 기본 브라우저로 넘긴다.
        assert 'href="https://www.law.go.kr' not in html
    finally:
        tab.close()


def test_clicking_an_annex_icon_downloads_in_app(
    qtbot_app, tmp_path, monkeypatch
) -> None:
    """표시를 누르면 브라우저 없이 받아 다운로드 목록에 쌓인다."""
    tab = _tab(tmp_path)
    try:
        opened: list[str] = []
        monkeypatch.setattr(
            "ui.tabs.resource_search.QDesktopServices.openUrl",
            lambda url: opened.append(url.toString()) or True,
        )

        started: list[tuple[str, str, str]] = []
        saved = tmp_path / "받은" / "[별표 1] 건축물의 종류.hwp"
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_bytes(b"hwp")

        class StubSignal:
            def __init__(self) -> None:
                self.callbacks: list = []

            def connect(self, callback) -> None:
                self.callbacks.append(callback)

            def emit(self, value=None) -> None:
                for callback in list(self.callbacks):
                    callback() if value is None else callback(value)

        class StubWorker:
            def __init__(self, url, destination, suggested_name="", parent=None):
                self.url = url
                self.destination = destination
                self.suggested_name = suggested_name
                self.progress = StubSignal()
                self.succeeded = StubSignal()
                self.failed = StubSignal()
                self.finished = StubSignal()

            def start(self) -> None:
                started.append((self.url, self.destination, self.suggested_name))
                self.succeeded.emit(str(saved))
                self.finished.emit()

            def deleteLater(self) -> None:
                pass

        monkeypatch.setattr(
            "ui.tabs.resource_search.AnnexFileDownloadWorker", StubWorker
        )

        tab._append_law_annex_section([], [], [dict(ANNEX_ENTRY)])
        tab._detail_link_clicked(QUrl("annexsave:0"))

        assert len(started) == 1
        url, _destination, suggested = started[0]
        assert url == ANNEX_ENTRY["file_url"]
        assert suggested == "[별표 1] 건축물의 종류"
        # 브라우저는 뜨지 않는다.
        assert opened == []
        # 받은 파일은 전문 다운로드와 같은 목록에 쌓인다.
        assert [path.name for path in tab._completed_downloads] == [saved.name]

        # PDF 표시는 PDF 주소로 받는다.
        tab._detail_link_clicked(QUrl("annexsavepdf:0"))
        assert started[1][0] == ANNEX_ENTRY["pdf_url"]
        # 같은 파일을 다시 받아도 목록에 두 줄이 되지 않는다.
        assert [path.name for path in tab._completed_downloads] == [saved.name]
    finally:
        tab.close()


@pytest.fixture(scope="module")
def qtbot_app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])
