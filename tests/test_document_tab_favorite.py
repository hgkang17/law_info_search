"""본문 탭의 즐겨찾기 별표 동작 검증."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QTabBar

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab

ROW = {
    "target": "law",
    "label": "법령",
    "id": "009294",
    "name": "국토의 계획 및 이용에 관한 법률",
    "related": "",
    "organization": "국토교통부",
    "date": "",
    "number": "",
    "effective": "",
    "short_name": "국토계획법",
    "raw": {},
}


def _tab(tmp_path) -> ResourceSearchTab:
    QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "res.ini"), QSettings.Format.IniFormat)
    return ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )


def _star(tab: ResourceSearchTab, index: int = 0) -> QPushButton:
    button = tab.document_tabs.tabButton(
        index, QTabBar.ButtonPosition.LeftSide
    )
    assert isinstance(button, QPushButton)
    return button


def test_document_tab_gets_a_favorite_star(tmp_path) -> None:
    tab = _tab(tmp_path)

    tab._open_document_tab(dict(ROW))

    assert tab.document_tabs.count() == 1
    star = _star(tab)
    assert star.text() == "☆"
    assert star.isEnabled()


def test_article_favorite_opens_only_selected_unit_as_body(tmp_path) -> None:
    tab = _tab(tmp_path)
    payload = {
        "법령": {
            "기본정보": {
                "법령명_한글": "산업입지 및 개발에 관한 법률",
                "법령ID": "000000",
            },
            "조문": {
                "조문단위": [
                    {"조문번호": "6", "조문내용": "제6조 다른 조문"},
                    {"조문번호": "7", "조문내용": "제7조 선택한 조문"},
                ]
            },
        }
    }
    row = {
        **ROW,
        "id": "000000",
        "name": "산업입지 및 개발에 관한 법률",
    }

    tab.open_cached_favorite_article(
        {"row": row, "payload": payload},
        {"jo": "000700", "hang": "", "ho": "", "mok": "", "label": "제7조"},
    )

    assert "제7조 선택한 조문" in tab.current_detail_text
    assert "제6조 다른 조문" not in tab.current_detail_text
    state = tab._document_states[tab._active_document_key]
    assert state["row"]["target"] == "law_article"


def test_returning_from_favorite_article_keeps_full_law_document(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    payload = {
        "법령": {
            "기본정보": {
                "법령명_한글": ROW["name"],
                "법령ID": ROW["id"],
            },
            "조문": {
                "조문단위": [
                    {"조문번호": "2", "조문내용": "제2조 전체 법률의 앞 조문"},
                    {"조문번호": "69", "조문내용": "제69조 선택한 조문"},
                ]
            },
        }
    }
    record = {"row": dict(ROW), "payload": payload}

    tab.open_cached_law(record)
    law_key = tab._active_document_key
    tab.open_cached_favorite_article(
        record,
        {"jo": "006900", "hang": "", "ho": "", "mok": "", "label": "제69조"},
    )
    article_key = tab._active_document_key
    assert (
        tab._document_states[law_key]["document"]
        is not tab._document_states[article_key]["document"]
    )
    assert "제2조 전체 법률의 앞 조문" not in tab.current_detail_text

    tab._activate_document_tab(tab._document_tab_index(law_key))
    app.processEvents()

    assert "제2조 전체 법률의 앞 조문" in tab.current_detail_text
    assert "제69조 선택한 조문" in tab.current_detail_text


def test_cached_render_is_loaded_after_deferred_document_isolation(tmp_path) -> None:
    payload = {
        "법령": {
            "기본정보": {
                "법령명_한글": ROW["name"],
                "법령ID": ROW["id"],
            },
            "조문": {
                "조문단위": [
                    {"조문번호": "2", "조문내용": "제2조 저장된 법률 전체 본문"},
                ]
            },
        }
    }
    source = _tab(tmp_path)
    source.open_cached_law({"row": dict(ROW), "payload": payload})
    snapshot = source._active_law_render_snapshot()

    restored = _tab(tmp_path)
    restored.open_cached_law(
        {"row": dict(ROW), "payload": payload, **snapshot}
    )

    assert "제2조 저장된 법률 전체 본문" in restored.current_detail_text
    assert "제2조 저장된 법률 전체 본문" in restored.detail_view.toPlainText()


def test_returning_from_article_restores_full_law_toc_immediately(tmp_path) -> None:
    tab = _tab(tmp_path)
    full_toc = [
        (2, "제1장 총칙", "toc-law-1"),
        (4, "제2조(정의)", "toc-law-2"),
        (4, "제3조(기본원칙)", "toc-law-3"),
    ]
    article_toc = [
        (2, "제3장 산업단지의 지정", "toc-article-1"),
        (4, "제6조(국가산업단지의 지정)", "toc-article-2"),
    ]

    tab._open_document_tab(dict(ROW))
    law_key = tab._active_document_key
    law_document = QTextDocument(tab)
    law_document.setPlainText("법령 전체 본문")
    law_state = tab._document_states[law_key]
    law_state.update(
        {
            "document": law_document,
            "plain_text": "법령 전체 본문",
            "toc_entries": full_toc,
        }
    )
    tab._set_active_text_document(law_document)
    tab._populate_toc(full_toc)

    article_row = {
        "target": "law_article",
        "id": "009294:000600:::",
        "label": "조항호목",
        "name": f"{ROW['name']} 제6조",
    }
    tab._open_document_tab(article_row, defer_restore=True)
    article_key = tab._active_document_key
    article_document = QTextDocument(tab)
    article_document.setPlainText("제6조 본문")
    article_state = tab._document_states[article_key]
    article_state.update(
        {
            "document": article_document,
            "plain_text": "제6조 본문",
            "toc_entries": article_toc,
        }
    )
    tab._set_active_text_document(article_document)
    tab._populate_toc(article_toc)

    tab._activate_document_tab(tab._document_tab_index(law_key))

    assert tab._current_toc_entries == full_toc
    assert tab.toc_tree.topLevelItem(0).text(0) == "제1장 총칙"
    assert law_state["toc_entries"] == full_toc


def test_article_favorite_waits_for_running_api_request(tmp_path) -> None:
    tab = _tab(tmp_path)

    class BusyWorker:
        @staticmethod
        def isRunning() -> bool:
            return True

    tab.worker = BusyWorker()
    tab.add_article_favorite_by_id(
        ROW["id"],
        "000600",
        f"{ROW['name']} 제6조",
        ROW["name"],
    )

    assert tab._pending_article_favorite is not None
    assert tab._article_favorite_waiting_for_worker is True
    assert "자동으로 추가" in tab.status_label.text()
    tab.worker = None


def test_reference_popup_star_saves_article_with_real_mouse_click(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    assert tab.law_cache.save(dict(ROW), {"법령": {"조문": {}}})
    popup = tab.reference_popup
    popup.reference_request = {
        "law_id": ROW["id"],
        "law_name": ROW["name"],
        "jo": "000200",
        "hang": "",
        "ho": "",
        "mok": "",
    }
    popup.set_content("제2조", "<p>제2조 본문</p>")
    popup.show()
    app.processEvents()

    QTest.mouseClick(popup.favorite_button, Qt.MouseButton.LeftButton)
    app.processEvents()

    assert tab.law_cache.is_article_favorite(ROW, "000200")
    assert popup.favorite_button.text() == "★"


def test_full_law_body_has_article_favorite_stars_on_heading_left(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    payload = {
        "법령": {
            "기본정보": {
                "법령명_한글": ROW["name"],
                "법령ID": ROW["id"],
            },
            "조문": {
                "조문단위": [
                    {"조문번호": "1", "조문내용": "제1조(목적) 이 법은…"},
                    {"조문번호": "2", "조문내용": "제2조(정의) 뜻은…"},
                ]
            },
        }
    }
    assert tab.law_cache.save(dict(ROW), payload)
    tab.resize(1200, 760)
    tab.show()
    tab.open_cached_law({"row": dict(ROW), "payload": payload})
    tab._set_reading_mode(True)
    app.processEvents()
    tab._position_three_stage_buttons()

    assert len(tab._article_favorite_buttons) == 2
    first_star = tab._article_favorite_buttons[0]
    assert first_star.text() == "☆"
    assert first_star.isVisible()
    anchor = tab._current_three_stage_articles[0]["anchor"]
    position = tab._three_stage_anchor_positions[anchor]
    cursor = tab.detail_view.textCursor()
    cursor.setPosition(position)
    heading_rect = tab.detail_view.cursorRect(cursor)
    assert first_star.geometry().right() < heading_rect.left()
    assert first_star.width() == ResourceSearchTab._ARTICLE_FAVORITE_SIZE
    assert (
        heading_rect.left() - first_star.geometry().right()
        <= ResourceSearchTab._ARTICLE_FAVORITE_GAP + 1
    )
    assert (
        cursor.blockFormat().leftMargin()
        == ResourceSearchTab._ARTICLE_FAVORITE_HEADING_MARGIN
    )

    first_star.click()
    assert tab.law_cache.is_article_favorite(ROW, "000100")
    assert first_star.text() == "★"
    assert tab._article_favorite_buttons[1].text() == "☆"

    first_star.click()
    assert not tab.law_cache.is_article_favorite(ROW, "000100")
    assert first_star.text() == "☆"


def test_inline_favorite_refresh_loads_saved_file_once(
    tmp_path, monkeypatch
) -> None:
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    payload = {
        "법령": {
            "기본정보": {
                "법령명_한글": ROW["name"],
                "법령ID": ROW["id"],
            },
            "조문": {
                "조문단위": [
                    {"조문번호": str(index), "조문내용": f"제{index}조 본문"}
                    for index in range(1, 6)
                ]
            },
        }
    }
    assert tab.law_cache.save(dict(ROW), payload)
    tab.resize(1200, 760)
    tab.show()
    tab.open_cached_law({"row": dict(ROW), "payload": payload})
    tab._set_reading_mode(True)
    app.processEvents()
    assert len(tab._article_favorite_buttons) == 5

    calls = {"count": 0}
    original = tab.law_cache.article_favorites

    def counting(row):
        calls["count"] += 1
        return original(row)

    monkeypatch.setattr(tab.law_cache, "article_favorites", counting)
    tab._refresh_inline_article_favorites()
    assert calls["count"] == 1


def test_star_toggles_saved_document(tmp_path) -> None:
    tab = _tab(tmp_path)
    tab.law_cache.save_snapshot(ROW, html="<p>본문</p>", plain_text="본문")

    tab._open_document_tab(dict(ROW))
    _star(tab).click()

    assert tab.law_cache.is_favorite(ROW) is True
    assert _star(tab).text() == "★"

    _star(tab).click()

    assert tab.law_cache.is_favorite(ROW) is False
    assert _star(tab).text() == "☆"


def test_star_follows_favorite_changed_elsewhere(tmp_path) -> None:
    """즐겨찾기 화면에서 별을 풀어도 열린 탭의 별표가 따라간다."""
    tab = _tab(tmp_path)
    tab.law_cache.save_snapshot(ROW, html="<p>본문</p>", plain_text="본문")
    tab._open_document_tab(dict(ROW))

    tab.law_cache.set_favorite(ROW, True)
    tab._refresh_document_tab_favorites()
    assert _star(tab).text() == "★"

    tab.law_cache.set_favorite(ROW, False)
    tab._refresh_document_tab_favorites()
    assert _star(tab).text() == "☆"


def test_long_title_wraps_instead_of_being_cut(tmp_path) -> None:
    """긴 법령명이 잘려 시행령ㆍ시행규칙이 구분되지 않으면 안 된다."""
    wrap = ResourceSearchTab._two_line_tab_title

    assert wrap("국토의 계획 및 이용에 관한 법률 시행규칙").endswith("시행규칙")
    assert "\n" in wrap("국토의 계획 및 이용에 관한 법률 시행규칙")
    assert "…" not in wrap("도시·군관리계획수립지침")
    # 짧은 이름은 그대로 한 줄이다.
    assert wrap("산지관리법") == "산지관리법"


def test_tab_strip_scrolls_when_tabs_overflow(tmp_path) -> None:
    tab = _tab(tmp_path)
    for order in range(8):
        row = dict(ROW)
        row["id"] = f"{order:06d}"
        row["name"] = f"국토의 계획 및 이용에 관한 법률 시행규칙 {order}"
        tab._open_document_tab(row)

    strip = tab.document_tab_strip
    strip.show()
    strip.resize(320, strip.height())
    strip.refresh()
    # 스크롤 범위는 레이아웃이 한 번 돌아야 갱신된다.
    QApplication.processEvents()

    assert tab.document_tabs.width() > strip.viewport().width()
    assert strip.horizontalScrollBar().maximum() > 0


def test_reopening_same_document_keeps_one_tab(tmp_path) -> None:
    tab = _tab(tmp_path)

    tab._open_document_tab(dict(ROW))
    tab._open_document_tab(dict(ROW))

    assert tab.document_tabs.count() == 1
    assert tab._document_tab_row(
        str(tab.document_tabs.tabData(0) or "")
    ) is not None
def _decree_payload(name, law_id, articles):
    return {
        "법령": {
            "기본정보": {"법령명_한글": name, "법령ID": law_id},
            "조문": {"조문단위": articles},
        }
    }


def test_article_tab_never_overwrites_another_law_snapshot(tmp_path) -> None:
    """조문 탭 화면이 다른 법령의 저장 파일을 덮으면 안 된다.

    pending_row는 "마지막으로 조회한 행"이라 화면과 어긋날 수 있었다.
    그 값으로 법령ID를 잡는 바람에, 조문 하나만 띄운 화면이 직전에 연
    법령의 저장 파일에 그대로 저장돼 즐겨찾기로 열 때마다 엉뚱한 본문이
    떴다.
    """
    tab = _tab(tmp_path)
    law_row = {
        **ROW,
        "id": "009419",
        "name": "국토의 계획 및 이용에 관한 법률 시행령",
    }
    tab.open_cached_law(
        {
            "row": law_row,
            "payload": _decree_payload(
                law_row["name"],
                "009419",
                [{"조문번호": "1", "조문내용": "제1조(목적) 이 영은…"}],
            ),
        }
    )
    assert tab.pending_row["id"] == "009419"

    article_row = {
        **ROW,
        "id": "009727",
        "name": "공공주택 특별법 시행령",
    }
    tab.open_cached_favorite_article(
        {
            "row": article_row,
            "payload": _decree_payload(
                article_row["name"],
                "009727",
                [{"조문번호": "7", "조문내용": "제7조(주택지구의 지정 등) …"}],
            ),
        },
        {"jo": "000700", "hang": "", "ho": "", "mok": "", "label": "제7조"},
    )

    # 조문 탭에서 고른 행은 그 조문을 뽑아 온 법령이어야 한다.
    picked = tab._three_stage_link_row()
    assert picked is not None
    assert picked["id"] == "009727"

    # 그래도 조문 화면은 법령 전문이 아니므로 저장까지 가서는 안 된다.
    written: list[tuple[str, str]] = []
    tab.law_cache.update_snapshot = (
        lambda row, snapshot, **_kwargs: written.append(
            (str(row.get("id")), str(snapshot.get("rendered_plain_text", ""))[:20])
        )
    )
    tab._apply_three_stage_links(
        {
            "document_key": tab._active_document_key,
            "document_level": "decree",
            "item_id": "009419",
            "law_name": "국토의 계획 및 이용에 관한 법률 시행령",
            "organization": "",
        },
        {},
    )
    assert written == []


def test_snapshot_from_another_law_is_ignored(tmp_path) -> None:
    """예전 판이 남긴 잘못된 저장 화면은 무시하고 원문에서 다시 그린다."""
    tab = _tab(tmp_path)
    law_row = {
        **ROW,
        "id": "009419",
        "name": "국토의 계획 및 이용에 관한 법률 시행령",
    }
    from ui.tabs.resource_search import LAW_RENDER_SNAPSHOT_VERSION

    tab.open_cached_law(
        {
            "row": law_row,
            "payload": _decree_payload(
                law_row["name"],
                "009419",
                [{"조문번호": "1", "조문내용": "제1조(목적) 이 영은…"}],
            ),
            "render_snapshot_version": LAW_RENDER_SNAPSHOT_VERSION,
            "rendered_font_size": 10,
            "rendered_html": "<h1>공공주택 특별법 시행령</h1>",
            "rendered_plain_text": "공공주택 특별법 시행령\n제7조(주택지구의 지정 등) …",
            "rendered_toc_entries": [[4, "제7조(주택지구의 지정 등)", "a"]],
            "rendered_three_stage_articles": [],
            "render_highlight_terms": [],
        }
    )
    body = tab.detail_view.toPlainText()
    assert "제7조(주택지구의 지정 등)" not in body
    assert "제1조(목적)" in body
