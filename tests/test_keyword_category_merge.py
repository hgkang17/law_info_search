"""연관검색ㆍ직접검색을 법령검색 탭 카테고리로 옮긴 뒤의 회귀 검증."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from models.law import AI_RELATED_AGENCY, AI_SEARCH_AGENCY
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

    # 통합검색 바로 옆에 한 쌍으로 붙는다.
    assert targets[:3] == ["__all__", "ai_related", "ai_search"]
    assert "law" in targets and "admrul" in targets


def test_keyword_search_left_the_main_menu(window) -> None:
    labels = [
        window.navigation.item(index).text().replace("\n", " ")
        for index in range(window.navigation.count())
    ]

    assert not any("키워드" in label for label in labels)
    # 페이지 번호와 메뉴 줄 번호는 1:1로 묶여 있어 함께 당겨져야 한다.
    assert window.navigation.count() == window.tabs.count() - 2


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


def test_detail_button_is_only_shown_for_integrated_search(window) -> None:
    resource = window.resource_tab
    resource.select_category("__all__")
    assert not resource.detail_button.isHidden()
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
    assert keyword.description_row.isHidden()
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
    assert [row["label"] for row in rows] == [
        "연관검색", "연관검색", "직접검색"
    ]
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
