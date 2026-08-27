"""ui/tabs/ai_chat_panel.py의 순수 변환 로직 검증.

화면 없이도 확인할 수 있는 부분만 다룬다 — 실제 위젯 렌더링ㆍ네트워크
호출은 이 파일이 아니라 수동 검증으로 이미 확인했다.
"""

import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ui.tabs.ai_chat_panel import AiChatPanel


def test_to_html_converts_citation_link() -> None:
    """모델 인용은 본문 화면과 같은 조항호목 링크(lawref)로 바꾼다."""
    text = "[농지법 제1조](law:000479:0001)에 따르면..."
    html = AiChatPanel._to_html(text)
    assert "lawref://open?" in html
    assert "id=000479" in html
    assert "jo=1" in html
    assert ">「농지법」 제1조</a>" in html
    assert "law:000479" not in html


def test_to_html_opens_annex_even_if_model_used_a_law_article_id() -> None:
    """별표 1 라벨에 제3조의5 주소를 붙이면 조문 팝업이 열렸다."""
    text = "[건축법 시행령 별표 1](law:002118:000305)을 클릭"
    html = AiChatPanel._to_html(text)
    assert "annexref://open?" in html
    assert "lawref://open?" not in html
    assert "별표 1" in html


def test_to_html_converts_document_link() -> None:
    text = "[도시ㆍ군관리계획수립지침](doc:admrul:2100000282348)을 보면"
    html = AiChatPanel._to_html(text)
    assert 'href="doc:admrul:2100000282348"' in html


def test_to_html_link_survives_alongside_bold() -> None:
    text = "**중요**: [농지법 제1조](law:000479:0001)"
    html = AiChatPanel._to_html(text)
    assert "<b>중요</b>" in html
    assert "lawref://open?" in html


def test_to_html_does_not_linkify_plain_brackets() -> None:
    """법이 아닌 일반 괄호 텍스트를 링크로 착각하면 안 된다."""
    text = "[참고] 이 조문은 예외가 있습니다"
    html = AiChatPanel._to_html(text)
    assert "<a href=" not in html


def test_to_html_escapes_text_inside_link_label() -> None:
    """인용 제목에 <, > 같은 문자가 섞여도 태그로 새면 안 된다."""
    text = "[<제1조>](law:000479:0001)"
    html = AiChatPanel._to_html(text)
    assert "&lt;제1조&gt;" in html
    assert "<제1조>" not in html


def test_to_html_keeps_numbered_list_markers() -> None:
    html = AiChatPanel._to_html("1. 허가 대상\n2. 예외")
    assert "1. 허가 대상" in html
    assert "2. 예외" in html
    assert "text-indent:-16px" in html


def test_to_html_uses_hanging_indent_for_bullets() -> None:
    html = AiChatPanel._to_html(
        "• 지정 요청: 문장이 길어져 다음 줄로 넘어가는 내용"
    )
    assert "text-indent:-12px" in html
    assert "• 지정 요청" in html


def test_to_html_linkifies_plain_sibling_articles() -> None:
    """마크다운을 빠뜨린 법·시행령·제N조도 눌러 열 수 있게 한다."""
    html = AiChatPanel._to_html(
        "[공공주택 특별법 제6조](law:012345:000600)\n"
        "(법 제17조제1항 단서)\n"
        "(제18조제2항)\n"
        "(시행령 제7조제5항)"
    )
    assert html.count("<a ") >= 4
    assert "jo=6" in html
    assert "jo=17" in html
    assert "hang=1" in html
    assert "jo=18" in html
    assert "hang=2" in html
    assert "jo=7" in html
    assert "hang=5" in html
    assert "id=012345" in html
    assert "%EC%8B%9C%ED%96%89%EB%A0%B9" in html  # 시행령


def test_to_html_joins_spaced_hang_into_one_article_link() -> None:
    """채팅에서만 `제27조 제4항`을 한 링크로 붙인다. 본문 정규식은 그대로다."""
    html = AiChatPanel._to_html(
        "「국토의 계획 및 이용에 관한 법률」\n"
        "기초조사 생략 요건 (국토계획법 제27조 제4항)"
    )
    assert "jo=27" in html
    assert "hang=4" in html
    assert "제27조제4항" in html
    assert re.search(r">제27조제4항</a>", html)
    hrefs = re.findall(r'href="([^"]+)"', html)
    article_links = [href for href in hrefs if "jo=27" in href]
    assert article_links
    assert all("hang=4" in href for href in article_links)


def test_squeeze_spaced_units_does_not_join_two_articles() -> None:
    assert (
        AiChatPanel._squeeze_spaced_law_units("제1조 제2조") == "제1조 제2조"
    )


def test_to_html_does_not_double_link_markdown_citations() -> None:
    html = AiChatPanel._to_html("[농지법 제1조](law:000479:0001)")
    assert html.count("<a ") == 1
    assert html.count("lawref://") == 1


def test_to_html_treats_circled_numbers_as_section_headers() -> None:
    html = AiChatPanel._to_html(
        "① 허가 대상\n1. 첫 번째\n근거: 「농지법」 제8조"
    )
    assert "font-weight:700" in html
    assert "① 허가 대상" in html
    assert "font-size:12px" in html
    assert "color:#5a6a7a" in html
    assert "jo=8" in html


def test_citation_to_href_keeps_hang_and_ho() -> None:
    href = AiChatPanel._citation_to_href(
        "국토의 계획 및 이용에 관한 법률 제2조제8호",
        "law:009294:000200",
    )
    assert href.startswith("lawref://open?")
    assert "id=009294" in href
    assert "jo=2" in href
    assert "ho=8" in href
    assert "name=" in href


def test_citation_to_href_sends_annex_label_to_annex_preview() -> None:
    href = AiChatPanel._citation_to_href(
        "건축법 시행령 별표 1",
        "law:002118:000305",
    )
    assert href.startswith("annexref://open?")
    assert "category=licbyl" in href
    assert "related=" in href
    assert "jo=" not in href


def test_bare_annex_label_keeps_related_law_name() -> None:
    """라벨이 '별표 1'만이면 답의 법령명으로 검색해야 한다."""
    href = AiChatPanel._citation_to_href(
        "별표 1",
        "law:000572:000305",
        related_name="건축법 시행령",
    )
    assert href.startswith("annexref://open?")
    assert "related=" in href
    html = AiChatPanel._to_html(
        "[건축법 시행령 제3조의5](law:000572:000305) "
        "[별표 1](law:000572:000100)"
    )
    assert "annexref://open?" in html
    assert "related=" in html
    assert "lawref://open?" in html


def test_citation_to_href_decodes_branch_article() -> None:
    href = AiChatPanel._citation_to_href(
        "국토계획법 제12조의2",
        "law:001866:001202",
    )
    assert "id=001866" in href
    assert "jo=12" in href
    assert "jo_branch=2" in href


def test_annex_form_link_does_not_open_article_popup() -> None:
    """별지 서식을 조문 팝업의 제9999조로 열면 안 된다."""
    href = AiChatPanel._citation_to_href(
        "공공주택 특별법 시행규칙 별지 제1호서식",
        "law:005233:999999",
    )
    assert href.startswith("annexref://open?")
    assert "category=licbyl" in href
    assert "jo=" not in href
    html = AiChatPanel._to_html(
        "[공공주택 특별법 시행규칙 별지 제1호서식](law:005233:999999)"
    )
    assert "annexref://open?" in html
    assert "lawref://" not in html


def test_annex_doc_link_keeps_serial_id() -> None:
    href = AiChatPanel._citation_to_href(
        "별지 제1호서식",
        "doc:licbyl:12345",
    )
    assert href.startswith("annexref://open?")
    assert "id=12345" in href
    assert "category=licbyl" in href


def test_inquiry_doc_link_is_not_treated_as_admin_rule() -> None:
    """질의회신을 행정규칙 id로 열면 법제처가 500을 낸다."""
    href = AiChatPanel._citation_to_href(
        "기초조사 등이 불필요한 도시계획시설의 폐지의 의미",
        "doc:admrul:molitCgmExpc:360866",
    )
    assert href == "doc:molitCgmExpc:360866"
    html = AiChatPanel._to_html(
        "[기초조사 등이 불필요한 도시계획시설의 폐지의 의미]"
        "(doc:admrul:molitCgmExpc:360866)"
    )
    assert "doc:molitCgmExpc:360866" in html
    assert "doc:admrul:molitCgmExpc" not in html


def test_document_link_goes_to_reference_handler() -> None:
    """행정규칙 링크도 본문 화면 팝업으로 넘긴다."""
    opened: list[str] = []

    class _Host:
        reference_handler = staticmethod(
            lambda url: opened.append(url.toString())
        )

    AiChatPanel._article_link_clicked(_Host(), "doc:admrul:2100000282348")
    assert opened == ["doc:admrul:2100000282348"]
    opened.clear()
    AiChatPanel._article_link_clicked(
        _Host(),
        "annexref://open?name=별지&category=licbyl",
    )
    assert opened[0].startswith("annexref://open?")


def test_verification_html_uses_lawref() -> None:
    from llm.verify_citations import (
        CitationCheck,
        STATUS_MISSING,
        STATUS_VERIFIED,
        verification_html,
    )

    html = verification_html(
        [
            CitationCheck(
                label="농지법 제1조",
                status=STATUS_VERIFIED,
                href="lawref://open?id=000479&jo=1",
            ),
            CitationCheck(
                label="농지법 제999조",
                status=STATUS_MISSING,
                href="lawref://open?id=000479&jo=999",
            ),
        ]
    )
    assert "사용한 법령 조문" in html
    assert "확인됨" not in html
    assert "존재하지 않음" not in html
    assert "「농지법」 제1조" in html
    assert "lawref://open?id=000479" in html
    assert "href=" in html
def test_markdown_table_becomes_a_real_table() -> None:
    """| 번호 | 용도 | 로 쓴 표를 세로 막대째 보여 주면 읽을 수 없다."""
    answer = (
        "| 번호 | 용도 | 세부 |\n"
        "|---|:---:|---|\n"
        "| 1 | 단독주택 | 다가구주택 |\n"
        "| 2 | 공동주택 | 아파트 |\n"
    )
    html = AiChatPanel._to_html(answer)
    assert "<table" in html
    assert html.count("<tr>") == 3
    assert "단독주택" in html
    # 세로 막대가 글자로 남아 있으면 안 된다.
    assert "| 번호 |" not in html
    # 가운데 맞춤을 적어 두면 그대로 따른다.
    assert 'align="center"' in html


def test_lines_that_only_look_like_tables_stay_text() -> None:
    """머리줄과 본문을 가르는 줄이 없으면 표가 아니다."""
    html = AiChatPanel._to_html("| 하나 | 둘 |\n| 셋 | 넷 |")
    assert "<table" not in html


def test_list_indent_counts_steps_not_spaces() -> None:
    """모델이 두 칸을 쓰든 네 칸을 쓰든 같은 단계는 같은 자리에 놓인다."""
    two = AiChatPanel._to_html("- 첫째\n  - 둘째")
    four = AiChatPanel._to_html("- 첫째\n    - 둘째")
    assert "margin-left:20px" in two and "margin-left:20px" in four
    assert "margin-left:34px" in two
    assert "margin-left:48px" in four


def test_paragraph_under_a_list_item_lines_up_with_it() -> None:
    """항목에 이어지는 설명이 왼쪽 끝까지 되돌아가면 목록이 끊겨 보인다."""
    html = AiChatPanel._to_html(
        "1. 허가 신청서\n   세움터에서도 신청할 수 있습니다.\n2. 대지 서류"
    )
    assert 'margin-left:20px;">세움터에서도' in html
