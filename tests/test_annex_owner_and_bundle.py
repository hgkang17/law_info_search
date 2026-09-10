"""타 법령의 별표와 자치법규의 번호 없는 통합 별표를 구별한다."""

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QTextDocument
from PySide6.QtCore import QUrl, QUrlQuery
from utils.legal_body import legal_body_to_html, apply_annex_links
from ui.tabs.resource_search import ResourceSearchTab


@pytest.mark.parametrize("entries", [{"별표": 0, "별지서식": 1}, {"별표 1": 2}])
def test_external_annex_does_not_open_local_ordinance_bundle(entries):
    app = QApplication.instance() or QApplication([])
    document = QTextDocument()
    document.setHtml(legal_body_to_html(
        '3. “노유자시설”이란 「건축법 시행령」 별표 1 제11호에 따른 시설을 말한다.',
        document_name="이천시 도시계획 조례", document_target="ordin", use_api_links=True,
    ))
    apply_annex_links(document, document_name="이천시 도시계획 조례", document_target="ordin", entries_by_label=entries)
    query = QUrlQuery(QUrl(document.find("별표 1").charFormat().anchorHref()))
    assert query.queryItemValue("related") == "건축법 시행령"
    assert query.queryItemValue("category") == "licbyl"
    assert query.queryItemValue("name") == "별표 1"


@pytest.mark.parametrize("target,entries,expected", [
    ("ordin", {"별표": 0, "별지서식": 1}, "annexopen:0"),
    ("law", {"별표": 0}, "annexref:"),
    ("ordin", {"별표": 0, "별표 1": 1}, "annexref:"),
])
def test_combined_annex_fallback_requires_ordinance_and_no_numbered_tables(target, entries, expected):
    app = QApplication.instance() or QApplication([])
    document = QTextDocument()
    document.setPlainText("별표 26 및 별표 2에 따른다. 별지 제3호서식")
    apply_annex_links(document, document_name="이천시 도시계획 조례", document_target=target, entries_by_label=entries)
    for text in ("별표 26", "별표 2"):
        assert document.find(text).charFormat().anchorHref().startswith(expected)
    assert document.find("별지 제3호서식").charFormat().anchorHref().startswith("annexref:")


def test_bundle_row_fallback_does_not_take_numbered_annex_or_form():
    bundle = {"target": "ordinbyl", "name": "[별표] 제1종전용주거지역 외", "id": "bundle", "raw": {"별표번호": "1"}}
    form = {"target": "ordinbyl", "name": "[별지서식] 서약서", "id": "form", "raw": {"별표번호": "2"}}
    assert ResourceSearchTab._pick_annex_row([bundle, form], item_id="", hint="별표 26", title="별표 26") is bundle
    assert ResourceSearchTab._pick_annex_row([bundle, form], item_id="", hint="별지 제3호서식", title="별지 제3호서식") is None
