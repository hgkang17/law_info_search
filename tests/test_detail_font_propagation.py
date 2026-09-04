"""글자 크기ㆍ글꼴을 바꾼 뒤 다른 본문 탭으로 갔을 때의 회귀 테스트."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _payload(law_id: str, name: str) -> dict:
    return {
        "법령": {
            "기본정보": {"법령명_한글": name, "법령ID": law_id},
            "조문": {
                "조문단위": [
                    {
                        "조문번호": "0001",
                        "조문가지번호": "00",
                        "조문제목": "목적",
                        "조문내용": "제1조(목적) 이 법의 목적을 정한다.",
                    }
                ]
            },
        }
    }


def test_font_size_change_reaches_other_open_document_tabs(
    qt_app, tmp_path
) -> None:
    """조절칸 값과 다른 탭의 실제 글자 크기가 어긋나면 안 된다.

    글자 크기는 화면 전체에 하나인데 바꿀 때는 보고 있던 문서만 다시
    그린다. 그려 둔 다른 탭 문서를 그대로 되살리면 조절칸은 새 값(11)을
    보여 주면서 글자는 옛 크기 그대로인 상태가 됐다.
    """
    settings = QSettings(
        str(tmp_path / "font.ini"), QSettings.Format.IniFormat
    )
    tab = ResourceSearchTab(
        lambda: "",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    try:
        first = {"target": "law", "id": "000001", "label": "법령", "name": "법률"}
        second = {"target": "law", "id": "000002", "label": "법령", "name": "시행령"}

        tab.pending_row = dict(first)
        tab._show_detail(_payload("000001", "법률"), save_cache=False)
        qt_app.processEvents()
        first_key = tab._active_document_key

        tab.pending_row = dict(second)
        tab._show_detail(_payload("000002", "시행령"), save_cache=False)
        qt_app.processEvents()

        # 두 번째 탭을 보는 상태에서 글자 크기를 올린다.
        tab._set_detail_font_size(13.0)
        qt_app.processEvents()

        # 첫 번째 탭으로 돌아온다.
        tab._restore_document_state(first_key)
        qt_app.processEvents()

        assert tab.detail_font_size == pytest.approx(13.0)
        applied = tab.detail_view.document().defaultFont().pointSizeF()
        assert applied == pytest.approx(13.0, abs=0.01), (
            f"조절칸은 13pt인데 첫 탭 본문은 {applied}pt로 남았다"
        )
    finally:
        tab.close()
