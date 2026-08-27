from utils.parsing import (
    search_terms,
    whitespace_flexible_pattern,
    whitespace_insensitive_contains,
)


def test_search_ignores_spacing_on_both_sides() -> None:
    assert whitespace_insensitive_contains(
        "설치할 수 있는 건축물", "설치할수있는건축물"
    )
    assert whitespace_insensitive_contains(
        "설치할수있는건축물", "설치할 수 있는 건축물"
    )
    assert whitespace_flexible_pattern("건축물") == r"건\s*축\s*물"


def test_city_management_plan_adds_compound_highlight_terms() -> None:
    terms = search_terms("도시관리계획")

    assert terms[0] == "도시관리계획"
    assert "도시" in terms
    assert "관리계획" in terms


def test_unrelated_query_is_not_split() -> None:
    assert search_terms("개발제한구역") == ("개발제한구역",)
