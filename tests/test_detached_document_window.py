"""열린 본문 탭을 띠 밖으로 끌어 놓으면 별도 창으로 꺼내는지 검증."""

import os
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.dialogs import DetachedCaptionButton, DetachedDocumentWindow
from ui.tabs.resource_search import ResourceSearchTab


@pytest.fixture(autouse=True)
def no_background_comparison_request(monkeypatch):
    # 이 묶음은 창/별 버튼의 동작만 검증한다. 실제 조회 스레드를 남기지 않는다.
    monkeypatch.setattr(ResourceSearchTab, "_queue_three_stage_link_request", lambda *args: None)

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
    settings = QSettings(str(tmp_path / "detach.ini"), QSettings.Format.IniFormat)
    return ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )


def test_dragging_a_tab_far_below_the_strip_is_a_detach_spot(tmp_path) -> None:
    tab = _tab(tmp_path)
    bar = tab.document_tabs
    margin = bar.DETACH_MARGIN

    assert bar._is_detach_spot(QPoint(10, bar.height() + margin + 5))
    assert not bar._is_detach_spot(QPoint(10, bar.height() // 2))
    # 좌우로 끄는 것은 순서 바꾸기이므로 꺼내지 않는다.
    assert not bar._is_detach_spot(QPoint(-400, bar.height() // 2))


def _payload() -> dict:
    return {
        "법령": {
            "기본정보": {"법령명_한글": ROW["name"], "법령ID": ROW["id"]},
            "조문": {
                "조문단위": [
                    {"조문번호": "1", "조문내용": "제1조(목적) 본문이다."},
                    {"조문번호": "2", "조문내용": "제2조(정의) 뜻이다."},
                ]
            },
        }
    }


def test_detaching_opens_a_window_and_closes_the_tab(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    payload = _payload()
    row = {**ROW, "short_name": "테법"}
    assert tab.law_cache.save(row, payload)
    tab.resize(1000, 700)
    tab.show()
    tab.open_cached_law({"row": row, "payload": payload})
    app.processEvents()
    key = tab._active_document_key

    tab._detach_document_tab(key, QPoint(200, 200))
    app.processEvents()

    assert tab.document_tabs.count() == 0
    assert len(tab._detached_document_windows) == 1
    window = tab._detached_document_windows[0]
    assert isinstance(window, DetachedDocumentWindow)
    assert "제1조(목적) 본문이다." in window.browser.toPlainText()
    assert ROW["name"] in window.windowTitle()
    assert "테법" in window.document_tabs.tabText(0)
    assert window.toc_panel.isVisible()
    assert window.toc_tree.topLevelItemCount() == 2
    assert "제1조" in window.toc_tree.topLevelItem(0).text(0)
    assert [
        button.kind for button in window.header.findChildren(DetachedCaptionButton)
    ] == ["minimize", "maximize", "close"]
    # 탭, 다운로드 목록 단추(+간격), 창 버튼 셋.
    assert window.header.layout().count() == 6
    assert window.layout().contentsMargins().top() == 10
    assert window.header.layout().contentsMargins().left() == 8
    assert window.header.layout().contentsMargins().right() == 8
    assert window.header.height() == 38
    assert window.document_tabs.height() == 38
    assert window.document_tabs.mapTo(window, QPoint(0, 0)) == QPoint(10, 10)
    assert window.stack.contentsMargins().top() == 2
    family = window.current_page().source_reader.family_law_tree
    assert family.topLevelItemCount() == 3
    next_law = family.topLevelItem(1)
    QTest.mouseClick(
        family.viewport(), Qt.MouseButton.LeftButton,
        pos=family.visualItemRect(next_law).center(),
    )
    assert next_law.background(0).color().name() == "#b9def5"
    assert window.document_tabs.count() == 1  # 전문 열기는 여전히 더블클릭이다.
    window.close()


def test_detached_toc_navigates_its_own_document_and_filters(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = DetachedDocumentWindow(
        "목차 검증", '<a name="first"></a><p>제1조</p>'
        + '<p>긴 본문</p>' * 150 + '<a name="last"></a><p>제2조</p>',
        None, app.font(),
    )
    try:
        window.attach_toc([(1, "제1장 총칙", "first"),
                           (4, "제1조 목적", "first"), (4, "제2조 정의", "last")])
        window.show()
        app.processEvents()
        chapter = window.toc_tree.topLevelItem(0)
        window._toc_item_clicked(chapter.child(1))
        assert window.scroll_position() > 0
        window.toc_search_input.setText("정의")
        assert not chapter.isHidden()
        assert chapter.child(0).isHidden()
        assert not chapter.child(1).isHidden()
        window.toc_search_input.clear()
        assert not chapter.child(0).isHidden()
        window._toc_item_clicked(chapter.child(0))
        assert window.scroll_position() <= window.browser.document().documentMargin()
    finally:
        window.close()
        app.processEvents()


def test_detaching_an_unknown_tab_is_ignored(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    tab._open_document_tab(dict(ROW))
    app.processEvents()

    tab._detach_document_tab("__preview__", QPoint(0, 0))
    tab._detach_document_tab("law:없는키", QPoint(0, 0))

    assert tab.document_tabs.count() == 1
    assert tab._detached_document_windows == []


def test_detached_window_carries_article_star_and_three_stage(tmp_path) -> None:
    """꺼낸 창에도 조문 별표와 3단비교 단추가 함께 간다."""
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    payload = _payload()
    assert tab.law_cache.save(dict(ROW), payload)
    tab.resize(1000, 700)
    tab.show()
    tab.open_cached_law({"row": dict(ROW), "payload": payload})
    app.processEvents()
    key = tab._active_document_key
    # 3단비교 자료가 확인된 조문만 3단 단추를 보인다. 제1조만 켜 둔다.
    # 꺼내기 직전에 화면 상태를 다시 저장하므로 화면 쪽 목록을 고친다.
    articles = tab._current_three_stage_articles
    assert articles, "본문에서 조문 목록을 만들지 못했다"
    articles[0]["comparison_available"] = True

    tab._detach_document_tab(key, QPoint(200, 200))
    app.processEvents()

    window = tab._detached_document_windows[0]
    # 조문 수만큼 별표가 만들어지고, 앵커 자리를 찾았다.
    assert len(window._favorite_buttons) == len(articles)
    assert window._article_anchor_positions
    assert any(star.isVisible() for star in window._favorite_buttons)
    # 본체와 동일하게 미조회(None)는 유지하고 자료 없음(False)만 숨긴다.
    shown = [
        button.isVisible() for button in window._three_stage_buttons
    ]
    assert shown[0] is True
    assert shown == [a.get("comparison_available") is not False for a in articles]
    window.close()


def test_detached_window_star_toggles_the_article_favorite(tmp_path) -> None:
    """꺼낸 창의 별을 누르면 본체와 같은 즐겨찾기가 걸린다."""
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    payload = _payload()
    assert tab.law_cache.save(dict(ROW), payload)
    tab.resize(1000, 700)
    tab.show()
    tab.open_cached_law({"row": dict(ROW), "payload": payload})
    app.processEvents()
    key = tab._active_document_key
    article = dict(tab._current_three_stage_articles[0])

    tab._detach_document_tab(key, QPoint(200, 200))
    app.processEvents()
    window = tab._detached_document_windows[0]
    assert window._favorite_state(article) is False

    window._favorite_buttons[0].click()
    app.processEvents()

    assert tab.law_cache.is_article_favorite(dict(ROW), article["jo"])
    assert window._favorite_state(article) is True
    window.close()
