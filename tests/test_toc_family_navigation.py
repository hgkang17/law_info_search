"""목차 위 법률/시행령/시행규칙 전문 전환."""

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab
from ui.tabs.ai_chat_panel import AiChatPanel
import workers.search_worker as workers


@pytest.fixture
def tab(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(AiChatPanel, "_start_visible_background_checks", lambda self: None)
    monkeypatch.setattr(ResourceSearchTab, "_queue_three_stage_link_request", lambda *a: None)
    widget = ResourceSearchTab(lambda: "test", RecentSearchManager(QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)), LawDocumentCache(tmp_path / "saved"))
    yield widget
    widget.close()


@pytest.mark.parametrize("name", ["건축법", "건축법 시행령", "건축법 시행규칙"])
def test_toc_family_tracks_current_document_and_double_click(tab, monkeypatch, name):
    tab.pending_row = {"target": "law", "id": "1", "name": name}
    tab._set_detail_document(name, [], [("조문", "제1조(목적) 본문")], build_toc=True)
    tree = tab.family_law_tree
    assert [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())] == ["건축법", "건축법 시행령", "건축법 시행규칙"]
    assert tree.currentItem().text(0) == name
    started = []
    monkeypatch.setattr(tab, "_start_worker", lambda worker, message: started.append(worker))
    index = 2 if name != "건축법 시행규칙" else 1
    tree.itemDoubleClicked.emit(tree.topLevelItem(index), 0)
    assert started[0].operation == "family_law_detail"
    assert started[0].law_name == tree.topLevelItem(index).text(0)


def test_toc_family_uses_official_short_name_but_opens_full_name(tab, monkeypatch):
    full = "국토의 계획 및 이용에 관한 법률 시행령"
    tab._law_short_name_cache["국토의계획및이용에관한법률"] = "국토계획법"
    tab.pending_row = {"target": "law", "id": "1", "name": full}
    tab._set_detail_document(full, [], [("조문", "제1조(목적) 본문")], build_toc=True)

    tree = tab.family_law_tree
    assert [tree.topLevelItem(i).text(0) for i in range(3)] == [
        "국토계획법", "국토계획법 시행령", "국토계획법 시행규칙",
    ]
    assert tree.currentItem().text(0) == "국토계획법 시행령"
    assert tree.height() == 70
    assert tree.font().pointSizeF() < tab.toc_tree.font().pointSizeF()

    started = []
    monkeypatch.setattr(tab, "_start_worker", lambda worker, message: started.append(worker))
    tree.itemDoubleClicked.emit(tree.topLevelItem(2), 0)
    assert started[0].law_name == "국토의 계획 및 이용에 관한 법률 시행규칙"


def test_ordinance_does_not_invent_enforcement_decree(tab):
    tab.pending_row = {"target": "ordin", "id": "2", "name": "이천시 도시계획 조례"}
    tab._set_detail_document("이천시 도시계획 조례", [], [("조문", "제1조(목적) 본문")], build_toc=True)
    assert tab.family_law_tree.isHidden()


def test_saved_ordinance_html_is_loaded_and_its_annex_links_are_repaired(tab):
    row = {"target": "ordin", "id": "2", "name": "이천시 도시계획 조례", "label": "자치법규"}
    record = {
        "html": '<p>제21조의2(기준) 별표 26에 따른다.</p><p>「건축법 시행령」 별표 1 제11호</p>',
        "plain_text": '제21조의2(기준) 별표 26에 따른다.\n「건축법 시행령」 별표 1 제11호',
        "annex_entries": [{"label": "별표", "title": "제1종전용주거지역 외", "file_url": "https://example.test/bundle.hwp"}],
    }
    tab._open_cached_resource_snapshot(row, record)
    document = tab.detail_view.document()
    assert "제21조의2" in document.toPlainText()
    assert document.find("별표 26").charFormat().anchorHref() == "annexopen:0"
    assert "category=licbyl" in document.find("별표 1").charFormat().anchorHref()


def test_family_worker_fetches_full_law_not_article(monkeypatch):
    monkeypatch.setattr(workers, "named_law_reference_row", lambda oc, name: {"id": "decree", "name": name})
    calls = []
    def detail(oc, target, item_id):
        calls.append((target, item_id))
        return {"법령": {"조문": {"조문단위": {"조문번호": "1", "조문내용": "제1조 목적"}}}}
    monkeypatch.setattr(workers, "get_resource_detail", detail)
    worker = workers.ResourceApiWorker("family_law_detail", oc="test", target="law", law_name="건축법 시행령")
    results = []
    worker.succeeded.connect(lambda operation, payload: results.append(payload))
    worker.run()
    assert calls == [("eflaw", "decree")]
    assert results[0]["row"]["name"] == "건축법 시행령"
