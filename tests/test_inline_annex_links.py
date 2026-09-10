"""본문 문장 속 별표ㆍ별지서식 인용에 링크가 걸리는지 검증."""

import os
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab


@pytest.fixture(autouse=True)
def no_background_comparison_request(monkeypatch):
    # 이 묶음은 본문 안의 별표 링크를 검사한다. 실제 3단비교 요청이
    # 끝나기 전에 QApplication이 종료되면 QThread 소멸로 실패한다.
    monkeypatch.setattr(ResourceSearchTab, "_queue_three_stage_link_request", lambda *a: None)


ROW = {
    "target": "law",
    "label": "법령",
    "id": "009419",
    "name": "국토의 계획 및 이용에 관한 법률 시행령",
    "related": "",
    "organization": "국토교통부",
    "date": "",
    "number": "",
    "effective": "",
    "short_name": "",
    "raw": {},
}

BODY = (
    "제71조(용도지역안에서의 건축제한) 법 제76조제1항에 따른 건축물의 종류는 "
    "별표 1과 같다. 다만, 별지 제3호서식으로 신청한 경우에는 별표 2의2를 따른다."
)


def _payload(with_annex: bool) -> dict:
    payload = {
        "법령": {
            "기본정보": {"법령명_한글": ROW["name"], "법령ID": ROW["id"]},
            "조문": {"조문단위": [{"조문번호": "71", "조문내용": BODY}]},
        }
    }
    if with_annex:
        payload["법령"]["별표"] = {
            "별표단위": [
                {
                    "별표구분": "별표",
                    "별표번호": "0001",
                    "별표가지번호": "00",
                    "별표제목": "용도지역안에서 건축할 수 있는 건축물",
                    "별표서식파일링크": "/LSW/flDownload.do?flSeq=1",
                }
            ]
        }
    return payload


def _tab(tmp_path) -> ResourceSearchTab:
    QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "annex.ini"), QSettings.Format.IniFormat)
    return ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )


def _anchor_links(tab) -> dict[str, str]:
    document = tab.detail_view.document()
    links: dict[str, str] = {}
    block = document.begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid() and fragment.charFormat().isAnchor():
                href = fragment.charFormat().anchorHref()
                if "annex" in href:
                    links.setdefault(href, "")
                    links[href] += fragment.text()
            iterator += 1
        block = block.next()
    return links


def test_body_annex_citation_opens_a_preview_popup(tmp_path) -> None:
    """문서 아래 별표 목록에 있는 인용은 그 별표만 미리보기 창으로 띄운다."""
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    tab.pending_row = dict(ROW)
    tab._show_detail(_payload(True))
    app.processEvents()

    links = _anchor_links(tab)
    assert "annexopen:0" in links
    assert "별표 1" in links["annexopen:0"]


def test_body_annex_link_survives_expanding_the_list(tmp_path) -> None:
    """아래 별표를 펼쳤다 접어도 본문 글의 링크는 그대로 남는다."""
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    tab.pending_row = dict(ROW)
    tab._show_detail(_payload(True))
    app.processEvents()

    tab._toggle_annex_preview("0")
    app.processEvents()

    assert "annexopen:0" in _anchor_links(tab)


def test_body_annex_citation_without_list_uses_search_link(tmp_path) -> None:
    """목록이 없는 인용은 별표를 찾아 여는 링크가 된다."""
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    tab.pending_row = dict(ROW)
    tab._show_detail(_payload(False))
    app.processEvents()

    links = _anchor_links(tab)
    assert any(href.startswith("annexref://open?") for href in links)
    assert any("category=licbyl" in href for href in links)


def test_inline_annex_label_reads_every_shape() -> None:
    pattern = ResourceSearchTab._INLINE_ANNEX_REFERENCE_PATTERN
    labels = [
        ResourceSearchTab._inline_annex_label(match)
        for match in pattern.finditer(
            "별표 1과 별표 제2호, 별표 3의2 그리고 별지 제4호서식과 별지 제5호의2서식"
        )
    ]

    assert labels == [
        "별표 1",
        "별표 2",
        "별표 3의2",
        "별지 제4호서식",
        "별지 제5호의2서식",
    ]


def test_body_annexref_link_is_handled_inside_the_program(tmp_path) -> None:
    """본문에서 누른 별표 링크를 바깥 프로그램으로 넘기지 않는다.

    넘기면 윈도우가 "이 annexref 링크를 열려면 새 앱이 필요합니다"를 띄운다.
    """
    from PySide6.QtCore import QUrl

    tab = _tab(tmp_path)
    opened: list[str] = []
    tab.open_annex_reference = lambda url: opened.append(url.toString())
    external: list[str] = []
    tab_module = __import__(
        "ui.tabs.resource_search", fromlist=["QDesktopServices"]
    )
    original = tab_module.QDesktopServices.openUrl
    tab_module.QDesktopServices.openUrl = staticmethod(
        lambda url: external.append(url.toString()) or True
    )
    try:
        tab._detail_link_clicked(
            QUrl("annexref://open?name=%EB%B3%84%ED%91%9C%201&category=ordinbyl")
        )
    finally:
        tab_module.QDesktopServices.openUrl = original

    assert opened and not external
