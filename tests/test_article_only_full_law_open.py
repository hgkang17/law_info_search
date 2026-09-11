"""조문 즐겨찾기만 저장한 뒤 법령 전문을 열 때의 회귀 검증."""

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab


ROW = {
    "target": "law", "label": "법령", "id": "009294",
    "name": "국토의 계획 및 이용에 관한 법률", "raw": {},
}
UNIT = {"jo": "002600", "hang": "000100", "ho": "", "mok": "", "label": "제26조제1항"}
PAYLOAD = {
    "법령": {
        "기본정보": {"법령명_한글": ROW["name"], "법령ID": ROW["id"]},
        "조문": {"조문단위": [
            {"조문번호": "1", "조문내용": "제1조(목적) 전문 첫 조문"},
            {"조문번호": "26", "조문내용": "제26조(입안) 전문의 다른 조문"},
        ]},
    },
}


@pytest.fixture
def tab(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(ResourceSearchTab, "_queue_three_stage_link_request", lambda *args: None)
    widget = ResourceSearchTab(
        lambda: "test-oc", RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    assert widget.law_cache.set_article_favorite(
        ROW, UNIT["jo"], UNIT["label"], True, hang=UNIT["hang"],
    )
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def _open(tab, entry):
    if entry == "search":
        return tab._request_resource_detail(dict(ROW))
    return tab.open_cached_law(tab.law_cache.load_for_row(ROW))


@pytest.mark.parametrize("entry", ["search", "saved"])
def test_article_only_record_fetches_full_law_and_preserves_favorites(tab, entry):
    original = tab.law_cache.load_for_row(ROW)
    assert original["kind"] == "article_favorites"
    assert "payload" not in original
    started = []
    tab._start_worker = lambda worker, message: started.append(worker)

    _open(tab, entry)

    assert len(started) == 1
    assert started[0].operation == "resource_detail"
    assert started[0].item_id == ROW["id"]
    # 요청을 시작한 것만으로 즐겨찾기 기록을 지우지 않는다.
    assert tab.law_cache.load_for_row(ROW) == original
    tab._show_detail(PAYLOAD)
    assert "전문 첫 조문" in tab.current_detail_text
    assert "전문의 다른 조문" in tab.current_detail_text
    saved = tab.law_cache.load_for_row(ROW)
    assert saved["payload"] == PAYLOAD
    assert saved["favorite_articles"] == original["favorite_articles"]
    assert saved.get("kind") != "article_favorites"

    # 다음 열람은 새로 저장한 전문을 재사용한다.
    _open(tab, entry)
    assert len(started) == 1
    assert "전문 첫 조문" in tab.current_detail_text


@pytest.mark.parametrize("entry", ["search", "saved"])
def test_article_only_record_without_api_key_prompts_without_losing_record(tab, monkeypatch, entry):
    original = tab.law_cache.load_for_row(ROW)
    tab.oc_provider = lambda: ""
    prompts = []
    monkeypatch.setattr("ui.tabs.resource_search.prompt_oc_api_key", lambda parent: prompts.append(parent))
    tab._start_worker = lambda *args: pytest.fail("인증키 없이 API 요청을 시작함")

    _open(tab, entry)

    assert prompts == [tab]
    assert tab.law_cache.load_for_row(ROW) == original
    assert tab.document_tabs.count() == 0
