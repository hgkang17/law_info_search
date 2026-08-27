import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication

from ui.widgets import DeferredWrapTextBrowser
from utils.formatting import hwp_friendly_clipboard_html


DETAIL_HTML = (
    '<div class="content">'
    '<div class="law-article" style="margin:14px 0 8px 0;">'
    '<span class="law-article-title" style="font-weight:700; color:#173b63;">'
    "제8조(다른 법률에 따른 토지 이용에 관한 구역 등의 지정 제한 등)</span>"
    " 본문입니다.</div>"
    '<div class="legal-indent level-0" '
    'style="margin:0 0 7px 20px; text-indent:-20px;">'
    '<span class="bullet-marker" style="font-weight:400; padding:0;">①&nbsp;</span>'
    '<span class="bullet-text" style="font-weight:400;">'
    "중앙행정기관의 장은 구역등의 지정목적에 부합되도록 하여야 한다.</span></div>"
    "</div>"
)


def _copied_html(source: str) -> str:
    app = QApplication.instance() or QApplication([])
    browser = DeferredWrapTextBrowser()
    browser.setHtml(source)
    cursor = browser.textCursor()
    cursor.select(QTextCursor.SelectionType.Document)
    browser.setTextCursor(cursor)
    browser.copy()
    app.processEvents()
    return QApplication.clipboard().mimeData().html()


def test_copied_article_title_uses_bold_tag() -> None:
    # 한글은 font-weight 숫자값을 읽지 못하므로 <b>로 나가야 한다.
    html = _copied_html(DETAIL_HTML)
    assert "<b>" in html
    assert "제8조" in html
    assert "font-weight:700" not in html


def test_copied_html_has_no_negative_indent() -> None:
    # 한글은 margin-left를 버리고 음수 text-indent의 절댓값만 첫 줄
    # 들여쓰기로 써서 번호를 왼쪽으로 튀어나오게 만든다. 음수 여백이
    # 아예 나가지 않아야 한다.
    html = _copied_html(DETAIL_HTML)
    assert "text-indent:-" not in html
    assert "margin-left:-" not in html


def test_hanging_indent_collapses_to_first_line_position() -> None:
    # margin-left 28px + text-indent -16px → 화면 첫 줄은 12px 자리이므로
    # 문단 전체를 9pt로 밀고 내어쓰기는 없앤다.
    source = (
        '<p style=" margin-top:0px; margin-left:28px; '
        'margin-right:0px; text-indent:-16px;">1. 보전관리지역</p>'
    )
    converted = hwp_friendly_clipboard_html(source)
    assert "margin-left:9pt" in converted
    assert "text-indent:0pt" in converted


def test_indent_hierarchy_is_preserved() -> None:
    # 화면 위계(① 0px < 1. 12px < 가. 28px)가 붙여넣기에서도 유지되어야 한다.
    def left_pt(margin_px: int, indent_px: int) -> int:
        source = (
            f'<p style=" margin-left:{margin_px}px; '
            f'text-indent:-{indent_px}px;">x</p>'
        )
        converted = hwp_friendly_clipboard_html(source)
        return int(
            re.search(r"margin-left:(\d+)pt", converted).group(1)
        )

    circled = left_pt(18, 18)
    numbered = left_pt(27, 15)
    item = left_pt(50, 22)
    assert circled < numbered < item


def test_normal_weight_span_is_untouched() -> None:
    source = '<span style=" font-weight:400; color:#172033;">본문</span>'
    assert hwp_friendly_clipboard_html(source) == source


def test_conversion_keeps_span_color_and_font() -> None:
    source = (
        '<span style=" font-family:\'Malgun Gothic\'; font-weight:700; '
        'color:#173b63;">제8조</span>'
    )
    converted = hwp_friendly_clipboard_html(source)
    assert converted.startswith("<b>") and converted.endswith("</b>")
    assert "color:#173b63" in converted
    assert "Malgun Gothic" in converted


def test_vertical_margins_are_left_to_hwp() -> None:
    # 위아래 간격까지 옮기면 한글 문서에서 문단 사이가 과하게 벌어진다.
    source = '<p style=" margin-top:14px; margin-bottom:8px; margin-left:12px;">글</p>'
    converted = hwp_friendly_clipboard_html(source)
    assert "margin-top:14px" in converted
    assert "margin-bottom:8px" in converted
    assert "margin-left:9pt" in converted


def test_blank_input_is_safe() -> None:
    assert hwp_friendly_clipboard_html("") == ""
