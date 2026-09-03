"""조ㆍ항 끝의 개정 이력 표기(``<개정 …>``) 보존과 표시 스타일 검증."""

import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from utils.formatting import AMENDMENT_NOTE_STYLE, body_to_html, style_amendment_notes
from utils.parsing import json_text, law_article_text

# body_to_html은 표지 폭을 QFontMetrics로 재므로 앱 인스턴스가 있어야 한다.
QApplication.instance() or QApplication([])


# 건축법 시행령 제2조 실제 응답 형식. 개정 표기가 조문내용 첫 줄 끝에 붙어
# 오고, 조문참고자료에는 ``[전문개정 …]``이 따로 온다.
ARTICLE_UNITS = [
    {
        "조문내용": (
            "제2조(정의) 이 영에서 사용하는 용어의 뜻은 다음과 같다. "
            "<개정 2009.7.16, 2010.2.18, 2020.4.28>"
        ),
        "항": [
            {
                "항내용": (
                    "① 법 제2조제1항제11호에 따른 도로에는 다음 각 목이 포함된다. "
                    "<신설 2016.1.19>"
                )
            }
        ],
        "조문참고자료": "[전문개정 2008.10.29]",
    }
]


def test_json_text_keeps_amendment_note_but_drops_real_tags():
    """개정 표기는 남기고 실제 HTML 태그만 지운다."""
    assert json_text("본문 <개정 2009.7.16>") == "본문 <개정 2009.7.16>"
    assert json_text("<p>본문</p><span>글자</span>") == "본문\n글자"
    # 이미지 태그는 개정 낱말을 갖지 않아 기존대로 제거된다.
    assert json_text('앞 <img src="x"> 뒤') == "앞 뒤"
    # 동그라미 번호 복원과 단독 ``<삭제>`` 처리는 그대로 유지된다.
    assert json_text("<16> 항목") == "⑯ 항목"
    assert json_text("제3조 <삭제>") == "제3조 <삭제>"


def test_law_article_text_shows_amendment_dates_like_the_official_site():
    """조ㆍ항 문장 끝의 개정 표기가 법제처 날짜 표기로 남는다."""
    text = law_article_text(ARTICLE_UNITS)
    lines = text.split("\n")
    assert lines[0].endswith("<개정 2009. 7. 16., 2010. 2. 18., 2020. 4. 28.>")
    assert lines[1].endswith("<신설 2016. 1. 19.>")
    assert lines[-1] == "[전문개정 2008. 10. 29.]"


def test_amendment_notes_get_smaller_light_blue_style():
    """개정 표기만 한 단계 작고 연한 파란색으로 감싼다."""
    html = body_to_html(law_article_text(ARTICLE_UNITS))
    styled = re.findall(
        rf'<span style="{re.escape(AMENDMENT_NOTE_STYLE)}">(.*?)</span>', html
    )
    assert styled == [
        "&lt;개정 2009. 7. 16., 2010. 2. 18., 2020. 4. 28.&gt;",
        "&lt;신설 2016. 1. 19.&gt;",
        "[전문개정 2008. 10. 29.]",
    ]
    assert "font-size:13px" in AMENDMENT_NOTE_STYLE


def test_plain_bracket_citation_is_not_styled():
    """개정 표기가 아닌 본문 대괄호는 물들이지 않는다."""
    html = style_amendment_notes(
        '"신축"이란 대지[기존 건축물이 해체된 대지를 포함한다]에 축조하는 것'
    )
    assert "<span" not in html


def test_amendment_note_line_starts_where_the_article_starts(tmp_path) -> None:
    """조문 끝 ``[본조신설 …]`` 줄이 조문과 같은 자리에서 시작한다.

    조문 첫 줄에는 별 단추 자리를 내려고 왼쪽 여백을 준다. 그 여백을 받지
    못한 개정 표기 줄만 왼쪽으로 튀어나와 보였다.
    """
    from PySide6.QtCore import QSettings

    from storage.cache import LawDocumentCache
    from storage.recent import RecentSearchManager
    from ui.tabs.resource_search import ResourceSearchTab

    payload = {
        "법령": {
            "기본정보": {"법령명_한글": "지방자치법", "법령ID": "000123"},
            "조문": {
                "조문단위": [
                    {
                        "조문내용": "제2조의2(주민과 지방자치단체의 관계) 주민은 권리를 가진다.",
                        "조문참고자료": "[본조신설 2018.12.27]",
                    }
                ]
            },
        }
    }
    settings = QSettings(str(tmp_path / "note.ini"), QSettings.Format.IniFormat)
    tab = ResourceSearchTab(
        lambda: "",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    try:
        row = {"target": "law", "id": "000123", "label": "법령", "name": "지방자치법"}
        tab.pending_row = row
        tab._open_document_tab(row, defer_restore=True)
        title, metadata, sections = tab._parse_law_detail(payload)
        tab._set_detail_document(title, metadata, sections, build_toc=True)

        margins = {}
        block = tab.detail_view.document().begin()
        while block.isValid():
            text = block.text().strip()
            if text.startswith("제2조의2"):
                margins["조문"] = block.blockFormat().leftMargin()
            elif text.startswith("[본조신설"):
                margins["개정표기"] = block.blockFormat().leftMargin()
            block = block.next()

        assert margins["조문"] == tab._ARTICLE_FAVORITE_HEADING_MARGIN
        assert margins["개정표기"] == margins["조문"]
    finally:
        tab.close()
