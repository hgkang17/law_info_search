"""본문 글자 크기가 조절칸 값과 같은지 보는 회귀 테스트.

본문 스타일에 ``font-size``를 적어 두면 사용자가 정한 값과 무관하게 늘 그
크기로 그려진다. 그래서 조절칸이 10pt를 가리켜도 법령 본문만 9.5pt로
그려졌고, 다른 경로로 그리는 수립지침류와 크기가 달라 보였다.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _payload() -> dict:
    return {
        "법령": {
            "기본정보": {"법령명_한글": "시험법", "법령ID": "1"},
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


def _body_font_sizes(tab: ResourceSearchTab) -> set[float]:
    document = tab.detail_view.document()
    default_size = round(document.defaultFont().pointSizeF(), 2)
    cursor = document.find("제1조")
    cursor.clearSelection()
    sizes: set[float] = set()
    while not cursor.atEnd():
        cursor.movePosition(
            QTextCursor.MoveOperation.NextCharacter,
            QTextCursor.MoveMode.KeepAnchor,
        )
        if cursor.selectedText().strip():
            size = round(cursor.charFormat().fontPointSize(), 2)
            sizes.add(size or default_size)
        cursor.clearSelection()
        cursor.movePosition(QTextCursor.MoveOperation.NextCharacter)
    return sizes


@pytest.mark.parametrize("wanted", [10.0, 12.5])
def test_body_text_uses_the_size_from_the_control(
    qt_app, tmp_path, wanted: float
) -> None:
    settings = QSettings(
        str(tmp_path / f"size-{wanted}.ini"), QSettings.Format.IniFormat
    )
    tab = ResourceSearchTab(
        lambda: "",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    try:
        tab.resize(900, 600)
        tab.show()
        tab._set_detail_font_size(wanted)
        tab.pending_row = {
            "target": "law",
            "id": "1",
            "label": "법령",
            "name": "시험법",
        }
        tab._show_detail(_payload(), save_cache=False)
        qt_app.processEvents()

        assert tab.detail_font_size == pytest.approx(wanted)
        assert _body_font_sizes(tab) == {wanted}, (
            f"조절칸은 {wanted}pt인데 본문에 다른 크기가 섞였다: "
            f"{_body_font_sizes(tab)}"
        )
    finally:
        tab.close()


def test_changing_font_size_rebinds_article_overlay_positions(
    qt_app, tmp_path
) -> None:
    """글자 크기를 바꿔도 별·3단 단추가 조문 제목 자리를 다시 찾는다."""
    settings = QSettings(str(tmp_path / "resize.ini"), QSettings.Format.IniFormat)
    tab = ResourceSearchTab(
        lambda: "",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    payload = {
        "법령": {
            "기본정보": {"법령명_한글": "시험법", "법령ID": "1"},
            "조문": {
                "조문단위": [
                    {
                        "조문번호": "0001",
                        "조문가지번호": "00",
                        "조문제목": "목적",
                        "조문내용": "제1조(목적) 이 법의 목적을 정한다.",
                    },
                    {
                        "조문번호": "0002",
                        "조문가지번호": "00",
                        "조문제목": "정의",
                        "조문내용": "제2조(정의) 용어의 뜻은 다음과 같다.",
                    },
                ]
            },
        }
    }
    try:
        tab.resize(900, 700)
        tab.show()
        tab.pending_row = {
            "target": "law",
            "id": "1",
            "label": "법령",
            "name": "시험법",
        }
        tab._show_detail(payload, save_cache=False)
        qt_app.processEvents()
        before = tab.detail_view.document().size().height()
        tab._set_detail_font_size(12.0, persist=False)
        qt_app.processEvents()
        after = tab.detail_view.document().size().height()
        assert after < before * 1.8, (
            f"글자 크기를 조금 올렸는데 문서 높이가 너무 커졌다 "
            f"({before} → {after})"
        )
        assert tab._three_stage_anchor_positions
        for anchor, position in tab._three_stage_anchor_positions.items():
            cursor = QTextCursor(tab.detail_view.document())
            cursor.setPosition(position)
            cursor.movePosition(
                QTextCursor.MoveOperation.EndOfBlock,
                QTextCursor.MoveMode.KeepAnchor,
            )
            assert cursor.selectedText().startswith("제"), anchor
    finally:
        tab.close()
