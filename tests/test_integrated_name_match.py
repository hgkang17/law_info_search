"""통합검색에서 이름을 그대로 적어 찾은 자료가 맨 위로 오는지 검증."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ui.tabs.resource_search import (
    ResourceSearchTab,
    search_name_key,
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
