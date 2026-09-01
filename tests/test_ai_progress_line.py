"""AI 대화 진행줄 검증.

법령을 여러 번 찾는 질문은 답까지 몇 분이 걸린다. 그동안 화면이
멈춰 보이지 않도록 몇 초째인지와 무엇을 하는 중인지를 계속 보인다.
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
)

from llm import (
    ClaudeCodeProvider,
    CodexAppServerProvider,
    GeminiProvider,
    ModelInfo,
)
from llm.ai_cli_setup import CLAUDE_CLI
from ui.tabs import ai_chat_panel
from ui.tabs.ai_chat_panel import (
    AiChatPanel,
    PROVIDER_TAB_LABELS,
    ShimmerLabel,
    _API_SETTINGS_BUTTON_WIDTH_MARGIN,
    _PROVIDER_COMBO_WIDTH_MARGIN,
    _label_width,
)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def avoid_real_cli_status_processes(monkeypatch) -> None:
    """화면 배치 테스트가 설치된 CLI를 실제로 실행하지 않게 한다."""
    monkeypatch.setattr(
        ai_chat_panel.CliStatusCoordinator,
        "request",
        lambda _self: None,
    )


@pytest.fixture
def panel(qt_app, tmp_path):
    # 실제 사용자 설정을 건드리지 않는다. 패널은 CLI 확인 결과처럼
    # 다음 실행까지 남는 값을 설정에 쓰므로, 시험이 그 파일을 함께
    # 쓰면 시험끼리도 서로 영향을 준다.
    settings = QSettings(
        str(tmp_path / "ai-panel.ini"), QSettings.Format.IniFormat
    )
    widget = AiChatPanel(settings=settings, standalone=True)
    try:
        yield widget
    finally:
        widget.deleteLater()


def _stream(panel):
    """화면에 보이는 제공자의 답 상태. 답은 제공자마다 따로 돈다."""
    return panel._streams[panel._active_provider_name]


def test_saved_gemini_catalog_waits_until_panel_is_visible(
    qt_app, tmp_path, monkeypatch
) -> None:
    """숨은 AI 패널은 저장된 키만으로 네트워크 스레드를 시작하지 않는다."""
    settings = QSettings(
        str(tmp_path / "hidden-panel.ini"), QSettings.Format.IniFormat
    )
    settings.setValue("ai/provider", GeminiProvider.name)
    settings.setValue(f"ai/key/{GeminiProvider.name}", "saved-key")
    requests: list[tuple[object, str]] = []

    monkeypatch.setattr(
        ai_chat_panel.ModelCatalogCoordinator,
        "request",
        lambda _self, provider_class, api_key: (
            requests.append((provider_class, api_key)) or "request-key"
        ),
    )
    monkeypatch.setattr(
        ai_chat_panel.CliStatusCoordinator,
        "request",
        lambda _self: None,
    )

    widget = AiChatPanel(settings=settings, standalone=True)
    try:
        assert requests == []
        assert widget._model_catalog_reload_pending is True

        widget._start_visible_background_checks()

        assert requests == [(GeminiProvider, "saved-key")]
        assert widget._model_catalog_reload_pending is False
    finally:
        widget.shutdown()
        widget.close()
        widget.deleteLater()


def test_shimmer_moves_only_while_running(qt_app) -> None:
    label = ShimmerLabel()
    label.setText("찾는 중")
    assert not label._timer.isActive()

    label.start()
    assert label._timer.isActive()
    label._advance()
    assert label._phase > 0

    label.stop()
    assert not label._timer.isActive()
    assert label._phase == 0.0


def test_progress_line_shows_seconds_and_what_it_is_doing(panel) -> None:
    panel._append_user("질문")
    panel._begin_answer()
    panel._show_progress("법령을 검색하는 중: 농지법", "tool")

    assert panel._current_status is not None
    assert "법령을 검색하는 중: 「농지법」" in panel._current_status.text()
    assert "초 동안" in panel._current_status.text()


def test_elapsed_seconds_keep_counting(panel) -> None:
    panel._append_user("질문")
    panel._begin_answer()
    _stream(panel)["started_at"] -= 12
    panel._refresh_status_line()

    assert panel._current_status.text().startswith("12초 동안")


def test_usage_is_kept_out_of_the_status_line(panel) -> None:
    """토큰 수는 자릿수가 커서 줄에는 안 쓰고 툴팁으로만 남긴다."""
    panel._append_user("질문")
    panel._begin_answer()
    panel._show_progress("토큰 100 넣고 10 받음", "usage")
    assert "토큰" not in panel._current_status.text()

    panel._show_progress("토큰 76,045 넣고 268 받음", "usage")
    panel._streaming = False
    _stream(panel)["started_at"] -= 23
    panel._refresh_status_line()

    assert panel._current_status.text() == "23초 걸렸습니다"
    assert panel._current_status.toolTip() == "토큰 76,045 넣고 268 받음"


def test_answer_start_clears_previous_usage(panel) -> None:
    panel._append_user("첫 질문")
    panel._begin_answer()
    panel._show_progress("토큰 100 넣고 10 받음", "usage")

    panel._append_user("두 번째 질문")
    panel._begin_answer()
    assert _stream(panel)["usage"] == ""


def test_tool_history_is_kept(panel) -> None:
    """지나간 도구까지 남아야 무엇을 근거로 답했는지 되짚을 수 있다."""
    panel._append_user("질문")
    panel._begin_answer()
    panel._show_progress("법령을 검색하는 중: 농지법", "tool")
    panel._show_progress("조문을 읽는 중: 제1조", "tool")
    panel._show_progress("답을 정리하는 중…", "thinking")

    assert _stream(panel)["tools"] == [
        "법령을 검색하는 중: 「농지법」",
        "조문을 읽는 중: 제1조",
    ]
    shown = panel._current_tool_log.text()
    assert "· 법령을 검색하는 중: 「농지법」" in shown
    assert "· 조문을 읽는 중: 제1조" in shown
    assert panel._current_tool_log.isVisibleTo(panel)


def test_repeated_tool_line_is_merged(panel) -> None:
    panel._append_user("질문")
    panel._begin_answer()
    panel._show_progress("조문을 읽는 중: 제1조", "tool")
    panel._show_progress("조문을 읽는 중: 제1조", "tool")

    assert _stream(panel)["tools"] == ["조문을 읽는 중: 제1조"]


def test_tool_line_shows_which_article_is_being_read() -> None:
    """조항호목 API의 6자리 코드를 사람이 읽는 조 번호로 되돌린다."""
    from llm.base import tool_hint, tool_progress_label

    # 앞의 0만 떼면 002500이 "2500"이 되어 "제2500조"로 찍혔었다.
    # 어느 법의 제25조인지는 화면이 [문서 id]를 이름으로 바꿔 붙인다.
    assert (
        tool_hint({"law_id": "009294", "jo": "002500"})
        == "[문서 009294] 제25조"
    )
    assert (
        tool_hint({"law_id": "009294", "jo": "002502"})
        == "[문서 009294] 제25조의2"
    )
    assert (
        tool_hint({"jo": "002500", "hang": "000200", "ho": "000100"})
        == "제25조제2항제1호"
    )
    # 검색어가 있으면 그쪽이 우선이다.
    assert tool_hint({"query": "농지법"}) == "농지법"
    # 본문 조회도 숫자 id를 그대로 그리지 않는다.
    assert tool_hint({"item_id": "2100000"}) == "[문서 2100000]"
    assert (
        tool_progress_label("search_law", {"query": "준산업단지"})
        == "법제처에서 법령 검색하는 중: 준산업단지"
    )
    assert tool_progress_label("", {}) == "도구를 쓰는 중"
    assert (
        tool_progress_label("mcp__law-search", {}, "도구를 준비하는 중")
        == "도구를 준비하는 중"
    )
    assert tool_progress_label("WebSearch", {}) == "일반 웹을 찾는 중"
    assert tool_progress_label("Bash", {}) == "도구를 쓰는 중"
    assert (
        tool_progress_label("Read", {}, "도구를 준비하는 중")
        == "도구를 준비하는 중"
    )
    assert (
        tool_progress_label(
            "search_law", {"query": "준산업단지", "search_scope": 2}
        )
        == "법제처에서 법령 본문 검색하는 중: 준산업단지"
    )
    assert (
        tool_progress_label(
            "get_article", {"law_id": "001839", "jo": "000200"}
        )
        == "법제처에서 조문 읽는 중: [문서 001839] 제2조"
    )
    assert (
        tool_progress_label("get_document", {"item_id": "003788"})
        == "법제처에서 본문 읽는 중: [문서 003788]"
    )
    assert (
        tool_progress_label("cite_check", {"case_number": "2013다61381"})
        == "판례 생사를 확인하는 중: 2013다61381"
    )
    assert (
        tool_progress_label(
            "impact_map", {"law_name": "민법", "jo": "010300"}
        )
        == "조문 영향 맵을 만드는 중: 민법 제103조"
    )
    assert (
        tool_progress_label(
            "ordinance_radar",
            {"query": "서울특별시 광진구 주차장 설치 및 관리 조례"},
        )
        == "조례 정비를 대조하는 중: 서울특별시 광진구 주차장 설치 및 관리 조례"
    )
    assert (
        tool_progress_label("search_inquiries", {"query": "농지전용"})
        == "법제처에서 질의회신 검색하는 중: 농지전용"
    )
    assert (
        tool_progress_label(
            "search_inquiries", {"query": "농지전용", "search_scope": 2}
        )
        == "법제처에서 질의회신 본문 검색하는 중: 농지전용"
    )
    assert (
        tool_progress_label(
            "get_inquiry", {"item_id": "555", "target": "molitCgmExpc"}
        )
        == "법제처에서 질의회신 본문 읽는 중: [문서 555]"
    )


def test_document_id_in_the_tool_line_becomes_the_full_law_name(panel, monkeypatch) -> None:
    """"[문서 009294] 제25조"를 저장된 본문의 법령 정식 명칭으로 바꿔 보인다."""

    monkeypatch.setattr(
        "ui.tabs.ai_chat_panel.lookup_cached_document_label",
        lambda _item_id: "",
    )

    class _Cache:
        def load_for_row(self, row):
            if str(row.get("id")) == "009294":
                return {"row": {"name": "국토의 계획 및 이용에 관한 법률"}}
            if str(row.get("id")) == "001839":
                return {
                    "row": {
                        "name": "산업입지 및 개발에 관한 법률",
                        "short_name": "산업입지법",
                    }
                }
            return None

    panel.document_cache = _Cache()
    panel._append_user("질문")
    panel._begin_answer()
    panel._show_progress("법제처에서 조문 읽는 중: [문서 009294] 제25조", "tool")
    panel._show_progress("법제처에서 조문 읽는 중: [문서 001839] 제2조", "tool")
    panel._show_progress("본문을 읽는 중: [문서 003788]", "tool")
    panel._show_progress("법제처에서 조문 읽는 중: [문서 999999] 제3조", "tool")

    assert _stream(panel)["tools"] == [
        "법제처에서 조문 읽는 중: 「국토의 계획 및 이용에 관한 법률」 제25조",
        "법제처에서 조문 읽는 중: 「산업입지 및 개발에 관한 법률」 제2조",
        "본문을 읽는 중",
        "법제처에서 조문 읽는 중: 제3조",
    ]
    assert "문서 999999" not in panel._current_tool_log.text()
    assert "003788" not in panel._current_tool_log.text()


def test_progress_line_quotes_law_names_not_keywords(panel) -> None:
    """진행 줄의 법령·지침 이름만 낫표로 감싼다. 검색 키워드는 그대로 둔다."""
    panel._append_user("질문")
    panel._begin_answer()
    panel._show_progress(
        "법제처에서 법령 검색하는 중: 국토의 계획 및 이용에 관한 법률",
        "tool",
    )
    panel._show_progress(
        "법제처에서 법령 검색하는 중: 국토의 계획 및 이용에 관한 법률 시행령",
        "tool",
    )
    panel._show_progress(
        "법제처에서 행정규칙 검색하는 중: 도시·군관리계획수립지침",
        "tool",
    )
    panel._show_progress(
        "법제처에서 질의회신 검색하는 중: 기초조사 생략",
        "tool",
    )
    panel._show_progress(
        "법제처에서 법령 본문 검색하는 중: 준산업단지",
        "tool",
    )

    assert _stream(panel)["tools"] == [
        "법제처에서 법령 검색하는 중: 「국토의 계획 및 이용에 관한 법률」",
        "법제처에서 법령 검색하는 중: 「국토의 계획 및 이용에 관한 법률 시행령」",
        "법제처에서 행정규칙 검색하는 중: 「도시·군관리계획수립지침」",
        "법제처에서 질의회신 검색하는 중: 기초조사 생략",
        "법제처에서 법령 본문 검색하는 중: 준산업단지",
    ]


def test_two_providers_can_answer_at_the_same_time(panel) -> None:
    """한 AI가 답하는 동안 다른 AI에게도 물을 수 있다."""

    def tab(label: str) -> int:
        return next(
            index
            for index in range(panel.provider_tabs.count())
            if panel.provider_tabs.tabText(index) == label
        )

    panel._provider_tab_changed(tab("Gemini"))
    first = panel._active_provider_name
    panel._append_user("첫 질문")
    panel._begin_answer()
    panel._append_chunk("제미나이 답")

    panel._provider_tab_changed(tab("Claude"))
    second = panel._active_provider_name
    panel._append_user("둘째 질문")
    panel._begin_answer()
    panel._append_chunk("클로드 답")

    # 두 답이 동시에 돌고, 글자는 서로 섞이지 않는다.
    assert {first, second} <= set(panel._streams)
    panel._append_chunk_for(first, " 뒷부분")
    assert panel._streams[first]["messages"][-1] == ["ai", "제미나이 답 뒷부분"]
    assert panel._streams[second]["messages"][-1] == ["ai", "클로드 답"]

    # 진행 문구와 도구 기록도 각자 따로 쌓인다.
    panel._progress_for(first, "법령을 검색하는 중: 농지법", "tool")
    panel._progress_for(second, "조문을 읽는 중: 제1조", "tool")
    assert panel._streams[first]["tools"] == ["법령을 검색하는 중: 「농지법」"]
    assert panel._streams[second]["tools"] == ["조문을 읽는 중: 제1조"]

    # 한쪽이 끝나도 다른 쪽은 계속 돈다.
    panel._answer_finished(first)
    assert first not in panel._streams
    assert second in panel._streams
    assert panel._streaming


def test_provider_tabs_have_separate_saved_chat_lists(qt_app, tmp_path) -> None:
    settings = QSettings(
        str(tmp_path / "ai-chat.ini"),
        QSettings.Format.IniFormat,
    )
    widget = AiChatPanel(settings=settings, standalone=True)
    try:
        widget.resize(900, 650)
        widget.show()
        qt_app.processEvents()
        assert [
            widget.provider_tabs.tabText(index)
            for index in range(widget.provider_tabs.count())
        ] == ["Gemini", "Claude", "Codex"]
        assert widget.provider_header_widget.height() == 36
        assert (
            widget.provider_tabs.tabRect(widget.provider_tabs.count() - 1).bottom()
            < widget.provider_header_widget.height()
        )

        gemini_index = next(
            index
            for index in range(widget.provider_tabs.count())
            if widget.provider_tabs.tabText(index) == "Gemini"
        )
        claude_index = next(
            index
            for index in range(widget.provider_tabs.count())
            if widget.provider_tabs.tabText(index) == "Claude"
        )
        widget.provider_tabs.setCurrentIndex(gemini_index)
        widget._messages = [["user", "제미나이 질문"], ["ai", "제미나이 답"]]
        widget._persist_current_chat()

        widget.provider_tabs.setCurrentIndex(claude_index)
        assert widget._messages == []
        widget._messages = [["user", "클로드 질문"], ["ai", "클로드 답"]]
        widget._persist_current_chat()

        widget.provider_tabs.setCurrentIndex(gemini_index)
        assert widget._messages == [
            ["user", "제미나이 질문"],
            ["ai", "제미나이 답"],
        ]
        assert widget.chat_history_list.count() == 1
        # 목록 한 줄은 제목 라벨과 삭제(×) 단추를 얹은 위젯이다.
        row = widget.chat_history_list.itemWidget(
            widget.chat_history_list.item(0)
        )
        title = row.findChild(QLabel, "aiChatHistoryItemTitle")
        assert title is not None and title.text() == "제미나이 질문"
        assert row.property("selected") is True
        menu_button = row.findChild(QPushButton, "aiChatHistoryMenu")
        assert menu_button is not None
        assert menu_button.text() == ""
        assert menu_button.accessibleName() == "채팅 메뉴"
        assert menu_button.size().width() == 24
        assert menu_button.size().height() == 24
        assert menu_button.focusPolicy() != Qt.FocusPolicy.NoFocus
        widget.resize(380, 500)
        widget.show()
        qt_app.processEvents()
        assert menu_button.isVisible()
        assert menu_button.geometry().right() <= row.rect().right()
        assert settings.contains("ai/chat_history/Gemini")
        assert settings.contains("ai/chat_history/Claude Code")
        assert widget.chat_workspace.handleWidth() == 12
        assert widget.chat_workspace.handle(1).isEnabled() is True
        assert widget.chat_workspace.widget(0).minimumWidth() == 0
        assert widget.chat_workspace.widget(1).minimumWidth() == 0
        assert widget.chat_workspace.isCollapsible(0) is True
        assert widget.chat_workspace.isCollapsible(1) is True
    finally:
        widget.shutdown()
        widget.deleteLater()


def test_embedded_panel_toggles_chat_list_without_hiding_composer(
    qt_app, tmp_path
) -> None:
    settings = QSettings(
        str(tmp_path / "embedded-history.ini"), QSettings.Format.IniFormat
    )
    widget = AiChatPanel(settings=settings, standalone=False)
    try:
        widget.resize(420, 700)
        widget.show()
        widget.provider_combo.setCurrentIndex(
            widget.provider_combo.findData(GeminiProvider)
        )
        qt_app.processEvents()

        assert widget.embedded_chat_pages.currentIndex() == 0
        assert widget.composer_frame.isVisibleTo(widget)
        assert widget.transcript_scroll.verticalScrollBarPolicy() == (
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        assert widget.history_toggle_button.width() == 28
        assert (
            widget.history_toggle_button.geometry().right()
            > widget.close_button.geometry().right()
        )
        assert widget.embedded_access_hint.text() == "무료 사용 가능"
        assert widget.embedded_access_hint.isVisibleTo(widget)
        widget.history_toggle_button.click()
        qt_app.processEvents()
        assert widget.embedded_chat_pages.currentWidget() is widget.history_panel
        assert widget.composer_frame.isVisibleTo(widget)
        assert widget.history_toggle_button.property("historyVisible") is True

        widget.history_toggle_button.click()
        assert widget.embedded_chat_pages.currentIndex() == 0
    finally:
        widget.shutdown()
        widget.deleteLater()


def test_short_chat_does_not_keep_long_chat_scroll_space(qt_app, tmp_path) -> None:
    settings = QSettings(
        str(tmp_path / "transcript-height.ini"), QSettings.Format.IniFormat
    )
    widget = AiChatPanel(settings=settings, standalone=True)
    try:
        widget.resize(900, 650)
        widget.show()
        widget._messages = [["ai", "\n".join(["긴 답변"] * 200)]]
        widget._render_saved_messages()
        qt_app.processEvents()
        qt_app.processEvents()
        assert widget.transcript_scroll.verticalScrollBar().maximum() > 0

        widget._messages = [["user", "안녕"], ["ai", "반갑습니다."]]
        widget._render_saved_messages()
        qt_app.processEvents()
        qt_app.processEvents()

        assert widget.transcript_scroll.verticalScrollBar().maximum() == 0
    finally:
        widget.shutdown()
        widget.deleteLater()


def test_transcript_scroll_ends_at_last_bubble(qt_app, tmp_path) -> None:
    settings = QSettings(
        str(tmp_path / "transcript-bottom.ini"), QSettings.Format.IniFormat
    )
    widget = AiChatPanel(settings=settings, standalone=True)
    try:
        widget.resize(900, 650)
        widget.show()
        widget._messages = [
            ["user", "긴 답변을 정리해 줘"],
            ["ai", "\n".join(f"답변 {index}" for index in range(180))],
        ]
        widget._render_saved_messages()
        qt_app.processEvents()
        qt_app.processEvents()

        bar = widget.transcript_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        last_bubble = widget.transcript_layout.itemAt(
            widget.transcript_layout.count() - 1
        ).widget()
        assert last_bubble is not None
        last_bottom = last_bubble.mapTo(
            widget.transcript_scroll.viewport(), last_bubble.rect().bottomLeft()
        ).y()
        trailing_space = widget.transcript_scroll.viewport().height() - last_bottom

        assert bar.maximum() > 0
        assert trailing_space <= 24
    finally:
        widget.shutdown()
        widget.deleteLater()


def test_finished_answer_does_not_expand_below_citations(qt_app, tmp_path) -> None:
    settings = QSettings(
        str(tmp_path / "citation-bottom.ini"), QSettings.Format.IniFormat
    )
    widget = AiChatPanel(settings=settings, standalone=True)
    try:
        widget.resize(1100, 800)
        widget.show()
        widget._append_user("이 규정을 검토해 줘")
        widget._begin_answer()
        section = (
            "## 검토 경로\n\n"
            "관리지역의 세분 여부와 적용 기준을 확인하고 관련 법령과 "
            "지침의 관계를 함께 검토합니다.\n\n"
            "| 구분 | 허용 여부 |\n"
            "|---|---|\n"
            "| 계획관리지역 | 원칙적으로 가능 |\n"
            "| 생산관리지역 | 요건을 확인하여 포함 |\n"
            "| 보전관리지역 | 면적 상한 안에서 포함 |\n\n"
            "- 기반시설과 환경 기준을 함께 확인합니다.\n"
            "- 세부적인 면적 요건도 별도로 검토합니다."
        )
        answer = (
            "\n\n---\n\n".join(section for _index in range(6))
            + "\n\n"
            "[국토계획법 제51조](law:009294:51), "
            "[국토계획법 제37조](law:009294:37), "
            "[국토계획법 제44조](law:009294:44)를 확인했습니다."
        )
        _stream_more(widget, qt_app, answer)
        widget._answer_finished(widget._active_provider_name)
        for _ in range(10):
            qt_app.processEvents()

        citation = widget.transcript_content.findChild(
            QLabel, "aiChatCitationCheck"
        )
        assert citation is not None
        answer_column = citation.parentWidget()
        assert answer_column is not None
        blank_inside_answer = answer_column.height() - (
            citation.y() + citation.height()
        )
        bar = widget.transcript_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        citation_bottom = citation.mapTo(
            widget.transcript_scroll.viewport(), citation.rect().bottomLeft()
        ).y()
        trailing_space = (
            widget.transcript_scroll.viewport().height() - citation_bottom
        )

        assert blank_inside_answer <= 12
        assert bar.maximum() > 0
        assert trailing_space <= 24
    finally:
        widget.shutdown()
        widget.deleteLater()


def test_sending_from_embedded_history_starts_new_chat(qt_app, tmp_path) -> None:
    settings = QSettings(
        str(tmp_path / "embedded-new-chat.ini"), QSettings.Format.IniFormat
    )
    widget = AiChatPanel(settings=settings, standalone=False)
    try:
        widget._messages = [["user", "기존 질문"], ["ai", "기존 답변"]]
        widget._persist_current_chat()
        old_chat_id = widget._active_chat_ids[widget._active_provider_name]
        widget.input_edit.setPlainText("새 질문")
        widget._toggle_embedded_chat_history()

        assert widget._prepare_embedded_history_send() is True
        assert widget.embedded_chat_pages.currentIndex() == 0
        assert widget.input_edit.toPlainText() == "새 질문"
        assert widget._messages == []
        assert widget._active_chat_ids[widget._active_provider_name] == ""
        assert any(
            str(record.get("id") or "") == old_chat_id
            for record in widget._provider_history()
        )
    finally:
        widget.shutdown()
        widget.deleteLater()


def test_clearing_outer_chat_immediately_clears_embedded_history(
    qt_app, tmp_path, monkeypatch
) -> None:
    settings = QSettings(
        str(tmp_path / "shared-history.ini"), QSettings.Format.IniFormat
    )
    outer = AiChatPanel(settings=settings, standalone=True)
    embedded = AiChatPanel(settings=settings, standalone=False)
    try:
        outer.chatHistoryCleared.connect(embedded.apply_external_history_clear)
        outer._messages = [["user", "공유 대화"], ["ai", "공유 답변"]]
        outer._persist_current_chat()
        embedded._refresh_chat_history()
        assert embedded.chat_history_list.count() == 1

        monkeypatch.setattr(
            "ui.tabs.ai_chat_panel.QMessageBox.question",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
        )
        outer._clear_chat_history()
        qt_app.processEvents()

        assert embedded.chat_history_list.count() == 0
        assert embedded._messages == []
        assert embedded._active_chat_ids[embedded._active_provider_name] == ""
    finally:
        outer.shutdown()
        embedded.shutdown()
        outer.deleteLater()
        embedded.deleteLater()


def test_continuing_embedded_chat_updates_open_outer_chat(qt_app, tmp_path) -> None:
    settings_path = str(tmp_path / "shared-chat-change.ini")
    outer_settings = QSettings(settings_path, QSettings.Format.IniFormat)
    embedded_settings = QSettings(
        settings_path, QSettings.Format.IniFormat
    )
    outer = AiChatPanel(settings=outer_settings, standalone=True)
    embedded = AiChatPanel(settings=embedded_settings, standalone=False)
    try:
        outer.chatHistoryChanged.connect(embedded.apply_external_history_change)
        embedded.chatHistoryChanged.connect(outer.apply_external_history_change)
        outer._messages = [["user", "최초 질문"], ["ai", "최초 답변"]]
        outer._persist_current_chat()
        chat_id = outer._active_chat_ids[outer._active_provider_name]

        embedded._refresh_chat_history()
        item = embedded.chat_history_list.item(0)
        embedded._history_item_clicked(item)
        assert embedded._active_chat_ids[embedded._active_provider_name] == chat_id

        embedded._messages.extend(
            [["user", "본문에서 추가 질문"], ["ai", "본문에서 추가 답변"]]
        )
        embedded._persist_current_chat()
        qt_app.processEvents()

        assert outer._active_chat_ids[outer._active_provider_name] == chat_id
        assert outer._messages[-2:] == [
            ["user", "본문에서 추가 질문"],
            ["ai", "본문에서 추가 답변"],
        ]
        saved = outer._find_chat(chat_id)
        assert saved is not None
        assert saved["messages"][-2:] == outer._messages[-2:]
    finally:
        outer.shutdown()
        embedded.shutdown()
        outer.deleteLater()
        embedded.deleteLater()


@pytest.mark.parametrize("standalone", [False, True])
def test_model_picker_is_compact_but_keeps_full_menu_labels(
    qt_app, tmp_path, standalone
) -> None:
    settings = QSettings(
        str(tmp_path / f"model-menu-{standalone}.ini"),
        QSettings.Format.IniFormat,
    )
    widget = AiChatPanel(settings=settings, standalone=standalone)
    try:
        full_label = (
            "Gemini 3.5 Flash Lite - 가장 빠른답변"
            "(1분당 15회요청, 분당 25만 토큰, 하루 500회)"
        )
        widget._fill_models((ModelInfo("fast", full_label),))
        widget.resize(520 if not standalone else 900, 650)
        widget.show()
        qt_app.processEvents()

        assert widget.model_combo.isHidden()
        assert widget.model_menu_button.text() == (
            "Gemini 3.5 Flash Lite — 가장 빠른 답변"
        )
        assert widget.model_menu_button.toolTip() == full_label
        assert widget.model_menu_button.height() == 26
        assert widget.send_button.width() == 32
        assert widget.send_button.height() == 32
        assert abs(
            widget.model_menu_button.geometry().center().y()
            - widget.send_button.geometry().center().y()
        ) <= 1
    finally:
        widget.shutdown()
        widget.deleteLater()


@pytest.mark.parametrize("standalone", [False, True])
def test_sent_user_question_remains_visible(qt_app, tmp_path, standalone) -> None:
    settings = QSettings(
        str(tmp_path / f"user-question-{standalone}.ini"),
        QSettings.Format.IniFormat,
    )
    widget = AiChatPanel(settings=settings, standalone=standalone)
    try:
        widget.resize(420 if not standalone else 900, 650)
        widget.show()
        question = "준산업단지 지정 절차를 알려줘"
        widget._append_user(question)
        widget._begin_answer()
        qt_app.processEvents()

        labels = widget.transcript_content.findChildren(
            QLabel, "aiChatUserText"
        )
        assert len(labels) == 1
        assert question in labels[0].text()
        assert labels[0].isVisibleTo(widget.transcript_content)
        assert labels[0].width() > 0
        assert widget._messages[0] == ["user", question]
        assert widget.send_button.minimumWidth() == 32
        assert widget.send_button.maximumWidth() == 32
        assert widget.send_button.minimumHeight() == 32
        assert widget.send_button.maximumHeight() == 32
    finally:
        widget._streams.clear()
        widget.shutdown()
        widget.deleteLater()


def test_embedded_provider_header_does_not_shift_between_ais(
    qt_app, tmp_path
) -> None:
    settings = QSettings(
        str(tmp_path / "provider-header.ini"), QSettings.Format.IniFormat
    )
    widget = AiChatPanel(settings=settings, standalone=False)
    try:
        widget.resize(520, 700)
        widget.show()
        qt_app.processEvents()

        assert widget.provider_combo.width() == _label_width(
            widget.provider_combo,
            tuple(PROVIDER_TAB_LABELS.values()),
            margin=_PROVIDER_COMBO_WIDTH_MARGIN,
        )
        assert widget.provider_combo.width() < 178
        assert widget.provider_header_widget.height() == 29
        longest_api_label = max(
            (
                "Gemini API 설정 필요",
                "Gemini API 키 확인 필요",
                "Gemini API 키 확인됨",
            ),
            key=len,
        )
        assert widget.api_settings_button.width() == _label_width(
            widget.api_settings_button,
            (
                "Gemini API 설정 필요",
                "Gemini API 키 확인 필요",
                "Gemini API 키 확인됨",
            ),
            margin=_API_SETTINGS_BUTTON_WIDTH_MARGIN,
        )
        assert widget.api_settings_button.width() <= (
            widget.api_settings_button.fontMetrics().horizontalAdvance(
                longest_api_label
            )
            + 10
        )
        assert (
            widget.api_settings_button.font().pointSizeF()
            == widget.connection_button.font().pointSizeF()
        )

        page_geometries = []
        header_geometries = []
        for provider_class, access_text in (
            (GeminiProvider, "무료 사용 가능"),
            (ClaudeCodeProvider, "유료 구독 필요"),
            (CodexAppServerProvider, "유료 구독 필요"),
        ):
            index = widget.provider_combo.findData(provider_class)
            assert index >= 0
            widget.provider_combo.setCurrentIndex(index)
            qt_app.processEvents()
            assert widget.embedded_access_hint.text() == access_text
            header_geometries.append(widget.provider_header_widget.geometry())
            page_geometries.append(widget.embedded_chat_pages.geometry())

        assert len(set(header_geometries)) == 1
        assert len(set(page_geometries)) == 1
    finally:
        widget.shutdown()
        widget.deleteLater()


def test_model_menu_uses_compact_text_check_without_native_indicator(
    panel,
) -> None:
    panel._fill_models(
        (
            ModelInfo("one", "첫 번째 모델"),
            ModelInfo("two", "두 번째 모델"),
        )
    )
    panel.model_combo.setCurrentIndex(1)
    captured = panel._build_model_menu().actions()

    assert len(captured) == 2
    assert captured[0].text().startswith(" 첫 번째")
    assert captured[1].text().startswith("✓ 두 번째")
    assert all(not action.isCheckable() for action in captured)


def test_gemini_model_menu_starts_with_unselectable_quota_note(panel) -> None:
    panel.provider_combo.setCurrentIndex(
        panel.provider_combo.findData(GeminiProvider)
    )
    panel._fill_models(
        (
            ModelInfo("one", "첫 번째 모델"),
            ModelInfo("two", "두 번째 모델"),
        )
    )
    panel.model_combo.setCurrentIndex(1)
    captured = panel._build_model_menu().actions()

    assert captured[0].text() == GeminiProvider.FREE_QUOTA_MENU_NOTE
    assert captured[0].isEnabled() is False
    assert captured[1].text().startswith(" 첫 번째")
    assert captured[2].text().startswith("✓ 두 번째")
    captured[0].trigger()
    assert panel.model_combo.currentIndex() == 1


@pytest.mark.parametrize("standalone", [False, True])
def test_ai_answer_wraps_in_narrow_embedded_and_tab_panels(
    qt_app, tmp_path, standalone
) -> None:
    """본문 옆·독립 탭 모두 긴 답변을 현재 폭에 맞춰 줄바꿈한다."""
    settings = QSettings(
        str(tmp_path / f"ai-wrap-{standalone}.ini"),
        QSettings.Format.IniFormat,
    )
    widget = AiChatPanel(settings=settings, standalone=standalone)
    try:
        column, label, _status, tool_log = widget._make_ai_bubble(
            "국토의 계획 및 이용에 관한 법률에 따른 " * 12
        )
        assert column.minimumWidth() == 0
        assert label.minimumWidth() == 0
        assert tool_log.minimumWidth() == 0
        assert label.wordWrap() is True
        assert label.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored
        assert tool_log.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored
    finally:
        widget.shutdown()
        widget.deleteLater()


@pytest.mark.parametrize(
    ("provider_class", "cli_label"),
    [
        (ClaudeCodeProvider, "Claude Code CLI"),
        (CodexAppServerProvider, "Codex CLI"),
    ],
)
def test_cli_provider_shows_matching_ai_connection_button(
    panel, provider_class, cli_label
) -> None:
    index = next(
        i
        for i in range(panel.provider_combo.count())
        if panel.provider_combo.itemData(i) is provider_class
    )

    panel.provider_combo.setCurrentIndex(index)

    assert not panel.connection_row_widget.isHidden()
    assert panel.connection_button.text() == "확인"
    assert cli_label in panel.connection_status_label.text()
    assert cli_label in panel.connection_button.toolTip()
    assert "npm" in panel.connection_button.toolTip()
    assert panel.cli_install_status_label.text() == "CLI : 확인 전"
    assert panel.cli_install_status_label.property("connectionState") == "checking"


def test_cli_status_combines_installation_and_login(panel) -> None:
    panel._ai_connection_ready(
        "Claude Code CLI", "1.0", True, True, "로그인 완료"
    )
    assert panel.cli_install_status_label.text() == "CLI : 연결됨"
    assert panel.cli_install_status_label.property("connectionState") == "connected"

    panel._ai_connection_ready(
        "Claude Code CLI", "1.0", True, False, "로그인 필요"
    )
    assert panel.cli_install_status_label.text() == "CLI : 미연결"
    assert (
        panel.cli_install_status_label.property("connectionState")
        == "disconnected"
    )


def test_gemini_shows_api_key_input(panel) -> None:
    """Gemini는 AI Studio 키로 직접 부른다 — CLI 설치 줄이 아니라 키 칸이다.

    개인용 Gemini Code Assist가 2026-06-18에 요청 처리를 멈춰 Gemini CLI의
    Google 로그인 경로를 쓸 수 없게 됐다. 그래서 API 키 방식으로 돌아왔다.
    """
    index = next(
        i
        for i in range(panel.provider_combo.count())
        if panel.provider_combo.itemData(i) is GeminiProvider
    )

    panel.provider_combo.setCurrentIndex(index)

    assert panel.key_row_widget.isHidden()
    assert not panel.api_settings_button.isHidden()
    assert panel.connection_row_widget.isHidden()
    panel.key_input.setText("saved-key")
    assert panel.api_settings_button.text() == "Gemini API 키 확인 필요"
    assert panel.api_settings_button.property("apiConfigured") is False


def test_send_arrow_turns_into_stop_while_answering(panel) -> None:
    panel._set_busy(False)
    assert panel.send_button.text() == "↑"
    assert panel.send_button.toolTip() == "보내기"

    panel._set_busy(True)
    assert panel.send_button.text() == "■"
    assert panel.send_button.toolTip() == "답변 중지"
    assert panel.send_button.isEnabled()
    assert panel.provider_tabs.isEnabled()


def test_answer_keeps_running_when_the_provider_tab_changes(panel) -> None:
    """탭을 옮겨도 돌던 답은 끊기지 않고 그 탭에 계속 쌓인다."""

    def tab(label: str) -> int:
        return next(
            index
            for index in range(panel.provider_tabs.count())
            if panel.provider_tabs.tabText(index) == label
        )

    home, away = tab("Gemini"), tab("Claude")
    panel._provider_tab_changed(home)
    running = panel._active_provider_name
    stopped: list[bool] = []
    panel._stop = lambda: stopped.append(True)

    panel._append_user("질문")
    panel._begin_answer()
    panel._append_chunk("앞부분")

    panel._provider_tab_changed(away)
    assert stopped == []
    # 화면에 보이는 탭은 안 돌지만 아까 그 답은 계속 돈다.
    assert not panel._streaming
    assert running in panel._streams
    # 화면에는 다른 제공자의 대화가 떠 있지만 글자는 계속 쌓인다.
    panel._append_chunk_for(running, " 뒷부분")

    panel._provider_tab_changed(home)
    assert panel._streaming
    assert panel._messages[-1] == ["ai", "앞부분 뒷부분"]
    assert panel._current_ai_label is not None
    assert panel._current_status is not None


def test_tool_log_and_citations_return_after_leaving_the_tab(panel) -> None:
    """답하는 중에 다른 AI로 갔다가 와도 도구·인용 줄이 다시 붙는다."""
    home, away = _tab_index(panel, "Gemini"), _tab_index(panel, "Claude")
    panel._provider_tab_changed(home)
    running = panel._active_provider_name
    panel._append_user("질문")
    panel._begin_answer()
    panel._show_progress("법령을 검색하는 중: 농지법", "tool")
    panel._append_chunk("[농지법 제1조](law:000479:000100)에 따릅니다.")

    panel._provider_tab_changed(away)
    panel._answer_finished(running)
    panel._provider_tab_changed(home)

    logs = [
        label
        for label in panel.findChildren(QLabel)
        if label.objectName() == "aiChatToolLog" and label.isVisibleTo(panel)
    ]
    assert logs
    assert "법령을 검색하는 중: 「농지법」" in logs[-1].text()
    cites = [
        label
        for label in panel.findChildren(QLabel)
        if label.objectName() == "aiChatCitationCheck"
    ]
    assert cites
    assert "농지법" in cites[-1].text()


def test_finished_tool_log_survives_switching_tabs(panel) -> None:
    """끝난 답을 다른 탭에 다녀와도 도구 기록이 남아야 한다."""
    home, away = _tab_index(panel, "Claude"), _tab_index(panel, "Codex")
    panel._provider_tab_changed(home)
    panel._append_user("질문")
    panel._begin_answer()
    panel._show_progress("조문을 읽는 중: 제1조", "tool")
    panel._append_chunk("답")
    panel._answer_finished()

    panel._provider_tab_changed(away)
    panel._provider_tab_changed(home)
    logs = [
        label
        for label in panel.findChildren(QLabel)
        if label.objectName() == "aiChatToolLog" and label.isVisibleTo(panel)
    ]
    assert logs
    assert "조문을 읽는 중: 제1조" in logs[-1].text()


def _tab_index(panel, label: str) -> int:
    return next(
        index
        for index in range(panel.provider_tabs.count())
        if panel.provider_tabs.tabText(index) == label
    )


def test_status_bar_belongs_to_the_ai_on_screen(panel) -> None:
    """하단 상태바는 AI마다 따로다. 옆 탭 문구가 남아 있으면 안 된다."""
    panel._provider_tab_changed(_tab_index(panel, "Gemini"))
    panel._set_status("Gemini에서 난 오류")
    assert panel.status_provider_label.text() == "Gemini"
    assert "Gemini에서 난 오류" == panel.status_label.text()

    panel._provider_tab_changed(_tab_index(panel, "Codex"))
    assert panel.status_provider_label.text() == "Codex"
    assert "Gemini에서 난 오류" != panel.status_label.text()

    panel._provider_tab_changed(_tab_index(panel, "Gemini"))
    assert "Gemini에서 난 오류" == panel.status_label.text()


def test_resting_line_shows_whether_the_ai_can_be_used(panel) -> None:
    """할 말이 없으면 그 AI를 지금 쓸 수 있는지를 보인다."""
    panel._provider_tab_changed(_tab_index(panel, "Claude"))
    assert panel.status_label.text() == "CLI 확인 전"

    panel._ai_connection_ready(CLAUDE_CLI.label, "1.0", False, True, "")
    panel._set_status("")
    assert panel.status_label.text() == "CLI 연결됨"


def test_other_tabs_trouble_does_not_land_on_this_status_bar(panel) -> None:
    """다른 탭에서 터진 실패는 그 탭에 적고, 여기서는 탭 색으로만 알린다."""
    gemini_tab = _tab_index(panel, "Gemini")
    panel._provider_tab_changed(gemini_tab)
    gemini = panel._active_provider_name
    panel._append_user("질문")
    panel._begin_answer()

    panel._provider_tab_changed(_tab_index(panel, "Codex"))
    panel._failure_for(gemini, "요청이 실패했습니다")

    assert "실패" not in panel.status_label.text()
    assert panel.provider_tabs.tabToolTip(gemini_tab) == "요청이 실패했습니다"
    assert panel.provider_tabs.tabTextColor(gemini_tab).isValid()

    # 그 탭으로 가면 문구가 보이고, 알림 표시는 지워진다.
    panel._provider_tab_changed(gemini_tab)
    assert panel.status_label.text() == "요청이 실패했습니다"
    assert not panel.provider_tabs.tabTextColor(gemini_tab).isValid()


def test_answer_signals_come_back_to_the_main_thread(panel, qt_app) -> None:
    """답 신호를 작업 스레드에서 받으면 프로그램이 통째로 죽는다.

    말풍선을 만들고 타이머를 멈추는 일은 화면 스레드의 몫이다. 예전에는
    제공자 이름을 functools.partial로 묶어 연결했는데, partial은 받는
    QObject가 없어 PySide6가 직접 연결로 이었다. 그래서 답이 끝나는
    순간 "Cannot create children for a parent that is in a different
    thread"와 "Thread tried to wait on itself"가 뜨며 꺼졌다.
    """
    from PySide6.QtCore import QThread

    from llm.base import ChatSession, Progress
    from ui.tabs.ai_chat_panel import ChatWorker

    class OneWordSession(ChatSession):
        def send(self, message):
            yield Progress("법령을 검색하는 중: 농지법", "tool")
            yield "답"

    seen: dict[str, object] = {}
    original = panel._persist_current_chat

    def spy(*args, **kwargs):
        seen["thread"] = QThread.currentThread()
        return original(*args, **kwargs)

    panel._persist_current_chat = spy

    panel._append_user("질문")
    panel._begin_answer()
    name = panel._active_provider_name
    worker = ChatWorker(OneWordSession(), "질문", name)
    thread = QThread()
    panel._streams[name]["worker"] = worker
    panel._streams[name]["thread"] = thread
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    panel._wire_answer_worker(worker)
    thread.start()

    deadline = time.time() + 10
    while "thread" not in seen and time.time() < deadline:
        qt_app.processEvents()

    assert seen.get("thread") is qt_app.thread()
    assert panel._messages[-1][0] == "ai"
    assert panel._messages[-1][1] == "답"
    assert panel._tools_on(panel._messages[-1]) == ["법령을 검색하는 중: 「농지법」"]
    assert name not in panel._streams


def _saved_chats(panel):
    return panel._provider_history()


def test_chat_can_be_renamed_and_pinned(panel) -> None:
    """채팅 목록의 ⋯ 메뉴로 이름을 바꾸고 위에 고정한다."""
    panel._append_user("첫 질문")
    panel._persist_current_chat()
    first = _saved_chats(panel)[0]["id"]

    panel._start_empty_conversation()
    panel._append_user("둘째 질문")
    panel._persist_current_chat()
    second = _saved_chats(panel)[0]["id"]
    assert [item["id"] for item in _saved_chats(panel)] == [second, first]

    panel._toggle_chat_pin(first)
    # 저장 순서는 그대로지만 화면에는 고정한 것이 위로 온다.
    panel._refresh_chat_history()
    shown = [
        panel.chat_history_list.item(index).data(Qt.ItemDataRole.UserRole)
        for index in range(panel.chat_history_list.count())
    ]
    assert shown == [first, second]

    record = panel._find_chat(first)
    record["custom_title"] = "농지법 검토"
    assert panel._chat_title(record) == "농지법 검토"


def test_opening_a_saved_chat_does_not_move_it_to_the_top(panel) -> None:
    """훑어보기만 해도 목록이 뒤집히면 어디까지 봤는지 알 수 없다."""
    panel._append_user("첫 질문")
    panel._persist_current_chat()
    first = _saved_chats(panel)[0]["id"]

    panel._start_empty_conversation()
    panel._append_user("둘째 질문")
    panel._persist_current_chat()
    order = [item["id"] for item in _saved_chats(panel)]

    # 앞 채팅을 열어 보기만 한다.
    panel._active_chat_ids[panel._active_provider_name] = first
    panel._messages = [["user", "첫 질문"]]
    panel._persist_current_chat()
    assert [item["id"] for item in _saved_chats(panel)] == order

    # 한 마디 더 주고받으면 그때 맨 위로 올라온다.
    panel._messages.append(["ai", "답"])
    panel._persist_current_chat()
    assert _saved_chats(panel)[0]["id"] == first
def _stream_more(panel, qt_app, text: str) -> None:
    """답이 더 흘러 들어와 타자기 효과로 그려지는 상황을 흉내 낸다."""
    panel._messages[-1][1] = text
    for _ in range(300):
        panel._reveal_tick()
        qt_app.processEvents()


def _long_lines(prefix: str, count: int) -> str:
    return "".join(f"{prefix} {i}번째 줄. 스크롤이 생기게 길게 늘인다.\n" for i in range(count))


def test_scrolling_up_while_answering_is_not_yanked_back(panel, qt_app) -> None:
    """답하는 도중에도 위로 올려 읽을 수 있어야 한다.

    글자가 나올 때마다 무조건 바닥으로 내리면, 앞에 지나간 표를 다시
    보려고 휠을 굴려도 곧바로 끌려 내려와 스크롤이 잠긴 것처럼 된다.
    """
    panel.resize(700, 400)
    panel.show()
    qt_app.processEvents()
    panel._append_user("긴 답 부탁")
    panel._begin_answer()
    bar = panel.transcript_scroll.verticalScrollBar()

    text = _long_lines("처음", 60)
    _stream_more(panel, qt_app, text)
    # 가만히 두면 바닥을 따라간다.
    assert bar.maximum() > 0
    assert bar.maximum() - bar.value() <= panel._BOTTOM_STICKY_PX

    # 위로 올리면 따라가기를 놓는다.
    bar.setValue(max(0, bar.maximum() - 200))
    qt_app.processEvents()
    held = bar.value()
    assert panel._follow_bottom is False

    # 그동안 답이 더 와도 보고 있던 자리에 머문다.
    text += _long_lines("이어서", 40)
    _stream_more(panel, qt_app, text)
    assert bar.value() == held

    # 바닥까지 다시 내려오면 그때부터 또 따라간다.
    bar.setValue(bar.maximum())
    qt_app.processEvents()
    assert panel._follow_bottom is True
    text += _long_lines("복귀 뒤", 40)
    _stream_more(panel, qt_app, text)
    assert bar.maximum() - bar.value() <= panel._BOTTOM_STICKY_PX


def test_sending_a_question_always_jumps_to_the_bottom(panel, qt_app) -> None:
    """올려 둔 채로 질문을 보내면, 방금 쓴 말은 보여야 한다."""
    panel.resize(700, 400)
    panel.show()
    qt_app.processEvents()
    panel._append_user("첫 질문")
    panel._begin_answer()
    _stream_more(panel, qt_app, _long_lines("처음", 60))
    bar = panel.transcript_scroll.verticalScrollBar()
    bar.setValue(0)
    qt_app.processEvents()
    assert panel._follow_bottom is False

    panel._append_user("둘째 질문")
    for _ in range(10):
        qt_app.processEvents()
    assert panel._follow_bottom is True
    assert bar.maximum() - bar.value() <= panel._BOTTOM_STICKY_PX


def test_question_banner_replaces_question_only_after_it_scrolls_out(
    panel, qt_app
) -> None:
    """질문 말풍선이 보일 때는 숨고, 위로 사라진 뒤에만 띠지가 뜬다."""
    panel.resize(700, 400)
    panel.show()
    qt_app.processEvents()
    question = "업종계획만 하고 획지별 분류는 안 하는지 알려줘"
    panel._append_user(question)
    panel._begin_answer()
    qt_app.processEvents()

    # 방금 쓴 질문 말풍선이 화면에 있으므로 같은 질문을 또 띄우지 않는다.
    assert not panel.question_banner.isVisible()
    assert panel.question_banner.toolTip() == question

    _stream_more(panel, qt_app, _long_lines("답", 60))
    # 답을 따라 내려가 질문 말풍선이 위로 사라지면 띠지가 대신 뜬다.
    assert panel.question_banner.isVisible()

    panel.transcript_scroll.verticalScrollBar().setValue(0)
    qt_app.processEvents()
    assert not panel.question_banner.isVisible()

    panel.transcript_scroll.verticalScrollBar().setValue(
        panel.transcript_scroll.verticalScrollBar().maximum()
    )
    qt_app.processEvents()
    assert panel.question_banner.isVisible()


def test_question_banner_goes_away_when_the_answer_finishes(
    panel, qt_app
) -> None:
    """답변 중에만 보조 띠지를 쓰고, 답이 끝나면 바로 원래 화면으로 돌아간다."""
    panel.resize(700, 400)
    panel.show()
    qt_app.processEvents()
    panel._append_user("첫 질문")
    panel._begin_answer()
    _stream_more(panel, qt_app, _long_lines("답", 60))
    bar = panel.transcript_scroll.verticalScrollBar()
    assert bar.maximum() > 0

    panel._release_question_banner()
    qt_app.processEvents()
    assert not panel.question_banner.isVisible()


def test_tool_log_alone_still_follows_the_bottom(panel, qt_app) -> None:
    """도구를 여러 번 부르는 질문은 답보다 기록이 먼저 몇 분씩 쌓인다.

    답 글자에만 자동 내림을 걸어 두면 그동안 화면이 따라가지 않아,
    지금 무엇을 하는 중인지가 아래로 밀려 안 보였다.
    """
    panel.resize(420, 500)
    panel.show()
    qt_app.processEvents()
    panel._append_user("준산업단지에 대해 알려줘")
    panel._begin_answer()
    for index in range(40):
        panel._progress_for(
            panel._active_provider_name,
            f"법제처에서 조문 읽는 중: 「산업입지 및 개발에 관한 법률」 제{index}조",
            "tool",
        )
        qt_app.processEvents()
    panel._settle_follow_scroll()

    bar = panel.transcript_scroll.verticalScrollBar()
    assert bar.maximum() > 0
    assert bar.maximum() - bar.value() <= panel._BOTTOM_STICKY_PX
def test_tool_log_marks_the_answer_as_finished(panel, qt_app) -> None:
    """도구를 여러 번 부른 답은 기록이 멈춘 것인지 다 된 것인지 알기 어렵다."""
    panel.resize(700, 400)
    panel.show()
    qt_app.processEvents()
    panel._append_user("질문")
    panel._begin_answer()
    for index in range(3):
        panel._progress_for(
            panel._active_provider_name, f"법제처에서 조문 읽는 중: 제{index}조", "tool"
        )
        qt_app.processEvents()
    log = panel._current_tool_log
    assert log is not None
    # 도는 동안에는 완료 표시가 없다.
    assert "답변 완료" not in log.text()

    panel._messages[-1][1] = "답"
    panel._streaming = False
    panel._answer_finished(panel._active_provider_name)
    for _ in range(10):
        qt_app.processEvents()
    assert "답변 완료" in log.text()
