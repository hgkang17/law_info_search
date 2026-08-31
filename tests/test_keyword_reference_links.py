"""키워드검색 탭이 법령검색 탭과 같은 조문 링크·3단비교를 쓰는지 검증."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QUrl, QUrlQuery
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.ai_search import AiLawSearchTab
from utils.formatting import law_reference_html_text


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _tab(tmp_path, service: str = "ai_search") -> AiLawSearchTab:
    _application()
    settings = QSettings(
        str(tmp_path / "keyword.ini"), QSettings.Format.IniFormat
    )
    return AiLawSearchTab(
        service,
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )


class _ReferenceTabSpy:
    """법령검색 탭 대역. 위임된 호출만 기록한다."""

    def __init__(self) -> None:
        self.opened_links: list[QUrl] = []
        self.three_stage_calls: list[dict[str, str]] = []

    def open_reference_link(self, url: QUrl) -> None:
        self.opened_links.append(QUrl(url))

    def open_three_stage_for_article(self, **kwargs: str) -> None:
        self.three_stage_calls.append(dict(kwargs))


def test_presidential_decree_reference_links_to_enforcement_decree() -> None:
    """`대통령령 제5조`는 현재 법령이 아니라 그 법의 시행령을 가리킨다."""
    html = law_reference_html_text(
        "대통령령 제5조제1항에 따라",
        (),
        current_law_name="국토의 계획 및 이용에 관한 법률",
        use_api_links=True,
    )

    assert "lawref://open?" in html
    assert "%EC%8B%9C%ED%96%89%EB%A0%B9" in html  # 시행령
    # 접두어는 링크 밖에 남고 조문만 링크가 된다.
    assert html.startswith("대통령령 <a href=")


def test_ministry_ordinance_reference_links_to_enforcement_rule() -> None:
    html = law_reference_html_text(
        "국토교통부령 제12조로 정한다",
        (),
        current_law_name="국토의 계획 및 이용에 관한 법률",
        use_api_links=True,
    )

    assert "%EC%8B%9C%ED%96%89%EA%B7%9C%EC%B9%99" in html  # 시행규칙


def test_decree_without_article_stays_plain_text() -> None:
    """`대통령령으로 정하는`처럼 조문이 없는 표현은 링크로 만들지 않는다."""
    html = law_reference_html_text(
        "대통령령으로 정하는 바에 따라",
        (),
        current_law_name="국토의 계획 및 이용에 관한 법률",
        use_api_links=True,
    )

    assert "<a href=" not in html


def test_keyword_detail_renders_internal_reference_links(tmp_path) -> None:
    tab = _tab(tmp_path)
    tab.result_rows = [
        {
            "target": "ai_search",
            "kind": "법령",
            "name": "국토의 계획 및 이용에 관한 법률",
            "provision": "제56조",
            "date": "",
            "agency": "",
            "content": "대통령령 제5조제1항 및 제3조제2항에 따른다.",
            "source_id": "001",
            "article_number": "56",
            "article_branch": "",
            "jo_code": "005600",
            "article_loading": "",
            "article_error": "",
            "publication_date": "",
            "publication_number": "",
        }
    ]
    tab.result_table.setRowCount(1)
    tab.result_table.setCurrentCell(0, 0)

    tab._show_selected_result(force_live=True)
    html = tab.detail_view.toHtml()

    assert "lawref://open?" in html


def test_administrative_rule_detail_keeps_self_reference_plain(tmp_path) -> None:
    """행정규칙은 조문 번호 체계가 달라 자기 참조 링크를 만들지 않는다."""
    tab = _tab(tmp_path)
    tab.result_rows = [
        {
            "target": "ai_search",
            "kind": "행정규칙",
            "name": "지구단위계획수립지침",
            "provision": "3-2-1",
            "date": "",
            "agency": "",
            "content": "제3조제2항에 따른다.",
            "source_id": "A001",
            "article_number": "3",
            "article_branch": "",
            "jo_code": "000300",
            "article_loading": "",
            "article_error": "",
            "publication_date": "",
            "publication_number": "",
        }
    ]
    tab.result_table.setRowCount(1)
    tab.result_table.setCurrentCell(0, 0)

    tab._show_selected_result(force_live=True)

    assert "lawref://open?" not in tab.detail_view.toHtml()
    # 행정규칙은 3단비교 대상이 아니다.
    assert tab.three_stage_button.isEnabled() is False


def test_reference_link_click_is_delegated_to_law_tab(tmp_path) -> None:
    tab = _tab(tmp_path)
    spy = _ReferenceTabSpy()
    tab.reference_tab = spy

    tab._detail_link_clicked(QUrl("lawref://open?name=%EB%B2%95&jo=5"))

    assert len(spy.opened_links) == 1
    query = QUrlQuery(spy.opened_links[0])
    assert spy.opened_links[0].scheme() == "lawref"
    assert query.queryItemValue("name") == "법"
    assert query.queryItemValue("jo") == "5"


def test_three_stage_button_delegates_current_article(tmp_path) -> None:
    tab = _tab(tmp_path)
    spy = _ReferenceTabSpy()
    tab.reference_tab = spy
    tab._active_detail_row = {
        "kind": "법령",
        "name": "국토의 계획 및 이용에 관한 법률",
        "provision": "제56조",
        "source_id": "001",
        "jo_code": "005600",
    }

    tab._update_three_stage_button(tab._active_detail_row)
    assert tab.three_stage_button.isEnabled() is True

    tab._open_three_stage_comparison()

    assert spy.three_stage_calls == [
        {
            "law_id": "001",
            "jo": "005600",
            "law_name": "국토의 계획 및 이용에 관한 법률",
            "label": "제56조",
        }
    ]


def test_three_stage_button_off_without_article_code(tmp_path) -> None:
    """별표·서식처럼 조문 번호가 없는 항목에는 3단비교가 없다."""
    tab = _tab(tmp_path)
    tab.reference_tab = _ReferenceTabSpy()

    tab._update_three_stage_button(
        {"kind": "법령", "name": "법", "source_id": "001", "jo_code": ""}
    )

    assert tab.three_stage_button.isEnabled() is False
    assert tab.three_stage_button.isHidden() is True


def test_three_stage_button_is_embedded_above_keyword_article(tmp_path) -> None:
    """3단비교는 도구줄이 아니라 해당 조문 본문 안에만 나타난다."""
    tab = _tab(tmp_path)
    tab.reference_tab = _ReferenceTabSpy()
    row = {
        "kind": "법령",
        "name": "국토의 계획 및 이용에 관한 법률",
        "provision": "제2조(정의)",
        "source_id": "001",
        "jo_code": "000200",
    }
    tab.detail_view.setPlainText(
        "조문내용\n\n제2조(정의) 이 법에서 사용하는 용어의 뜻은 다음과 같다."
    )

    tab._update_three_stage_button(row)

    assert tab.three_stage_button.parent() is tab.detail_view.viewport()
    assert tab._three_stage_position == tab.detail_view.toPlainText().rfind(
        "제2조(정의)"
    )
    cursor = QTextCursor(tab.detail_view.document())
    cursor.setPosition(tab._three_stage_position)
    assert cursor.blockFormat().topMargin() == 32.0
    assert tab.three_stage_button.size().width() == 56
    assert tab.three_stage_button.size().height() == 24
