"""탭 전체 닫기ㆍ제목 글꼴 유지ㆍ별표 즐겨찾기 재열기 검증."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QTextBrowser

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab
from ui.theme import apply_detail_font_family
from utils.formatting import DETAIL_DOCUMENT_STYLE


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
    settings = QSettings(str(tmp_path / "bulk.ini"), QSettings.Format.IniFormat)
    return ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )


def test_document_title_keeps_its_own_font_when_redrawn() -> None:
    """저장 본문을 다시 그려도 제목은 화면 UI 글꼴 그대로다."""
    QApplication.instance() or QApplication([])
    browser = QTextBrowser()
    browser.setHtml(
        DETAIL_DOCUMENT_STYLE
        + '<h1>테스트 법률</h1><div class="content">'
        '<p class="paragraph">제1조(목적) 본문</p></div>'
    )

    applied = apply_detail_font_family(browser.toHtml())
    title = applied[applied.find("<h1") : applied.find("</h1>")]

    assert "Malgun Gothic" in title
    assert "Gulim" not in title
    # 본문 쪽은 본문 글꼴로 통일된다.
    assert "Gulim" in applied[applied.find("</h1>") :]


def test_close_all_document_tabs_closes_every_tab(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    for index in range(3):
        row = dict(ROW, id=f"00100{index}", name=f"테스트 법률 {index}")
        tab._open_document_tab(row)
    app.processEvents()
    assert tab.document_tabs.count() == 3

    tab._close_all_document_tabs()
    app.processEvents()

    assert tab.document_tabs.count() == 0
    assert not tab.close_all_documents_button.isVisible()


def test_saved_annex_favorite_opens_the_annex_view(tmp_path) -> None:
    """별표ㆍ서식 저장본은 빈 본문 대신 미리보기 줄로 열린다."""
    tab = _tab(tmp_path)
    opened: list[dict] = []
    tab._show_annex_links = lambda row: opened.append(dict(row))

    annex_row = dict(
        ROW,
        target="licbyl",
        label="법령 별표·서식",
        id="7788",
        name="[별표 1] 용도지역 안에서의 건축제한",
    )
    tab._open_cached_resource_snapshot(annex_row, {"row": annex_row})

    assert opened and opened[0]["id"] == "7788"


def test_new_annex_favorite_survives_opening_and_returning(tmp_path) -> None:
    """미저장 별표를 즐겨찾기한 뒤 본문에서 돌아와도 별이 유지된다."""
    tab = _tab(tmp_path)
    annex_row = dict(
        ROW,
        target="ordinbyl",
        label="자치법규 별표·서식",
        id="22142677",
        name="[별표 24] 건축물의 용도별 기준",
        raw={
            "별표종류": "별표",
            "별표번호": "002300",
            "별표서식파일링크": (
                "/LSW/flDownload.do?gubun=ELIS&flSeq=167149183"
            ),
        },
    )
    # 메인 창이 공용 상태줄을 붙이기 전의 독립 탭에는 `_bar`가 없다.
    assert not hasattr(tab.status_label, "_bar")

    tab._toggle_favorite_for_row(annex_row)
    tab._exit_reading_mode()

    assert tab.law_cache.is_favorite(annex_row)


def test_reference_popup_font_control_is_shared(tmp_path) -> None:
    """팝업 글자 크기를 바꾸면 3단비교 팝업도 같은 크기를 쓴다."""
    tab = _tab(tmp_path)
    tab._set_popup_font_size(11.0)

    assert tab.popup_font_size == 11.0
    assert tab.reference_popup.content_font_point == 11.0
    assert tab.three_stage_popup.content_font_point == 11.0


def test_detail_scroll_is_not_recorded_while_content_is_replaced(
    tmp_path,
) -> None:
    """본문을 갈아 끼우는 동안의 스크롤 값은 문서 상태에 남지 않는다."""
    tab = _tab(tmp_path)
    tab._document_states["k"] = {"scroll": 120}
    tab._active_document_key = "k"

    tab._scroll_memory_suspended = 1
    tab._remember_detail_scroll(0)
    assert tab._document_states["k"]["scroll"] == 120

    tab._scroll_memory_suspended = 0
    tab._remember_detail_scroll(340)
    assert tab._document_states["k"]["scroll"] == 340


def test_annex_toggle_marks_the_line_without_moving_the_view() -> None:
    """별표를 펼칠 때 화면을 끌어올리는 보조 함수는 두지 않는다.

    누른 별표 줄은 목차 바로가기와 같은 음영으로만 짚는다.
    """
    assert not hasattr(ResourceSearchTab, "_focus_annex_item")
    assert callable(getattr(ResourceSearchTab, "_highlight_anchor_line", None))
