"""조ㆍ항ㆍ호ㆍ목을 조각마다 링크로 나누고, 팝업 안 대통령령을 잇는지 검증."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import re
from urllib.parse import unquote

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab
from utils.formatting import body_to_html, law_reference_html_text


LAW_NAME = "국토의 계획 및 이용에 관한 법률"


def _tab(tmp_path) -> ResourceSearchTab:
    QApplication.instance() or QApplication([])
    settings = QSettings(
        str(tmp_path / "reference.ini"), QSettings.Format.IniFormat
    )
    return ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )


def _links(html: str) -> list[tuple[str, str]]:
    return [
        (unquote(text), unquote(href.replace("&amp;", "&")))
        for href, text in re.findall(
            r'<a href="([^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL
        )
    ]


def test_each_unit_of_a_citation_opens_its_own_range() -> None:
    """법제처처럼 조ㆍ항ㆍ호가 각각 제 범위의 링크가 된다."""
    html = law_reference_html_text(
        f"「{LAW_NAME}」 제76조제5항제1호의2에 따라",
        (),
        use_api_links=True,
    )
    links = _links(html)

    assert [text for text, _ in links] == [
        f"「{LAW_NAME}」 제76조",
        "제5항",
        "제1호의2",
    ]
    assert links[0][1].endswith("&jo=76")
    assert links[1][1].endswith("&jo=76&hang=5")
    assert links[2][1].endswith("&jo=76&hang=5&ho=1&ho_branch=2")


def test_sibling_citation_units_split_without_touching_the_prefix() -> None:
    """``법 제76조제5항``도 접두어는 평문으로 두고 조ㆍ항만 나눈다."""
    html = law_reference_html_text(
        "법 제76조제5항에 따라",
        (),
        current_law_name=f"{LAW_NAME} 시행령",
        use_api_links=True,
    )
    links = _links(html)

    assert html.startswith("법 <a href=")
    assert [text for text, _ in links] == ["제76조", "제5항"]
    assert links[0][1].endswith("&jo=76")
    assert links[1][1].endswith("&jo=76&hang=5")


def test_mok_unit_keeps_the_narrower_range() -> None:
    html = law_reference_html_text(
        f"「{LAW_NAME}」 제2조제6호가목",
        (),
        use_api_links=True,
    )
    links = _links(html)

    assert [text for text, _ in links][-1] == "가목"
    assert links[-1][1].endswith("&jo=2&ho=6&mok=가")


def test_web_link_citation_stays_one_anchor() -> None:
    """프로그램 밖 웹 주소는 조까지만 가리키므로 예전처럼 한 링크로 둔다."""
    html = law_reference_html_text(
        f"「{LAW_NAME}」 제76조제5항제1호의2",
        (),
        use_api_links=False,
    )

    assert len(_links(html)) == 1


def _three_stage_payload() -> dict:
    return {
        "LawService": {
            "기본정보": {"법령명": LAW_NAME},
            "위임조문삼단비교": {
                "법률조문": [
                    {
                        "법령명": LAW_NAME,
                        "조번호": "0076",
                        "조가지번호": "00",
                        "조제목": "제76조(용도지역 및 용도지구에서의 건축물의 제한 등)",
                        "조내용": (
                            "⑤ 다음 각 호의 어느 하나에 해당하는 경우에는 "
                            "대통령령으로 정하는 바에 따른다.\n"
                            "1의2. 「자연공원법」에 따른 공원구역"
                        ),
                        "시행령조문": {
                            "법령명": f"{LAW_NAME} 시행령",
                            "조번호": "0083",
                            "조가지번호": "00",
                            "조제목": "제83조(용도지역ㆍ용도지구 및 용도구역안에서의 건축제한의 예외 등)",
                            "조내용": "법 제76조제5항 각 호에 따른 건축물의 제한은 다음과 같다.",
                        },
                    }
                ]
            },
        }
    }


def test_popup_reuses_cached_three_stage_data_for_the_decree_link(
    tmp_path,
) -> None:
    """팝업 조문 속 ``대통령령``도 받아 둔 3단비교 자료로 링크가 된다."""
    tab = _tab(tmp_path)
    tab._three_stage_payload_cache["009294"] = _three_stage_payload()

    links = tab._popup_authority_links(LAW_NAME, "007600", "000500")

    assert "대통령령" in links
    assert "jo=83" in links["대통령령"]
    # 하단 기록에 어느 조문이 위임했는지 남는다.
    assert "via_label" in links["대통령령"]


def test_popup_does_not_borrow_another_law_three_stage_data(tmp_path) -> None:
    """법령명이 다르면 조 번호가 같아도 그 시행령을 걸지 않는다."""
    tab = _tab(tmp_path)
    tab._three_stage_payload_cache["000000"] = _three_stage_payload()

    assert tab._popup_authority_links("건축법", "007600") == {}


def test_popup_authority_mention_becomes_a_link(tmp_path) -> None:
    tab = _tab(tmp_path)
    tab._three_stage_payload_cache["009294"] = _three_stage_payload()
    links = tab._popup_authority_links(LAW_NAME, "007600", "000500")

    text, tokens = ResourceSearchTab._mask_authority_mentions(
        "⑤ 대통령령으로 정하는 바에 따른다.", links
    )
    html = ResourceSearchTab._restore_authority_mentions(
        body_to_html(text, (), current_law_name=LAW_NAME, use_api_links=True),
        tokens,
    )

    assert ">대통령령</a>" in html
    assert "jo=83" in html.replace("&amp;", "&")
