"""통합검색에서 이름을 그대로 적어 찾은 자료가 맨 위로 오는지 검증."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ui.tabs.resource_search import (
    ResourceSearchTab,
    search_name_key,
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
