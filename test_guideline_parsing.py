from molit_cgm_expc_qt import (
    insert_admin_clause_breaks,
    json_text,
    merge_circled_reference_lines,
    merge_marker_reference_fragments,
    split_paren_item_after_sentence_end,
)


def test_admin_inline_circled_references_stay_in_the_same_item() -> None:
    source = (
        "⑦ 상기 ① 및 ②의 규정에 의한 변경인 경우"
        "⑧ 다음 항목"
        "⑩ ①ㆍ②ㆍ⑤ㆍ⑥ㆍ⑧ 및 ⑨의 규정에 의한 변경인 경우"
    )

    assert insert_admin_clause_breaks(source).splitlines() == [
        "⑦ 상기 ① 및 ②의 규정에 의한 변경인 경우",
        "⑧ 다음 항목",
        "⑩ ①ㆍ②ㆍ⑤ㆍ⑥ㆍ⑧ 및 ⑨의 규정에 의한 변경인 경우",
    ]


def test_legacy_saved_guideline_reference_lines_are_repaired() -> None:
    legacy_lines = [
        "⑦ 상기",
        "① 및",
        "②의 규정에 의한 변경인 경우",
        "⑧ 다음 항목",
        "⑩",
        "①ㆍ",
        "②ㆍ",
        "⑤ㆍ",
        "⑥ㆍ",
        "⑧ 및",
        "⑨의 규정에 의한 변경인 경우",
    ]

    repaired = merge_circled_reference_lines(
        merge_marker_reference_fragments(legacy_lines)
    )

    assert repaired == [
        "⑦ 상기 ① 및 ②의 규정에 의한 변경인 경우",
        "⑧ 다음 항목",
        "⑩①ㆍ②ㆍ⑤ㆍ⑥ㆍ⑧ 및 ⑨의 규정에 의한 변경인 경우",
    ]


def test_angle_number_markers_are_not_removed_as_html_tags() -> None:
    assert json_text("<16> 장애인<br><17> 에너지<br><18> 생물") == (
        "⑯ 장애인\n⑰ 에너지\n⑱ 생물"
    )


def test_parent_item_recovery_is_limited_to_guidelines() -> None:
    source = "⑮ 개발제한구역 안에 설치하는 기반시설(4) 재해취약성분석"

    assert split_paren_item_after_sentence_end(
        source, administrative_rule=True
    ) == [
        "⑮ 개발제한구역 안에 설치하는 기반시설",
        "(4) 재해취약성분석",
    ]
    assert split_paren_item_after_sentence_end(source) == [source]
