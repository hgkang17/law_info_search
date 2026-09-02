import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtCore import QSettings

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from utils.formatting import body_to_html
from utils.constants import FONT_FAMILY
from utils.parsing import (
    insert_admin_clause_breaks,
    normalize_admin_rule_text,
    split_inline_closing_paren_items,
    split_inline_paren_items,
)
from ui.tabs.resource_search import ResourceSearchTab


def test_pre_normalized_admin_rule_skips_only_duplicate_normalization() -> None:
    _app = QApplication.instance() or QApplication([])
    source = "3-1-2-2. 전용주거지역(1) 공통기준\n① 첫 번째 기준"
    normalized = normalize_admin_rule_text(source)

    assert body_to_html(source, administrative_rule=True) == body_to_html(
        normalized,
        administrative_rule=True,
        administrative_rule_normalized=True,
    )


def test_guideline_first_parenthesized_item_moves_below_clause_title() -> None:
    _app = QApplication.instance() or QApplication([])
    source = "3-1-2-2. 전용주거지역(1) 공통기준\n① 첫 번째 기준"

    normalized = insert_admin_clause_breaks(source)
    html = body_to_html(source, administrative_rule=True)

    assert normalized.startswith("3-1-2-2. 전용주거지역\n(1) 공통기준")
    assert "전용주거지역(1)" not in html
    assert "<span class=\"bullet-text\" style=\"font-weight:400;\">공통기준" in html


def test_road_clause_title_and_first_parenthesized_item_are_separate() -> None:
    _app = QApplication.instance() or QApplication([])
    source = (
        "4-9-2-1. 도로(1) 기준도로가 없는 경우(일부구간 포함)\n"
        "① 주변에 우회가능한 도로가 개설되어 있는 경우 : 폐지 검토\n"
        "(2) 일부미개설 도로(폭원)"
    )

    normalized = insert_admin_clause_breaks(source)
    assert normalized.startswith(
        "4-9-2-1. 도로\n(1) 기준도로가 없는 경우(일부구간 포함)"
    )
    html = body_to_html(source, administrative_rule=True)
    assert "도로(1)" not in html
    assert "4-9-2-1.&nbsp;" in html
    assert "(1)&nbsp;" in html


def test_parenthesized_number_inside_guideline_sentence_stays_inline() -> None:
    source = "3-1-2-2. 계획면적은 기준면적(1)을 적용한다."

    normalized = insert_admin_clause_breaks(source)

    assert normalized == source


def test_parenthesized_reference_with_particle_stays_on_same_line() -> None:
    source = (
        "① 지구단위계획으로 결정한 변경결정으로서 상기 "
        "(1)에서 정한 변경인 경우"
    )

    normalized = insert_admin_clause_breaks(source)
    html = body_to_html(source, administrative_rule=True)

    assert "상기 (1)에서 정한" in normalized
    assert "상기<br>" not in html
    assert "(1)&nbsp;에서" not in html


def test_previously_broken_parenthesized_reference_is_rejoined() -> None:
    source = "① 변경결정으로서 상기\n(1)에서 정한 변경인 경우"

    normalized = insert_admin_clause_breaks(source)

    assert normalized == "① 변경결정으로서 상기 (1)에서 정한 변경인 경우"


def test_spaced_parenthesized_reference_is_rejoined() -> None:
    source = "① 변경결정으로서 상기\n(1) 에서 정한 변경인 경우"

    normalized = insert_admin_clause_breaks(source)

    assert normalized == "① 변경결정으로서 상기 (1)에서 정한 변경인 경우"


def test_guideline_clause_subreference_is_rejoined() -> None:
    source = (
        "2-3-16. 이 지침 2-2-5\n"
        "(2) 단서에 따라 보전관리지역을 편입하는 경우\n"
        "(1) 편입의 필요성에 대한 사항\n"
        "(2) 환경 및 경관훼손에 관한 사항"
    )

    normalized = insert_admin_clause_breaks(source)

    assert normalized.splitlines() == [
        "2-3-16. 이 지침 2-2-5 (2) 단서에 따라 보전관리지역을 편입하는 경우",
        "(1) 편입의 필요성에 대한 사항",
        "(2) 환경 및 경관훼손에 관한 사항",
    ]


def test_guideline_chapter_reference_sentence_is_not_styled_as_heading() -> None:
    source = (
        "제8장까지에서 규정하고 있는 계획기준 중 구역의 여건 및 계획의 "
        "특성상 적용하기 곤란하다고 판단하는 경우에는 변경하여 적용할 수 있다."
    )

    html = body_to_html(source, administrative_rule=True)

    assert 'class="law-heading"' not in html
    assert source in re.sub(r"<[^>]+>", "", html)


def test_inline_parenthesized_items_are_still_split() -> None:
    source = "8-3-3. 포함할 내용(1) 명칭(2) 범위(3) 관리방안"

    normalized = insert_admin_clause_breaks(source)

    assert normalized.splitlines() == [
        "8-3-3. 포함할 내용",
        "(1) 명칭",
        "(2) 범위",
        "(3) 관리방안",
    ]


def test_inline_parenthesized_items_can_continue_from_middle_number() -> None:
    source = (
        "(3) 용도지역ㆍ용도지구ㆍ용도구역계획"
        "(4) 도시ㆍ군계획시설계획"
        "(5) 도시개발사업계획"
        "(6) 단계별 집행계획(재원조달방안을 포함)"
    )

    normalized = insert_admin_clause_breaks(source)

    assert normalized.splitlines() == [
        "(3) 용도지역ㆍ용도지구ㆍ용도구역계획",
        "(4) 도시ㆍ군계획시설계획",
        "(5) 도시개발사업계획",
        "(6) 단계별 집행계획(재원조달방안을 포함)",
    ]


def test_inline_parenthesized_items_can_skip_missing_numbers() -> None:
    source = (
        "(7) 건축물의 배치 변경인 경우"
        "(8) 경미한 변경인 경우"
        "(10) 주차장출입구의 위치변경"
        "(11) 지하 시설물의 높이 변경"
        "(12) 대문 형태의 변경"
        "(13) 간판에 관한 계획"
        "(16) 생물서식공간에 관한 계획"
        "(17) 건축선의 변경"
    )

    normalized = insert_admin_clause_breaks(source)

    assert [line[:4].strip() for line in normalized.splitlines()] == [
        "(7)",
        "(8)",
        "(10)",
        "(11)",
        "(12)",
        "(13)",
        "(16)",
        "(17)",
    ]


def test_guideline_number_inside_parentheses_stays_inline() -> None:
    source = "(6) 건축선(\n3-10-1.에 따른 건축선을 말한다. 이하 같다)의 변경"

    normalized = insert_admin_clause_breaks(source)

    assert normalized == (
        "(6) 건축선(3-10-1.에 따른 건축선을 말한다. 이하 같다)의 변경"
    )


def test_guideline_date_is_not_split_as_numbered_items() -> None:
    source = (
        "(4) 특정 지구단위계획구역 : 아래의 시설 설치가 필요한 경우 "
        "① 2002. 12. 31. 이전에 종전의 법에 따라 지정된 시설용지지구 "
        "② (1)부터 (3)까지에 해당하지 아니하는 것"
    )

    normalized = insert_admin_clause_breaks(source)

    assert "① 2002. 12. 31. 이전에" in normalized
    assert "\n12. 31." not in normalized
    assert "\n31. 이전에" not in normalized
    assert normalized.splitlines() == [
        "(4) 특정 지구단위계획구역 : 아래의 시설 설치가 필요한 경우",
        "① 2002. 12. 31. 이전에 종전의 법에 따라 지정된 시설용지지구",
        "② (1)부터 (3)까지에 해당하지 아니하는 것",
    ]


def test_previously_split_guideline_date_is_rejoined() -> None:
    source = "① 2002.\n12.\n31. 이전에 지정된 시설용지지구"

    assert insert_admin_clause_breaks(source) == (
        "① 2002. 12. 31. 이전에 지정된 시설용지지구"
    )


def test_guideline_parent_range_rejoins_between_top_level_items() -> None:
    source = (
        "(4) 특정 지구단위계획구역\n"
        "① 2002. 12. 31. 이전에 지정된 시설용지지구로서\n"
        "(1) 부터(3)까지에 해당하지 아니하는 것\n"
        "② 시장ㆍ군수가 필요하다고 인정하는 것\n"
        "(5) 복합형 지구단위계획구역\n"
        "(1)부터(4)까지의 지구단위계획 중 2 이상을 동시에 지정하는 경우\n"
        "(6) 용도지구 대체형 지구단위계획구역"
    )

    normalized = insert_admin_clause_breaks(source)

    assert normalized.splitlines() == [
        "(4) 특정 지구단위계획구역",
        "① 2002. 12. 31. 이전에 지정된 시설용지지구로서 (1)부터(3)까지에 해당하지 아니하는 것",
        "② 시장ㆍ군수가 필요하다고 인정하는 것",
        "(5) 복합형 지구단위계획구역 (1)부터(4)까지의 지구단위계획 중 2 이상을 동시에 지정하는 경우",
        "(6) 용도지구 대체형 지구단위계획구역",
    ]


def test_inline_closing_parenthesis_items_are_split_in_order() -> None:
    source = (
        "저장소1) 발전용: 전기를 생산하는 용도"
        "2) 산업용: 제조업의 원료 또는 연료"
        "3) 열병합용: 전기와 열을 함께 생산하는 용도"
    )

    assert split_inline_closing_paren_items(source) == [
        "저장소",
        "1) 발전용: 전기를 생산하는 용도",
        "2) 산업용: 제조업의 원료 또는 연료",
        "3) 열병합용: 전기와 열을 함께 생산하는 용도",
    ]


def test_single_closing_parenthesis_number_stays_inline() -> None:
    source = "이 기준은 별표의 구분 1)에 해당한다."

    assert split_inline_closing_paren_items(source) == [source]


def test_parenthesized_footnote_references_are_not_closing_paren_items() -> None:
    source = (
        "※ (1)과 (2)에 따른 도시ㆍ군관리계획 입안권자 지정 후 "
        "입안ㆍ결정절차는 일반적인 경우와 동일하다."
    )

    assert split_inline_closing_paren_items(source) == [source]
    normalized = insert_admin_clause_breaks(source)
    assert normalized == source


def test_split_parenthesized_range_and_enumeration_references_are_rejoined() -> None:
    source = (
        "(2) 구체적인 사항은 지구단위계획수립지침 2-6-4.(3)부터\n"
        "(5) 까지를 준용한다.\n"
        "(3) 지구 지정을 제안하려는 자는 3-2-8-3.의\n"
        "(5)ㆍ(6)에 따른 사항을 제안서에 반영하여야 한다."
    )

    normalized = insert_admin_clause_breaks(source)
    assert normalized.splitlines() == [
        "(2) 구체적인 사항은 지구단위계획수립지침 2-6-4.(3)부터 (5)까지를 준용한다.",
        "(3) 지구 지정을 제안하려는 자는 3-2-8-3.의 (5)ㆍ(6)에 따른 사항을 제안서에 반영하여야 한다.",
    ]


def test_footnote_number_and_circled_clause_reference_stay_inline() -> None:
    source = (
        "(1) 본문 내용이다.※\n"
        "(1) 단서 중 별도의 협의란 관계 법률에 따른 협의를 말한다.\n"
        "(5) 해제결정을 이행한 경우(해제결정의 경우 "
        "8-3-2-4.⑤의 절차가 완료된 경우도 포함한다)에는 알린다."
    )

    normalized = insert_admin_clause_breaks(source)
    assert normalized.splitlines() == [
        "(1) 본문 내용이다.※ (1) 단서 중 별도의 협의란 관계 법률에 따른 협의를 말한다.",
        "(5) 해제결정을 이행한 경우(해제결정의 경우 8-3-2-4.⑤의 절차가 완료된 경우도 포함한다)에는 알린다.",
    ]


def test_circled_reference_after_guideline_clause_stays_inline() -> None:
    source = (
        "① 신청인이 8-3-3-1.의\n"
        "① 에 해당하는 사유로 신청한 경우에는 해제결정을 이행한다.\n"
        "② 신청인이 8-3-3-1.의 ②에 해당하는 사유로 신청한 경우에는 "
        "해제결정을 이행한다."
    )

    normalized = insert_admin_clause_breaks(source)
    assert normalized.splitlines() == [
        "① 신청인이 8-3-3-1.의 ① 에 해당하는 사유로 신청한 경우에는 해제결정을 이행한다.",
        "② 신청인이 8-3-3-1.의 ②에 해당하는 사유로 신청한 경우에는 해제결정을 이행한다.",
    ]


def test_guideline_parenthesized_items_have_distinct_indent() -> None:
    _app = QApplication.instance() or QApplication([])
    html = body_to_html(
        "3-2-8-1. 기준\n(1) 첫 번째 지역\n① 세부 기준",
        administrative_rule=True,
    )

    assert "3-2-8-1.&nbsp;" in html
    assert "(1)&nbsp;" in html
    parent_item = re.search(
        r'class="legal-indent level-1" style="margin:0 0 7px (\d+)px;[^>]*>'
        r'.*?\(1\)&nbsp;',
        html,
    )
    assert parent_item is not None
    assert int(parent_item.group(1)) > 28


def test_period_numbered_items_have_twenty_four_pixel_left_indent() -> None:
    _app = QApplication.instance() or QApplication([])
    html = body_to_html("① 상위 항\n1. 첫 번째 호\n2. 두 번째 호")
    items = re.findall(
        r'style="margin:0 0 7px (\d+)px;[^>]*>\s*'
        r'<span class="bullet-marker"[^>]*>([^<]+)&nbsp;',
        html,
    )
    marker_font = QFont(FONT_FAMILY)
    marker_font.setPixelSize(14)
    expected_margin = 26 + 4 + QFontMetrics(marker_font).horizontalAdvance("1.")
    assert (str(expected_margin), "1.") in items
    assert (str(expected_margin), "2.") in items


def test_law_hang_ho_mok_indent_is_twelve_pixels_more() -> None:
    _app = QApplication.instance() or QApplication([])
    html = body_to_html("① 항 내용\n1. 호 내용\n가. 목 내용\n(1) 세목 내용")
    items = {
        marker: margin
        for margin, marker in re.findall(
            r'style="margin:0 0 7px (\d+)px;[^>]*>\s*'
            r'<span class="bullet-marker"[^>]*>([^<]+)&nbsp;',
            html,
        )
    }
    marker_font = QFont(FONT_FAMILY)
    marker_font.setPixelSize(14)
    metrics = QFontMetrics(marker_font)
    assert items["①"] == str(14 + 4 + metrics.horizontalAdvance("①"))
    assert items["1."] == str(26 + 4 + metrics.horizontalAdvance("1."))
    assert items["가."] == str(42 + 4 + metrics.horizontalAdvance("가."))
    assert items["(1)"] == str(66 + 4 + metrics.horizontalAdvance("(1)"))


def test_guideline_period_numbered_items_have_40px_left_indent_only() -> None:
    _app = QApplication.instance() or QApplication([])
    html = body_to_html(
        "2-1-11. 수립지침 조항\n1. 첫 번째 항목\n2. 두 번째 항목",
        administrative_rule=True,
    )
    items = re.findall(
        r'style="margin:0 0 7px (\d+)px;[^>]*>\s*'
        r'<span class="bullet-marker"[^>]*>([^<]+)&nbsp;',
        html,
    )
    marker_font = QFont(FONT_FAMILY)
    marker_font.setPixelSize(14)
    numbered_margin = 40 + 4 + QFontMetrics(marker_font).horizontalAdvance("1.")
    clause_margin = 4 + 4 + QFontMetrics(marker_font).horizontalAdvance(
        "2-1-11."
    )

    assert (str(numbered_margin), "1.") in items
    assert (str(numbered_margin), "2.") in items
    assert (str(clause_margin), "2-1-11.") in items


def test_guideline_korean_period_items_split_as_whole_tokens_and_indent_50px() -> None:
    _app = QApplication.instance() or QApplication([])
    source = (
        "② 계획을 수립할 수 있다. 가. 의무수립주체 내용 "
        "나. 임의수립주체 내용 다. 그 밖의 내용"
    )

    normalized = insert_admin_clause_breaks(source)
    assert normalized.splitlines() == [
        "② 계획을 수립할 수 있다.",
        "가. 의무수립주체 내용",
        "나. 임의수립주체 내용",
        "다. 그 밖의 내용",
    ]

    html = body_to_html(source, administrative_rule=True)
    marker_font = QFont(FONT_FAMILY)
    marker_font.setPixelSize(14)
    for marker in ("가.", "나.", "다."):
        expected_margin = 50 + 4 + QFontMetrics(marker_font).horizontalAdvance(marker)
        assert f'margin:0 0 7px {expected_margin}px;' in html


def test_guideline_korean_sentence_endings_are_not_item_markers() -> None:
    source = "3-1-1. 계획을 수립한다. 다음 기준을 적용한다."

    assert insert_admin_clause_breaks(source).splitlines() == [source]


def test_guideline_korean_item_chain_does_not_split_sentence_ending_before_paren() -> None:
    source = (
        "② 시ㆍ군 경관계획은 다음과 같이 수립할 수 있다. "
        "가. 의무수립주체 내용 나. 임의수립주체는 계획을 수립할 수 있다.)"
    )

    assert insert_admin_clause_breaks(source).splitlines() == [
        "② 시ㆍ군 경관계획은 다음과 같이 수립할 수 있다.",
        "가. 의무수립주체 내용",
        "나. 임의수립주체는 계획을 수립할 수 있다.)",
    ]


def test_guideline_attached_korean_item_chain_still_splits_real_items() -> None:
    source = "시설은 경우가. 주차장 폐차장나. 도시공원 대상이다다. 기타시설"

    assert insert_admin_clause_breaks(source).splitlines() == [
        "시설은 경우",
        "가. 주차장 폐차장",
        "나. 도시공원 대상이다",
        "다. 기타시설",
    ]


def test_guideline_year_placeholders_stay_inline_and_circle_items_indent() -> None:
    _app = QApplication.instance() or QApplication([])
    source = (
        "4-8-2-1. 재원조달계획\n"
        "(2) 계획기간 : 기준년도(○○01년)~목표년도(○○10년), 10개년\n"
        "○ 지역 선사시대 유적지에서 발굴된 유물 및 국립"
    )

    normalized = insert_admin_clause_breaks(source)
    assert "기준년도(○○01년)~목표년도(○○10년), 10개년" in normalized
    assert "\n○○01년" not in normalized

    html = body_to_html(source, administrative_rule=True)
    assert "기준년도(○○01년)~목표년도(○○10년), 10개년" in html
    marker_font = QFont(FONT_FAMILY)
    marker_font.setPixelSize(14)
    circle_margin = 12 + 4 + QFontMetrics(marker_font).horizontalAdvance("○")
    assert f'margin:0 0 7px {circle_margin}px;' in html


def test_old_saved_guideline_rebuilds_parent_ranges_from_plain_text() -> None:
    record = {
        "administrative_rule_parse_version": 1,
        "administrative_rule_sections": [
            {"label": "조문", "value": "이전 버전의 잘못된 완성본"}
        ],
        "plain_text": (
            "문서 제목\n\n[조문]\n"
            "(4) 특정 지구단위계획구역\n"
            "① 지정된 시설용지지구로서\n"
            "(1)부터(3)까지에 해당하지 아니하는 것\n"
            "(5) 복합형 지구단위계획구역 (1)부터\n"
            "(4)까지의 지구단위계획 중 2 이상을 지정하는 경우\n"
            "(6) 용도지구 대체형 지구단위계획구역"
        ),
    }

    sections = ResourceSearchTab._cached_admrul_sections(record)

    assert sections == [
        (
            "조문",
            "(4) 특정 지구단위계획구역\n"
            "① 지정된 시설용지지구로서 (1)부터(3)까지에 해당하지 아니하는 것\n"
            "(5) 복합형 지구단위계획구역 (1)부터 (4)까지의 지구단위계획 중 2 이상을 지정하는 경우\n"
            "(6) 용도지구 대체형 지구단위계획구역",
        )
    ]


def test_attached_top_level_items_and_tilde_range_are_repaired() -> None:
    source = (
        "② (1)부터(3)까지에 해당하지 아니하고 필요하다고 인정하는 것"
        "(5) 복합형 지구단위계획구역 : (1)부터 (4)까지의 계획 중 "
        "2 이상을 동시에 지정하는 경우(6) 용도지구 대체형 구역\n"
        "(9) 복합구역 :\n"
        "(1) ~\n"
        "(8) 의 지정목적 중 2 이상의 목적을 복합하여 달성하는 경우"
    )

    assert insert_admin_clause_breaks(source).splitlines() == [
        "② (1)부터(3)까지에 해당하지 아니하고 필요하다고 인정하는 것",
        "(5) 복합형 지구단위계획구역 : (1)부터 (4)까지의 계획 중 2 이상을 동시에 지정하는 경우",
        "(6) 용도지구 대체형 구역",
        "(9) 복합구역 : (1)~(8)의 지정목적 중 2 이상의 목적을 복합하여 달성하는 경우",
    ]


def test_circled_item_keeps_parenthesized_proviso_reference_inline() -> None:
    source = (
        "④ 보전관리지역에 지구단위계획을 수립할 때에는 "
        "(2) 단서에 따른 경우를 제외하고는 녹지 또는 공원으로 계획할 것"
    )

    assert insert_admin_clause_breaks(source) == source


def test_saved_circled_proviso_reference_is_rejoined() -> None:
    source = (
        "④ 보전관리지역에 지구단위계획을 수립할 때에는\n"
        "(2) 단서에 따른 경우를 제외하고는 녹지 또는 공원으로 계획할 것"
    )

    assert insert_admin_clause_breaks(source) == source.replace("\n", " ")


def test_guideline_numbered_clause_references_stay_under_parent_items() -> None:
    source = (
        "2-2-6. 다음 지역에는 지정할 수 없다.\n"
        "(1) 도시ㆍ군관리계획수립지침\n"
        "3-2-8-1. (3)에 해당하는 지역\n"
        "(2) 관리지역 중 도시ㆍ군관리계획수립지침\n"
        "3-2-8-1. (4)에 해당하는 지역\n"
        "3-2-8-4. (2)에 해당하는 지역\n"
        "2-2-7. 지구단위계획구역으로 지정하여야 하는 지역"
    )

    assert insert_admin_clause_breaks(source).splitlines() == [
        "2-2-6. 다음 지역에는 지정할 수 없다.",
        "(1) 도시ㆍ군관리계획수립지침 3-2-8-1. (3)에 해당하는 지역",
        "(2) 관리지역 중 도시ㆍ군관리계획수립지침 3-2-8-1. (4)에 해당하는 지역 3-2-8-4. (2)에 해당하는 지역",
        "2-2-7. 지구단위계획구역으로 지정하여야 하는 지역",
    ]


def test_guideline_inline_clause_reference_does_not_hide_next_clause() -> None:
    source = (
        "2-6-7. 시장ㆍ군수는 제안시에는2-6-6.의 도시ㆍ군관리계획도서를 "
        "작성하도록 할 수 있다.2-6-8. 주민제안을 받은 시장ㆍ군수는 "
        "그 처리결과를 제안자에게 통보하여야 한다."
    )

    assert insert_admin_clause_breaks(source).splitlines() == [
        "2-6-7. 시장ㆍ군수는 제안시에는2-6-6.의 도시ㆍ군관리계획도서를 작성하도록 할 수 있다.",
        "2-6-8. 주민제안을 받은 시장ㆍ군수는 그 처리결과를 제안자에게 통보하여야 한다.",
    ]


def test_guideline_spaced_clause_references_stay_inside_numbered_clauses() -> None:
    source = (
        "3-2-2-1. 공공시설등을 설치하여 제공하는 경우를 포함한다. "
        "3-2-2. 에 따른 비율까지 완화할 수 있다."
        "3-2-2-2. 공공시설등을 설치하여 제공하는 경우에는 "
        "3-2-2. 및 3-2-2-1. 에 따라 완화할 수 있다."
        "3-2-2-3. 3-2-2.의 규정을 적용함에 있어 가중치를 정할 수 있다."
        "3-2-2-4. 반환되는 경우에는 3-2-2. 규정을 적용한다."
    )

    assert insert_admin_clause_breaks(source).splitlines() == [
        "3-2-2-1. 공공시설등을 설치하여 제공하는 경우를 포함한다. 3-2-2. 에 따른 비율까지 완화할 수 있다.",
        "3-2-2-2. 공공시설등을 설치하여 제공하는 경우에는 3-2-2. 및 3-2-2-1. 에 따라 완화할 수 있다.",
        "3-2-2-3. 3-2-2.의 규정을 적용함에 있어 가중치를 정할 수 있다.",
        "3-2-2-4. 반환되는 경우에는 3-2-2. 규정을 적용한다.",
    ]


def test_guideline_decimal_result_is_separated_from_next_clause() -> None:
    source = (
        "3-2-2-3. 가중치 산정 결과는 600%/800% = 3/4 = 0.75"
        "3-2-2-4. 반환되는 경우에는 보상금액을 정한다."
    )

    assert insert_admin_clause_breaks(source).splitlines() == [
        "3-2-2-3. 가중치 산정 결과는 600%/800% = 3/4 = 0.75",
        "3-2-2-4. 반환되는 경우에는 보상금액을 정한다.",
    ]


def test_guideline_repairs_spaced_decimal_before_next_clause() -> None:
    source = (
        "3-2-2-3. 가중치 산정 결과는 600%/800% = 3/4 =\n"
        "0. 753-2-2-4. 반환되는 경우에는 보상금액을 정한다. "
        "3-2-2-5. 문화유산 보존조치가 필요한 경우"
    )

    assert insert_admin_clause_breaks(source).splitlines() == [
        "3-2-2-3. 가중치 산정 결과는 600%/800% = 3/4 = 0.75",
        "3-2-2-4. 반환되는 경우에는 보상금액을 정한다.",
        "3-2-2-5. 문화유산 보존조치가 필요한 경우",
    ]


def test_guideline_reference_list_between_sibling_clauses_stays_inline() -> None:
    source = (
        "3-2-7. 개발진흥지구의 높이제한을 완화할 수 있다.\n"
        "3-2-8. 3-2-2.(2), 3-2-2-1,\n"
        "3-2-2-4, 3-2-2-5,\n"
        "3-2-3. (1) 및 3-2-6.의 용적률 완화규정은 적용하지 않는다.\n"
        "3-2-9. 행위제한 기준을 완화하여 적용할 수 있다."
    )

    assert insert_admin_clause_breaks(source).splitlines() == [
        "3-2-7. 개발진흥지구의 높이제한을 완화할 수 있다.",
        "3-2-8. 3-2-2.(2), 3-2-2-1, 3-2-2-4, 3-2-2-5, 3-2-3. (1) 및 3-2-6.의 용적률 완화규정은 적용하지 않는다.",
        "3-2-9. 행위제한 기준을 완화하여 적용할 수 있다.",
    ]


def test_guideline_reference_list_keeps_real_subitems_and_next_clause() -> None:
    source = (
        "3-2-8. 3-2-2.(2), 3-2-2-1,\n\n"
        "3-2-2-4., 3-2-2-5, 3-2-3. (1) 및 3-2-6.의 용적률 완화규정은 "
        "적용하지 아니하는 것을 원칙으로 한다.\n"
        "(1) 개발제한구역ㆍ시가화조정구역인 경우\n"
        "(2) 기존의 용도지역 용적률을 적용하지 아니하는 경우\n"
        "3-2-9. 행위제한 기준을 완화하여 적용할 수 있다."
    )

    expected = [
        "3-2-8. 3-2-2.(2), 3-2-2-1, 3-2-2-4., 3-2-2-5, 3-2-3. (1) 및 3-2-6.의 용적률 완화규정은 적용하지 아니하는 것을 원칙으로 한다.",
        "(1) 개발제한구역ㆍ시가화조정구역인 경우",
        "(2) 기존의 용도지역 용적률을 적용하지 아니하는 경우",
        "3-2-9. 행위제한 기준을 완화하여 적용할 수 있다.",
    ]

    normalized = insert_admin_clause_breaks(source)
    assert normalized.splitlines() == expected
    assert insert_admin_clause_breaks(normalized).splitlines() == expected


def test_guideline_repairs_stray_bracket_before_next_clause() -> None:
    source = (
        "3-4-1. 환경관리계획을 수립한다.\n"
        "(1) 절토를 최소화한다.\n"
        "(2) 생태민감지역을 보존한다.\n"
        "(3) 자연지형을 살릴 수 있도록 계획한다.[3-4-2. 에너지 및 자원 "
        "재활용을 고려하여 계획을 수립한다.\n"
        "(1) 자연에너지의 이용률을 높인다.\n"
        "(2) 수자원계획을 수립한다.\n"
        "(3) 자연환기가 잘되도록 한다. 3-4-3. 환경오염방지를 고려한다."
    )

    normalized = insert_admin_clause_breaks(source)
    lines = normalized.splitlines()
    assert "[3-4-2." not in normalized
    assert "3-4-2. 에너지 및 자원 재활용을 고려하여 계획을 수립한다." in lines
    assert "3-4-3. 환경오염방지를 고려한다." in lines


def test_guideline_clause_starting_with_particle_prefix_word_is_split() -> None:
    source = (
        "3-4-1. 환경관리계획을 수립한다.\n"
        "(3) 자연지형을 살리도록 계획한다.3-4-2. 에너지 및 자원 재활용을 "
        "고려한다.\n"
        "(3) 자연환기가 잘되도록 한다. 3-4-3. 환경오염방지를 고려한다."
    )

    assert insert_admin_clause_breaks(source).splitlines() == [
        "3-4-1. 환경관리계획을 수립한다.",
        "(3) 자연지형을 살리도록 계획한다.",
        "3-4-2. 에너지 및 자원 재활용을 고려한다.",
        "(3) 자연환기가 잘되도록 한다.",
        "3-4-3. 환경오염방지를 고려한다.",
    ]


def test_guideline_deleted_clauses_without_period_are_separated() -> None:
    source = (
        "제7장 삭제 제1절 삭제1-7-1-1 삭제1-7-1-2 삭제 "
        "제2절 삭제1-7-2-1 삭제1-7-2-2 삭제1-7-2-3 삭제1-7-2-4 삭제"
    )

    normalized = insert_admin_clause_breaks(source)
    assert normalized.splitlines() == [
        "제7장 삭제",
        "제1절 삭제",
        "1-7-1-1 삭제",
        "1-7-1-2 삭제",
        "제2절 삭제",
        "1-7-2-1 삭제",
        "1-7-2-2 삭제",
        "1-7-2-3 삭제",
        "1-7-2-4 삭제",
    ]

    html = body_to_html(source, administrative_rule=True)
    assert ">제1절 삭제</div>" in html
    assert ">제2절 삭제</div>" in html
    assert "1-7-1-1 삭제<br>1-7-1-2 삭제" in html


def test_guideline_keeps_chapter_ranges_inline_and_supports_two_level_clauses() -> None:
    source = (
        "제8장 기타 수립기준\n"
        "제2절 특정 지구단위계획 수립기준\n"
        "8-2-1. 제1장부터 제3장까지의 기준에 적합하게 계획을 수립하여야 하며, "
        "제4장부터 제7장까지의 기준중 적용 가능한 기준을 적용한다.\n"
        "제9장 행정사항\n"
        "9-1. 이 지침 시행 당시의 기준을 적용한다.\n"
        "9-2. 변경할 수 있다."
    )

    expected = [
        "제8장 기타 수립기준",
        "제2절 특정 지구단위계획 수립기준",
        "8-2-1. 제1장부터 제3장까지의 기준에 적합하게 계획을 수립하여야 하며, 제4장부터 제7장까지의 기준중 적용 가능한 기준을 적용한다.",
        "제9장 행정사항",
        "9-1. 이 지침 시행 당시의 기준을 적용한다.",
        "9-2. 변경할 수 있다.",
    ]

    normalized = insert_admin_clause_breaks(source)
    assert normalized.splitlines() == expected
    assert insert_admin_clause_breaks(normalized).splitlines() == expected


def test_guideline_only_breaks_at_next_sibling_or_first_child_clause() -> None:
    source = (
        "1-1-1. 적용 대상은 1-1-7.의 기준을 따른다.\n"
        "1-1-5. 및 2-3-4.를 함께 검토한다.\n"
        "1-1-1-1. 첫 번째 세부기준이다.\n"
        "1-1-2. 다음 기준이다."
    )

    assert insert_admin_clause_breaks(source).splitlines() == [
        "1-1-1. 적용 대상은 1-1-7.의 기준을 따른다. 1-1-5. 및 2-3-4.를 함께 검토한다.",
        "1-1-1-1. 첫 번째 세부기준이다.",
        "1-1-2. 다음 기준이다.",
    ]


def test_guideline_section_heading_resets_clause_sequence() -> None:
    source = (
        "제1절 지침의 의의\n"
        "1-1-1. 첫 번째 내용이다.\n"
        "1-1-2. 두 번째 내용이다.\n"
        "제2절 지구단위계획의 성격\n"
        "1-2-1. 새로운 절의 첫 번째 내용이다.\n"
        "제3절 지구단위계획과 다른 계획과의 관계\n"
        "1-3-1. 다시 시작하는 내용이다."
    )

    assert insert_admin_clause_breaks(source).splitlines() == [
        "제1절 지침의 의의",
        "1-1-1. 첫 번째 내용이다.",
        "1-1-2. 두 번째 내용이다.",
        "제2절 지구단위계획의 성격",
        "1-2-1. 새로운 절의 첫 번째 내용이다.",
        "제3절 지구단위계획과 다른 계획과의 관계",
        "1-3-1. 다시 시작하는 내용이다.",
    ]


def test_guideline_repairs_clause_attached_to_section_heading() -> None:
    source = (
        "제2장 지구단위계획구역의 지정 및 지구단위계획의 수립\n"
        "제1절 지구단위계획구역 지정의 일반원칙 2-1-1. 첫 내용이다. "
        "2-1-2. 두 번째 내용이다."
    )

    assert insert_admin_clause_breaks(source).splitlines() == [
        "제2장 지구단위계획구역의 지정 및 지구단위계획의 수립",
        "제1절 지구단위계획구역 지정의 일반원칙",
        "2-1-1. 첫 내용이다.",
        "2-1-2. 두 번째 내용이다.",
    ]


def test_normalized_parent_item_is_not_resplit_at_clause_reference() -> None:
    source = (
        "(1) 도시ㆍ군관리계획수립지침 3-2-8-1. (3) 에 해당하는 지역\n"
        "(2) 관리지역 중 도시ㆍ군관리계획수립지침 "
        "3-2-8-1. (4) 에 해당하는 지역"
    )

    normalized = insert_admin_clause_breaks(source)

    assert normalized.splitlines() == [
        "(1) 도시ㆍ군관리계획수립지침 3-2-8-1. (3)에 해당하는 지역",
        "(2) 관리지역 중 도시ㆍ군관리계획수립지침 3-2-8-1. (4)에 해당하는 지역",
    ]
    assert split_inline_paren_items(normalized.splitlines()[0]) == [
        normalized.splitlines()[0]
    ]


def test_full_guideline_sample_has_no_parenthesized_reference_split() -> None:
    sample_path = Path(__file__).resolve().parent.parent / "perf_sample_guideline.txt"
    source = sample_path.read_text(encoding="utf-8")

    normalized = insert_admin_clause_breaks(source)
    suspicious = [
        line
        for line in normalized.splitlines()
        if re.match(
            r"^\([0-9]+\)\s*(?:에서|에|의|항|호|목|을|를|은|는|이|가)(?=\s|$)",
            line,
        )
    ]

    assert "상기 (1)에서 정한 변경인 경우" in normalized
    assert "3-1-2-2. 전용주거지역\n(1) 공통기준" in normalized
    assert suspicious == []
def test_guideline_parenthesized_range_after_colon_stays_on_same_line() -> None:
    source = (
        "(8) 용도지구대체 : 기존 용도지구를 대체하는 경우\n"
        "(9) 복합구역 :\n"
        "(1) ~ (8)의 지정목적중 2 이상의 목적을 복합하여 달성하고자 하는 경우"
    )

    assert insert_admin_clause_breaks(source).splitlines() == [
        "(8) 용도지구대체 : 기존 용도지구를 대체하는 경우",
        "(9) 복합구역 : (1) ~ (8)의 지정목적중 2 이상의 목적을 복합하여 달성하고자 하는 경우",
    ]


def test_circled_hangul_item_breaks_after_sentence_in_guideline() -> None:
    """수립지침 ㉮ 세항은 문장 끝 뒤에서 새 줄로 나눈다."""
    _app = QApplication.instance() or QApplication([])
    source = (
        "④ 광역적 기초생활권을 설정한다."
        "㉮ 둘 이상의 시ㆍ군이 공동으로 설치하는 시설"
    )
    assert insert_admin_clause_breaks(source).splitlines() == [
        "④ 광역적 기초생활권을 설정한다.",
        "㉮ 둘 이상의 시ㆍ군이 공동으로 설치하는 시설",
    ]
    html = body_to_html(source, administrative_rule=True)
    assert "설정한다.㉮" not in html.replace("&nbsp;", "")
    assert "㉮&nbsp;" in html


def test_circled_hangul_reference_stays_inline() -> None:
    source = "④ ㉮의 시설과 연계하여 계획한다."
    assert insert_admin_clause_breaks(source) == source


def test_admin_rule_popup_uses_body_parser_not_br_join(tmp_path) -> None:
    """AI 행정규칙 팝업도 본문 화면과 같은 파서·HTML을 쓴다."""
    _app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "res.ini"), QSettings.Format.IniFormat)
    tab = ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    payload = {
        "_law_go_kr_images": {
            "158685505": "data:image/gif;base64,R0lGODlhAQABAAAAACw="
        },
        "AdmRulService": {
            "개정문": {"개정문내용": "훈령 개정문 원본"},
            "행정규칙기본정보": {"행정규칙명": "도시·군관리계획수립지침"},
            "조문내용": (
                "1-6-2-1. 광역적 기초생활권을 설정한다."
                '<img id="158685505"></img>'
                "㉮ 둘 이상의 시ㆍ군이 공동으로 설치하는 시설"
            ),
            "별표단위": {"별표내용": "| 용도지역 | 면적 |"},
        }
    }
    row = {
        "target": "admrul",
        "label": "행정규칙",
        "id": "2100000282348",
        "name": "도시·군관리계획수립지침",
        "raw": {},
    }
    title, html = tab._document_reference_html(row, payload=payload)
    assert title == "도시·군관리계획수립지침"
    assert "legal-indent" in html
    assert "1-6-2-1." in html
    assert "설정한다.㉮" not in html.replace("&nbsp;", "")
    assert "data:image/gif;base64,R0lGODlhAQABAAAAACw=" in html
    assert "[[LAW_IMAGE:" not in html
    assert "개정문" not in html
    assert "별표내용" not in html
    assert "{'" not in html
