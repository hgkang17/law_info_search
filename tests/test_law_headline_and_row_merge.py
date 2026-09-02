"""법령 본문 머리글(약칭ㆍ시행일)과 3단비교 항ㆍ호 행 병합 검증."""

import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui.tabs.resource_search import ResourceSearchTab
from utils.formatting import (
    body_to_html,
    detail_document_header,
    law_headline_text,
)
from utils.formatting import law_reference_html_text
from utils.parsing import (
    insert_admin_clause_breaks,
    law_article_text,
    normalize_amendment_note_dates,
)
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


def test_amendment_note_dates_use_law_go_kr_format() -> None:
    assert normalize_amendment_note_dates(
        "이 법에서 사용하는 용어의 뜻은 다음과 같다. <개정 2011.4.14, 2024.2.6>"
    ) == "이 법에서 사용하는 용어의 뜻은 다음과 같다. <개정 2011. 4. 14., 2024. 2. 6.>"
    assert normalize_amendment_note_dates("[전문개정 2009.2.6][제목개정 2015.12.29]") == (
        "[전문개정 2009. 2. 6.][제목개정 2015. 12. 29.]"
    )
    # 날짜에 글자가 바로 붙어 오면 한 칸 띄운다.
    assert "2012. 12. 18. 법률" in normalize_amendment_note_dates(
        "[2012.12.18법률 제11579호에 의하여 개정함]"
    )


def test_amendment_note_dates_leave_body_numbers_alone() -> None:
    """개정 표기가 아닌 본문 숫자ㆍ조문 인용은 건드리지 않는다."""
    body = "제3조제1항에 따라 100.5제곱미터 이상인 경우 제44조의3제2항을 적용한다."
    assert normalize_amendment_note_dates(body) == body
    assert normalize_amendment_note_dates("기준은 1.5.2에 따른다.") == "기준은 1.5.2에 따른다."


def test_article_note_is_appended_as_its_own_line() -> None:
    units = [
        {
            "조문내용": "제1조(목적) 이 법은 …을 목적으로 한다.",
            "조문참고자료": "[전문개정 2009.2.6]",
        }
    ]
    lines = law_article_text(units).splitlines()
    assert lines[0].startswith("제1조(목적)")
    assert lines[-1] == "[전문개정 2009. 2. 6.]"


def test_enumerated_ho_reference_links_to_the_same_article() -> None:
    """``제2조제1호 및 제2호``의 뒤 호도 앞 조를 이어받아 링크가 된다."""
    html = law_reference_html_text(
        "제2조제1호 및 제2호의 시설을 말한다.",
        (),
        use_api_links=True,
        current_law_name="국토의 계획 및 이용에 관한 법률 시행규칙",
    )
    linked = re.findall(r">([^<>]+)</a>", html)
    assert linked == ["제2조제1호", "제2호"]
    assert "jo=2&ho=2" in html.replace("&amp;", "&")


def test_standalone_ho_reference_stays_plain() -> None:
    """앞에 조 인용이 없는 단독 호는 예전처럼 평문으로 둔다."""
    html = law_reference_html_text(
        "제2호에 해당하는 자는 신고한다.",
        (),
        use_api_links=True,
        current_law_name="건축법",
    )
    assert "<a href=" not in html


def test_repeal_notice_added_only_for_history_rows() -> None:
    base = [("법령ID", "000808")]
    assert ResourceSearchTab._with_repeal_notice(base, {"history_code": "연혁"})[0] == (
        "현행여부",
        "연혁 법령 — 현행이 아닙니다",
    )
    assert ResourceSearchTab._with_repeal_notice(base, {"revision": "폐지"})[0] == (
        "현행여부",
        "폐지 — 현재 효력이 없습니다",
    )
    assert ResourceSearchTab._with_repeal_notice(base, {"from_history": True})[0][0] == (
        "현행여부"
    )
    # 현행 법령에는 붙이지 않는다.
    assert ResourceSearchTab._with_repeal_notice(
        base, {"history_code": "현행", "revision": "일부개정"}
    ) == base
