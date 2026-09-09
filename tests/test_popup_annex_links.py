"""팝업ㆍ3단비교 조문 안의 별표 인용에도 링크를 건다.

본문 화면은 그려 놓은 문서 위에서 자리를 찾아 링크를 걸지만
(`_apply_inline_annex_links`), 팝업과 3단비교 표는 HTML 문자열을 그대로
넣어서 그 단계가 없었다. 물환경보전법 제2조의 환경부령 링크로 연 팝업에
``별표 1에 따른다``가 그냥 글씨로 남아 있었다.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ui.tabs.resource_search import ResourceSearchTab


def _linked(text: str, *, related_law: str = "물환경보전법 시행규칙") -> str:
    masked, tokens = ResourceSearchTab._mask_annex_mentions(
        text, related_law=related_law, category="licbyl"
    )
    return ResourceSearchTab._restore_annex_mentions(masked, tokens)


def test_annex_reference_becomes_a_link() -> None:
    html = _linked("법 제2조제8호에 따른 특정수질유해물질은 별표 1과 같다.")

    assert 'href="annexref://open?name=' in html
    assert "%EB%B3%84%ED%91%9C%201" in html  # 별표 1
    assert "related=" in html


def test_form_reference_becomes_a_link() -> None:
    html = _linked("신청서는 별지 제3호서식에 따른다.")

    assert 'href="annexref://open?name=' in html
    assert "별지 제3호서식" in html


def test_branch_number_keeps_its_label() -> None:
    masked, tokens = ResourceSearchTab._mask_annex_mentions(
        "별표 1의2에 따른 기준", related_law="법", category="licbyl"
    )

    assert [label for _mention, _href, label in tokens.values()] == [
        "별표 1의2"
    ]


def test_annex_list_line_is_left_alone() -> None:
    """``[별표 1] 이름``은 별표 목록 줄이라 제 링크를 따로 갖는다."""
    text = "[별표 1] 특정수질유해물질"

    masked, tokens = ResourceSearchTab._mask_annex_mentions(
        text, related_law="법", category="licbyl"
    )

    assert masked == text
    assert tokens == {}


def test_no_related_law_means_no_link() -> None:
    """어느 법령의 별표인지 모르면 걸지 않는다."""
    masked, tokens = ResourceSearchTab._mask_annex_mentions(
        "별표 1에 따른다", related_law="", category="licbyl"
    )

    assert masked == "별표 1에 따른다"
    assert tokens == {}
