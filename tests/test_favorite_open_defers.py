"""즐겨찾기에서 두 번 눌러 열 때 목록이 그 자리에서 무너지지 않는지 검증."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab
from ui.tabs.viewed_laws import ViewedLawsTab


ANNEX_ROW = {
    "target": "licbyl",
    "label": "법령 별표·서식",
    "id": "7788",
    "name": "[별표 21] 생산관리지역안에서 건축할 수 있는 건축물",
    "related": "국토의 계획 및 이용에 관한 법률 시행령",
    "organization": "국토교통부",
    "date": "",
    "number": "",
    "effective": "",
    "short_name": "",
    "raw": {
        "별표번호": "002100",
        "별표종류": "별표",
        "별표서식PDF파일링크": "/LSW/flDownload.do?flSeq=1",
    },
}


def _cache(tmp_path) -> LawDocumentCache:
    QApplication.instance() or QApplication([])
    return LawDocumentCache(tmp_path / "saved")


def test_opening_a_favorite_is_deferred_out_of_the_click(tmp_path) -> None:
    """열기는 두 번 누르기 처리에서 빠져나온 뒤에 시작한다.

    여는 도중에 저장 기록이 바뀌면 이 목록이 통째로 다시 그려진다. 그
    자리에서 열면 눌린 항목이 지워진 채로 Qt가 뒷정리를 이어가다 프로그램이
    그대로 꺼졌다.
    """
    app = QApplication.instance() or QApplication([])
    cache = _cache(tmp_path)
    assert cache.save_snapshot(dict(ANNEX_ROW), html="", plain_text="")
    settings = QSettings(str(tmp_path / "v.ini"), QSettings.Format.IniFormat)
    tab = ViewedLawsTab(cache, settings=settings)
    opened: list[object] = []
    tab.openRequested.connect(opened.append)

    path = cache.path_for_row(dict(ANNEX_ROW))
    tab._open_path(str(path))

    # 누르기 처리 중에는 아직 열지 않는다.
    assert opened == []
    app.processEvents()
    assert len(opened) == 1
    assert isinstance(opened[0], dict)


def test_opening_an_annex_body_rewrites_the_saved_record(tmp_path) -> None:
    """별표 본문을 열면 저장 기록이 갱신되며 목록 갱신 신호가 뜬다."""
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "r.ini"), QSettings.Format.IniFormat)
    tab = ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    changes: list[int] = []
    tab.law_cache.changed.connect(lambda: changes.append(1))

    tab._show_annex_links(dict(ANNEX_ROW))
    app.processEvents()

    assert changes, "별표 본문을 열면 저장 기록이 바뀐다"
