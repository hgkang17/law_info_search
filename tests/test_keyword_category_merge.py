"""연관검색ㆍ직접검색을 법령검색 탭 카테고리로 옮긴 뒤의 회귀 검증."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

import molit_cgm_expc_api as api_module
from models.law import (
    AI_RELATED_AGENCY,
    AI_SEARCH_AGENCY,
    RESOURCE_ALL_TARGET,
)
from ui.main_window import LawSearchWindow
import workers.search_worker as search_worker_module
from workers.search_worker import ResourceApiWorker


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qt_app):
    window = LawSearchWindow()
    yield window
    window.close()


def _category_targets(window: LawSearchWindow) -> list[str]:
    bar = window.resource_tab.category_tabs
    return [str(bar.tabData(index)) for index in range(bar.count())]


def test_keyword_categories_sit_next_to_integrated_search(window) -> None:
    targets = _category_targets(window)

    # 조문검색 캡슐이 통합검색 바로 옆에 붙는다. 연관검색은 고를 자리를
    # 두지 않고 통합검색 결과에 "AI추천" 구분으로 섞여 나온다.
    assert targets[:2] == ["__all__", "ai_search"]
    # 별표·서식 캡슐은 세 대상을 한 번에 찾는 전체가 기본이다.
    assert targets[2:] == ["law", "admrul", "ordin", "__annex_all__"]


def test_annex_capsule_carries_the_chosen_annex_target(window) -> None:
    """별표ㆍ서식 캡슐 하나가 세 API와 전체검색을 함께 맡는다."""
    resource = window.resource_tab

    for target in ("licbyl", "admbyl", "ordinbyl", "__annex_all__"):
        assert resource.select_category(target)
        assert resource.category_target == target
        assert resource.is_annex_category
        assert resource.annex_target.currentData() == target
        assert not resource.annex_target.isHidden()
        assert _category_targets(window)[-1] == target

    # 콤보로 고르면 카테고리도 함께 바뀐다. 맨 위는 전체다.
    resource.annex_target.setCurrentIndex(1)
    assert resource.category_target == "licbyl"
    resource.annex_target.setCurrentIndex(0)
    assert resource.category_target == "__annex_all__"

    resource.select_category("law")
    assert not resource.is_annex_category
    assert resource.annex_target.isHidden()


def test_keyword_capsule_returns_to_article_search(window) -> None:
    """캡슐은 조문검색만 맡는다. 연관 화면은 저장 본문 복원 때만 나온다."""
    resource = window.resource_tab
    assert not hasattr(window.ai_search_tab, "mode_switch")

    # 저장해 둔 연관검색 본문을 되살리는 경로는 그대로 남는다.
    resource.select_category("ai_related")
    assert window.ai_tabs.currentWidget() is window.ai_related_tab

    # 다른 분류를 거쳐 캡슐을 다시 고르면 조문검색으로 돌아온다.
    resource.select_category("law")
    resource.select_category("ai_search")
    assert resource.category_target == "ai_search"
    assert window.ai_tabs.currentWidget() is window.ai_search_tab


def test_keyword_search_left_the_main_menu(window) -> None:
    labels = [
        window.navigation.item(index).text().replace("\n", " ")
        for index in range(window.navigation.count())
    ]

    assert not any("키워드" in label for label in labels)
    # 페이지 번호와 메뉴 줄 번호는 1:1로 묶여 있어 함께 당겨져야 한다.
    # 메뉴와 짝이 없는 페이지는 저장내역ㆍAI 검토ㆍ시작 화면 셋이다.
    assert window.navigation.count() == window.tabs.count() - 3


def test_choosing_a_keyword_category_swaps_the_page(window) -> None:
    resource = window.resource_tab

    resource.select_category("ai_related")
    assert resource.is_keyword_category
    assert resource.content_stack.currentWidget() is resource._keyword_page
    assert window.ai_tabs.currentWidget() is window.ai_related_tab

    resource.select_category("ai_search")
    assert window.ai_tabs.currentWidget() is window.ai_search_tab

    resource.select_category("law")
    assert not resource.is_keyword_category
    assert resource.content_stack.currentWidget() is resource.resource_body


def test_keyword_search_card_matches_law_and_annex_size(window, qt_app) -> None:
    resource = window.resource_tab
    window.resize(1400, 900)
    window.show()
    qt_app.processEvents()

    def card_box(card):
        top_left = card.mapTo(resource, QPoint(0, 0))
        return top_left.x(), card.width(), card.height()

    resource.select_category("law")
    qt_app.processEvents()
    law_box = card_box(resource.search_card)

    resource.select_category("licbyl")
    qt_app.processEvents()
    annex_box = card_box(resource.search_card)

    resource.select_category("ai_related")
    qt_app.processEvents()
    related_box = card_box(window.ai_related_tab.search_card)

    resource.select_category("ai_search")
    qt_app.processEvents()
    direct_box = card_box(window.ai_search_tab.search_card)

    assert annex_box[0] == law_box[0]
    assert annex_box[1] == law_box[1]
    assert related_box[0] == law_box[0]
    assert related_box[1] == law_box[1]
    assert related_box[2] == law_box[2]
    assert direct_box[0] == law_box[0]
    assert direct_box[1] == law_box[1]
    assert direct_box[2] == law_box[2]


def test_result_count_badge_size_is_shared(window, qt_app) -> None:
    resource = window.resource_tab
    window.resize(1400, 900)
    window.show()
    qt_app.processEvents()

    resource.select_category("law")
    qt_app.processEvents()
    law_hint = resource.result_count.sizeHint()

    resource.select_category("licbyl")
    qt_app.processEvents()
    annex_hint = resource.result_count.sizeHint()

    resource.select_category("ai_related")
    qt_app.processEvents()
    related_hint = window.ai_related_tab.result_count.sizeHint()

    resource.select_category("ai_search")
    qt_app.processEvents()
    direct_hint = window.ai_search_tab.result_count.sizeHint()

    assert annex_hint == law_hint
    assert related_hint == law_hint
    assert direct_hint == law_hint
    assert law_hint.height() <= 24


def test_integrated_search_no_longer_shows_detail_button(window) -> None:
    resource = window.resource_tab
    resource.select_category("__all__")
    assert resource.detail_button.isHidden()
    resource.select_category("law")
    assert resource.detail_button.isHidden()
    resource.select_category("admrul")
    assert resource.detail_button.isHidden()
    resource.select_category("ordin")
    assert resource.detail_button.isHidden()
    for annex_target in ("licbyl", "admbyl", "ordinbyl"):
        resource.select_category(annex_target)
        assert resource.detail_button.isHidden()


def test_saved_records_route_into_the_law_search_tab(window) -> None:
    window._show_keyword_category("ai_search")

    # 저장내역에서 연 직접검색 본문도 이제 법령검색 자리에서 열린다.
    assert window.navigation.currentRow() == 1
    assert window.resource_tab.category_target == "ai_search"


def test_main_menu_clears_stale_reading_mode_before_returning_to_law_search(
    window,
) -> None:
    resource = window.resource_tab
    window._show_keyword_category("ai_search")
    resource._set_reading_mode(True)

    assert resource._reading_mode
    assert resource.category_tabs.isHidden()

    # 다른 메뉴를 거쳐 법령검색으로 돌아오는 사용자 동작을 재현한다.
    window.navigation.setCurrentRow(2)
    window.navigation.setCurrentRow(1)

    assert not resource._reading_mode
    assert not resource.category_tabs.isHidden()
    assert resource.detail_card.isHidden()
    assert resource.main_splitter.sizes()[1:] == [0, 0]


def test_keyword_reading_mode_hides_outer_law_category_bar(window) -> None:
    resource = window.resource_tab
    window._show_keyword_category("ai_search")
    keyword = window.ai_search_tab
    keyword._show_detail_split()

    keyword._set_reading_mode(True)
    assert resource.category_tabs.isHidden()
    assert not window.header_card.isHidden()
    assert not window.open_documents_widget.isHidden()
    assert keyword.main_splitter.sizes()[0] == 0
    assert keyword.expand_detail_button.isHidden()

    keyword._set_reading_mode(False)
    assert not resource.category_tabs.isHidden()
    assert not keyword._reading_mode
    assert keyword.detail_card.isHidden()


def test_switching_keyword_category_clears_previous_reading_mode(window) -> None:
    """같은 메인 탭 안에서 키워드 화면을 바꿔도 공용 UI가 복원된다."""
    window._show_keyword_category("ai_search")
    direct = window.ai_search_tab
    direct._show_detail_split()
    direct._set_reading_mode(True)

    window._show_keyword_category("ai_related")

    assert window.ai_tabs.currentWidget() is window.ai_related_tab
    assert not direct._reading_mode
    assert not window.resource_tab.category_tabs.isHidden()
    assert not window.navigation_card.isHidden()


def _keyword_root(tag, name_field, name, id_field, item_id, org_field, org):
    root = ET.Element("결과")
    node = ET.SubElement(root, tag, {"id": "1"})
    ET.SubElement(node, name_field).text = name
    ET.SubElement(node, id_field).text = item_id
    ET.SubElement(node, org_field).text = org
    ET.SubElement(node, "공포일자").text = "20240115"
    ET.SubElement(node, "발령일자").text = "20240115"
    ET.SubElement(node, "시행일자").text = "20240701"
    return root, node


def test_integrated_search_keeps_keyword_article_rows(window) -> None:
    related, first = _keyword_root(
        "법령", "법령명", "국토의 계획 및 이용에 관한 법률",
        "법령ID", "001234", "소관부처명", "국토교통부",
    )
    ET.SubElement(first, "조문번호").text = "77"
    ET.SubElement(first, "조문가지번호").text = "0"
    ET.SubElement(first, "조문제목").text = "용도지역의 건폐율"
    # 같은 법령의 다른 조문도 단독 연관검색과 같은 별도 결과다.
    repeated = ET.SubElement(related, "법령", {"id": "2"})
    ET.SubElement(repeated, "법령명").text = "국토의 계획 및 이용에 관한 법률"
    ET.SubElement(repeated, "법령ID").text = "001234"
    ET.SubElement(repeated, "조문번호").text = "84"
    ET.SubElement(repeated, "조문가지번호").text = "0"
    ET.SubElement(repeated, "조문제목").text = "용도지역안에서의 건폐율"

    direct, admin = _keyword_root(
        "행정규칙", "행정규칙명", "개발제한구역 관리지침",
        "행정규칙ID", "009999", "발령기관명", "국토교통부",
    )
    ET.SubElement(admin, "조문번호").text = "2"
    ET.SubElement(admin, "조문가지번호").text = "0"
    ET.SubElement(admin, "조문제목").text = "관리의 원칙"
    # 별표ㆍ서식은 본문을 열 일련번호가 없어 통합 목록에서 뺀다.
    annex = ET.SubElement(direct, "법령별표서식", {"id": "3"})
    ET.SubElement(annex, "법령명").text = "제외 대상 별표"
    ET.SubElement(annex, "법령ID").text = "007777"

    roots = [(AI_RELATED_AGENCY, related), (AI_SEARCH_AGENCY, direct)]
    rows, total = window.resource_tab._parse_keyword_rows(roots, [])

    assert total == 3
    # 어느 API에서 왔든 통합 목록에서는 "AI추천" 한 구분으로 묶는다.
    assert [row["label"] for row in rows] == ["AI추천", "AI추천", "AI추천"]
    assert all(row["ai_recommended"] for row in rows)
    assert [row["id"] for row in rows] == ["001234", "001234", "009999"]
    assert [row["display_name"] for row in rows[:2]] == [
        "제77조 용도지역의 건폐율",
        "제84조 용도지역안에서의 건폐율",
    ]
    assert [row["keyword_jo"] for row in rows[:2]] == ["007700", "008400"]
    assert [row["related"] for row in rows[:2]] == [
        "국토의 계획 및 이용에 관한 법률",
        "국토의 계획 및 이용에 관한 법률",
    ]
    # 본문 조회는 기존 법령ㆍ행정규칙 경로를 그대로 탄다.
    assert [row["target"] for row in rows] == ["law", "law", "admrul"]
    assert not rows[0]["resolve_admrul_id"]
    assert rows[2]["resolve_admrul_id"]
    assert rows[2]["keyword_jo"] == "000200"
    assert rows[2]["jo_code"] == "000200"
    assert rows[0]["effective"] == "2024.07.01"
    assert not any(row["id"] == "007777" for row in rows)


def test_agency_scope_search_keeps_duplicate_target_responses(monkeypatch) -> None:
    calls = []

    def fake_search_list(oc, **kwargs):
        calls.append((oc, kwargs))
        return ET.Element("결과", {"scope": str(kwargs["search"])})

    monkeypatch.setattr(api_module, "search_list", fake_search_list)

    roots, errors = api_module.search_agency_scopes(
        "test-key",
        ((AI_RELATED_AGENCY, 0), (AI_RELATED_AGENCY, 1)),
        query="공간재구조화",
    )

    assert errors == []
    assert [root.get("scope") for _agency, root in roots] == ["0", "1"]
    assert {call[1]["search"] for call in calls} == {0, 1}
    assert all(call[1]["target"] == "aiRltLs" for call in calls)


def test_integrated_search_requests_both_related_article_scopes(
    qt_app, monkeypatch
) -> None:
    resource_calls = []
    keyword_calls = []

    def fake_resource(oc, target, query, **kwargs):
        resource_calls.append((oc, target, query, kwargs))
        return {}

    law_root, _law = _keyword_root(
        "법령", "법령명", "도시개발법", "법령ID", "001", "소관부처명",
        "국토교통부",
    )
    admin_root, _admin = _keyword_root(
        "행정규칙", "행정규칙명", "공간재구조화계획 수립 등에 관한 지침",
        "행정규칙ID", "46796", "발령기관명", "국토교통부",
    )

    def fake_keyword(oc, requests, **kwargs):
        keyword_calls.append((oc, tuple(requests), kwargs))
        return [
            (AI_RELATED_AGENCY, law_root),
            (AI_RELATED_AGENCY, admin_root),
        ], []

    monkeypatch.setattr(search_worker_module, "search_resource", fake_resource)
    monkeypatch.setattr(
        search_worker_module, "search_agency_scopes", fake_keyword
    )
    succeeded = []
    worker = ResourceApiWorker(
        "resource_search",
        oc="test-key",
        target=RESOURCE_ALL_TARGET,
        query="공간재구조화",
    )
    worker.succeeded.connect(
        lambda operation, result: succeeded.append((operation, result))
    )

    worker.run()

    assert keyword_calls == [
        (
            "test-key",
            (
                (AI_RELATED_AGENCY, 0),
                (AI_RELATED_AGENCY, 1),
                (AI_SEARCH_AGENCY, 1),
            ),
            {"query": "공간재구조화", "display": 100},
        )
    ]
    assert len(resource_calls) > 1
    payload = succeeded[0][1]
    assert [agency for agency, _root in payload["keyword_roots"]] == [
        AI_RELATED_AGENCY,
        AI_RELATED_AGENCY,
    ]


def test_integrated_keyword_admin_rule_resolves_serial_before_detail(
    qt_app, monkeypatch
) -> None:
    name = "공간재구조화계획 수립 등에 관한 지침"
    search_calls = []
    detail_calls = []

    def fake_search(oc, target, query, **kwargs):
        search_calls.append((oc, target, query, kwargs))
        return {
            "AdmRulSearch": {
                "admrul": [
                    {
                        "행정규칙명": name,
                        "행정규칙ID": "11111",
                        "행정규칙일련번호": "900001",
                    },
                    {
                        "행정규칙명": name,
                        "행정규칙ID": "46796",
                        "행정규칙일련번호": "900002",
                        "발령일자": "20230101",
                        "발령번호": "2023-1",
                    },
                    {
                        "행정규칙명": name,
                        "행정규칙ID": "46796",
                        "행정규칙일련번호": "900003",
                        "발령일자": "20240731",
                        "발령번호": "제2024-410호",
                    },
                ]
            }
        }

    payload = {"AdmRulService": {"조문내용": "제2조(일반원칙) 내용"}}

    def fake_detail(oc, target, item_id, *, id_param="ID"):
        detail_calls.append((oc, target, item_id, id_param))
        return payload

    monkeypatch.setattr(search_worker_module, "search_resource", fake_search)
    monkeypatch.setattr(search_worker_module, "get_resource_detail", fake_detail)
    succeeded = []
    failed = []
    worker = ResourceApiWorker(
        "resource_detail",
        oc="test-key",
        target="admrul",
        item_id="46796",
        detail_target="admrul",
        law_name=name,
        resolve_admrul_id=True,
        issue_date="2024.07.31",
        issue_number="2024-410",
    )
    worker.succeeded.connect(
        lambda operation, result: succeeded.append((operation, result))
    )
    worker.failed.connect(lambda operation, error: failed.append((operation, error)))

    worker.run()

    assert search_calls == [
        ("test-key", "admrul", name, {"display": 100})
    ]
    assert detail_calls == [("test-key", "admrul", "900003", "ID")]
    assert succeeded == [("resource_detail", payload)]
    assert failed == []


def test_admin_rule_name_matches_middle_dot_and_araea_dot(monkeypatch) -> None:
    monkeypatch.setattr(
        search_worker_module,
        "search_resource",
        lambda *_args, **_kwargs: {
            "AdmRulSearch": {
                "admrul": {
                    "행정규칙명": "훈령ㆍ예규 등의 발령 및 관리에 관한 규정",
                    "행정규칙일련번호": "900004",
                }
            }
        },
    )

    item_id = search_worker_module.administrative_rule_detail_id(
        "test-key", "훈령·예규 등의 발령 및 관리에 관한 규정"
    )

    assert item_id == "900004"


def test_named_law_reference_falls_back_to_admin_rule(
    qt_app, monkeypatch
) -> None:
    name = "훈령·예규 등의 발령 및 관리에 관한 규정"
    payload = {
        "AdmRulService": {
            "행정규칙기본정보": {"행정규칙명": name},
            "조문내용": "제1조(목적) 이 규정은 발령 및 관리에 관한 사항을 정한다.",
        }
    }
    detail_calls = []
    attached = []

    monkeypatch.setattr(
        search_worker_module,
        "named_law_reference_row",
        lambda _oc, _name: (_ for _ in ()).throw(ValueError("법령 없음")),
    )
    monkeypatch.setattr(
        search_worker_module,
        "administrative_rule_detail_id",
        lambda oc, rule_name: (
            "2200000078285"
            if (oc, rule_name) == ("test-key", name)
            else ""
        ),
    )

    def fake_detail(oc, target, item_id, *, id_param="ID"):
        detail_calls.append((oc, target, item_id, id_param))
        return payload

    monkeypatch.setattr(search_worker_module, "get_resource_detail", fake_detail)
    monkeypatch.setattr(
        search_worker_module,
        "attach_admin_rule_images",
        lambda result: attached.append(result),
    )
    succeeded = []
    failed = []
    worker = ResourceApiWorker(
        "law_reference_detail",
        oc="test-key",
        target="law",
        law_name=name,
    )
    worker.succeeded.connect(
        lambda operation, result: succeeded.append((operation, result))
    )
    worker.failed.connect(lambda operation, error: failed.append((operation, error)))

    worker.run()

    assert detail_calls == [
        ("test-key", "admrul", "2200000078285", "ID")
    ]
    assert attached == [payload]
    assert failed == []
    assert succeeded[0][0] == "law_reference_detail"
    result = succeeded[0][1]
    assert result["mode"] == "admin_rule"
    assert result["row"]["target"] == "admrul"
    assert result["row"]["name"] == name
    assert result["payload"] is payload


def test_integrated_keyword_admin_rule_shows_only_selected_article(window) -> None:
    direct, admin = _keyword_root(
        "행정규칙", "행정규칙명", "공간재구조화계획 수립 등에 관한 지침",
        "행정규칙ID", "46796", "발령기관명", "국토교통부",
    )
    ET.SubElement(admin, "조문번호").text = "2"
    ET.SubElement(admin, "조문가지번호").text = "0"
    ET.SubElement(admin, "조문제목").text = "공간재구조화계획 수립의 일반원칙"
    rows, _total = window.resource_tab._parse_keyword_rows(
        [(AI_RELATED_AGENCY, direct)], []
    )
    row = rows[0]
    window.resource_tab.pending_row = row
    payload = {
        "AdmRulService": {
            "행정규칙기본정보": {
                "행정규칙명": "공간재구조화계획 수립 등에 관한 지침"
            },
            "조문내용": (
                "제1조(목적) 첫 조문 내용"
                "제2조(공간재구조화계획 수립의 일반원칙) 선택한 조문 내용"
                "제3조(계획의 내용) 다음 조문 내용"
            ),
            "부칙": "부칙 내용",
        }
    }

    _title, metadata, sections = window.resource_tab._parse_admrul_detail(
        payload
    )

    assert ("행정규칙ID", "46796") in metadata
    assert sections == [
        (
            "조문",
            "제2조(공간재구조화계획 수립의 일반원칙) 선택한 조문 내용",
        )
    ]


def test_integrated_admin_rule_articles_use_distinct_snapshot_keys(window) -> None:
    first = {
        "target": "admrul",
        "id": "46796",
        "name": "공간재구조화계획 수립 등에 관한 지침",
        "jo_code": "000200",
    }
    second = {**first, "jo_code": "000300"}

    assert window.resource_tab.law_cache.key_for_row(first) != (
        window.resource_tab.law_cache.key_for_row(second)
    )


def test_integrated_search_keeps_keyword_hits_already_found_by_list_search(
    window,
) -> None:
    related, node = _keyword_root(
        "법령", "법령명", "국토의 계획 및 이용에 관한 법률",
        "법령ID", "001234", "소관부처명", "국토교통부",
    )
    ET.SubElement(node, "조문번호").text = "77"
    ET.SubElement(node, "조문제목").text = "용도지역의 건폐율"
    already_found = [{"target": "law", "id": "001234", "name": "목록검색 결과"}]

    rows, total = window.resource_tab._parse_keyword_rows(
        [(AI_RELATED_AGENCY, related)], already_found
    )

    assert total == 1
    assert rows[0]["display_name"] == "제77조 용도지역의 건폐율"
    assert rows[0]["name"] == "국토의 계획 및 이용에 관한 법률"


def test_missing_keyword_payload_is_not_an_error(window) -> None:
    assert window.resource_tab._parse_keyword_rows(None, []) == ([], 0)
    assert window.resource_tab._parse_keyword_rows([], []) == ([], 0)
