"""조문검색의 약칭+조문 지정 조회와 캐시 복원."""

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

import workers.search_worker as workers
from models.law import AI_SEARCH_AGENCY
from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.ai_search import AiLawSearchTab
from utils.parsing import serialize_agency_search_payload, deserialize_agency_search_payload


@pytest.mark.parametrize("suffix", ["", " 시행령", " 시행규칙"])
def test_named_article_worker_and_visible_result(tmp_path, monkeypatch, suffix):
    app = QApplication.instance() or QApplication([])
    canonical = "국토의 계획 및 이용에 관한 법률" + suffix
    captured = []
    def find_law(oc, name):
        assert name == canonical
        return {"id": "009294", "name": canonical}
    def article(oc, law_id, jo, **units):
        captured.append((law_id, jo, units))
        return {"법령": {"조문": {"조문단위": {
            "조문번호": "19", "조문가지번호": "2",
            "조문내용": "제19조의2(기준) 지정한 조문 본문이다.",
        }}}}
    monkeypatch.setattr(workers, "named_law_reference_row", find_law)
    monkeypatch.setattr(workers, "get_law_article", article)
    monkeypatch.setattr(workers, "search_agencies", lambda *a, **k: pytest.fail("키워드 API를 부르면 안 된다"))
    query = "국토계획법" + suffix + " 19조의2"
    worker = workers.ApiWorker("search", oc="test", query=query, agencies=(AI_SEARCH_AGENCY,))
    results = []
    failures = []
    worker.succeeded.connect(lambda operation, payload: results.append(payload))
    worker.failed.connect(lambda operation, message: failures.append(message))
    worker.run()
    assert not failures
    assert captured == [("009294", "001902", {"hang": "", "ho": ""})]
    # 저장/복원 후에도 직접 받은 본문이라는 표식과 한글 내용이 남아야 한다.
    payload = deserialize_agency_search_payload(serialize_agency_search_payload(results[0]))
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    tab = AiLawSearchTab("ai_search", lambda: "", RecentSearchManager(settings), LawDocumentCache(tmp_path / "saved"))
    try:
        tab.query_input.setText(query)
        tab._show_search_results(payload)
        tab._open_detail_expanded()
        app.processEvents()
        assert len(tab.result_rows) == 1
        row = tab.result_rows[0]
        assert row["name"] == canonical
        assert row["jo_code"] == "001902"
        assert row["article_api_loaded"] == "1"
        assert "지정한 조문 본문" in tab.detail_view.toPlainText()
    finally:
        tab.close()


def test_empty_article_does_not_create_a_result(monkeypatch):
    monkeypatch.setattr(workers, "named_law_reference_row", lambda *a: {"id": "1", "name": "건축법"})
    monkeypatch.setattr(workers, "get_law_article", lambda *a, **k: {})
    root = workers.named_article_search_root("test", "건축법 9999조")
    assert root.findtext("검색결과개수") == "0"
    assert not root.findall("법령")


def test_old_keyword_cache_is_bypassed_for_named_article(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import xml.etree.ElementTree as ET

    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    tab = AiLawSearchTab("ai_search", lambda: "test", RecentSearchManager(settings), LawDocumentCache(tmp_path / "saved"))
    payload = serialize_agency_search_payload({"roots": [(AI_SEARCH_AGENCY, ET.Element("old"))], "errors": []})
    tab.search_result_cache = SimpleNamespace(load=lambda *args: {"payload": payload})
    started = []
    monkeypatch.setattr(tab, "_start_worker", lambda worker, message: started.append(worker))
    try:
        tab.query_input.setText("국토계획법 시행령 19조의2")
        tab.start_search()
        assert len(started) == 1
        assert started[0].query == "국토계획법 시행령 19조의2"
    finally:
        tab.close()
