import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from utils.formatting import body_to_html
from utils.parsing import insert_admin_clause_breaks


def test_parenthesized_reference_is_not_resplit_during_html_render() -> None:
    app = QApplication.instance() or QApplication([])
    source = (
        "2-2-2. 경미한 사항\n"
        "(2) 지구단위계획중 경미한 사항에 해당하는 경우\n"
        "① 변경결정인 경우\n"
        "(1) 에서 정한 변경인 경우\n"
        "② 가구의 변경인 경우"
    )

    normalized = insert_admin_clause_breaks(source)
    assert "① 변경결정인 경우 (1)에서 정한 변경인 경우" in normalized

    html = body_to_html(source, administrative_rule=True)
    # The circled marker is rendered in its own span; the referenced (1)
    # must remain inline in the bullet text rather than becoming a new marker.
    assert "변경결정인 경우 (1)에서 정한 변경인 경우" in html
    assert ">(1)&nbsp;</span>" not in html
    assert app is not None
