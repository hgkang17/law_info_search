"""열거한 호는 앞 조/항을 이어받되 새 문장/새 조문으로 넘기지 않는다."""

from html import unescape
import re
from urllib.parse import parse_qs, urlsplit

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QTextDocument

from utils.formatting import law_reference_html_text
from utils.legal_body import legal_body_to_html, repair_enumerated_reference_links


LAW = "국토의 계획 및 이용에 관한 법률"


def links(html):
    return {
        text: parse_qs(urlsplit(unescape(href)).query)
        for href, text in re.findall(r'<a href="([^"]+)"[^>]*>(.*?)</a>', html)
    }


@pytest.mark.parametrize("prefix", ["법 ", f"「{LAW}」 "])
@pytest.mark.parametrize("join", [" 및 ", " 또는 ", ", ", "ㆍ", "부터 ", " 내지 "])
def test_enumerated_ho_inherits_law_article_and_paragraph(prefix, join):
    result = links(law_reference_html_text(
        prefix + "제26조제1항제1호" + join + "제5호", (),
        current_law_name=LAW + " 시행령", current_law_id="decree-id", use_api_links=True,
    ))["제5호"]
    assert result == {"name": [LAW], "jo": ["26"], "hang": ["1"], "ho": ["5"]}


@pytest.mark.parametrize(("text", "label", "expected"), [
    ("제26조의2제1항의2제1호의2 및 제5호 및 제7호", "제7호",
     {"jo": ["26"], "jo_branch": ["2"], "hang": ["1"], "hang_branch": ["2"], "ho": ["7"]}),
    ("제26조제1항제1호 및 제2항제5호", "제5호",
     {"jo": ["26"], "hang": ["2"], "ho": ["5"]}),
    ("제26조제1항제1호 및 제27조제5호", "제5호", {"jo": ["27"], "ho": ["5"]}),
    ("제26조제1항제1호 및 제5호가목", "가목",
     {"jo": ["26"], "hang": ["1"], "ho": ["5"], "mok": ["가"]}),
])
def test_enumeration_preserves_only_parent_units(text, label, expected):
    result = links(law_reference_html_text(text, (), current_law_name=LAW, use_api_links=True))[label]
    assert result == {"name": [LAW], **expected}


@pytest.mark.parametrize("tail", [
    "에 따른다. 제2항 및 제5호", "에 따른 제5호", "\n제5호", "와 관련된 제5호",
    " 및 「건축법」 제5호",
])
def test_unrelated_bare_ho_does_not_borrow_old_article(tail):
    result = links(law_reference_html_text(
        "제26조제1항제1호" + tail, (), current_law_name=LAW, use_api_links=True,
    ))
    assert "제5호" not in result


@pytest.mark.parametrize("target", ["law", "admrul", "ordin"])
def test_shared_legal_body_keeps_enumeration_and_annex_links(target):
    app = QApplication.instance() or QApplication([])
    html = legal_body_to_html(
        f"1. 「{LAW}」 제26조제1항제1호 및 제5호에 따른다. 별표 1 및 별지 제3호서식 참조.",
        document_target=target, document_name="시험규정", current_law_name="시험규정",
        use_api_links=True,
    )
    assert links(html)["제5호"] == {
        "name": [LAW], "jo": ["26"], "hang": ["1"], "ho": ["5"],
    }
    assert "annexref://" in html
    assert "별지 제3호서식" in html


@pytest.mark.parametrize("gap", [" 및 ", ", ", "에 따른다. ", "</p><p>"])
def test_old_html_repairs_only_enumerated_ho_without_changing_text(gap):
    app = QApplication.instance() or QApplication([])
    document = QTextDocument()
    document.setHtml(
        '<p><a href="lawref://open?name=Test&amp;jo=26&amp;hang=1&amp;ho=1">제1호</a>'
        + gap + '<a href="lawref://open?name=Test&amp;jo=26&amp;ho=5">제<b>5</b>호</a></p>'
    )
    text = document.toPlainText()
    repair_enumerated_reference_links(document)
    assert document.toPlainText() == text
    cursor = document.find("제5호")
    params = parse_qs(urlsplit(cursor.charFormat().anchorHref()).query)
    assert params.get("hang") == (["1"] if gap in (" 및 ", ", ") else None)
    cursor = document.find("5")
    assert cursor.charFormat().fontWeight() == 700


def test_cached_popup_repairs_enumeration_on_display():
    from ui.dialogs import LawReferencePopup

    app = QApplication.instance() or QApplication([])
    popup = LawReferencePopup(lambda url: None)
    try:
        popup.set_content("저장된 조문", '<p>'
            '<a href="lawref://open?name=Test&amp;jo=26&amp;hang=1&amp;ho=1">제1호</a> 및 '
            '<a href="lawref://open?name=Test&amp;jo=26&amp;ho=5">제5호</a></p>')
        cursor = popup.browser.document().find("제5호")
        assert parse_qs(urlsplit(cursor.charFormat().anchorHref()).query)["hang"] == ["1"]
    finally:
        popup.close()


def test_previous_popup_cache_schema_is_rejected(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    import ui.tabs.resource_search as module

    monkeypatch.setattr(module, "LAW_REFERENCE_CACHE_DIR", tmp_path)
    key = "enumeration-cache"
    path = module.ResourceSearchTab._reference_cache_path(key)
    path.write_text(json.dumps({
        "schema": module.LAW_REFERENCE_CACHE_SCHEMA - 1,
        "kind": "law_reference", "key": key, "title": "old",
        "html": '<div class="content">old</div>',
    }), encoding="utf-8")
    tab = SimpleNamespace(
        _reference_cache_path=module.ResourceSearchTab._reference_cache_path,
        _reference_popup_states={},
    )
    assert module.ResourceSearchTab._load_reference_cache(tab, key) is None
