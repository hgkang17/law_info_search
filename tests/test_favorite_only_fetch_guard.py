"""별만 누른 조회 표식이 다음 본문 열기를 가로채지 않는지 검증."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab


LAW_ROW = {
    "target": "law",
    "label": "법령",
    "id": "009419",
    "name": "국토의 계획 및 이용에 관한 법률 시행령",
    "related": "",
    "organization": "국토교통부",
    "date": "",
    "number": "",
    "effective": "",
    "short_name": "",
    "raw": {},
}

ORDIN_ROW = {
    "target": "ordin",
    "label": "자치법규",
    "id": "2152413",
    "name": "경기도 사무위임 조례",
    "related": "",
    "organization": "경기도",
    "date": "",
    "number": "",
    "effective": "",
    "short_name": "",
    "raw": {},
}

LAW_PAYLOAD = {
    "법령": {
        "기본정보": {"법령명_한글": LAW_ROW["name"], "법령ID": LAW_ROW["id"]},
        "조문": {"조문단위": [{"조문번호": "1", "조문내용": "제1조(목적) 법령 본문."}]},
    }
}

ORDIN_PAYLOAD = {
    "LawService": {
        "자치법규기본정보": {
            "자치법규명": ORDIN_ROW["name"],
            "지자체기관명": "경기도",
        },
        "조문": {"조": [{"조내용": "제1조(목적) 조례 본문이다."}]},
    }
}


def _tab(tmp_path) -> ResourceSearchTab:
    QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "guard.ini"), QSettings.Format.IniFormat)
    return ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )


def test_star_on_a_saved_row_leaves_no_pending_fetch_mark(tmp_path) -> None:
    """저장본이 있으면 API를 부르지 않으므로 기다릴 응답도 없다."""
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    assert tab.law_cache.save(dict(LAW_ROW), LAW_PAYLOAD)
    tab.result_rows = [dict(LAW_ROW)]

    tab._toggle_favorite_for_row(dict(LAW_ROW), select_row_index=0)
    app.processEvents()

    assert tab.law_cache.is_favorite(LAW_ROW)
    assert tab._favorite_only_row is None


def test_stale_mark_does_not_swallow_another_document(tmp_path) -> None:
    """표식이 남아 있어도 다른 문서의 응답은 화면에 뜬다."""
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    # 예전 판에서 남을 수 있던 표식을 흉내 낸다.
    tab._favorite_only_row = dict(LAW_ROW)
    tab.pending_row = dict(ORDIN_ROW)

    tab._worker_succeeded("resource_detail", ORDIN_PAYLOAD)
    app.processEvents()

    assert "경기도 사무위임 조례" in tab.detail_view.toPlainText()
    assert tab._favorite_only_row is None
