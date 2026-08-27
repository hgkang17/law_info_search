import os
import re
from urllib.parse import quote

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui.tabs.resource_search import ResourceSearchTab


def test_successful_comparison_lookup_marks_empty_articles_unavailable() -> None:
    articles = [
        {"jo": "000300", "label": "제3조"},
        {"jo": "000400", "label": "제4조"},
    ]
    links = {
        "000400": [{"href": "lawref://open?name=시행령&jo=4", "text": "시행령 제4조"}]
    }

    updated = ResourceSearchTab._apply_subordinate_links_to_articles(
        articles, links
    )

    assert updated[0]["comparison_available"] is False
    assert updated[1]["comparison_available"] is True


def test_rule_article_resolves_inside_parent_law_article() -> None:
    articles = [
        {
            "조번호": "0028",
            "조가지번호": "00",
            "조제목": "제28조(주민과 지방의회의 의견 청취)",
            "시행령조문": {
                "법령명": "국토의 계획 및 이용에 관한 법률 시행령",
                "조번호": "0022",
                "조가지번호": "00",
                "조제목": "제22조(주민 및 지방의회의 의견청취)",
                "조내용": "법 제28조제5항 및 제6항에 따른다.",
            },
            "시행규칙조문": {
                "법령명": "국토의 계획 및 이용에 관한 법률 시행규칙",
                "조번호": "0002",
                "조가지번호": "02",
                "조제목": "제2조의2(주민과 지방의회의 의견 청취)",
                "조내용": "영 제22조제7항제3호너목에서 정하는 시설을 말한다.",
            },
        }
    ]

    resolved = ResourceSearchTab._resolve_three_stage_article_nodes(
        articles,
        law_name="국토의 계획 및 이용에 관한 법률 시행규칙",
        jo="000202",
    )

    assert resolved is not None
    base, decrees, rules = resolved
    assert base["조번호"] == "0028"
    assert [node["조번호"] for node in decrees] == ["0022"]
    assert [node["조가지번호"] for node in rules] == ["02"]


def test_decree_article_is_available_without_a_connected_rule() -> None:
    payload = {
        "LawService": {
            "위임조문삼단비교": {
                "법률조문": {
                    "조번호": "0002",
                    "시행령조문": {
                        "법령명": "국토의 계획 및 이용에 관한 법률 시행령",
                        "조번호": "0002",
                        "조가지번호": "00",
                        "조제목": "제2조(기반시설)",
                        "조내용": "법 제2조제6호에서 위임된 사항",
                    },
                }
            }
        }
    }

    links = ResourceSearchTab._three_stage_subordinate_links(
        payload, document_level="decree"
    )
    updated = ResourceSearchTab._apply_subordinate_links_to_articles(
        [{"jo": "000200", "label": "제2조(기반시설)"}], links
    )

    assert links == {"000200": []}
    assert updated[0]["subordinate_links"] == []
    assert updated[0]["comparison_available"] is True


def test_department_html_space_is_normalized_for_rule_links() -> None:
    rule_name = "국토의 계획 및 이용에 관한 법률 시행규칙"
    payload = {
        "LawService": {
            "위임조문삼단비교": {
                "법률조문": {
                    "조번호": "0043",
                    "시행령조문": {
                        "법령명": "국토의 계획 및 이용에 관한 법률 시행령",
                        "조번호": "0035",
                        "조내용": "국토교통부령으로 정하는 시설",
                    },
                    "시행규칙조문": {
                        "법령명": rule_name,
                        "조번호": "0006",
                        "조제목": "제6조(시설)",
                        "조내용": "영 제35조제1항에 따른 시설",
                    },
                }
            }
        }
    }

    links = ResourceSearchTab._three_stage_subordinate_links(
        payload,
        document_level="decree",
        organization="국토교통부&#x20;",
    )

    assert links["003500"][0]["text"] == "국토교통부령 제6조"
    assert f"name={quote(rule_name, safe='')}" in links["003500"][0]["href"]

    law_links = ResourceSearchTab._three_stage_subordinate_links(
        payload,
        document_level="law",
        organization="국토교통부&#x20;",
    )
    assert any(
        link["text"] == "국토교통부령 제6조"
        for link in law_links["004300"]
    )


def test_direct_ministerial_delegation_keeps_actual_rule_name() -> None:
    actual_rule_name = "도시ㆍ군계획시설의 결정ㆍ구조 및 설치기준에 관한 규칙"
    payload = {
        "LawService": {
            "위임조문삼단비교": {
                "법률조문": {
                    "조번호": "0043",
                    "조내용": "필요한 사항은 국토교통부령으로 정한다.",
                    "시행규칙조문": {
                        "법령명": actual_rule_name,
                        "조번호": "0002",
                        "조제목": "제2조(도시ㆍ군계획시설결정의 범위)",
                        "조내용": "법 제43조제3항에 따른 기준을 정한다.",
                    },
                }
            }
        }
    }

    links = ResourceSearchTab._three_stage_subordinate_links(
        payload,
        document_level="law",
        organization="국토교통부",
    )

    link = links["004300"][0]
    assert link["text"] == "국토교통부령 제2조"
    assert f"name={quote(actual_rule_name, safe='')}" in link["href"]
    assert "시행규칙" not in link["href"]


def test_rule_buttons_only_exist_for_rules_in_comparison_payload() -> None:
    rule_name = "국토의 계획 및 이용에 관한 법률 시행규칙"
    payload = {
        "LawService": {
            "위임조문삼단비교": {
                "법률조문": {
                    "조번호": "0028",
                    "시행규칙조문": {
                        "법령명": rule_name,
                        "조번호": "0002",
                        "조가지번호": "00",
                        "조제목": "제2조(주민과 지방의회의 의견 청취)",
                        "조내용": "법 제28조에 따른다.",
                    },
                }
            }
        }
    }

    links = ResourceSearchTab._three_stage_subordinate_links(
        payload, document_level="rule"
    )
    updated = ResourceSearchTab._apply_subordinate_links_to_articles(
        [
            {"jo": "000100", "label": "제1조(목적)"},
            {"jo": "000200", "label": "제2조(주민과 지방의회의 의견 청취)"},
        ],
        links,
    )

    assert links == {"000200": []}
    assert updated[0]["comparison_available"] is False
    assert updated[1]["comparison_available"] is True


def test_rule_comparison_uses_parent_law_name_in_law_column() -> None:
    tab = ResourceSearchTab.__new__(ResourceSearchTab)
    parent_law_name = "국토의 계획 및 이용에 관한 법률"
    rule_name = f"{parent_law_name} 시행규칙"
    payload = {
        "LawService": {
            "기본정보": {"법령명": rule_name},
            "위임조문삼단비교": {
                "법률조문": {
                    "조번호": "0041",
                    "조가지번호": "00",
                    "조제목": "제41조(공유수면매립 준공인가의 통보)",
                    "조내용": "대통령령으로 정하는 바에 따라 통보한다.",
                    "시행령조문": {
                        "법령명": f"{parent_law_name} 시행령",
                        "조번호": "0035",
                        "조가지번호": "00",
                        "조제목": "제35조(통보 방법)",
                        "조내용": "국토교통부령으로 정하는 방법에 따른다.",
                    },
                    "시행규칙조문": {
                        "법령명": rule_name,
                        "조번호": "0004",
                        "조가지번호": "00",
                        "조제목": "제4조(공유수면매립 준공인가의 통보)",
                        "조내용": "법 제41조제3항에 따라 통보한다.",
                    },
                }
            },
        }
    }

    html = tab._build_three_stage_comparison_html(
        payload,
        law_id="009469",
        law_name=rule_name,
        jo="000400",
        label="제4조(공유수면매립 준공인가의 통보)",
    )
    assert "table-layout:fixed; border:none" in html
    assert ".comparison-table td { border:none; padding:0; }" in html
    assert "vertical-align:top; padding:0 3px;" in html
    assert ".comparison-edge, .comparison-divider { width:1px;" in html
    assert "font-size:1px; line-height:1px; padding:0;" in html
    assert html.count('class="comparison-horizontal-rule"') == 2
    assert ".comparison-item { border:none;" in html
    assert "border-bottom:1px solid #dce6ef" not in html
    law_cell_match = re.search(
        r'<td class="comparison-cell"(?: rowspan="\d+")?>(.*?)</td>',
        html,
        re.DOTALL,
    )
    assert law_cell_match is not None
    law_column = law_cell_match.group(1)
    headers = re.findall(r"<th>([^<]*)</th>", html)

    # 법령명은 열 머리에만 적는다. 법률 열 머리가 모법명이어야 하고,
    # 조문 칸에는 법령명이 다시 나오지 않는다.
    assert headers[0] == parent_law_name
    assert headers[2] == rule_name
    assert "시행규칙" not in law_column
    assert 'class="comparison-law-name"' not in law_column
    assert (
        f"lawref://open?name={quote(parent_law_name, safe='')}&amp;jo=41"
        in html
    )
    assert (
        f"lawref://open?name={quote(rule_name, safe='')}&amp;jo=4"
        in html
    )
    assert ">대통령령</a>으로 정하는" in html
    assert ">국토교통부령</a>으로 정하는" in html


def test_article_43_paragraph_3_uses_specific_molit_rule() -> None:
    link = ResourceSearchTab._specific_ministerial_rule_link(
        {
            "law_name": "국토의 계획 및 이용에 관한 법률",
            "jo": "004300",
        },
        "국토교통부령",
        "000300",
    )

    assert link is not None
    assert link["text"] == "도시ㆍ군계획시설의 결정ㆍ구조 및 설치기준에 관한 규칙"
    assert "시행규칙" not in link["href"]
    assert quote(link["text"], safe="") in link["href"]


def test_specific_molit_rule_does_not_override_other_paragraphs() -> None:
    assert (
        ResourceSearchTab._specific_ministerial_rule_link(
            {
                "law_name": "국토의 계획 및 이용에 관한 법률",
                "jo": "004300",
            },
            "국토교통부령",
            "000200",
        )
        is None
    )


def test_decree_article_2_paragraph_3_uses_facility_rule() -> None:
    link = ResourceSearchTab._specific_ministerial_rule_link(
        {
            "law_name": "국토의 계획 및 이용에 관한 법률 시행령",
            "jo": "000200",
        },
        "국토교통부령",
        "000300",
    )

    assert link is not None
    assert link["text"] == "도시ㆍ군계획시설의 결정ㆍ구조 및 설치기준에 관한 규칙"


def test_three_stage_comparison_restores_inline_korean_item_breaks() -> None:
    _app = QApplication.instance() or QApplication([])
    tab = ResourceSearchTab.__new__(ResourceSearchTab)
    payload = {
        "LawService": {
            "기본정보": {"법령명": "국토의 계획 및 이용에 관한 법률 시행령"},
            "위임조문삼단비교": {
                "법률조문": {
                    "법령명": "국토의 계획 및 이용에 관한 법률",
                    "조번호": "0035",
                    "조가지번호": "00",
                    "조제목": "제35조(도시ㆍ군계획시설의 설치ㆍ관리)",
                    "조내용": (
                        "① 다음 각 호의 경우를 말한다.\n"
                        "② 이미 줄바꿈된 항도 함께 있다.\n"
                        "③ 이 조문은 전체적으로 줄바꿈이 충분하다.\n"
                        "1. 기반시설을 설치하는 경우가. 주차장 및 공공공지와 "
                        "폐차장나. 도시공원 및 녹지다. 그 밖의 시설"
                    ),
                }
            },
        }
    }

    html = tab._build_three_stage_comparison_html(
        payload,
        law_id="001234",
        law_name="국토의 계획 및 이용에 관한 법률",
        jo="003500",
        label="제35조(도시ㆍ군계획시설의 설치ㆍ관리)",
    )

    assert '<span class="bullet-marker"' in html
    assert "가.&nbsp;" in html
    assert "나.&nbsp;" in html
    assert "다.&nbsp;" in html
    assert "경우가." not in html
    assert "폐차장나." not in html
