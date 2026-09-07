"""별표를 펼쳤다 접어도 읽던 자리가 남는지 세 갈래 모두 검증."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab


BODY = "가나다라마바사 별표 1과 같다. 별지 제2호서식으로 낸다. " * 6

ANNEX_UNITS = [
    {
        "별표구분": "별첨",
        "별표번호": f"{number:04d}",
        "별표가지번호": "00",
        "별표제목": f"별첨 서식 {number}",
        "별표서식파일링크": f"/LSW/flDownload.do?flSeq={number}",
        "별표서식PDF파일링크": f"/LSW/flDownload.do?flSeq={number + 100}",
    }
    for number in range(1, 4)
]


def _law_payload() -> dict:
    return {
        "법령": {
            "기본정보": {"법령명_한글": "테스트 법률", "법령ID": "001000"},
            "조문": {
                "조문단위": [
                    {"조문번호": str(n), "조문내용": f"제{n}조(제목{n}) {BODY}"}
                    for n in range(1, 41)
                ]
            },
            "별표": {"별표단위": ANNEX_UNITS},
        }
    }


def _admrul_payload() -> dict:
    return {
        "AdmRulService": {
            "행정규칙기본정보": {
                "행정규칙명": "도시ㆍ군관리계획수립지침",
                "행정규칙종류": "훈령",
            },
            "조문내용": [
                "\n".join(f"{n}-1-1. 지침 항목 {n} {BODY}" for n in range(1, 41))
            ],
            "별표": {"별표단위": ANNEX_UNITS},
        }
    }


def _ordin_payload() -> dict:
    return {
        "LawService": {
            "자치법규기본정보": {
                "자치법규명": "이천시 도시계획 조례",
                "지자체기관명": "이천시",
            },
            "조문": {
                "조": [
                    {"조내용": " ".join(f"제{n}조(항목{n}) {BODY}" for n in range(1, 31))}
                ]
            },
            "별표": {"별표단위": ANNEX_UNITS},
        }
    }


CASES = (
    ("law", "법령", "테스트 법률", _law_payload),
    ("admrul", "행정규칙", "도시ㆍ군관리계획수립지침", _admrul_payload),
    ("ordin", "자치법규", "이천시 도시계획 조례", _ordin_payload),
)


def _tab(tmp_path) -> ResourceSearchTab:
    QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "annex.ini"), QSettings.Format.IniFormat)
    tab = ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    tab.resize(1200, 800)
    tab.show()
    return tab


@pytest.mark.parametrize("target,label,name,payload_factory", CASES)
def test_collapsing_an_annex_keeps_the_reading_position(
    tmp_path, target, label, name, payload_factory
) -> None:
    """법령ㆍ행정규칙ㆍ자치법규 모두 접은 뒤 맨 위로 튀지 않는다."""
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    tab.pending_row = {
        "target": target,
        "label": label,
        "id": "001000",
        "name": name,
        "related": "",
        "organization": "국토교통부",
        "date": "",
        "number": "",
        "effective": "",
        "short_name": "",
        "raw": {},
    }
    tab._show_detail(payload_factory())
    app.processEvents()

    tab._toggle_annex_preview("0")
    for _ in range(4):
        app.processEvents()
    expanded_at = tab.detail_view.verticalScrollBar().value()
    assert expanded_at > 0

    tab._toggle_annex_preview("0")
    for _ in range(4):
        app.processEvents()
    QTest.qWait(500)

    assert tab.detail_view.verticalScrollBar().value() == expanded_at


def test_scroll_is_held_until_the_layout_grows(tmp_path) -> None:
    """배치가 늦게 자라도 되돌린 자리를 끝까지 붙잡는다."""
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    tab.pending_row = {
        "target": "law",
        "label": "법령",
        "id": "001000",
        "name": "테스트 법률",
        "related": "",
        "organization": "국토교통부",
        "date": "",
        "number": "",
        "effective": "",
        "short_name": "",
        "raw": {},
    }
    tab._show_detail(_law_payload())
    app.processEvents()

    scroll_bar = tab.detail_view.verticalScrollBar()
    target = int(scroll_bar.maximum() * 0.6)
    scroll_bar.setValue(0)
    tab._hold_document_scroll(tab._active_document_key, target)
    QTest.qWait(600)

    assert scroll_bar.value() == min(target, scroll_bar.maximum())
