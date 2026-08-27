"""문장 중간에서 끊긴 ``다.)`` 꼬리가 목으로 잘못 그려지지 않는지 검증."""

import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from utils.formatting import body_to_html
from utils.parsing import merge_sentence_tail_item_lines


def _plain(html: str) -> list[str]:
    """렌더된 HTML을 줄 단위 평문으로 되돌린다."""
    text = html.replace("<br>", "\n").replace("</div>", "\n")
    text = re.sub(r"<[^>]+>", "", text)
    text = (
        text.replace("&quot;", '"')
        .replace("&amp;", "&")
        .replace("&nbsp;", " ")
    )
    return [line.strip() for line in text.split("\n") if line.strip()]


# 경관계획수립지침 1-5-1. 원문. API가 ``사용할 수 있`` 뒤에서 줄을 끊는다.
GUIDELINE_SOURCE = (
    "② 시ㆍ군 경관계획은 다음과 같은 주체가 수립하거나 수립할 수 있다.\n"
    "가. 의무수립주체 : 경관법 제7조제1항에 따른 특ㆍ광역시장, "
    "인구 10만명 초과의 시장ㆍ군수(광역시 관할구역에 있는 군은 제외한다)\n"
    "나. 임의수립주체 : 경관법 제7조제2항에 따른 인구 10만명 이하의 "
    '시ㆍ군의 시장ㆍ군수, 광역시의 군수(이하 "구청장등"이라 한다) 또는 '
    '경제자유구역청장 (경관계획은 "구 경관계획"이라는 명칭을 사용할 수 있\n'
    "다.)\n"
    "(3) 특정경관계획"
)


def test_broken_sentence_tail_returns_to_previous_line() -> None:
    QApplication.instance() or QApplication([])

    lines = _plain(body_to_html(GUIDELINE_SOURCE, administrative_rule=True))

    assert not any(line.startswith("다.") for line in lines)
    tail_line = next(line for line in lines if "임의수립주체" in line)
    assert tail_line.endswith("사용할 수 있다.)")


def test_real_item_marker_still_becomes_its_own_item() -> None:
    """뒤에 본문이 있는 ``다.``는 그대로 목으로 남아야 한다."""
    QApplication.instance() or QApplication([])
    source = (
        "가. 의무수립주체 : 특ㆍ광역시장\n"
        "나. 임의수립주체 : 시장ㆍ군수\n"
        "다. 협의주체 : 경제자유구역청장"
    )

    lines = _plain(body_to_html(source, administrative_rule=True))

    assert any(line.startswith("다. 협의주체") for line in lines)


def test_merge_only_touches_closing_punctuation_tails() -> None:
    assert merge_sentence_tail_item_lines(["사용할 수 있", "다.)"]) == [
        "사용할 수 있다.)"
    ]
    assert merge_sentence_tail_item_lines(['한다.", ', "다.)"]) == [
        '한다.",다.)'
    ]
    # 본문이 있는 목 표지는 건드리지 않는다.
    assert merge_sentence_tail_item_lines(["나. 앞 항목", "다. 뒤 항목"]) == [
        "나. 앞 항목",
        "다. 뒤 항목",
    ]
    # 앞 줄이 없으면 붙일 곳이 없으므로 그대로 둔다.
    assert merge_sentence_tail_item_lines(["다.)"]) == ["다.)"]


def test_general_law_rendering_is_untouched() -> None:
    """일반 법령 경로에는 이 병합을 적용하지 않는다."""
    QApplication.instance() or QApplication([])
    source = "1. 첫째 호\n가. 목 내용\n나. 다른 목"

    lines = _plain(body_to_html(source, administrative_rule=False))

    assert any(line.startswith("가. 목 내용") for line in lines)
    assert any(line.startswith("나. 다른 목") for line in lines)
