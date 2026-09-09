"""법률 목(가.ㆍ나.) 분리와 목 단위 위임 링크 선택.

국토계획법 제26조가 사례다. 제1항제3호가 ``... 지정 및 변경에 관한 사항``
처럼 명사로 끝나고 그 뒤에 ``가. ... 나. ...``가 줄바꿈 없이 붙어 온다.
목이 나뉘지 않으면 3단비교 표도 위임 링크도 목 단위를 찾지 못해 조문
맨 윗줄로 밀린다.
"""

import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ui.tabs.resource_search import ResourceSearchTab
from utils.parsing import insert_admin_clause_breaks


LAW_26_CONTENT = (
    "①  주민(이해관계자를 포함한다. 이하 같다)은 다음 각 호의 사항에 "
    "대하여 제24조에 따라 도시ㆍ군관리계획을 입안할 수 있는 자에게 "
    "도시ㆍ군관리계획의 입안을 제안할 수 있다.\n"
    "3.  다음 각 목의 어느 하나에 해당하는 용도지구의 지정 및 변경에 "
    "관한 사항"
    "가.  개발진흥지구 중 공업기능 또는 유통물류기능 등을 집중적으로 "
    "개발ㆍ정비하기 위한 개발진흥지구로서 대통령령으로 정하는 개발진흥지구"
    "나.  제37조에 따라 지정된 용도지구 중 해당 용도지구에 따른 건축물이나 "
    "그 밖의 시설의 용도ㆍ종류 및 규모 등의 제한을 지구단위계획으로 "
    "대체하기 위한 용도지구\n"
    "④  제1항제3호에 따른 개발진흥지구의 지정 제안을 위하여 충족하여야 할 "
    "지구의 규모, 용도지역 등의 요건은 대통령령으로 정한다.\n"
    "⑤  제1항부터 제4항까지에 규정된 사항 외에 도시ㆍ군관리계획의 제안, "
    "제안을 위한 토지소유자의 동의 비율, 제안서의 처리 절차 등에 필요한 "
    "사항은 대통령령으로 정한다."
)


def test_announced_items_split_when_the_intro_ends_with_a_noun() -> None:
    """``다음 각 목``을 예고했으면 예고 문장이 마침표로 끝나지 않아도 자른다."""
    source = (
        "3. 다음 각 목의 어느 하나에 해당하는 용도지구의 지정 및 변경에 "
        "관한 사항"
        "가. 개발진흥지구로서 대통령령으로 정하는 개발진흥지구"
        "나. 지구단위계획으로 대체하기 위한 용도지구"
    )

    lines = insert_admin_clause_breaks(source).splitlines()

    assert lines == [
        "3. 다음 각 목의 어느 하나에 해당하는 용도지구의 지정 및 변경에 관한 사항",
        "가. 개발진흥지구로서 대통령령으로 정하는 개발진흥지구",
        "나. 지구단위계획으로 대체하기 위한 용도지구",
    ]


def test_plain_mention_of_items_still_needs_three_markers() -> None:
    """``다음``이 없는 ``각 목`` 언급은 종전대로 셋을 요구한다."""
    source = "각 목의 기준에 따라 신청한 자가. 그 밖에 인정하는 자나. 관계인"

    assert insert_admin_clause_breaks(source).splitlines() == [source]


def _subordinate_links() -> list[dict[str, str]]:
    """국토계획법 제26조에 걸리는 시행령 링크(실제 3단비교 응답 구조)."""
    return [
        {
            "text": "대통령령 제19조의2",
            "href": "lawref://open?name=시행령&jo=001902",
            "target_code": "001902",
            "source_hang": "000100",
            "source_ho": "000300",
            "source_mok": "가",
        },
        {
            "text": "대통령령 제19조의2",
            "href": "lawref://open?name=시행령&jo=001902",
            "target_code": "001902",
            "source_hang": "000100",
            "source_ho": "",
            "source_mok": "",
        },
        {
            "text": "대통령령 제19조의2",
            "href": "lawref://open?name=시행령&jo=001902",
            "target_code": "001902",
            "source_hang": "000400",
            "source_ho": "",
            "source_mok": "",
        },
        {
            "text": "대통령령 제20조",
            "href": "lawref://open?name=시행령&jo=002000",
            "target_code": "002000",
            "source_hang": "000100",
            "source_ho": "",
            "source_mok": "",
        },
    ]


def _matched_at(article_text: str, occurrence: int) -> list[dict[str, str]]:
    index = ResourceSearchTab._build_inline_source_index(article_text)
    positions = [
        match.start() for match in re.finditer("대통령령", article_text)
    ]
    hang, ho, mok = ResourceSearchTab._inline_law_source_context(
        positions[occurrence], *index
    )
    return ResourceSearchTab._links_for_inline_source(
        _subordinate_links(), hang, ho, mok
    )


def test_mok_delegation_picks_exactly_one_target() -> None:
    """제1항제3호가목의 ``대통령령``은 목까지 짚은 시행령 하나만 연다."""
    article_text = insert_admin_clause_breaks(LAW_26_CONTENT)

    matched = _matched_at(article_text, 0)

    assert [link["text"] for link in matched] == ["대통령령 제19조의2"]
    assert matched[0]["source_mok"] == "가"


def test_hang_delegation_does_not_pull_in_other_paragraphs() -> None:
    """제4항의 ``대통령령``은 제4항을 짚은 조문만 연다."""
    article_text = insert_admin_clause_breaks(LAW_26_CONTENT)

    matched = _matched_at(article_text, 1)

    assert [link["source_hang"] for link in matched] == ["000400"]


def test_unreferenced_paragraph_still_offers_the_articles_of_that_jo() -> None:
    """어느 시행령도 짚지 않은 항이라도 그 조의 위임 조문은 고를 수 있다."""
    article_text = insert_admin_clause_breaks(LAW_26_CONTENT)

    matched = _matched_at(article_text, 2)

    # 같은 조문이 근거 항만 달리해 여러 번 들어 있어도 여는 곳 기준으로
    # 하나씩만 남는다.
    assert sorted(link["target_code"] for link in matched) == [
        "001902",
        "002000",
    ]
