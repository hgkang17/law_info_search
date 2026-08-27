from __future__ import annotations

from ui.main_window import LawSearchWindow


class _Stack:
    def __init__(self, current) -> None:
        self._current = current

    def currentWidget(self):
        return self._current


class _ReadingPage:
    _reading_mode = True

    def _exit_reading_mode(self) -> None:
        self._reading_mode = False


class _ResourceTab:
    """법령검색 탭 자리. 키워드검색 카테고리인지만 흉내낸다."""

    def __init__(self, is_keyword_category: bool = False) -> None:
        self.is_keyword_category = is_keyword_category


class _Host:
    def __init__(self, page, resource_tab=None, keyword_page=None) -> None:
        self.tabs = _Stack(page)
        self.ai_tabs = _Stack(keyword_page)
        self.resource_tab = resource_tab or _ResourceTab()


def test_mouse_back_exits_current_reading_mode() -> None:
    page = _ReadingPage()
    host = _Host(page)

    assert LawSearchWindow._handle_mouse_back(host)
    assert not page._reading_mode
    assert not LawSearchWindow._handle_mouse_back(host)


def test_mouse_back_reaches_the_keyword_page_inside_law_search() -> None:
    """연관검색ㆍ직접검색은 법령검색 탭 안에 있어 한 겹 더 들어가야 한다."""
    keyword_page = _ReadingPage()
    resource_tab = _ResourceTab(is_keyword_category=True)
    host = _Host(resource_tab, resource_tab, keyword_page)

    assert LawSearchWindow._handle_mouse_back(host)
    assert not keyword_page._reading_mode
