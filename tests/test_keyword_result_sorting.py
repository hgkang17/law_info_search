"""키워드검색 결과 표의 열 정렬 검증."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.ai_search import AiLawSearchTab


def _row(**overrides) -> dict[str, str]:
    row = {
        "target": "ai_search",
        "kind": "법령",
        "name": "가나다법",
        "provision": "제2조",
        "date": "2024.01.01",
        "agency": "국토교통부",
        "content": "내용",
        "source_id": "001",
        "article_number": "2",
        "article_branch": "",
        "jo_code": "000200",
        "article_loading": "",
        "article_error": "",
        "publication_date": "",
        "publication_number": "",
    }
    row.update(overrides)
    return row


ROWS = [
    _row(name="다라마법", provision="제10조", jo_code="001000",
         date="2022.05.05", agency="산림청", kind="법령"),
    _row(name="가나다법", provision="제2조", jo_code="000200",
         date="2024.01.01", agency="국토교통부", kind="법령"),
    _row(name="나다라지침", provision="별표 1", jo_code="",
         date="2023.03.03", agency="해양수산부", kind="행정규칙"),
]


def _tab(tmp_path) -> AiLawSearchTab:
    QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "ai.ini"), QSettings.Format.IniFormat)
    tab = AiLawSearchTab(
        "ai_search",
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    tab.result_rows = [dict(row) for row in ROWS]
    tab._render_result_rows()
    return tab


def _column(tab: AiLawSearchTab, index: int) -> list[str]:
    return [
        tab.result_table.item(row, index).text()
        for row in range(tab.result_table.rowCount())
    ]


def test_sorting_by_name_and_reversing(tmp_path) -> None:
    tab = _tab(tmp_path)

    tab._sort_by_column(3)
    assert _column(tab, 3) == ["가나다법", "나다라지침", "다라마법"]

    # 같은 열을 다시 누르면 뒤집힌다.
    tab._sort_by_column(3)
    assert _column(tab, 3) == ["다라마법", "나다라지침", "가나다법"]


def test_provision_sorts_by_article_number_not_text(tmp_path) -> None:
    """글자로 견주면 제10조가 제2조 앞에 온다. 조문 코드로 견줘야 한다."""
    tab = _tab(tmp_path)

    tab._sort_by_column(2)

    # 조문끼리는 번호 차례, 조문 코드가 없는 별표는 뒤로 간다.
    assert _column(tab, 2) == ["제2조", "제10조", "별표 1"]


def test_every_column_sorts(tmp_path) -> None:
    tab = _tab(tmp_path)

    tab._sort_by_column(1)
    assert _column(tab, 1) == ["법령", "법령", "행정규칙"]

    tab._sort_by_column(4)
    assert _column(tab, 4) == ["2022.05.05", "2023.03.03", "2024.01.01"]

    tab._sort_by_column(5)
    assert _column(tab, 5) == ["국토교통부", "산림청", "해양수산부"]


def test_saved_column_puts_saved_rows_first(tmp_path) -> None:
    tab = _tab(tmp_path)
    tab.law_cache.save_snapshot(
        tab.result_rows[2], html="<p>본문</p>", plain_text="본문"
    )

    tab._sort_by_column(0)

    assert _column(tab, 3)[0] == "나다라지침"


def test_sort_indicator_follows_the_clicked_column(tmp_path) -> None:
    tab = _tab(tmp_path)
    header = tab.result_table.horizontalHeader()

    tab._sort_by_column(4)

    assert header.isSortIndicatorShown()
    assert header.sortIndicatorSection() == 4
    assert header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder

    tab._sort_by_column(4)
    assert header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder


def test_sorting_keeps_rows_and_table_in_step(tmp_path) -> None:
    """표의 차례와 result_rows가 어긋나면 선택한 행의 본문이 뒤바뀐다."""
    tab = _tab(tmp_path)

    tab._sort_by_column(3)

    assert [row["name"] for row in tab.result_rows] == _column(tab, 3)
