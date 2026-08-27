"""약칭 확장과 무관 결과 차단."""

from llm.base import progress_law_name
from llm.law_aliases import (
    display_alias,
    expand_search_queries,
    has_related_hit,
    resolve_law_alias,
    resolved_law_matches,
    score_law_relevance,
)


def test_resolve_국토계획법() -> None:
    resolved = resolve_law_alias("국토계획법")
    assert resolved.canonical == "국토의 계획 및 이용에 관한 법률"
    assert resolved.matched_alias == "국토계획법"


def test_expand_includes_research_alias() -> None:
    queries = expand_search_queries("도시관리계획")
    assert "국토의 계획 및 이용에 관한 법률" in queries
    assert "도시·군관리계획수립지침" in queries


def test_expand_embedded_alias() -> None:
    queries = expand_search_queries("화관법 시행령")
    assert any("화학물질관리법" in item for item in queries)


def test_related_hit_accepts_canonical_name() -> None:
    assert has_related_hit(
        "국토계획법",
        [("국토의 계획 및 이용에 관한 법률", "국토계획법")],
    )


def test_related_hit_rejects_unrelated_first_result() -> None:
    assert not has_related_hit(
        "인공지능법",
        [("119긴급신고의 관리 및 운영에 관한 법률 시행규칙", "")],
    )


def test_display_alias_uses_the_usual_short_name() -> None:
    assert display_alias("국토의 계획 및 이용에 관한 법률") == "국토계획법"
    assert display_alias("산업입지 및 개발에 관한 법률") == "산업입지법"
    assert display_alias("산업입지 및 개발에 관한 법률 시행령") == "산업입지법 시행령"
    assert display_alias("건축법") == ""


def test_progress_line_prefers_official_short_name() -> None:
    assert (
        progress_law_name("산업입지 및 개발에 관한 법률", "산업입지법")
        == "산업입지법"
    )
    assert (
        progress_law_name("산업입지 및 개발에 관한 법률 시행령", "산업입지법")
        == "산업입지법 시행령"
    )
    assert (
        progress_law_name("국토의 계획 및 이용에 관한 법률")
        == "국토계획법"
    )


def test_score_prefers_exact_law_name() -> None:
    assert score_law_relevance("민법", "민법") > score_law_relevance("난민법", "민법")


def test_resolved_law_matches_rejects_like_substring() -> None:
    assert resolved_law_matches("민법", "민법")
    assert not resolved_law_matches("민법", "난민법")
    assert resolved_law_matches("주차장법", "주차장법")
    assert resolved_law_matches("국토계획법", "국토의 계획 및 이용에 관한 법률")
