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


class _Host:
    def __init__(self, page) -> None:
        self.tabs = _Stack(page)
        self.ai_tabs = _Stack(None)


def test_mouse_back_exits_current_reading_mode() -> None:
    page = _ReadingPage()
    host = _Host(page)

    assert LawSearchWindow._handle_mouse_back(host)
    assert not page._reading_mode
    assert not LawSearchWindow._handle_mouse_back(host)
