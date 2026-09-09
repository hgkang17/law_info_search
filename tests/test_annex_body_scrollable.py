"""별표ㆍ서식 본문이 펼친 미리보기만큼 굴러가는지 검증."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab


ANNEX_ROW = {
    "target": "licbyl",
    "label": "법령 별표·서식",
    "id": "8899",
    "name": "용도지역 안에서의 건축물의 제한(제71조 관련)",
    "related": "국토의 계획 및 이용에 관한 법률 시행령",
    "organization": "국토교통부",
    "date": "",
    "number": "",
    "effective": "",
    "short_name": "",
    "raw": {
        "별표번호": "000100",
        "별표종류": "별표",
        "별표서식PDF파일링크": "/LSW/flDownload.do?flSeq=1",
        "별표서식파일링크": "/LSW/flDownload.do?flSeq=2",
    },
}


def _tab(tmp_path) -> ResourceSearchTab:
    QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "scroll.ini"), QSettings.Format.IniFormat)
    tab = ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    tab.resize(1200, 700)
    tab.show()
    return tab


def test_expanded_preview_reserves_its_height_in_the_document(tmp_path) -> None:
    """문서가 패널 아래까지 자라야 스크롤이 잠기지 않는다.

    예전에는 HTML을 만든 뒤에 패널을 펼쳐서, 문서에는 접힘 높이만 남고
    패널만 두 배로 커졌다. 그러면 문서가 화면보다 짧아 스크롤 범위가 0이
    되고, 화면 밖으로 넘어간 미리보기 아랫부분을 볼 수 없었다.
    """
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    tab.result_rows = [dict(ANNEX_ROW)]

    tab._show_annex_links(dict(ANNEX_ROW))
    for _ in range(5):
        app.processEvents()

    key = tab._active_annex_preview_key
    panel = tab._annex_preview_panels.get(key)
    assert panel is not None
    assert panel.height() == ResourceSearchTab.ANNEX_PREVIEW_EXPANDED_HEIGHT
    assert (
        tab._annex_preview_slot_height(key)
        == ResourceSearchTab.ANNEX_PREVIEW_EXPANDED_HEIGHT
    )

    view = tab.detail_view
    scroll_bar = view.verticalScrollBar()
    assert view.document().size().height() >= panel.geometry().bottom()
    assert scroll_bar.maximum() > 0

    scroll_bar.setValue(scroll_bar.maximum())
    app.processEvents()
    assert scroll_bar.value() == scroll_bar.maximum()
    tab.close()
