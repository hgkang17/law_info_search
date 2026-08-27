import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from utils.formatting import body_to_html


def test_bare_paragraph_references_in_current_article_are_not_links() -> None:
    _app = QApplication.instance() or QApplication([])
    html = body_to_html(
        "제2조(기반시설) 본문이다.\n"
        "② 제1항에 따른 기반시설은 세분할 수 있다.\n"
        "③ 제1항 및 제2항의 규정에 의한다.",
        current_law_name="국토의 계획 및 이용에 관한 법률 시행령",
        current_law_id="009419",
        use_api_links=True,
    )

    assert "id=009419&amp;jo=2&amp;hang=" not in html
    assert "lawref://open" not in html
    assert "제1항" in html
    assert "제2항" in html


def test_explicit_article_reference_remains_a_link() -> None:
    _app = QApplication.instance() or QApplication([])
    html = body_to_html(
        "제2조(기반시설) 법 제43조제1항에 따른 시설이다.",
        current_law_name="국토의 계획 및 이용에 관한 법률 시행령",
        current_law_id="009419",
        use_api_links=True,
    )

    assert "lawref://open" in html
    assert "jo=43" in html
    assert "hang=1" in html
