"""자치법규 본문도 항ㆍ호ㆍ목이 줄로 나뉘는지 검증."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab


ROW = {
    "target": "ordin",
    "label": "자치법규",
    "id": "1234567",
    "name": "이천시 도시계획 조례",
    "related": "",
    "organization": "이천시",
    "date": "",
    "number": "",
    "effective": "",
    "short_name": "",
    "raw": {},
}

ARTICLE = (
    "제5조(도시계획위원회의 구성) ① 위원회는 위원장 1명을 포함한 15명 이내의 "
    "위원으로 구성한다. ② 위원은 다음 각 호의 사람 중에서 시장이 위촉한다. "
    "1. 시의회 의원 2. 관계 공무원 3. 도시계획에 관한 학식과 경험이 풍부한 사람"
)


def _tab(tmp_path) -> ResourceSearchTab:
    QApplication.instance() or QApplication([])
    settings = QSettings(
        str(tmp_path / "ordin.ini"), QSettings.Format.IniFormat
    )
    return ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )


def test_ordinance_article_is_split_into_paragraph_lines(tmp_path) -> None:
    tab = _tab(tmp_path)
    tab.pending_row = dict(ROW)
    payload = {
        "LawService": {
            "자치법규기본정보": {
                "자치법규명": ROW["name"],
                "지자체기관명": "이천시",
            },
            "조문": {"조": [{"조내용": ARTICLE}]},
        }
    }

    _title, _metadata, sections = tab._parse_ordin_detail(payload)
    lines = sections[0][1].splitlines()

    assert lines[0].startswith("제5조(도시계획위원회의 구성)")
    assert lines[1].startswith("①")
    assert lines[2].startswith("②")
    assert lines[3].startswith("1.")
    assert lines[4].startswith("2.")
    assert lines[5].startswith("3.")


def _ordinance_payload_with_annex() -> dict:
    return {
        "LawService": {
            "자치법규기본정보": {
                "자치법규ID": "2152079",
                "자치법규일련번호": "2152413",
                "자치법규명": "증평군 군계획 조례",
                "지자체기관명": "충청북도 증평군",
            },
            "조문": {"조": [{"조내용": "제1조(목적) 목적을 정한다."}]},
            "별표": {
                "별표단위": {
                    # 실제 응답은 내부 번호가 23이어도 제목에는 별표 24로
                    # 표시되는 사례가 있어 제목의 표기를 우선해야 한다.
                    "별표제목": "[별표 24] 건축물의 용도별 기준",
                    "별표첨부파일명": (
                        "http://www.law.go.kr/flDownload.do?gubun=ELIS&"
                        "flSeq=167149183"
                    ),
                    "별표번호": "0023",
                    "별표키": "22142677",
                    "별표구분": "서식",
                    "별표가지번호": "00",
                }
            },
        }
    }


def test_ordinance_annex_uses_title_label_and_official_preview() -> None:
    entries = ResourceSearchTab._law_annex_entries(
        _ordinance_payload_with_annex()
    )

    assert len(entries) == 1
    assert entries[0]["label"] == "별표 24"
    assert entries[0]["title"] == "건축물의 용도별 기준"
    assert entries[0]["file_url"].startswith("https://www.law.go.kr/")
    assert "ordinBylContentsInfoR.do?" in entries[0]["preview_url"]
    assert "bylSeq=22142677" in entries[0]["preview_url"]
    assert "ordinSeq=2152413" in entries[0]["preview_url"]


def test_ordinance_body_keeps_annex_for_cached_reopen(tmp_path) -> None:
    tab = _tab(tmp_path)
    tab.pending_row = dict(ROW, id="2152413", name="증평군 군계획 조례")
    tab._show_detail(_ordinance_payload_with_annex())

    assert tab._annex_section_entries
    assert "[별표 24] 건축물의 용도별 기준" in tab.current_detail_text
    assert "annex:0" in tab.detail_view.toHtml()

    record = tab.law_cache.load_snapshot(tab.pending_row)
    assert record is not None
    assert record["annex_entries"][0]["label"] == "별표 24"
