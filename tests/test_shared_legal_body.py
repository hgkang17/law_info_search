"""같은 본문을 모든 표시 경로로 보내 링크ㆍ줄바꿈의 누락을 검증한다."""

from html.parser import HTMLParser

import pytest
from PySide6.QtCore import QSettings, QUrl, QUrlQuery
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.ai_search import AiLawSearchTab
from ui.tabs.resource_search import ResourceSearchTab
from ui.tabs.ai_chat_panel import AiChatPanel
from utils.parsing import law_article_text, normalize_legal_body


class _Anchors(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.urls = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.urls.extend(value for key, value in attrs if key == "href")


@pytest.fixture
def tab(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(ResourceSearchTab, "_queue_three_stage_link_request", lambda *a: None)
    monkeypatch.setattr(AiChatPanel, "_start_visible_background_checks", lambda self: None)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    widget = ResourceSearchTab(lambda: "", RecentSearchManager(settings), LawDocumentCache(tmp_path / "saved"))
    yield widget
    widget.close()


SOURCE = "제1조(기준) 별표 1 및 제2조에 따른다."


def test_decree_enumerated_ho_click_keeps_all_api_units(tab, monkeypatch):
    from utils.formatting import law_reference_html_text

    html = law_reference_html_text(
        "법 제26조제1항제1호 및 제5호", (),
        current_law_name="국토의 계획 및 이용에 관한 법률 시행령", use_api_links=True,
    )
    url = next(url for url in _Anchors(html).urls if QUrlQuery(QUrl(url)).queryItemValue("ho") == "5")
    monkeypatch.setattr(tab, "_load_reference_cache", lambda key: {"title": "제5호", "html": "<p>본문</p>"})
    tab.open_reference_link(QUrl(url))
    requests = [popup.reference_request for popup in tab._all_reference_popups()]
    assert any(request and request.get("jo") == "002600"
               and request.get("hang") == "000100" and request.get("ho") == "000500"
               for request in requests)


@pytest.mark.parametrize("target", ["law", "admrul", "ordin"])
def test_enumerated_ho_in_full_document_popup_and_comparison(tab, target):
    law = "국토의 계획 및 이용에 관한 법률"
    source = f"제19조의2(기준) 1. 「{law}」 제26조제1항제1호 및 제5호에 따른다."
    row = {"target": target, "id": "test-id", "name": "검증문서"}
    payloads = {
        "law": {"법령": {"조문": {"조문단위": {"조문내용": source}}}},
        "ordin": {"LawService": {"조문": {"조": {"조내용": source}}}},
        "admrul": {"AdmRulService": {"조문내용": source}},
    }
    tab.pending_row = row
    tab._set_detail_document(row["name"], [], [("조문", source)], build_toc=True,
                             administrative_rule=target == "admrul")
    _, popup_html = tab._document_reference_html(row, payload=payloads[target])
    comparison_html = tab._three_stage_node_html(
        {"조내용": source}, fallback_law_name=row["name"],
    )
    for html in (tab.detail_view.toHtml(), popup_html, comparison_html):
        queries = [QUrlQuery(QUrl(url)) for url in _Anchors(html).urls if url.startswith("lawref:")]
        fifth = [query for query in queries if query.queryItemValue("ho") == "5"]
        assert fifth
        assert all(query.queryItemValue("name") == law
                   and query.queryItemValue("jo") == "26"
                   and query.queryItemValue("hang") == "1" for query in fifth)


@pytest.mark.parametrize("target,category", [("law", "licbyl"), ("admrul", "admbyl"), ("ordin", "ordinbyl")])
def test_document_and_document_popup_share_annex_target(tab, target, category):
    row = {"target": target, "id": "test-id", "name": "검증문서"}
    payloads = {
        "law": {"법령": {"조문": {"조문단위": {"조문내용": SOURCE}}}},
        "ordin": {"LawService": {"조문": {"조": {"조내용": SOURCE}}}},
        "admrul": {"AdmRulService": {"조문내용": SOURCE}},
    }
    tab.pending_row = row
    tab._set_detail_document(row["name"], [], [("조문", SOURCE)], build_toc=True,
                             administrative_rule=target == "admrul")
    _, popup_html = tab._document_reference_html(row, payload=payloads[target])
    for html in (tab.detail_view.toHtml(), popup_html):
        annex = [QUrlQuery(QUrl(url)) for url in _Anchors(html).urls if url.startswith("annexref:")]
        assert len(annex) == 1
        assert annex[0].queryItemValue("name") == "별표 1"
        assert annex[0].queryItemValue("category") == category
        assert annex[0].queryItemValue("related") == row["name"]


@pytest.mark.parametrize("target", ["law", "ordin", "admrul"])
def test_shared_normalization_preserves_subitems_and_references(target):
    text = "제1조(기준)\n가. 다음에 따른다. 1) 첫째 2) 둘째 가) 세부 기준 나) 세부 예외"
    normalized = normalize_legal_body(text, target)
    assert normalize_legal_body(normalized, target) == normalized
    for marker in ("1)", "2)", "가)", "나)"):
        assert any(line.startswith(marker) for line in normalized.splitlines())
    untouched = "제2호나) 목의 규정, 2026. 9. 10., 1.5퍼센트"
    assert normalize_legal_body(untouched, target) == untouched


def test_full_law_parser_and_article_extractor_share_plain_text(tab):
    units = {"조문번호": "1", "조문내용": "제1조(기준)", "항": {
        "항내용": "① 다음 각 목에 따른다.", "호": {"목": {
            "목내용": "가. 세부 기준 1) 첫째 2) 둘째 가) 세부 나) 예외"}}}}
    tab.pending_row = {"target": "law", "id": "id", "name": "검증법"}
    _, _, sections = tab._parse_law_detail({"법령": {"조문": {"조문단위": units}}})
    assert sections[0][1] == law_article_text(units)
    assert "\n1)" in sections[0][1]


def test_three_stage_cell_is_balanced_and_has_annex_and_article_links(tab):
    html = tab._three_stage_node_html({"법령명": "검증법", "조제목": "제1조(기준)",
                                      "조내용": SOURCE, "조번호": "1"}, fallback_law_name="검증법")
    assert html.count("<div") == html.count("</div>")
    urls = _Anchors(html).urls
    assert any(url.startswith("annexref:") for url in urls)
    assert any(url.startswith("lawref:") for url in urls)


@pytest.mark.parametrize("scheme", ["annexref", "lawref", "lawsub"])
def test_keyword_link_routes_to_shared_popup(tab, scheme):
    keyword = AiLawSearchTab("ai_search", lambda: "", tab.recent_search_manager, tab.law_cache)
    opened = []
    from types import SimpleNamespace
    keyword.reference_tab = SimpleNamespace(open_reference_link=opened.append)
    keyword._detail_link_clicked(QUrl(f"{scheme}://open?name=test"))
    assert len(opened) == 1
    keyword.close()


@pytest.mark.parametrize("kind,category", [("법령", "licbyl"), ("행정규칙", "admbyl")])
def test_old_keyword_snapshot_gets_annex_links_without_api_or_text_changes(tab, kind, category):
    keyword = AiLawSearchTab("ai_search", lambda: "", tab.recent_search_manager, tab.law_cache)
    record = {"row": {"name": "검증문서", "kind": kind},
              "html": "<p>별표 1의 기준에 따른다.</p>", "plain_text": "별표 1의 기준에 따른다."}
    keyword.open_cached_snapshot(record)
    assert keyword.detail_view.toPlainText() == record["plain_text"]
    urls = _Anchors(keyword.detail_view.toHtml()).urls
    assert any(f"category={category}" in url for url in urls)
    keyword.close()


def test_decree_popup_uses_rule_links_from_the_same_cached_family(tab):
    tab._three_stage_payload_cache = {"id": {"LawService": {
        "기본정보": {"기준법령명": "검증법"},
        "위임조문삼단비교": {"법률조문": {"조번호": "1", "법령명": "검증법",
            "시행령조문": {"조번호": "2", "법령명": "검증법 시행령", "조내용": "국토교통부령으로 정한다."},
            "시행규칙조문": {"조번호": "3", "법령명": "검증법 시행규칙", "조내용": "영 제2조에 따른다."}}}}}}
    links = tab._popup_authority_links("검증법 시행령", "000200")
    assert links
    assert "시행규칙" in QUrlQuery(QUrl(next(iter(links.values())))).queryItemValue("name")
    assert tab._popup_authority_links("다른법 시행령", "000200") == {}
