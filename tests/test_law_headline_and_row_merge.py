"""법령 본문 머리글(약칭ㆍ시행일)과 3단비교 항ㆍ호 행 병합 검증."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui.tabs.resource_search import ResourceSearchTab
from utils.formatting import (
    body_to_html,
    detail_document_header,
    law_headline_text,
)
from utils.parsing import insert_admin_clause_breaks
from utils.three_stage_alignment import law_content_blocks

# body_to_html은 표지 폭을 QFontMetrics로 재므로 앱 인스턴스가 있어야 한다.
QApplication.instance() or QApplication([])


# 국토의 계획 및 이용에 관한 법률 실제 응답 형식. 법종구분은 감싼 형태로 온다.
LAW_PAYLOAD = {
    "법령": {
        "기본정보": {
            "법령명_한글": "국토의 계획 및 이용에 관한 법률",
            "법령명약칭": "국토계획법",
            "법종구분": {"content": "법률", "법종구분코드": "A0002"},
            "공포번호": "21447",
            "공포일자": "20260305",
            "시행일자": "20260701",
            "제개정구분": "타법개정",
        }
    }
}

# 제144조(과태료). 항마다 호가 딸려 있어 블록이 여러 개로 나뉜다.
ARTICLE_144 = (
    "①  다음 각 호의 어느 하나에 해당하는 자에게는 1천만원 이하의 과태료를"
    " 부과한다.1.  제44조의3제2항에 따른 허가를 받지 아니하고 공동구를 점용한 자"
    "2.  정당한 사유 없이 제130조제1항에 따른 행위를 방해한 자"
    "②  다음 각 호의 어느 하나에 해당하는 자에게는 500만원 이하의 과태료를"
    " 부과한다.1.  제56조제4항 단서에 따른 신고를 하지 아니한 자"
    "2.  제137조제1항에 따른 보고를 하지 아니한 자"
)


def _article_blocks() -> list[dict[str, str]]:
    return law_content_blocks(body_to_html(insert_admin_clause_breaks(ARTICLE_144)))


def test_law_headline_matches_law_go_kr_notation() -> None:
    short_name, subtitle = ResourceSearchTab._law_document_headline(LAW_PAYLOAD)
    assert short_name == "국토계획법"
    assert subtitle == "[시행 2026. 7. 1.] [법률 제21447호, 2026. 3. 5., 타법개정]"


def test_law_headline_ignores_non_law_payload() -> None:
    assert ResourceSearchTab._law_document_headline({"AdmRulService": {}}) == ("", "")
    assert ResourceSearchTab._law_document_headline(None) == ("", "")


def test_headline_survives_missing_fields() -> None:
    payload = {"법령": {"기본정보": {"시행일자": "20260701"}}}
    short_name, subtitle = ResourceSearchTab._law_document_headline(payload)
    assert short_name == ""
    assert subtitle == "[시행 2026. 7. 1.]"


def test_document_header_shows_short_name_and_effective_line() -> None:
    html_parts, plain_parts = detail_document_header(
        "국토의 계획 및 이용에 관한 법률",
        [("법령ID", "009294")],
        (),
        short_name="국토계획법",
        subtitle="[시행 2026. 7. 1.] [법률 제21447호, 2026. 3. 5., 타법개정]",
    )
    html = "".join(html_parts)
    assert '<span class="doc-short-name">( 약칭: 국토계획법 )</span>' in html
    assert '<div class="doc-subtitle">[시행 2026. 7. 1.]' in html
    assert "( 약칭: 국토계획법 )" in plain_parts


def test_document_header_without_headline_keeps_old_shape() -> None:
    html_parts, plain_parts = detail_document_header("행정규칙명", [], ())
    html = "".join(html_parts)
    # 스타일 정의에는 두 클래스가 늘 들어 있으므로 실제로 그린 요소만 본다.
    assert '<span class="doc-short-name">' not in html
    assert '<div class="doc-subtitle">' not in html
    assert "<h1>행정규칙명</h1>" in html
    assert plain_parts == ["행정규칙명"]


def test_pinned_headline_text_joins_short_name_and_subtitle() -> None:
    assert law_headline_text("국토계획법", "[시행 2026. 7. 1.]") == (
        "( 약칭: 국토계획법 )  [시행 2026. 7. 1.]"
    )
    assert law_headline_text("", "") == ""


def test_rows_merge_when_no_subordinate_cites_a_ho() -> None:
    """시행령이 항까지만 인용하면 항과 호를 한 행으로 묶어 간격을 없앤다."""
    blocks = _article_blocks()
    assert len(blocks) == 6  # ①+2호, ②+2호

    merged = ResourceSearchTab._merge_law_blocks_for_display(
        blocks, [("000100", "", ""), ("000200", "", "")]
    )
    assert len(merged) == 2
    assert [block["hang"] for block in merged] == ["000100", "000200"]
    # 합쳐도 호 본문이 사라지지 않는다.
    assert "제44조의3제2항" in merged[0]["html"]
    assert "제56조제4항" in merged[1]["html"]


def test_rows_keep_split_when_a_subordinate_cites_a_ho() -> None:
    """호를 짚어 인용한 하위법령이 있으면 그 항은 호마다 나눈 채로 둔다."""
    blocks = _article_blocks()
    merged = ResourceSearchTab._merge_law_blocks_for_display(
        blocks, [("000100", "000200", "")]
    )
    # ① 묶음(3블록)은 그대로, ② 묶음(3블록)만 하나로 합쳐진다.
    assert len(merged) == 4
    assert [block["ho"] for block in merged[:3]] == ["", "000100", "000200"]
