"""열린 본문 탭을 띠 밖으로 끌어 놓으면 별도 창으로 꺼내는지 검증."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QSettings
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.dialogs import DetachedDocumentWindow
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


def _tab(tmp_path) -> ResourceSearchTab:
    QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "detach.ini"), QSettings.Format.IniFormat)
    return ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )


def test_dragging_a_tab_far_below_the_strip_is_a_detach_spot(tmp_path) -> None:
    tab = _tab(tmp_path)
    bar = tab.document_tabs
    margin = bar.DETACH_MARGIN

    assert bar._is_detach_spot(QPoint(10, bar.height() + margin + 5))
    assert not bar._is_detach_spot(QPoint(10, bar.height() // 2))
    # 좌우로 끄는 것은 순서 바꾸기이므로 꺼내지 않는다.
    assert not bar._is_detach_spot(QPoint(-400, bar.height() // 2))


def _payload() -> dict:
    return {
        "법령": {
            "기본정보": {"법령명_한글": ROW["name"], "법령ID": ROW["id"]},
            "조문": {
                "조문단위": [
                    {"조문번호": "1", "조문내용": "제1조(목적) 본문이다."},
                    {"조문번호": "2", "조문내용": "제2조(정의) 뜻이다."},
                ]
            },
        }
    }


def test_detaching_opens_a_window_and_closes_the_tab(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    payload = _payload()
    assert tab.law_cache.save(dict(ROW), payload)
    tab.resize(1000, 700)
    tab.show()
    tab.open_cached_law({"row": dict(ROW), "payload": payload})
    app.processEvents()
    key = tab._active_document_key

    tab._detach_document_tab(key, QPoint(200, 200))
    app.processEvents()

    assert tab.document_tabs.count() == 0
    assert len(tab._detached_document_windows) == 1
    window = tab._detached_document_windows[0]
    assert isinstance(window, DetachedDocumentWindow)
    assert "제1조(목적) 본문이다." in window.browser.toPlainText()
    assert ROW["name"] in window.windowTitle()
    window.close()


def test_detaching_an_unknown_tab_is_ignored(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    tab._open_document_tab(dict(ROW))
    app.processEvents()

    tab._detach_document_tab("__preview__", QPoint(0, 0))
    tab._detach_document_tab("law:없는키", QPoint(0, 0))

    assert tab.document_tabs.count() == 1
    assert tab._detached_document_windows == []
