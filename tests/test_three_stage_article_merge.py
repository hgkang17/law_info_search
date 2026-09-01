"""반복 수록된 법률 조문 합치기와 조문 표지 복원 검증."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import re

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab
from utils.parsing import insert_admin_clause_breaks
from utils.patterns import (
    KOREAN_ITEM_MARKERS,
    LAW_ITEM_PATTERN,
    LAW_UNIT_REFERENCE_PATTERN,
)
from utils.three_stage_alignment import (
    block_index_for_unit,
    hang_groups_from_blocks,
    law_content_blocks,
    primary_source_unit,
)


def _tab(tmp_path) -> ResourceSearchTab:
    QApplication.instance() or QApplication([])
    settings = QSettings(
        str(tmp_path / "three.ini"), QSettings.Format.IniFormat
    )
    return ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )


def _column_items(html: str) -> list[tuple[str, str]]:
    """열 HTML에서 (법령명, 조제목) 짝을 뽑는다. 법령명이 없으면 빈 문자열."""
    return re.findall(
        r'comparison-item">(?:<div class="comparison-law-name">([^<]*)</div>)?'
        r'<div class="comparison-article-title">(?:<a[^>]*>)?([^<]+)',
        html,
    )


def _law_article(decree_number: str, decree_title: str) -> dict:
    """법제처 API가 위임 관계마다 하나씩 내려주는 법률 조문 항목."""
    return {
        "조번호": "0002",
        "조가지번호": "00",
        "조제목": "제2조(정의)",
        "조내용": "이 법에서 사용하는 용어의 뜻은 다음과 같다.",
        "시행령조문": {
            "법령명": "국토의 계획 및 이용에 관한 법률 시행령",
            "조번호": decree_number,
            "조가지번호": "00",
            "조제목": decree_title,
            "조내용": "법 제2조에 따른 시설을 말한다.",
        },
    }


REPEATED_ARTICLES = [
    _law_article("0002", "제2조(기반시설)"),
    _law_article("0003", "제3조(광역시설)"),
    _law_article("0004", "제4조(공공시설)"),
]


def test_repeated_law_articles_merge_their_decrees() -> None:
    """같은 조문이 위임 건수만큼 반복돼도 시행령을 모두 모은다."""
    resolved = ResourceSearchTab._resolve_three_stage_article_nodes(
        REPEATED_ARTICLES,
        law_name="국토의 계획 및 이용에 관한 법률",
        jo="000200",
    )

    assert resolved is not None
    _base, decrees, _rules = resolved
    codes = [ResourceSearchTab._three_stage_article_code(n) for n in decrees]
    assert codes == ["000200", "000300", "000400"]


def test_unrelated_article_still_returns_nothing() -> None:
    resolved = ResourceSearchTab._resolve_three_stage_article_nodes(
        REPEATED_ARTICLES,
        law_name="국토의 계획 및 이용에 관한 법률",
        jo="009900",
    )

    assert resolved is None


def test_decree_view_finds_article_in_any_repeated_entry() -> None:
    """시행령 화면에서 열어도 뒤쪽 항목에 실린 조문을 찾는다."""
    resolved = ResourceSearchTab._resolve_three_stage_article_nodes(
        REPEATED_ARTICLES,
        law_name="국토의 계획 및 이용에 관한 법률 시행령",
        jo="000400",
    )

    assert resolved is not None
    _base, decrees, _rules = resolved
    codes = [ResourceSearchTab._three_stage_article_code(n) for n in decrees]
    assert codes == ["000400"]


def _rule_node(law_name: str, number: str, title: str) -> dict:
    return {
        "법령명": law_name,
        "조번호": number,
        "조가지번호": "00",
        "조제목": title,
        "조내용": "내용",
    }


def test_repeated_law_name_is_printed_only_once(tmp_path) -> None:
    """같은 법령이 이어지면 법령명을 첫 항목에만 찍는다."""
    tab = _tab(tmp_path)
    decree = "국토의 계획 및 이용에 관한 법률 시행령"
    nodes = [
        _rule_node(decree, "0002", "제2조(기반시설)"),
        _rule_node(decree, "0003", "제3조(광역시설)"),
        _rule_node(decree, "0004", "제4조(공공시설)"),
    ]

    html = ""
    previous = ""
    for node in nodes:
        html += tab._three_stage_node_html(
            node,
            fallback_law_name="시행령",
            show_law_name=node["법령명"] != previous,
        )
        previous = node["법령명"]

    assert _column_items(html) == [
        (decree, "제2조(기반시설)"),
        ("", "제3조(광역시설)"),
        ("", "제4조(공공시설)"),
    ]


def test_law_name_reappears_when_it_changes(tmp_path) -> None:
    """다른 법령이 섞이면 바뀌는 지점에서 다시 표시한다."""
    tab = _tab(tmp_path)
    rule = "국토의 계획 및 이용에 관한 법률 시행규칙"
    facility = "도시ㆍ군계획시설의 결정ㆍ구조 및 설치기준에 관한 규칙"
    nodes = [
        _rule_node(rule, "0006", "제6조(가)"),
        _rule_node(facility, "0002", "제2조(나)"),
        _rule_node(facility, "0003", "제3조(다)"),
        _rule_node(rule, "0009", "제9조(라)"),
    ]

    html = ""
    previous = ""
    for node in nodes:
        html += tab._three_stage_node_html(
            node,
            fallback_law_name="시행규칙",
            show_law_name=node["법령명"] != previous,
        )
        previous = node["법령명"]

    assert _column_items(html) == [
        (rule, "제6조(가)"),
        (facility, "제2조(나)"),
        ("", "제3조(다)"),
        (rule, "제9조(라)"),
    ]


LAW_CONTENT_HTML = (
    '<div class="paragraph">이 법에서 쓰는 뜻은 다음과 같다.</div>'
    '<div class="legal-indent level-1" style="margin:0;">'
    '<span class="bullet-marker" style="font-weight:400;">1.&nbsp;</span>'
    '<span class="bullet-text" style="font-weight:400;">산지</span></div>'
    '<div class="legal-indent level-2" style="margin:0;">'
    '<span class="bullet-marker" style="font-weight:400;">가.&nbsp;</span>'
    '<span class="bullet-text" style="font-weight:400;">1호의 가목</span></div>'
    '<div class="legal-indent level-1" style="margin:0;">'
    '<span class="bullet-marker" style="font-weight:400;">2.&nbsp;</span>'
    '<span class="bullet-text" style="font-weight:400;">산지전용</span></div>'
    '<div class="legal-indent level-1" style="margin:0;">'
    '<span class="bullet-marker" style="font-weight:400;">5의2.&nbsp;</span>'
    '<span class="bullet-text" style="font-weight:400;">가지번호 호</span></div>'
)


def test_law_content_splits_into_subparagraph_blocks() -> None:
    """시행령을 근거 호ㆍ목 옆에 세우려면 법률 본문도 같은 단위로 잘려야 한다."""
    blocks = law_content_blocks(LAW_CONTENT_HTML)

    assert [(block["ho"], block.get("mok") or "") for block in blocks] == [
        ("", ""),
        ("000100", ""),
        ("000100", "가"),
        ("000200", ""),
        ("000502", ""),
    ]
    assert "1호의 가목" in blocks[2]["html"]


def test_block_index_matches_the_source_subparagraph() -> None:
    blocks = law_content_blocks(LAW_CONTENT_HTML)

    assert block_index_for_unit(blocks, "", "000200") == 3
    assert block_index_for_unit(blocks, "", "000502") == 4
    assert block_index_for_unit(blocks, "", "000100") == 1
    assert block_index_for_unit(blocks, "", "000100", "가") == 2
    # 근거를 찾지 못하면 조문 머리 줄에 모은다.
    assert block_index_for_unit(blocks, "", "009900") == 0


def test_primary_source_unit_skips_empty_references() -> None:
    units = [
        {"source_hang": "", "source_ho": "", "source_mok": ""},
        {"source_hang": "", "source_ho": "000800", "source_mok": "다"},
    ]

    assert primary_source_unit(units) == (
        "",
        "000800",
        "다",
    )


def test_rule_reference_through_decree_title_is_recognised() -> None:
    """``「…법률 시행령」(이하 “영”이라 한다) 제4조``도 시행령 인용이다."""
    codes = ResourceSearchTab._decree_codes_referenced_by_rule(
        "「국토의 계획 및 이용에 관한 법률 시행령」(이하 “영”이라 한다) "
        "제4조제2호에서 “국토교통부령으로 정하는 시설”이란"
    )

    assert codes == {"000400"}


def test_source_unit_label_uses_body_marker_form() -> None:
    label = ResourceSearchTab._three_stage_source_label
    assert label({"source_ho": "000800"}) == "8."
    assert label({"source_ho": "000802"}) == "8의2."
    assert label({"source_hang": "000200", "source_ho": ""}) == "②"
    assert label({"source_hang": "", "source_ho": ""}) == ""


def test_source_unit_is_anchored_and_highlighted() -> None:
    """모법 조문 전체가 오므로 근거 호에 닻과 음영을 붙인다."""
    content = (
        '<div class="legal-indent level-1" style="margin:0;">'
        '<span class="bullet-marker" style="font-weight:400;">7.&nbsp;</span>'
        '<span class="bullet-text" style="font-weight:400;">앞 호</span></div>'
        '<div class="legal-indent level-1" style="margin:0;">'
        '<span class="bullet-marker" style="font-weight:400;">8.&nbsp;</span>'
        '<span class="bullet-text" style="font-weight:400;">광역시설</span></div>'
    )

    marked = ResourceSearchTab._mark_three_stage_source_unit(content, "8.")

    assert 'name="thd-source"' in marked
    # 닻과 음영은 8호에만 붙고 7호는 그대로다.
    assert marked.count("background:#fdf0bd;") == 2
    assert marked.index('name="thd-source"') > marked.index("앞 호")
    assert "광역시설" in marked


def test_source_unit_can_point_at_an_item_inside_the_subparagraph() -> None:
    """``법 제2조제2호다목``은 2호가 아니라 그 안의 다목을 짚는다."""
    content = (
        '<div class="legal-indent level-1" style="margin:0;">'
        '<span class="bullet-marker" style="font-weight:400;">1.&nbsp;</span>'
        '<span class="bullet-text" style="font-weight:400;">산지</span></div>'
        '<div class="legal-indent level-2" style="margin:0;">'
        '<span class="bullet-marker" style="font-weight:400;">다.&nbsp;</span>'
        '<span class="bullet-text" style="font-weight:400;">1호의 다목</span></div>'
        '<div class="legal-indent level-1" style="margin:0;">'
        '<span class="bullet-marker" style="font-weight:400;">2.&nbsp;</span>'
        '<span class="bullet-text" style="font-weight:400;">산지전용</span></div>'
        '<div class="legal-indent level-2" style="margin:0;">'
        '<span class="bullet-marker" style="font-weight:400;">다.&nbsp;</span>'
        '<span class="bullet-text" style="font-weight:400;">2호의 다목</span></div>'
    )

    marked = ResourceSearchTab._mark_three_stage_source_unit(
        content, "2.", inner_label="다."
    )

    # 앞선 1호의 다목이 아니라 2호 안의 다목에 붙어야 한다.
    anchored = marked.index('name="thd-source"')
    assert marked.index("2호의 다목") > anchored
    assert marked.index("1호의 다목") < anchored


def test_item_letters_do_not_match_other_syllables() -> None:
    """``제1호 각 목 외의 부분``의 ``각``을 목 표지로 읽지 않는다."""
    units = ResourceSearchTab._law_source_units_referenced_by_decree(
        "법 제2조제1호 각 목 외의 부분에서 정하는 토지를 말한다.", "000200"
    )

    assert units == [{"source_hang": "", "source_ho": "000100", "source_mok": ""}]


def test_item_reference_is_captured(tmp_path=None) -> None:
    units = ResourceSearchTab._law_source_units_referenced_by_decree(
        "법 제2조제2호다목에서 “대통령령으로 정하는 임산물”이란", "000200"
    )

    assert units == [
        {"source_hang": "", "source_ho": "000200", "source_mok": "다"}
    ]


def test_missing_source_unit_leaves_content_untouched() -> None:
    content = (
        '<div class="legal-indent level-1" style="margin:0;">'
        '<span class="bullet-marker" style="font-weight:400;">7.&nbsp;</span>'
        '<span class="bullet-text" style="font-weight:400;">앞 호</span></div>'
    )

    assert ResourceSearchTab._mark_three_stage_source_unit(content, "8.") == content
    assert ResourceSearchTab._mark_three_stage_source_unit(content, "") == content


def test_branch_numbered_subparagraph_stays_whole() -> None:
    """``5의2.``는 한 표지다. ``5의`` + ``2.``로 쪼개지면 번호가 어긋난다."""
    source = (
        "5. “지구단위계획”이란 도시ㆍ군관리계획을 말한다."
        "5의2. 삭제"
        "5의3. “성장관리계획”이란 계획을 말한다."
        "6. “기반시설”이란 대통령령으로 정하는 시설을 말한다."
    )

    lines = insert_admin_clause_breaks(source).splitlines()

    assert lines == [
        "5. “지구단위계획”이란 도시ㆍ군관리계획을 말한다.",
        "5의2. 삭제",
        "5의3. “성장관리계획”이란 계획을 말한다.",
        "6. “기반시설”이란 대통령령으로 정하는 시설을 말한다.",
    ]


def test_dates_are_still_not_split_into_items() -> None:
    """``2002. 12. 31.``의 월ㆍ일을 항목 번호로 잘라내지 않는다."""
    source = "이 규정은 2002. 12. 31. 부터 시행한다."

    assert insert_admin_clause_breaks(source).splitlines() == [source]


def test_item_markers_resume_from_line_leading_marker() -> None:
    """줄이 ``사.``로 시작해도 뒤따르는 아.ㆍ자.를 복원한다."""
    source = (
        "사. 도시혁신구역의 지정에 관한 계획과 도시혁신계획"
        "아. 복합용도구역의 지정에 관한 계획과 복합용도계획"
        "자. 도시ㆍ군계획시설입체복합구역의 지정에 관한 계획"
    )

    lines = insert_admin_clause_breaks(source).splitlines()

    assert lines == [
        "사. 도시혁신구역의 지정에 관한 계획과 도시혁신계획",
        "아. 복합용도구역의 지정에 관한 계획과 복합용도계획",
        "자. 도시ㆍ군계획시설입체복합구역의 지정에 관한 계획",
    ]


def test_late_item_markers_resume_through_neo() -> None:
    """제22조제7항제3호의 파.ㆍ하.ㆍ거.ㆍ너.도 각각 복원한다."""
    source = (
        "파. 하수도(하수종말처리시설에 한한다)"
        "하. 폐기물처리 및 재활용시설"
        "거. 수질오염방지시설"
        "너. 그 밖에 국토교통부령으로 정하는 시설"
    )

    assert insert_admin_clause_breaks(source).splitlines() == [
        "파. 하수도(하수종말처리시설에 한한다)",
        "하. 폐기물처리 및 재활용시설",
        "거. 수질오염방지시설",
        "너. 그 밖에 국토교통부령으로 정하는 시설",
    ]


def test_all_requested_item_markers_are_supported_through_heo() -> None:
    expected = "가나다라마바사아자차카타파하거너더러머버서어저처커터퍼허"

    assert KOREAN_ITEM_MARKERS == expected
    for marker in expected:
        assert LAW_ITEM_PATTERN.fullmatch(f"{marker}. 내용")
        reference = LAW_UNIT_REFERENCE_PATTERN.fullmatch(f"{marker}목")
        assert reference is not None
        assert reference.group("mok") == marker


def test_two_markers_are_not_enough_evidence() -> None:
    """표지가 둘뿐이면 문장 끝 글자와 구분되지 않으므로 자르지 않는다."""
    source = "나. 앞 항목 내용다. 뒤 항목 내용"

    assert insert_admin_clause_breaks(source).splitlines() == [source]


def test_announced_two_item_list_is_restored() -> None:
    """``다음 각 목의`` 예고 뒤 문장 끝에 붙은 목은 둘이어도 자른다."""
    source = (
        "8. “광역시설”이란 다음 각 목의 시설로서 대통령령으로 정하는 "
        "시설을 말한다."
        "가. 둘 이상의 관할 구역에 걸쳐 있는 시설"
        "나. 둘 이상이 공동으로 이용하는 시설"
    )

    lines = insert_admin_clause_breaks(source).splitlines()

    assert lines == [
        "8. “광역시설”이란 다음 각 목의 시설로서 대통령령으로 정하는 시설을 말한다.",
        "가. 둘 이상의 관할 구역에 걸쳐 있는 시설",
        "나. 둘 이상이 공동으로 이용하는 시설",
    ]


def test_announcement_does_not_split_inside_a_word() -> None:
    """``신청한 자가.``처럼 낱말 중간에서 시작하면 목록으로 보지 않는다."""
    source = "각 목의 기준에 따라 신청한 자가. 그 밖에 인정하는 자나. 관계인"

    assert insert_admin_clause_breaks(source).splitlines() == [source]


DECREE_25_CONTENT = (
    "① 법 제30조제2항에서 대통령령으로 정하는 중요한 사항이란 다음 "
    "각 호의 어느 하나에 해당하는 계획을 말한다.\n"
    "1. 광역도시계획과 관련한 계획\n"
    "2. 개발제한구역 해제 이후의 계획\n"
    "3. 국토교통부령이 정하는 도시ㆍ군관리계획\n"
    "② 법 제30조제3항 단서에 따라 공동위원회를 구성한다.\n"
    "③ 다음 각 호의 경우 법 제30조제5항 단서에 따른다.\n"
    "1. 다음 각 목의 경우\n"
    "가. 면적 변경\n"
    "나. 위치 변경\n"
    "다. 그 밖에 국토교통부령으로 정하는 경미한 사항의 변경\n"
    "6의3. 문화시설의 변경\n"
    "7. 그 밖에 국토교통부령이 정하는 경미한 사항의 변경\n"
    "⑦ 특별시장은 관계 서류를 송부하여야 한다.[제목개정 2012. 4. 10.]"
)

RULE_3_CONTENT = (
    "① 영 제25조제3항제1호다목에서 “국토교통부령으로 정하는 "
    "경미한 사항의 변경”이란 명칭 변경을 말한다.\n"
    "② 영 제25조제3항제6호의3에서 “국토교통부령으로 정하는 시설”이란 "
    "전시시설을 말한다.\n"
    "③ 영 제25조제3항제7호에서 “국토교통부령으로 정하는 경미한 사항의 "
    "변경”이란 용도지역 변경을 말한다."
)


def _article_30_payload(extra_decree: dict | None = None) -> dict:
    """제30조 위임이 두 건일 때 법제처가 법률 조를 반복 수록하는 형태."""
    named_decree = {
        "법령명": "국토의 계획 및 이용에 관한 법률 시행령",
        "조번호": "0025",
        "조가지번호": "00",
        "조제목": "제25조(도시ㆍ군관리계획의 결정)",
        "조내용": DECREE_25_CONTENT,
    }
    first = {
        "법령명": "국토의 계획 및 이용에 관한 법률",
        "조번호": "0030",
        "조가지번호": "00",
        "조제목": "제30조(도시ㆍ군관리계획의 결정)",
        "조내용": (
            "① 관계 행정기관의 장과 협의한다.\n"
            "② 대통령령으로 정하는 중요한 사항에 관한 도시ㆍ군관리계획을 "
            "결정하려면 미리 협의하여야 한다.\n"
            "③ 도시계획위원회의 심의를 거쳐야 한다.\n"
            "⑤ 경미한 사항은 대통령령으로 정한다."
        ),
        "시행령조문": named_decree,
        "시행규칙조문": [
            {
                "법령명": "국토의 계획 및 이용에 관한 법률 시행규칙",
                "조번호": "0002",
                "조가지번호": "03",
                "조제목": "제2조의3(국토교통부장관과 미리 협의하여야 하는 "
                "도시ㆍ군관리계획)",
                "조내용": (
                    "영 제25조제1항제3호에서 “국토교통부령이 정하는 "
                    "도시ㆍ군관리계획”이란 공원 면적 축소를 말한다."
                ),
            },
            {
                "법령명": "국토의 계획 및 이용에 관한 법률 시행규칙",
                "조번호": "0003",
                "조가지번호": "00",
                "조제목": "제3조(경미한 도시ㆍ군관리계획변경사항)",
                "조내용": RULE_3_CONTENT,
            },
        ],
    }
    articles: list[dict] = [first]
    if extra_decree is not None:
        articles.append(
            {
                "법령명": "국토의 계획 및 이용에 관한 법률",
                "조번호": "0030",
                "조가지번호": "00",
                "조제목": "제30조(도시ㆍ군관리계획의 결정)",
                "조내용": first["조내용"],
                "시행령조문": extra_decree,
            }
        )
    return {
        "LawService": {
            "기본정보": {"법령명": "국토의 계획 및 이용에 관한 법률"},
            "위임조문삼단비교": {"법률조문": articles},
        }
    }


def _comparison_column_pairs(html: str) -> list[tuple[str, str]]:
    """헤더를 뺀 각 행의 (시행령 칸, 시행규칙 칸). rowspan 뒤 2칸 행도 포함한다."""
    pairs: list[tuple[str, str]] = []
    for row in re.findall(r"<tr>(.*?)</tr>", html, re.DOTALL)[1:]:
        tds = re.findall(
            r'<td class="comparison-cell"[^>]*>(.*?)</td>',
            row,
            re.DOTALL,
        )
        if len(tds) == 3:
            pairs.append((tds[1], tds[2]))
        elif len(tds) == 2:
            pairs.append((tds[0], tds[1]))
    return pairs


def test_unnamed_repeated_decree_is_merged() -> None:
    """법령명이 비어 반복된 같은 시행령 조는 이름 있는 쪽만 남긴다."""
    named = {
        "법령명": "국토의 계획 및 이용에 관한 법률 시행령",
        "조번호": "0025",
        "조가지번호": "00",
        "조제목": "제25조(도시ㆍ군관리계획의 결정)",
        "조내용": DECREE_25_CONTENT,
    }
    unnamed = {
        "법령명": "",
        "조번호": "0025",
        "조가지번호": "00",
        "조제목": "제25조(도시ㆍ군관리계획의 결정)",
        "조내용": DECREE_25_CONTENT,
    }

    unique = ResourceSearchTab._deduplicate_three_stage_nodes(
        [unnamed, named, dict(unnamed)]
    )

    assert len(unique) == 1
    assert unique[0]["법령명"] == named["법령명"]


def test_hang_groups_keep_subparagraphs_with_their_paragraph() -> None:
    blocks = [
        {"hang": "000100", "ho": "", "html": "①"},
        {"hang": "000100", "ho": "000100", "html": "1."},
        {"hang": "000100", "ho": "000300", "html": "3."},
        {"hang": "000200", "ho": "", "html": "②"},
        {"hang": "000300", "ho": "", "html": "③"},
        {"hang": "000300", "ho": "000100", "html": "1."},
    ]
    groups = hang_groups_from_blocks(blocks)
    assert [[block["html"] for block in group] for group in groups] == [
        ["①", "1.", "3."],
        ["②"],
        ["③", "1."],
    ]


def test_different_statutes_with_same_article_number_stay_apart() -> None:
    unique = ResourceSearchTab._deduplicate_three_stage_nodes(
        [
            {
                "법령명": "국토의 계획 및 이용에 관한 법률 시행규칙",
                "조번호": "0045",
                "조가지번호": "00",
                "조제목": "제45조(가)",
                "조내용": "영 제25조제3항제7호에서 정한다.",
            },
            {
                "법령명": "수산자원관리법 시행규칙",
                "조번호": "0045",
                "조가지번호": "00",
                "조제목": "제45조(나)",
                "조내용": "영 제25조제3항제7호에서 정한다.",
            },
        ]
    )

    names = [node["법령명"] for node in unique]
    assert names == [
        "국토의 계획 및 이용에 관한 법률 시행규칙",
        "수산자원관리법 시행규칙",
    ]


def test_rule_decree_units_include_hang_and_item() -> None:
    units = ResourceSearchTab._decree_units_referenced_by_rule(
        "영 제25조제1항제3호에서 정하는 계획과 "
        "영 제25조제3항제1호다목에서 정하는 변경"
    )

    assert units[0]["article_code"] == "002500"
    assert units[0]["source_hang"] == "000100"
    assert units[0]["source_ho"] == "000300"
    assert units[1]["source_hang"] == "000300"
    assert units[1]["source_ho"] == "000100"
    assert units[1]["source_mok"] == "다"


def test_unnamed_repeated_decree_does_not_render_twice(tmp_path) -> None:
    tab = _tab(tmp_path)
    extra = {
        "법령명": "",
        "조번호": "0025",
        "조가지번호": "00",
        "조제목": "제25조(도시ㆍ군관리계획의 결정)",
        "조내용": DECREE_25_CONTENT,
    }
    html = tab._build_three_stage_comparison_html(
        _article_30_payload(extra),
        law_id="009294",
        law_name="국토의 계획 및 이용에 관한 법률",
        jo="003000",
        label="제30조(도시ㆍ군관리계획의 결정)",
    )

    assert html.count(">제25조(도시ㆍ군관리계획의 결정)<") == 1
    assert html.count('class="comparison-law-name">시행령<') == 0


def test_rule_aligns_to_decree_line_with_ministerial_ordinance(tmp_path) -> None:
    """시행규칙 제2조의3은 시행령 ① 제3호 국토교통부령 줄에 붙는다."""
    tab = _tab(tmp_path)
    html = tab._build_three_stage_comparison_html(
        _article_30_payload(),
        law_id="009294",
        law_name="국토의 계획 및 이용에 관한 법률",
        jo="003000",
        label="제30조(도시ㆍ군관리계획의 결정)",
    )
    pairs = _comparison_column_pairs(html)

    matched_item_3 = [
        (decree, rule)
        for decree, rule in pairs
        if "정하는 도시" in decree and "3.&nbsp;" in decree
    ]
    assert matched_item_3
    assert "제2조의3" in matched_item_3[0][1]
    assert "제3조(경미한" not in matched_item_3[0][1]

    matched_mok = [
        (decree, rule)
        for decree, rule in pairs
        if "다.&nbsp;" in decree and "정하는 경미한" in decree
    ]
    assert matched_mok
    assert "제3조(경미한" in matched_mok[0][1]
    assert "제25조제3항제1호다목" in matched_mok[0][1]
    assert "제25조제3항제7호" not in matched_mok[0][1]
    assert "제6호의3" not in matched_mok[0][1]

    matched_item_6_3 = [
        (decree, rule)
        for decree, rule in pairs
        if "6의3.&nbsp;" in decree
    ]
    assert matched_item_6_3
    assert "제25조제3항제6호의3" in matched_item_6_3[0][1]
    assert "제1호다목" not in matched_item_6_3[0][1]

    matched_item_7 = [
        (decree, rule)
        for decree, rule in pairs
        if "7.&nbsp;" in decree and "제25조제3항제7호" in rule
    ]
    assert matched_item_7
    assert "제25조제3항제7호" in matched_item_7[0][1]
    assert "제1호다목" not in matched_item_7[0][1]


def test_uncited_decree_paragraph_does_not_jump_to_the_top(tmp_path) -> None:
    """법 항을 인용하지 않은 시행령 ⑦은 법률 ① 위로 올라가지 않는다."""
    tab = _tab(tmp_path)
    html = tab._build_three_stage_comparison_html(
        _article_30_payload(),
        law_id="009294",
        law_name="국토의 계획 및 이용에 관한 법률",
        jo="003000",
        label="제30조(도시ㆍ군관리계획의 결정)",
    )
    law_rows = []
    for row in re.findall(r"<tr>(.*?)</tr>", html, re.DOTALL)[1:]:
        tds = re.findall(
            r'<td class="comparison-cell"[^>]*>(.*?)</td>',
            row,
            re.DOTALL,
        )
        if len(tds) == 3:
            law_rows.append(tds)

    law_one = next(tds for tds in law_rows if "①&nbsp;" in tds[0])
    assert "관계 서류를 송부" not in law_one[1]
    assert "제25조(도시" not in law_one[1]

    law_five = next(tds for tds in law_rows if "⑤&nbsp;" in tds[0])
    later_decree = "".join(
        decree
        for decree, _rule in _comparison_column_pairs(html)
        if "제30조제5항" in decree or "관계 서류를 송부" in decree
    )
    assert "관계 서류를 송부" in later_decree
    assert "관계 서류를 송부" not in law_five[0]


def test_decree_paragraph_two_aligns_to_law_paragraph_three(tmp_path) -> None:
    """시행령 ②가 법 제30조제3항을 들면 법률 ③ 옆에 붙는다."""
    tab = _tab(tmp_path)
    html = tab._build_three_stage_comparison_html(
        _article_30_payload(),
        law_id="009294",
        law_name="국토의 계획 및 이용에 관한 법률",
        jo="003000",
        label="제30조(도시ㆍ군관리계획의 결정)",
    )
    law_rows = []
    for row in re.findall(r"<tr>(.*?)</tr>", html, re.DOTALL)[1:]:
        tds = re.findall(
            r'<td class="comparison-cell"[^>]*>(.*?)</td>',
            row,
            re.DOTALL,
        )
        if len(tds) == 3:
            law_rows.append(tds)

    law_two = next(tds for tds in law_rows if "②&nbsp;" in tds[0])
    law_three = next(tds for tds in law_rows if "③&nbsp;" in tds[0])

    assert "제30조제2항" in law_two[1]
    assert "공동위원회" not in law_two[1]
    assert "공동위원회" in law_three[1]
    assert "제30조제3항" in law_three[1]
    assert "제30조제2항" not in law_three[1]


def test_duplicate_decree_links_collapse_to_named_article() -> None:
    extra = {
        "법령명": "시행령",
        "조번호": "0025",
        "조가지번호": "00",
        "조제목": "제25조(도시ㆍ군관리계획의 결정)",
        "조내용": DECREE_25_CONTENT,
    }
    links = ResourceSearchTab._three_stage_subordinate_links(
        _article_30_payload(extra),
        document_level="law",
    )

    decree_links = [
        link
        for link in links["003000"]
        if link.get("target_code") == "002500"
        and link.get("source_hang") == "000200"
    ]
    assert len(decree_links) == 1
    assert decree_links[0].get("law_name") != "시행령"
    assert decree_links[0].get("law_name") == (
        "국토의 계획 및 이용에 관한 법률 시행령"
    )


def test_announcement_needs_markers_in_order() -> None:
    """예고가 있어도 가.부터 순서대로가 아니면 자르지 않는다."""
    source = "다음 각 목의 사항을 말한다.나. 어떤 것다. 다른 것"

    assert insert_admin_clause_breaks(source).splitlines() == [source]
