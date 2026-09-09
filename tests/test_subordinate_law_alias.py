"""약칭 뒤에 붙은 ``시행령``ㆍ``시행규칙``도 정식 제명으로 푼다.

메인 화면에서 ``국토계획법 25조``는 조문을 바로 세워 주는데
``국토계획법 시행령 25조``는 목록 API가 그 이름을 못 찾아 조문 줄이
아예 서지 않았다. 약칭표에는 모법만 있기 때문이다.
"""

from llm.law_aliases import resolve_law_alias
from utils.parsing import split_article_query


def test_alias_with_decree_suffix_resolves_to_full_name() -> None:
    resolved = resolve_law_alias("국토계획법 시행령")

    assert resolved.canonical == "국토의 계획 및 이용에 관한 법률 시행령"


def test_alias_with_rule_suffix_resolves_to_full_name() -> None:
    resolved = resolve_law_alias("국토계획법 시행규칙")

    assert resolved.canonical == "국토의 계획 및 이용에 관한 법률 시행규칙"


def test_full_name_with_suffix_is_left_alone() -> None:
    """정식 제명은 약칭표를 거치지 않고 그대로 쓴다."""
    resolved = resolve_law_alias("건축법 시행령")

    assert resolved.canonical == "건축법 시행령"


def test_unknown_name_is_not_invented() -> None:
    """모르는 이름에 시행령을 붙여 없는 법을 만들지 않는다."""
    resolved = resolve_law_alias("있을 리 없는 이름 시행령")

    assert resolved.canonical == "있을 리 없는 이름 시행령"


def test_article_query_keeps_the_subordinate_law_name() -> None:
    """검색어 분리도 ``시행령``을 법령명 쪽에 남긴다."""
    request = split_article_query("국토계획법 시행령 25조")

    assert request is not None
    assert request["law_name"] == "국토계획법 시행령"
    assert request["jo"] == "002500"
    assert (
        resolve_law_alias(request["law_name"]).canonical
        == "국토의 계획 및 이용에 관한 법률 시행령"
    )
