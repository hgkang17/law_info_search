"""별표·서식 전체검색이 세 API 결과를 합쳐 보여 주는지 검증."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from models.law import ANNEX_ALL_TARGET, ANNEX_TARGETS
from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab
import workers.search_worker as search_worker_module
from workers.search_worker import ResourceApiWorker


@pytest.fixture
def tab(tmp_path):
    QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "res.ini"), QSettings.Format.IniFormat)
    return ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )


def _annex_payload(root: str, item: str, names: list[str]) -> dict:
    return {
        root: {
            "totalCnt": str(len(names)),
            item: [
                {
                    "별표일련번호": f"{index}",
                    "별표명": name,
                    "관련법령명": "관련 자료",
                    "관련행정규칙명": "관련 자료",
                    "관련자치법규명": "관련 자료",
                    "소관부처명": "국토교통부",
                    "지자체기관명": "국토교통부",
                    "공포일자": "20260101",
                    "발령일자": "20260101",
                    "공포번호": "1",
                    "발령번호": "1",
                }
                for index, name in enumerate(names, 1)
            ],
        }
    }


def test_worker_calls_all_three_annex_apis(monkeypatch) -> None:
    """전체를 고르면 법령·행정규칙·자치법규 별표를 차례로 부른다."""
    called: list[tuple[str, int]] = []

    def fake_search(oc, target, query, *, search_scope=1, display=100, **kwargs):
        called.append((target, search_scope))
        return {"licBylSearch": {"totalCnt": "0"}}

    monkeypatch.setattr(search_worker_module, "search_resource", fake_search)
    worker = ResourceApiWorker(
        "resource_search",
        oc="test-oc",
        target=ANNEX_ALL_TARGET,
        query="용도별",
        search_scope=3,
    )
    worker.run()

    assert [target for target, _scope in called] == list(ANNEX_TARGETS)
    # 고른 검색범위는 세 API에 그대로 전달된다.
    assert {scope for _target, scope in called} == {3}


def test_one_failed_api_does_not_drop_the_others(monkeypatch) -> None:
    """한 대상이 실패해도 나머지 결과는 그대로 낸다."""
    def fake_search(oc, target, query, *, search_scope=1, display=100, **kwargs):
        if target == "admbyl":
            raise RuntimeError("서버 오류")
        return {"licBylSearch": {"totalCnt": "0"}}

    monkeypatch.setattr(search_worker_module, "search_resource", fake_search)
    results: list[object] = []
    worker = ResourceApiWorker(
        "resource_search",
        oc="test-oc",
        target=ANNEX_ALL_TARGET,
        query="용도별",
    )
    worker.succeeded.connect(lambda _operation, payload: results.append(payload))
    worker.run()

    payload = results[0]
    assert set(payload["annex_results"]) == {"licbyl", "ordinbyl"}
    assert any("서버 오류" in error for error in payload["errors"])


def test_rows_from_three_apis_are_merged_with_a_kind_column(tab) -> None:
    """세 대상 결과가 한 표에 합쳐지고 '구분' 열이 보인다."""
    assert tab.select_category(ANNEX_ALL_TARGET)
    tab._show_search_results(
        {
            "annex_results": {
                "licbyl": _annex_payload(
                    "licBylSearch", "licbyl", ["용도별 건축물의 종류"]
                ),
                "admbyl": _annex_payload(
                    "admRulBylSearch", "admrulbyl", ["건설공사의 용도별 분류"]
                ),
                "ordinbyl": _annex_payload(
                    "licBylSearch", "ordinbyl", ["공용차량의 용도별 기준"]
                ),
            },
            "errors": [],
        }
    )

    assert [row["name"] for row in tab.result_rows] == [
        "용도별 건축물의 종류",
        "건설공사의 용도별 분류",
        "공용차량의 용도별 기준",
    ]
    assert [row["target"] for row in tab.result_rows] == list(ANNEX_TARGETS)
    assert not tab.result_table.isColumnHidden(1)
