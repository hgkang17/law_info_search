"""열린 본문 표시줄에서 질의회신ㆍ해석례ㆍ판례를 닫을 수 있는지 확인한다.

법령 본문만 닫을 수 있고 이 세 화면은 한 번 열면 표시줄에서 지울 방법이
없었다. 새 검색을 하기 전까지 계속 남아 자리를 차지했다.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from ui.main_window import LawSearchWindow


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qt_app):
    created = LawSearchWindow()
    yield created
    created.deleteLater()


def _open_detail(tab, name: str) -> None:
    """검색 결과 하나를 연 것처럼 본문 상태를 채운다."""
    tab._active_detail_row = {"id": "12345", "name": name, "title": name}
    tab.current_detail_text = f"{name} 본문입니다."


def _tokens(window: LawSearchWindow) -> list[str]:
    return [
        str(document["token"])
        for document in window._collect_open_documents()
    ]


def _closable_sources(window: LawSearchWindow) -> set[str]:
    window._refresh_open_documents()
    sources = set()
    for index in range(window.open_document_tabs.count()):
        if window._open_document_closable(index):
            document = window._open_document_descriptor_at(index)
            sources.add(str(document.get("source")))
    return sources


@pytest.mark.parametrize(
    ("attribute", "source", "label"),
    [
        ("central_tab", "central", "중앙부처 질의회신"),
        ("expc_tab", "expc", "법령해석례"),
        ("prec_tab", "prec", "판례"),
    ],
)
def test_search_screen_document_can_be_closed(
    window: LawSearchWindow, attribute: str, source: str, label: str
) -> None:
    tab = getattr(window, attribute)
    _open_detail(tab, label)

    window._refresh_open_documents()
    index = next(
        index
        for index in range(window.open_document_tabs.count())
        if str(
            (window._open_document_descriptor_at(index) or {}).get("source")
        )
        == source
    )
    assert window._open_document_closable(index) is True

    window._close_open_document_tab(index)

    assert tab.current_detail_text == ""
    assert tab._active_detail_row is None
    assert not any(token.startswith(f"{source}:") for token in _tokens(window))


def test_closing_one_screen_leaves_the_others(window: LawSearchWindow) -> None:
    """하나를 닫아도 다른 화면의 본문은 그대로 남는다."""
    _open_detail(window.central_tab, "중앙부처 질의회신")
    _open_detail(window.expc_tab, "법령해석례")
    _open_detail(window.prec_tab, "판례")
    window._refresh_open_documents()

    index = next(
        index
        for index in range(window.open_document_tabs.count())
        if str(
            (window._open_document_descriptor_at(index) or {}).get("source")
        )
        == "expc"
    )
    window._close_open_document_tab(index)

    tokens = _tokens(window)
    assert any(token.startswith("central:") for token in tokens)
    assert any(token.startswith("prec:") for token in tokens)
    assert not any(token.startswith("expc:") for token in tokens)


def test_keyword_screens_can_be_closed(window: LawSearchWindow) -> None:
    """조문검색으로 연 본문도 표시줄에서 바로 닫는다."""
    _open_detail(window.ai_related_tab, "연관법령")
    _open_detail(window.ai_search_tab, "조문검색")

    assert {"ai_related", "ai_search"} <= _closable_sources(window)

    window.ai_search_tab.close_open_document()
    assert window.ai_search_tab._active_detail_row is None
    assert window.ai_search_tab.current_detail_text == ""
