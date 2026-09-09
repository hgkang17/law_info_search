"""자치법규 별표를 목록에서 바로 열었을 때의 미리보기ㆍ저장 표시 검증.

자치법규 별표는 PDF가 없고 별표명이 ``[별표]``로 시작한다. 그 두 가지가
각각 미리보기와 저장 체크를 조용히 망가뜨렸다.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from urllib.parse import parse_qs, urlsplit

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab


ORDIN_ANNEX_ROW = {
    "target": "ordinbyl",
    "label": "자치법규 별표·서식",
    "id": "21618027",
    "name": "[별표]제1종전용주거지역안에서 건축할 수 있는 건축물 외",
    "related": "이천시 도시계획 조례",
    "organization": "이천시",
    "date": "",
    "number": "",
    "effective": "",
    "short_name": "",
    "raw": {
        "별표일련번호": "21618027",
        "관련자치법규일련번호": "2113131",
        "별표번호": "000100",
        "별표종류": "서식",
        "별표서식파일링크": (
            "/LSW/flDownload.do?gubun=ELIS&flSeq=162017267&flNm=byl"
        ),
    },
}

# 법령 별표는 PDF가 함께 오므로 지금까지도 미리보기가 됐다. 자치법규만
# 고치고 이쪽 동작은 그대로 두는지 함께 확인한다.
LAW_ANNEX_ROW = {
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
    settings = QSettings(str(tmp_path / "ordin.ini"), QSettings.Format.IniFormat)
    return ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )


def test_ordinance_annex_row_builds_a_preview_url(tmp_path) -> None:
    """PDF가 없는 자치법규 별표도 변환 뷰어 주소로 미리보기를 만든다."""
    tab = _tab(tmp_path)
    entry = tab._annex_row_entry(dict(ORDIN_ANNEX_ROW))

    assert entry["pdf_url"] == ""
    assert tab._annex_can_preview(entry)

    parts = urlsplit(entry["preview_url"])
    assert parts.netloc == "www.law.go.kr"
    assert parts.path == "/LSW/ordinBylContentsInfoR.do"
    query = {key: values[-1] for key, values in parse_qs(parts.query).items()}
    assert query["bylSeq"] == "21618027"
    assert query["ordinSeq"] == "2113131"
    assert query["bylFlSeq"] == "162017267"
    # 자치법규ID는 목록 API에 없다. 내려받는 쪽에서 채운다.
    assert "ordinId" not in query


def test_law_annex_row_keeps_the_pdf_preview(tmp_path) -> None:
    """법령 별표는 예전처럼 PDF로 미리 본다. 뷰어 주소를 만들지 않는다."""
    tab = _tab(tmp_path)
    entry = tab._annex_row_entry(dict(LAW_ANNEX_ROW))

    assert entry["preview_url"] == ""
    assert tab._annex_can_preview(entry)


def test_bracketed_annex_name_still_counts_as_saved(tmp_path) -> None:
    """``[별표]``로 시작하는 이름은 파일명이 ``_``로 시작한다.

    저장 폴더의 관리용 파일을 이름 앞 밑줄로 가리던 때에는, 이런 별표가
    저장 체크ㆍ저장내역ㆍ즐겨찾기 목록에서 통째로 빠졌다.
    """
    tab = _tab(tmp_path)
    row = dict(ORDIN_ANNEX_ROW)

    assert tab._save_annex_row_snapshot(row)
    key = tab.law_cache.key_for_row(row)
    assert key.startswith("_")

    assert key in tab.law_cache.saved_keys_for_rows([row])
    assert tab._row_is_saved(row)
    assert [record["name"] for record in tab.law_cache.list_records()] == [
        row["name"]
    ]


def test_saved_checkmark_survives_opening_the_annex(tmp_path) -> None:
    """본문을 열고 나와도 목록의 저장 체크가 그대로 켜져 있다."""
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    row = dict(ORDIN_ANNEX_ROW)
    tab.result_rows = [row]
    tab._render_result_rows()
    app.processEvents()

    tab._show_annex_links(dict(row))
    app.processEvents()
    tab._refresh_cache_checkmarks()

    assert tab.result_table.item(0, 0).checkState().value == 2
