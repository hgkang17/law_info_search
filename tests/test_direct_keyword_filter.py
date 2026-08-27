from ui.tabs.ai_search import AiLawSearchTab


def test_direct_search_excludes_partial_api_matches() -> None:
    unrelated = {
        "name": "대외무역법",
        "provision": "제5조 무역에 관한 제한 등 특별 조치",
        "content": "물품의 수출과 수입을 제한하거나 금지할 수 있다.",
    }
    related = {
        "name": "개발제한구역의 지정 및 관리에 관한 특별조치법",
        "provision": "제12조 행위제한",
        "content": "개발제한구역법에 따른 행위제한",
    }

    assert not AiLawSearchTab._direct_row_matches_query(
        unrelated, "개발제한구역법"
    )
    assert AiLawSearchTab._direct_row_matches_query(
        related, "개발제한구역법"
    )
