"""별은 즐겨찾기만 하고, 본문은 두 번 눌러야 열리는지 검증."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab


ANNEX_ROW = {
    "target": "licbyl",
    "label": "법령 별표·서식",
    "id": "8899",
    "name": "[별표 1] 용도지역 안에서의 건축물의 용도ㆍ종류 및 규모 등의 제한",
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
    settings = QSettings(str(tmp_path / "star.ini"), QSettings.Format.IniFormat)
    return ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )


def test_star_click_does_not_open_the_annex_body(tmp_path) -> None:
    """별은 즐겨찾기 단추다. 누른다고 본문 화면으로 끌려가지 않는다."""
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    tab.result_rows = [dict(ANNEX_ROW)]

    tab._toggle_favorite_for_row(dict(ANNEX_ROW), select_row_index=0)
    app.processEvents()

    assert tab.law_cache.is_favorite(ANNEX_ROW)
    assert tab.document_tabs.count() == 0


def test_star_click_toggles_off_again(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    tab.result_rows = [dict(ANNEX_ROW)]

    tab._toggle_favorite_for_row(dict(ANNEX_ROW), select_row_index=0)
    app.processEvents()
    tab._toggle_favorite_for_row(dict(ANNEX_ROW), select_row_index=0)
    app.processEvents()

    assert not tab.law_cache.is_favorite(ANNEX_ROW)
    assert tab.document_tabs.count() == 0


def test_double_click_path_still_opens_the_body(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)

    tab._show_annex_links(dict(ANNEX_ROW))
    app.processEvents()

    assert tab.document_tabs.count() == 1
    panel = tab._annex_preview_panels[tab._active_annex_preview_key]
    assert panel.expand_button.text() == "축소"
    assert panel.height() == 680


def test_saving_the_body_again_keeps_the_favorite(tmp_path) -> None:
    """본문을 다시 저장해도(뒤로 갔다 오기) 즐겨찾기가 풀리지 않는다."""
    cache = LawDocumentCache(tmp_path / "saved")
    row = dict(ANNEX_ROW)
    assert cache.save_snapshot(row, html="<p>첫 저장</p>", plain_text="첫 저장")
    assert cache.set_favorite(row, True)

    assert cache.save_snapshot(row, html="<p>다시 저장</p>", plain_text="다시")

    assert cache.is_favorite(row)
    record = json.loads(
        cache.path_for_row(row).read_text(encoding="utf-8")
    )
    assert record["favorite"] is True
    assert record["html"] == "<p>다시 저장</p>"


def test_saving_the_body_again_keeps_memos_and_colors(tmp_path) -> None:
    cache = LawDocumentCache(tmp_path / "saved")
    row = dict(ANNEX_ROW)
    assert cache.save_snapshot(row, html="<p>본문</p>", plain_text="본문")
    path = cache.path_for_row(row)
    record = json.loads(path.read_text(encoding="utf-8"))
    record["memos"] = [{"start": 0, "end": 2, "text": "메모"}]
    record["formatting_spans"] = [
        {"start": 0, "end": 2, "mode": "background", "color": "#ffff00"}
    ]
    path.write_text(
        json.dumps(record, ensure_ascii=False), encoding="utf-8"
    )

    assert cache.save_snapshot(row, html="<p>다시</p>", plain_text="다시")

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["memos"][0]["text"] == "메모"
    assert saved["formatting_spans"][0]["color"] == "#ffff00"
