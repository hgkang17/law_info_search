"""저장본에서 별표ㆍ별첨 목록이 사라지지 않는지 검증."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab


ROW = {
    "target": "admrul",
    "label": "행정규칙",
    "id": "12345",
    "name": "도시ㆍ군관리계획수립지침",
    "related": "",
    "organization": "국토교통부",
    "date": "",
    "number": "",
    "effective": "",
    "short_name": "",
    "raw": {},
}

PAYLOAD = {
    "AdmRulService": {
        "행정규칙기본정보": {
            "행정규칙명": ROW["name"],
            "행정규칙종류": "훈령",
        },
        "조문내용": ["제1편 총칙", "1-1-1. 이 지침은 …"],
        "별표": {
            "별표단위": [
                {
                    "별표구분": "별첨",
                    "별표번호": "0001",
                    "별표가지번호": "00",
                    "별표제목": "도시ㆍ군관리계획 결정조서",
                    "별표서식파일링크": "/LSW/flDownload.do?flSeq=1",
                }
            ]
        },
    }
}


def _tab(tmp_path) -> ResourceSearchTab:
    QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "annex.ini"), QSettings.Format.IniFormat)
    return ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )


def test_quiet_save_keeps_the_annex_list(tmp_path) -> None:
    """화면 없이 저장할 때도 별첨 목록을 함께 담는다."""
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)

    assert tab._save_detail_payload_quietly(dict(ROW), PAYLOAD)
    record = tab.law_cache.load_snapshot(dict(ROW))

    assert record is not None
    assert [entry["label"] for entry in record["annex_entries"]] == ["별첨 1"]

    tab._open_cached_resource_snapshot(dict(ROW), dict(record))
    app.processEvents()
    assert len(tab._annex_section_entries) == 1
    assert "별첨" in tab.detail_view.toPlainText()


def test_resaving_does_not_drop_the_annex_list(tmp_path) -> None:
    tab = _tab(tmp_path)
    assert tab._save_detail_payload_quietly(dict(ROW), PAYLOAD)

    assert tab.law_cache.save_snapshot(
        dict(ROW), html="<p>다시</p>", plain_text="다시"
    )

    record = tab.law_cache.load_snapshot(dict(ROW))
    assert [entry["label"] for entry in record["annex_entries"]] == ["별첨 1"]


def test_old_record_recovers_the_list_from_the_payload(tmp_path) -> None:
    """목록이 빠진 옛 저장본도 원문이 있으면 별첨을 되찾는다."""
    tab = _tab(tmp_path)
    assert tab.law_cache.save_snapshot(
        dict(ROW),
        html="<p>본문</p>",
        plain_text="본문",
        extra={"detail_payload": PAYLOAD},
    )
    record = tab.law_cache.load_snapshot(dict(ROW))
    assert "annex_entries" not in record

    entries = ResourceSearchTab._cached_annex_entries(record)

    assert [entry["label"] for entry in entries] == ["별첨 1"]
