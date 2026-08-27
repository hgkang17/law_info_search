"""AI 답의 별표ㆍ서식 링크가 그 서식을 제대로 열어 주는지."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QUrl, QUrlQuery
from PySide6.QtWidgets import QApplication

from PySide6.QtCore import QSettings
from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.ai_chat_panel import AiChatPanel
from ui.tabs import resource_search
from ui.tabs.resource_search import (
    ResourceSearchTab,
    annex_name_similarity,
    query_value,
)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def test_annex_link_keeps_parentheses_in_the_name(qt_app) -> None:
    """괄호가 %28로 남으면 제목에 그대로 보이고 검색어도 어긋난다."""
    name = "건축ㆍ대수선ㆍ용도변경 (변경)허가 신청서"
    href = AiChatPanel._annex_href(name, "doc:licbyl:12345")
    query = QUrlQuery(QUrl(href))
    assert query_value(query, "name") == name
    assert "%28" not in query_value(query, "name")


def _rows() -> list[dict[str, object]]:
    return [
        {
            "id": "1",
            "name": "[별지 제1호서식] 건축ㆍ대수선ㆍ용도변경 (변경)허가 신청서",
            "raw": {},
        },
        {
            "id": "2",
            "name": "[별지 제2호서식] 건축ㆍ대수선ㆍ용도변경 (변경)신고서",
            "raw": {},
        },
        {"id": "3", "name": "[별표 1] 건축물의 용도", "raw": {}},
    ]


def test_annex_row_is_picked_when_the_name_is_written_a_bit_differently() -> None:
    """모델은 머리표를 빼고 띄어쓰기도 다르게 적는다. 그래도 찾아야 한다."""
    row = ResourceSearchTab._pick_annex_row(
        _rows(),
        item_id="",
        hint="",
        title="건축 대수선 용도변경 변경허가신청서",
    )
    assert row is not None
    assert row["id"] == "1"


def test_unrelated_annex_name_opens_nothing() -> None:
    """비슷하지 않은 이름까지 아무거나 열면 잘못된 서식을 보여 준다."""
    assert (
        ResourceSearchTab._pick_annex_row(
            _rows(), item_id="", hint="", title="농지전용허가신청서"
        )
        is None
    )


def test_annex_name_similarity_ignores_head_labels() -> None:
    assert annex_name_similarity(
        "건축ㆍ대수선ㆍ용도변경 (변경)허가 신청서",
        "[별지 제1호서식] 건축ㆍ대수선ㆍ용도변경 (변경)허가 신청서",
    ) == pytest.approx(1.0)
class _InstantAnnexWorker(resource_search.AnnexReferenceWorker):
    """법제처를 부르지 않고 곧바로 끝나는 가짜 조회."""

    def run(self) -> None:  # noqa: D102 - 부모 설명 그대로
        return


def test_second_click_starts_a_new_lookup(qt_app, tmp_path, monkeypatch) -> None:
    """한 번 열고 닫은 뒤 다시 누르면 그대로 멈춰 있으면 안 된다.

    끝난 QThread는 deleteLater로 지워지는데, 그걸 계속 손에 쥔 채
    isRunning()을 부르면 예외가 난다. 그 예외가 조회 시작 앞에서 터져
    팝업이 "불러오는 중"에서 영영 멈춰 있었다.
    """
    settings = QSettings(
        str(tmp_path / "annex.ini"), QSettings.Format.IniFormat
    )
    tab = ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    monkeypatch.setattr(
        resource_search, "AnnexReferenceWorker", _InstantAnnexWorker
    )
    url = QUrl("annexref://open?name=건축법 시행령 별표 1&category=licbyl")

    tab.open_annex_reference(url)
    first = tab._annex_worker
    assert first is not None
    first.wait(1000)
    for _ in range(20):
        qt_app.processEvents()
    # 끝난 작업은 손에서 놓아야 다음 클릭이 산다.
    assert tab._annex_worker is None

    tab.open_annex_reference(url)
    assert tab._annex_worker is not None
    assert tab._annex_worker is not first
    tab._annex_worker.wait(1000)
    for _ in range(20):
        qt_app.processEvents()


def test_bare_annex_label_searches_related_law(qt_app, tmp_path, monkeypatch) -> None:
    """'별표 1'만 있으면 법령마다 있어 고르지 못한다. 관련 법령명으로 찾는다."""
    settings = QSettings(
        str(tmp_path / "annex.ini"), QSettings.Format.IniFormat
    )
    tab = ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    monkeypatch.setattr(
        resource_search, "AnnexReferenceWorker", _InstantAnnexWorker
    )
    url = QUrl(
        "annexref://open?name=별표 1&category=licbyl&related=건축법 시행령"
    )
    tab.open_annex_reference(url)
    worker = tab._annex_worker
    assert worker is not None
    assert worker.query == "건축법 시행령"
    assert worker.search_scope == 2
    assert worker.title == "별표 1"
    worker.wait(1000)
    for _ in range(20):
        qt_app.processEvents()
def _numbered_rows() -> list[dict[str, object]]:
    """법제처 별표 목록에는 "…로 이동" 같은 길잡이 행이 섞여 나온다."""
    return [
        {
            "id": "a",
            "name": "[별표 1의7]로 이동",
            "raw": {"별표번호": "000107"},
        },
        {
            "id": "b",
            "name": "[별표 1] 용도별 건축물의 종류(제3조의5 관련)",
            "raw": {"별표번호": "000100"},
        },
    ]


def test_stub_row_is_never_opened() -> None:
    """"별표 1"이 "별표 1의7"에 그대로 들어 있어 엉뚱한 게 열렸다."""
    row = ResourceSearchTab._pick_annex_row(
        _numbered_rows(), item_id="", hint="1", title="건축법 시행령 별표 1"
    )
    assert row is not None
    assert row["id"] == "b"


def test_missing_annex_number_opens_nothing() -> None:
    """번호를 달고 온 결과에 찾는 번호가 없으면 아무것도 열지 않는다."""
    assert (
        ResourceSearchTab._pick_annex_row(
            _numbered_rows(),
            item_id="",
            hint="000900",
            title="건축법 시행령 별표 9",
        )
        is None
    )


def _tab(tmp_path):
    settings = QSettings(
        str(tmp_path / "popup.ini"), QSettings.Format.IniFormat
    )
    return ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )


def test_a_second_annex_opens_its_own_preview(qt_app, tmp_path) -> None:
    """별표 두 개를 나란히 놓고 견줄 수 있어야 한다."""
    tab = _tab(tmp_path)
    first = tab._pdf_popup_for_request("https://www.law.go.kr/a.pdf")
    assert first is tab.pdf_preview_popup
    first._url = "https://www.law.go.kr/a.pdf"
    first.show()
    qt_app.processEvents()

    second = tab._pdf_popup_for_request("https://www.law.go.kr/b.pdf")
    assert second is not first

    # 같은 별표를 또 누르면 새 창 대신 그 창을 다시 앞으로 가져온다.
    assert tab._pdf_popup_for_request("https://www.law.go.kr/a.pdf") is first

    # 닫아 둔 창은 다시 쓴다. 창이 무한정 쌓이면 안 된다.
    first.hide()
    qt_app.processEvents()
    assert tab._pdf_popup_for_request("https://www.law.go.kr/c.pdf") is first
    assert len(tab._all_pdf_popups()) == 2
