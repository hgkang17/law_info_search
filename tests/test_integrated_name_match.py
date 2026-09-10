"""통합검색에서 이름을 그대로 적어 찾은 자료가 맨 위로 오는지 검증."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ui.tabs.resource_search import (
    ResourceSearchTab,
    search_name_key,
    search_name_family_rank,
    search_name_query_coverage,
    search_name_similarity,
)


def test_same_name_scores_full_match() -> None:
    assert (
        search_name_similarity("이천시 도시계획 조례", "이천시 도시계획 조례")
        == 1.0
    )
    # 공백ㆍ가운뎃점만 다른 이름도 같은 것으로 본다.
    assert search_name_key("이천시 도시ㆍ군계획 조례") == "이천시도시군계획조례"


def test_matched_name_passes_the_promotion_threshold() -> None:
    ratio = ResourceSearchTab.INTEGRATED_NAME_MATCH_RATIO
    assert (
        search_name_similarity(
            "이천시 도시계획 조례", "이천시 도시ㆍ군계획 조례"
        )
        >= ratio
    )


def test_parenthetical_reference_is_ignored_for_name_match() -> None:
    ratio = ResourceSearchTab.INTEGRATED_NAME_MATCH_RATIO
    assert search_name_key(
        "용도별 건축물의 종류(제3조의5 관련)"
    ) == "용도별건축물의종류"
    assert (
        search_name_similarity(
            "용도별 건축물의 종류",
            "용도별 건축물의 종류(제3조의5 관련)",
        )
        >= ratio
    )


def test_annex_head_label_and_parenthetical_reference_are_both_ignored() -> None:
    ratio = ResourceSearchTab.INTEGRATED_NAME_MATCH_RATIO
    result_name = "[별표 1] 용도별 건축물의 종류(제3조의5 관련)"

    assert search_name_key(result_name) == "용도별건축물의종류"
    assert search_name_similarity("용도별 건축물의 종류", result_name) >= ratio


def test_partial_annex_title_uses_query_coverage() -> None:
    assert search_name_query_coverage(
        "용도별 건축물",
        "용도별 건축물의 종류(제3조의5 관련)",
    ) == 1.0


def test_known_or_nearly_matching_short_name_is_promoted() -> None:
    ratio = ResourceSearchTab.INTEGRATED_NAME_MATCH_RATIO
    assert (
        search_name_similarity(
            "국토계획법", "국토의 계획 및 이용에 관한 법률"
        )
        >= ratio
    )
    assert (
        search_name_similarity(
            "국토계획벚",
            "국토의 계획 및 이용에 관한 법률",
            "국토계획법",
        )
        >= ratio
    )
    # 상위법 이름이 하위법령에 들어간 것만으로는 약칭 일치가 아니다.
    assert search_name_similarity("건축법", "건축법 시행령") < ratio


def test_unrelated_name_stays_below_the_threshold() -> None:
    ratio = ResourceSearchTab.INTEGRATED_NAME_MATCH_RATIO
    assert (
        search_name_similarity(
            "이천시 도시계획 조례", "국토의 계획 및 이용에 관한 법률"
        )
        < ratio
    )
    # 하위법령은 상위법 이름을 그대로 품지만 맨 위로 올리지는 않는다.
    assert search_name_similarity("건축법", "건축법 시행령") < ratio


def test_exact_resource_precedes_same_named_ai_article() -> None:
    """농지법 본체와 농지법 추천 조문이 모두 100%여도 본체가 먼저다."""
    ratio = ResourceSearchTab.INTEGRATED_NAME_MATCH_RATIO
    rows = [
        {"target": "law", "name": "농지법", "ai_recommended": True},
        {"target": "law", "name": "농지법"},
    ]

    def key(row):
        score = search_name_similarity("농지법", row["name"])
        matched = score >= ratio
        return (
            0 if matched else 1,
            1 if matched and row.get("ai_recommended") else 0,
            -score if matched else 0.0,
            ResourceSearchTab._integrated_group_order(row),
        )

    rows.sort(key=key)
    assert not rows[0].get("ai_recommended")


def test_exact_annex_name_gets_a_tier_ahead_of_ai_recommendation() -> None:
    query = "용도별 건축물의 종류(제3조의5 관련)"
    annex = {
        "target": "licbyl",
        "name": "용도별 건축물의 종류(제3조의5 관련)",
    }
    ai = {
        "target": "law",
        "name": "건축법 시행령",
        "ai_recommended": True,
    }

    def key(row):
        score = search_name_similarity(query, row["name"])
        matched = score >= ResourceSearchTab.INTEGRATED_NAME_MATCH_RATIO
        exact = search_name_key(query) == search_name_key(row["name"])
        return (
            0 if exact and not row.get("ai_recommended") else 1,
            0 if matched else 1,
            1 if matched and row.get("ai_recommended") else 0,
            -score if matched else 0.0,
            ResourceSearchTab._integrated_group_order(row),
        )

    rows = [ai, annex]
    rows.sort(key=key)
    assert rows[0] is annex


def test_query_coverage_ignores_a_name_that_merely_cites_the_law() -> None:
    """짧은 법령명이 긴 별표명 안에 들어 있기만 한 것은 이름 일치가 아니다.

    ``농지법``으로 찾을 때 그 법을 인용하는 행정규칙 별표
    (``「농지법」 제23조제1항9호 및 …``)까지 최상단 묶음으로 올라왔다.
    """
    assert (
        search_name_query_coverage(
            "농지법",
            "「농지법」 제23조제1항9호 및 같은 법 시행령 제24조제3항에 따라 "
            "임대차가 가능해지는 농지",
        )
        == 0.0
    )
    # 이름 앞부분만 적어 찾는 원래 쓰임새는 그대로 둔다.
    assert (
        search_name_query_coverage(
            "용도별 건축물", "용도별 건축물의 종류(제3조의5 관련)"
        )
        == 1.0
    )


def test_law_family_is_promoted_as_one_set() -> None:
    """법령명을 찾으면 그 법ㆍ시행령ㆍ시행규칙이 한 묶음으로 맨 위에 선다."""
    assert search_name_family_rank("농지법", "농지법") == 0
    assert search_name_family_rank("농지법", "농지법 시행령") == 1
    assert search_name_family_rank("농지법", "농지법 시행규칙") == 2
    # 상위법 이름을 품기만 한 다른 자료는 묶음에 들지 않는다.
    assert (
        search_name_family_rank(
            "농지법", "「농지법」 제23조제1항9호 및 같은 법 시행령 제24조제3항"
        )
        is None
    )
    assert search_name_family_rank("농지법", "농지법 시행령 시행규칙") is None


def test_law_family_sorts_before_ai_recommendations() -> None:
    rows = [
        {"target": "law", "name": "농지법", "ai_recommended": True},
        {"target": "law", "name": "농지법 시행규칙"},
        {"target": "law", "name": "농지법"},
        {"target": "law", "name": "농지법 시행령"},
    ]

    def key(row):
        rank = search_name_family_rank("농지법", row["name"])
        is_family = rank is not None and not row.get("ai_recommended")
        return (0 if is_family else 1, rank if is_family else 0)

    rows.sort(key=key)
    assert [row["name"] for row in rows[:3]] == [
        "농지법",
        "농지법 시행령",
        "농지법 시행규칙",
    ]
    assert rows[3].get("ai_recommended")


def test_subordinate_law_search_keeps_its_own_row_first() -> None:
    """하위법령으로 찾으면 그 줄이 0번, 나머지 한 벌이 법→령→규칙 차례."""
    assert (
        search_name_family_rank(
            "국토계획법 시행규칙",
            "국토의 계획 및 이용에 관한 법률 시행규칙",
            "국토계획법 시행규칙",
        )
        == 0
    )
    assert (
        search_name_family_rank(
            "국토계획법 시행규칙",
            "국토의 계획 및 이용에 관한 법률",
            "국토계획법",
        )
        == 1
    )
    assert (
        search_name_family_rank(
            "국토계획법 시행규칙",
            "국토의 계획 및 이용에 관한 법률 시행령",
            "국토계획법 시행령",
        )
        == 2
    )
    # 시행령으로 찾아도 마찬가지로 자기 줄이 먼저다.
    assert search_name_family_rank("농지법 시행령", "농지법 시행령") == 0
    assert search_name_family_rank("농지법 시행령", "농지법") == 1
    assert search_name_family_rank("농지법 시행령", "농지법 시행규칙") == 2
    # 이름이 비슷할 뿐인 다른 법령은 한 벌에 들지 않는다.
    assert search_name_family_rank("농지법 시행령", "농어촌정비법") is None


def _law_list_payload(*names: str) -> dict:
    return {
        "LawSearch": {
            "totalCnt": len(names),
            "law": [
                {
                    # 같은 법령은 어느 응답에서 와도 같은 ID여야 겹침을
                    # 걸러 낼 수 있다.
                    "법령ID": f"{abs(hash(name)) % 1000000:06d}",
                    "법령명한글": name,
                    "소관부처명": "국토교통부",
                    "공포일자": "20250101",
                    "공포번호": "1",
                    "시행일자": "20250101",
                    "법령구분명": "법률",
                }
                for name in names
            ],
        }
    }


def test_law_family_rows_fill_in_the_missing_members(tmp_path) -> None:
    """시행규칙으로 찾아도 모법ㆍ시행령이 목록에 함께 오른다."""
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from storage.cache import LawDocumentCache
    from storage.recent import RecentSearchManager

    QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "family.ini"), QSettings.Format.IniFormat)
    tab = ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    tab.query_input.setText("농지법 시행규칙")
    existing, _total = tab._parse_resource_rows(
        _law_list_payload("농지법 시행규칙"), "law"
    )
    family = tab._law_family_rows(
        _law_list_payload(
            "농지법", "농지법 시행령", "농지법 시행규칙", "농어촌정비법"
        ),
        existing,
    )

    # 이미 목록에 있는 시행규칙은 다시 넣지 않고, 무관한 법령도 거른다.
    assert [row["name"] for row in family] == ["농지법", "농지법 시행령"]


def test_law_family_rows_ignore_a_plain_law_name_search(tmp_path) -> None:
    """모법 이름으로 찾은 검색에는 덧붙일 것이 없다(응답도 없다)."""
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from storage.cache import LawDocumentCache
    from storage.recent import RecentSearchManager

    QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "family2.ini"), QSettings.Format.IniFormat)
    tab = ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    tab.query_input.setText("농지법")
    assert tab._law_family_rows(None, []) == []
