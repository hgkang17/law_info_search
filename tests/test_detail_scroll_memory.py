"""본문을 굴린 자리가 문서 상태에 남아 다시 그려도 유지되는지 검증."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab

ROW = {
    "target": "law",
    "label": "법령",
    "id": "001000",
    "name": "테스트 법률",
    "related": "",
    "organization": "국토교통부",
    "date": "",
    "number": "",
    "effective": "",
    "short_name": "",
    "raw": {},
}


def _payload() -> dict:
    units = [
        {
            "조문번호": str(number),
            "조문내용": f"제{number}조(제목{number}) 본문입니다. "
            + "가나다라마바사 " * 12,
        }
        for number in range(1, 61)
    ]
    return {
        "법령": {
            "기본정보": {"법령명_한글": ROW["name"], "법령ID": ROW["id"]},
            "조문": {"조문단위": units},
        }
    }


def _tab(tmp_path) -> ResourceSearchTab:
    QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "scroll.ini"), QSettings.Format.IniFormat)
    return ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )


def _opened_tab(tmp_path):
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    payload = _payload()
    assert tab.law_cache.save(dict(ROW), payload)
    tab.resize(1200, 760)
    tab.show()
    tab.open_cached_law({"row": dict(ROW), "payload": payload})
    tab._set_reading_mode(True)
    app.processEvents()
    return app, tab


def test_scrolling_updates_the_saved_document_position(tmp_path) -> None:
    """굴린 자리가 바로 상태에 남아야 다시 그릴 때 맨 위로 튀지 않는다."""
    app, tab = _opened_tab(tmp_path)
    scroll_bar = tab.detail_view.verticalScrollBar()
    scroll_bar.setValue(int(scroll_bar.maximum() * 0.6))
    app.processEvents()

    state = tab._document_states[tab._active_document_key]
    assert scroll_bar.value() > 0
    assert state["scroll"] == scroll_bar.value()


def test_article_favorite_star_does_not_take_focus(tmp_path) -> None:
    """본문 위에 얹은 별표는 초점을 가져가지 않는다."""
    _app, tab = _opened_tab(tmp_path)
    tab._position_three_stage_buttons()

    assert tab._article_favorite_buttons
    for button in tab._article_favorite_buttons:
        assert button.focusPolicy() == Qt.FocusPolicy.NoFocus
