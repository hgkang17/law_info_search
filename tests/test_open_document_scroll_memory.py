"""메뉴 이동 때 보관한 열린 본문 위치가 낡아 맨 위로 튀지 않는지 검증."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from ui.main_window import LawSearchWindow


def _record(target: str, item_id: str, name: str) -> dict:
    row = {
        "target": target, "label": "법령", "id": item_id, "name": name,
        "related": "", "organization": "국토교통부", "date": "", "number": "",
        "effective": "", "short_name": "", "raw": {},
    }
    units = [
        {
            "조문번호": str(number),
            "조문내용": f"제{number}조(제목{number}) 본문입니다. " + "가나다라마바사 " * 12,
        }
        for number in range(1, 61)
    ]
    payload = {
        "법령": {
            "기본정보": {"법령명_한글": name, "법령ID": item_id},
            "조문": {"조문단위": units},
        }
    }
    return {"row": row, "payload": payload}


def _pump(app, rounds: int = 30) -> None:
    import time

    for _ in range(rounds):
        app.processEvents()
        time.sleep(0.02)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def test_first_law_keeps_its_place_after_menu_trip_and_tab_switch(qt_app):
    """법률을 연 직후 메뉴에 다녀온 뒤 읽고, 시행령에 갔다 와도 제자리다.

    예전에는 메뉴를 떠날 때 보관한 0이 그대로 남아 상단 띠로 법률을
    다시 누르면 맨 위로 튀었다(시행령은 보관값이 없어 멀쩡했다).
    """
    window = LawSearchWindow()
    window.resize(1400, 900)
    window.show()
    window.navigation.setCurrentRow(1)
    tab = window.resource_tab
    bar = tab.detail_view.verticalScrollBar()
    try:
        tab.open_cached_law(_record("law", "991001", "시험 법률"), clear_highlights=False)
        _pump(qt_app)
        window._refresh_open_documents()
        law_token = f"resource:{tab._active_document_key}"
        window._activate_favorites_page()
        _pump(qt_app)
        window._activate_open_document(law_token)
        _pump(qt_app)
        bar.setValue(bar.maximum() // 3)
        _pump(qt_app, 5)
        law_position = bar.value()
        assert law_position > 0

        tab.open_cached_law(
            _record("law", "991002", "시험 법률 시행령"), clear_highlights=False
        )
        _pump(qt_app)
        window._refresh_open_documents()
        decree_token = f"resource:{tab._active_document_key}"
        bar.setValue(bar.maximum() // 4)
        _pump(qt_app, 5)
        decree_position = bar.value()

        window._activate_open_document(law_token)
        _pump(qt_app)
        assert bar.value() == law_position
        window._activate_open_document(decree_token)
        _pump(qt_app)
        assert bar.value() == decree_position
    finally:
        window.close()
        qt_app.processEvents()
