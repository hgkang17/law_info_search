"""법령 전문 아래쪽의 별표·서식 링크 회귀 테스트."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings, QUrl, Qt
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
            "기본정보": {
                "법령명_한글": "표시 시험법 시행령",
                "법령ID": "000001",
            },
            "조문": {
                "조문단위": [
                    {"조문내용": "제1조(목적) 이 영의 목적을 정한다."}
                ]
            },
            "별표": {
                "별표단위": [
                    {
                        "별표구분": "별표",
                        "별표번호": "0001",
                        "별표가지번호": "00",
                        "별표제목문자열": "시험 기준(제1조 관련)",
                        "별표서식파일링크": "/LSW/flDownload.do?flSeq=11",
                        "별표서식PDF파일링크": "/LSW/flDownload.do?flSeq=12",
                    },
                    {
                        "별표구분": "별지서식",
                        "별표번호": "0002",
                        "별표가지번호": "03",
                        "별표제목": "시험 신청서",
                        "별표서식파일링크": "/LSW/flDownload.do?flSeq=21",
                    },
                ]
            },
        }
    }


def test_law_annex_entries_use_links_from_body_payload() -> None:
    entries = ResourceSearchTab._law_annex_entries(_payload())

    assert [entry["label"] for entry in entries] == [
        "별표 1",
        "별지 제2호의3서식",
    ]
    assert entries[0]["file_url"].endswith("flDownload.do?flSeq=11")
    assert entries[0]["pdf_url"].endswith("flDownload.do?flSeq=12")


def test_annex_links_are_rendered_after_articles(qt_app, tmp_path) -> None:
    settings = QSettings(
        str(tmp_path / "annex-links.ini"), QSettings.Format.IniFormat
    )
    tab = ResourceSearchTab(
        lambda: "",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    row = {
        "target": "law",
        "id": "000001",
        "label": "법령",
        "name": "표시 시험법 시행령",
    }
    tab.pending_row = row
    tab._open_document_tab(row, defer_restore=True)
    title, metadata, sections = tab._parse_law_detail(_payload())
    tab._set_detail_document(
        title,
        metadata,
        sections,
        build_toc=True,
        law_annexes=tab._law_annex_entries(_payload()),
    )

    html = str(tab._document_states[tab._active_document_key]["source_html"])
    # 별표 목록에는 따로 제목 줄을 두지 않는다. 찾아올 자리 표시만 남긴다.
    assert "별표·서식 (2건)</a></h2>" not in html
    # 조문 구간은 제목을 달지 않으므로 첫 조문 글자를 기준으로 본다.
    assert html.index("제1조(목적)") < html.index('<a name="law-annexes">')
    # 제목을 누르면 그 자리에서 펼쳐지고, 내려받기는 오른쪽 작은 표시로 연다.
    assert "[별표1] 시험 기준(제1조 관련)" in html
    assert "[별지제2호의3서식] 시험 신청서" in html
    assert 'href="annex:0"' in html
    # 펼침 표시는 글자가 아니라 단추 모양 그림이다.
    assert "annex_expand.svg" in html
    assert "annex_hwp.svg" in html and "annex_pdf.svg" in html
    assert "flDownload.do?flSeq=11" in html
    assert "flDownload.do?flSeq=12" in html
    # 굵은 글씨와 세 줄짜리 링크 묶음은 없앴다.
    assert "원본 다운로드" not in html
    assert "PDF 다운로드" not in html
    assert tab.current_detail_text.index("[조문]") < tab.current_detail_text.index(
        "[별표·서식 (2건)]"
    )
    assert (
        tab.detail_view.textInteractionFlags()
        & Qt.TextInteractionFlag.LinksAccessibleByKeyboard
    )
    # 본문 끝의 별표도 왼쪽 조문 목차에서 바로 갈 수 있어야 한다.
    toc = tab._document_states[tab._active_document_key]["toc_entries"]
    anchors = [anchor for _depth, _label, anchor in toc]
    assert "law-annexes" in anchors
    assert "annex-item-0" in anchors
    assert "annex-item-1" in anchors
    labels = {anchor: label for _depth, label, anchor in toc}
    assert labels["law-annexes"] == "별표·서식 (2건)"
    assert labels["annex-item-0"] == "[별표1] 시험 기준(제1조 관련)"
    tab.close()


def test_annex_helper_name_is_not_shadowed_by_state(qt_app, tmp_path) -> None:
    """별표 목록을 뽑는 함수와 화면 상태가 같은 이름을 쓰지 않는다.

    한때 펼침 상태를 ``_law_annex_entries``라는 같은 이름의 속성에 담아,
    본문을 열 때 ``self._law_annex_entries(payload)``가 리스트를 호출하며
    ``'list' object is not callable``로 죽었다. 저장해 둔 조문을 여는 길이
    통째로 막혔던 문제라 이름이 다시 겹치지 않는지 지킨다.
    """
    settings = QSettings(
        str(tmp_path / "annex-name.ini"), QSettings.Format.IniFormat
    )
    tab = ResourceSearchTab(
        lambda: "",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    try:
        assert callable(tab._law_annex_entries)
        entries = tab._law_annex_entries(_payload())
        assert [entry["label"] for entry in entries] == [
            "별표 1",
            "별지 제2호의3서식",
        ]

        # 별표 목록을 한 번 그린 뒤에도 함수 자리는 그대로여야 한다.
        parts: list[str] = []
        tab._append_law_annex_section(parts, [], entries)
        assert callable(tab._law_annex_entries)
        assert tab._annex_section_entries == entries
    finally:
        tab.close()


def test_annex_title_opens_constrained_inline_pdf_panel(
    qt_app, tmp_path, monkeypatch
) -> None:
    settings = QSettings(
        str(tmp_path / "inline-annex.ini"), QSettings.Format.IniFormat
    )
    tab = ResourceSearchTab(
        lambda: "",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    try:
        tab.resize(900, 800)
        tab.show()
        row = {
            "target": "law",
            "id": "000001",
            "label": "법령",
            "name": "표시 시험법 시행령",
        }
        tab.pending_row = row
        tab._open_document_tab(row, defer_restore=True)
        title, metadata, sections = tab._parse_law_detail(_payload())
        tab._set_detail_document(
            title,
            metadata,
            sections,
            build_toc=True,
            law_annexes=tab._law_annex_entries(_payload()),
        )
        monkeypatch.setattr(tab, "_start_annex_download", lambda *_args: None)

        tab._toggle_annex_preview("0")
        qt_app.processEvents()

        assert not tab.inline_annex_preview.isHidden()
        assert tab.inline_annex_preview.parent() is tab.detail_view.viewport()
        assert tab.inline_annex_preview.minimumHeight() >= 320
        assert tab.inline_annex_preview.maximumHeight() <= 600
        assert tab.inline_annex_preview.height() <= 560
        viewport_height = tab.detail_view.viewport().height()
        if viewport_height > 360:
            assert tab.inline_annex_preview.height() < viewport_height
        assert tab.inline_annex_preview.pdf_view.pageMode().name == "MultiPage"
        assert tab.inline_annex_preview.page_spin.minimum() == 1
        source = str(tab._document_states[tab._active_document_key]["source_html"])
        assert tab.ANNEX_SECTION_START in source
        # 자리는 이름 앵커가 아니라 스페이서 그림 하나로 잡는다. 이름을
        # 붙인 빈 글자는 Qt가 위 별표 제목 줄에 붙여 버려 미리보기가 한
        # 줄 위에서 시작했다.
        assert tab.ANNEX_PREVIEW_SPACER_IMAGE in source
        tab._place_inline_annex_preview()
        qt_app.processEvents()
        title_cursor = tab._find_named_anchor_cursor("annex-item-0")
        slot_cursor = tab._find_named_anchor_cursor(tab.ANNEX_PREVIEW_SLOT_NAME)
        assert title_cursor is not None
        assert slot_cursor is not None
        assert title_cursor.position() < slot_cursor.position()
        assert tab.inline_annex_preview.geometry().height() >= 320
        assert tab.inline_annex_preview.geometry().width() <= 720
        assert tab.inline_annex_preview.geometry().left() <= 10
        assert tab.inline_annex_preview.geometry().top() >= (
            tab.detail_view.cursorRect(title_cursor).top() - 2
        )
        tab.inline_annex_preview._toggle_expanded()
        assert tab.inline_annex_preview.expand_button.text() == "축소"
        assert tab.inline_annex_preview.height() == 560
        tab.inline_annex_preview._toggle_expanded()
        assert tab.inline_annex_preview.expand_button.text() == "크게"
        assert tab.inline_annex_preview.height() == 340
        assert tab._active_annex_preview_key.endswith("flSeq=12")

        tab._close_inline_annex_preview()
        assert tab.inline_annex_preview.isHidden()
        assert tab._annex_previews == {}
    finally:
        tab.close()


def test_opening_another_annex_keeps_previous_preview_open(
    qt_app, tmp_path, monkeypatch
) -> None:
    settings = QSettings(
        str(tmp_path / "multiple-inline-annex.ini"), QSettings.Format.IniFormat
    )
    tab = ResourceSearchTab(
        lambda: "",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    try:
        tab.resize(900, 900)
        tab.show()
        row = {
            "target": "law",
            "id": "000001",
            "label": "법령",
            "name": "표시 시험법 시행령",
        }
        tab.pending_row = row
        tab._open_document_tab(row, defer_restore=True)
        title, metadata, sections = tab._parse_law_detail(_payload())
        tab._set_detail_document(
            title,
            metadata,
            sections,
            build_toc=True,
            law_annexes=tab._law_annex_entries(_payload()),
        )
        monkeypatch.setattr(tab, "_start_annex_download", lambda *_args: None)

        tab._toggle_annex_preview("0")
        qt_app.processEvents()
        first_key = tab._active_annex_preview_key
        first_panel = tab._annex_preview_panels[first_key]

        tab._toggle_annex_preview("1")
        qt_app.processEvents()

        assert len(tab._annex_previews) == 2
        assert len(tab._annex_preview_panels) == 2
        assert first_key in tab._annex_previews
        assert not first_panel.isHidden()
        assert tab._active_annex_preview_key != first_key
    finally:
        tab.close()


def test_annex_section_split_finds_saved_html_without_comments() -> None:
    """저장 toHtml()은 주석을 버린다. 앵커만으로도 별표 구간을 찾아야 한다."""
    source = (
        '<h1>시험법</h1>'
        '<a name="law-annexes"></a>'
        '<div class="content">[별표1]</div>'
    )
    head, tail = ResourceSearchTab._split_annex_section_html(source)
    assert head.endswith("<h1>시험법</h1>")
    assert tail == ""
    commented = (
        "앞<!--annex-section--><a name=\"law-annexes\"></a>"
        "목록<!--/annex-section-->뒤"
    )
    head, tail = ResourceSearchTab._split_annex_section_html(commented)
    assert head == "앞"
    assert tail == "뒤"


def test_annex_link_url_uses_path(qt_app, tmp_path, monkeypatch) -> None:
    settings = QSettings(
        str(tmp_path / "annex-url.ini"), QSettings.Format.IniFormat
    )
    tab = ResourceSearchTab(
        lambda: "",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    try:
        tab.resize(900, 800)
        tab.show()
        row = {
            "target": "law",
            "id": "000001",
            "label": "법령",
            "name": "표시 시험법 시행령",
        }
        tab.pending_row = row
        tab._open_document_tab(row, defer_restore=True)
        title, metadata, sections = tab._parse_law_detail(_payload())
        tab._set_detail_document(
            title,
            metadata,
            sections,
            build_toc=True,
            law_annexes=tab._law_annex_entries(_payload()),
        )
        monkeypatch.setattr(tab, "_start_annex_download", lambda *_args: None)
        tab._detail_link_clicked(QUrl("annex:0"))
        qt_app.processEvents()
        assert tab._active_annex_preview_key.endswith("flSeq=12")
        assert not tab.inline_annex_preview.isHidden()
    finally:
        tab.close()


def test_body_lookup_button_is_removed_from_integrated_search(
    qt_app, tmp_path
) -> None:
    settings = QSettings(
        str(tmp_path / "integrated-button.ini"), QSettings.Format.IniFormat
    )
    tab = ResourceSearchTab(
        lambda: "",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    try:
        tab.select_category("law")
        assert tab.detail_button.isHidden()
        tab.select_category("__all__")
        assert tab.detail_button.isHidden()
        tab.select_category("admrul")
        assert tab.detail_button.isHidden()
    finally:
        tab.close()


def test_resource_category_switch_restores_search_list_state(
    qt_app, tmp_path
) -> None:
    settings = QSettings(
        str(tmp_path / "category-state.ini"), QSettings.Format.IniFormat
    )
    tab = ResourceSearchTab(
        lambda: "",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    try:
        tab.select_category("__all__")
        tab.query_input.setText("도시계획")
        tab.result_rows = [
            {
                "target": "law",
                "label": "법령",
                "id": "1",
                "name": "도시계획법",
                "related": "",
                "kind": "법률",
                "date": "",
                "effective": "",
            }
        ]
        tab._render_result_rows()
        tab.result_count.setText("1건")

        tab.select_category("law")
        assert tab.result_table.rowCount() == 0
        tab.select_category("__all__")

        assert tab.query_input.text() == "도시계획"
        assert tab.result_table.rowCount() == 1
        assert tab.result_count.text() == "1건"
    finally:
        tab.close()


def test_saved_law_keeps_annex_list_clickable_after_reopen(
    qt_app, tmp_path, monkeypatch
) -> None:
    """저장 본문을 다시 열어도 별표 제목이 눌리는지 확인한다.

    저장 본문은 그려 둔 HTML을 그대로 되살리므로 `_set_detail_document`를
    거치지 않는다. 그 안에서만 채우던 `_annex_section_entries`가 비어 있으면
    화면에는 별표 목록이 보이는데 눌러도 아무 일이 없다.
    """
    settings = QSettings(
        str(tmp_path / "saved-annex.ini"), QSettings.Format.IniFormat
    )
    tab = ResourceSearchTab(
        lambda: "",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    try:
        monkeypatch.setattr(tab, "_start_annex_download", lambda *_args: None)
        row = {
            "target": "law",
            "id": "000001",
            "label": "법령",
            "name": "표시 시험법 시행령",
        }
        # 실제 저장본처럼 "그려 둔 HTML" 스냅샷을 함께 넣는다. 이것이
        # 있어야 open_cached_law가 복원 경로(_restore_cached_law_render)를
        # 타고, 그때 _set_detail_document를 건너뛴다.
        tab.pending_row = dict(row)
        tab._show_detail(_payload(), save_cache=False)
        qt_app.processEvents()
        assert tab._annex_section_entries, "첫 조회에서 별표 목록이 비었다"
        record = {"row": row, "payload": _payload(), "name": row["name"]}
        record.update(tab._active_law_render_snapshot())

        # 다른 문서를 보다 돌아온 상황을 만든다.
        tab._annex_section_entries = []

        tab.open_cached_law(record)
        qt_app.processEvents()

        assert tab._annex_section_entries, "저장 본문에 별표 목록이 복원되지 않았다"

        tab._detail_link_clicked(QUrl("annex:0"))
        qt_app.processEvents()
        assert not tab.inline_annex_preview.isHidden()
    finally:
        tab.close()


def test_annex_list_survives_switching_document_tabs(
    qt_app, tmp_path, monkeypatch
) -> None:
    """다른 본문 탭을 다녀와도 별표 제목이 계속 눌려야 한다.

    별표 목록은 화면 하나에 전역으로 두면 안 된다. 탭마다 다른 목록이라
    문서 상태에 함께 담아 두고 탭을 되살릴 때 같이 복원한다.
    """
    settings = QSettings(
        str(tmp_path / "tab-annex.ini"), QSettings.Format.IniFormat
    )
    tab = ResourceSearchTab(
        lambda: "",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    try:
        monkeypatch.setattr(tab, "_start_annex_download", lambda *_args: None)
        row = {
            "target": "law",
            "id": "000001",
            "label": "법령",
            "name": "표시 시험법 시행령",
        }
        tab.pending_row = dict(row)
        tab._show_detail(_payload(), save_cache=False)
        qt_app.processEvents()
        key = tab._active_document_key
        assert tab._annex_section_entries

        # 별표가 없는 다른 문서로 옮겼다가 돌아온다.
        tab._save_active_document_state()
        tab._annex_section_entries = []
        tab._restore_document_state(key)
        qt_app.processEvents()

        assert tab._annex_section_entries, "탭을 되살릴 때 별표 목록이 비었다"
        tab._detail_link_clicked(QUrl("annex:0"))
        qt_app.processEvents()
        assert not tab.inline_annex_preview.isHidden()
    finally:
        tab.close()


def test_inline_pdf_load_none_is_not_treated_as_failure(qt_app) -> None:
    """load()가 None을 돌려줘도 실패 문구를 바로 띄우지 않는다."""
    from ui.dialogs import InlinePdfPreviewPanel

    panel = InlinePdfPreviewPanel()
    try:
        panel.document.load = lambda _device: None
        panel.show_pdf(b"%PDF-1.4", "시험 별표")
        qt_app.processEvents()
        assert "실패했습니다: None" not in panel.status_label.text()
    finally:
        panel.close()
