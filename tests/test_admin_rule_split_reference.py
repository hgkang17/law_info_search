import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from utils.formatting import body_to_html
from utils.parsing import insert_admin_clause_breaks


def test_split_clause_subreference_with_circled_number_is_rejoined() -> None:
    source = (
        "3-2-7-2. 보호취락지구\n"
        "(3) 지구의 지정기준\n"
        "① 법률에 따라 지정하는 것을 원칙으로 한다.\n"
        "② 각 시ㆍ군은 3-2-7-1.\n"
        "(3) ③에서 정하는 지구의 지정 및 개발에 관한 기준을 준용한다.\n"
        "3-2-7-3. 집단취락지구"
    )

    normalized = insert_admin_clause_breaks(source)
    assert normalized.splitlines() == [
        "3-2-7-2. 보호취락지구",
        "(3) 지구의 지정기준",
        "① 법률에 따라 지정하는 것을 원칙으로 한다.",
        "② 각 시ㆍ군은 3-2-7-1. (3) ③에서 정하는 지구의 지정 및 개발에 관한 기준을 준용한다.",
        "3-2-7-3. 집단취락지구",
    ]

    _app = QApplication.instance() or QApplication([])
    html = body_to_html(source, administrative_rule=True)
    assert "3-2-7-1. (3) ③에서 정하는" in html
    assert html.count("(3)&nbsp;") == 1
