"""법령 전문 아래쪽의 별표·서식 링크 회귀 테스트."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _payload() -> dict:
    return {
        "법령": {
            "기본정보": {
                "법령명_한글": "표시 시험법 시행령",
                "법령ID": "000001",
            },
            "조문": {
                "조문단위": [
                    {"조문내용": "제1조(목적) 이 영의 목적을 정한다."}
                ]
            },
            "별표": {
                "별표단위": [
                    {
                        "별표구분": "별표",
                        "별표번호": "0001",
                        "별표가지번호": "00",
                        "별표제목문자열": "시험 기준(제1조 관련)",
                        "별표서식파일링크": "/LSW/flDownload.do?flSeq=11",
                        "별표서식PDF파일링크": "/LSW/flDownload.do?flSeq=12",
                    },
                    {
                        "별표구분": "별지서식",
                        "별표번호": "0002",
                        "별표가지번호": "03",
                        "별표제목": "시험 신청서",
                        "별표서식파일링크": "/LSW/flDownload.do?flSeq=21",
                    },
                ]
            },
        }
    }


def test_law_annex_entries_use_links_from_body_payload() -> None:
    entries = ResourceSearchTab._law_annex_entries(_payload())

    assert [entry["label"] for entry in entries] == [
        "별표 1",
        "별지 제2호의3서식",
    ]
    assert entries[0]["file_url"].endswith("flDownload.do?flSeq=11")
    assert entries[0]["pdf_url"].endswith("flDownload.do?flSeq=12")


def test_annex_links_are_rendered_after_articles(qt_app, tmp_path) -> None:
    settings = QSettings(
        str(tmp_path / "annex-links.ini"), QSettings.Format.IniFormat
    )
    tab = ResourceSearchTab(
        lambda: "",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    row = {
        "target": "law",
        "id": "000001",
        "label": "법령",
        "name": "표시 시험법 시행령",
    }
    tab.pending_row = row
    tab._open_document_tab(row, defer_restore=True)
    title, metadata, sections = tab._parse_law_detail(_payload())
    tab._set_detail_document(
        title,
        metadata,
        sections,
        build_toc=True,
        law_annexes=tab._law_annex_entries(_payload()),
    )

    html = str(tab._document_states[tab._active_document_key]["source_html"])
    assert html.index("<h2>조문</h2>") < html.index(
        '<h2><a name="law-annexes">별표·서식 (2건)</a></h2>'
    )
    # 제목을 누르면 그 자리에서 펼쳐지고, 내려받기는 오른쪽 작은 표시로 연다.
    assert "[별표1] 시험 기준(제1조 관련)" in html
    assert "[별지제2호의3서식] 시험 신청서" in html
    assert 'href="annex:0"' in html
    assert "annex_hwp.svg" in html and "annex_pdf.svg" in html
    assert "flDownload.do?flSeq=11" in html
    assert "flDownload.do?flSeq=12" in html
    # 굵은 글씨와 세 줄짜리 링크 묶음은 없앴다.
    assert "원본 다운로드" not in html
    assert "PDF 다운로드" not in html
    assert tab.current_detail_text.index("[조문]") < tab.current_detail_text.index(
        "[별표·서식 (2건)]"
    )
    assert (
        tab.detail_view.textInteractionFlags()
        & Qt.TextInteractionFlag.LinksAccessibleByKeyboard
    )
    assert tab._document_states[tab._active_document_key]["toc_entries"][-1] == (
        0,
        "별표·서식 (2건)",
        "law-annexes",
    )
    tab.close()


def test_annex_helper_name_is_not_shadowed_by_state(qt_app, tmp_path) -> None:
    """별표 목록을 뽑는 함수와 화면 상태가 같은 이름을 쓰지 않는다.

    한때 펼침 상태를 ``_law_annex_entries``라는 같은 이름의 속성에 담아,
    본문을 열 때 ``self._law_annex_entries(payload)``가 리스트를 호출하며
    ``'list' object is not callable``로 죽었다. 저장해 둔 조문을 여는 길이
    통째로 막혔던 문제라 이름이 다시 겹치지 않는지 지킨다.
    """
    settings = QSettings(
        str(tmp_path / "annex-name.ini"), QSettings.Format.IniFormat
    )
    tab = ResourceSearchTab(
        lambda: "",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    try:
        assert callable(tab._law_annex_entries)
        entries = tab._law_annex_entries(_payload())
        assert [entry["label"] for entry in entries] == [
            "별표 1",
            "별지 제2호의3서식",
        ]

        # 별표 목록을 한 번 그린 뒤에도 함수 자리는 그대로여야 한다.
        parts: list[str] = []
        tab._append_law_annex_section(parts, [], entries)
        assert callable(tab._law_annex_entries)
        assert tab._annex_section_entries == entries
    finally:
        tab.close()
