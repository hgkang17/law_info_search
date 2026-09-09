"""법령 목 안에 붙어 온 세부항목이 줄로 나뉘는지 검증."""

from __future__ import annotations

from utils.parsing import (
    split_inline_korean_closing_paren_items,
    split_inline_law_subitems,
)


SOURCE = (
    "    가. 단위 도시ㆍ군계획시설부지 면적의 5퍼센트 미만의 변경인 경우. "
    "다만, 다음의 어느 하나에 해당하는 시설은 해당 요건을 충족하는 경우만 "
    "해당한다.      1) 도로: 시작지점이 변경되지 않는 경우      "
    "2) 공원 및 녹지: 다음의 어느 하나에 해당하는 경우        "
    "가) 면적이 증가되는 경우        나) 변경되는 면적의 합계가 "
    "1만제곱미터 미만인 경우"
)


def test_number_and_korean_subitems_each_get_their_own_line() -> None:
    """법령 API는 목 하나를 통째로 한 문자열에 담아 준다.

    줄이 나뉘어 있지 않으면 본문 변환이 줄머리 표지를 알아보지 못해
    세부항목이 한 문단으로 붙어 보인다(국토계획법 제30조제2항에서 연
    시행령 제25조).
    """
    lines = split_inline_law_subitems(SOURCE).splitlines()

    assert lines[0].startswith("가. 단위 도시")
    assert lines[1].startswith("1) 도로:")
    assert lines[2].startswith("2) 공원 및 녹지:")
    assert lines[3].startswith("가) 면적이 증가되는")
    assert lines[4].startswith("나) 변경되는 면적의")


def test_single_or_out_of_order_markers_are_left_alone() -> None:
    """차례대로 이어지는 표지만 자른다. 문장 속 인용은 건드리지 않는다."""
    for text in (
        "제3조제1항제2호나) 목의 규정",
        "단독으로 2) 만 있는 문장",
        "※ (1)과 (2)에 따른 경우",
        "가) 하나만 있는 경우",
        "별표 1 제2호가목1)에 따른다",
    ):
        assert split_inline_law_subitems(text).splitlines() == [text]


def test_korean_marker_split_needs_two_consecutive_markers() -> None:
    assert split_inline_korean_closing_paren_items("가) 첫째 나) 둘째") == [
        "가) 첫째",
        "나) 둘째",
    ]
    # 차례가 건너뛰면 자르지 않는다.
    assert split_inline_korean_closing_paren_items("가) 첫째 다) 셋째") == [
        "가) 첫째 다) 셋째"
    ]
