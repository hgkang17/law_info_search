"""최근 검색어를 설정 파일에 남긴다."""

from __future__ import annotations

from PySide6.QtCore import QObject, QSettings, Signal


class RecentSearchManager(QObject):
    """검색 탭들이 공유하는 최근 검색어를 저장하고 변경 사항을 알림."""

    changed = Signal(object)
    MAX_ITEMS = 10

    def __init__(self, settings: QSettings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        saved = settings.value("recent_searches", [])
        if isinstance(saved, str):
            saved = [saved]
        self.items = [
            str(value).strip()
            for value in list(saved or [])
            if str(value).strip()
        ][: self.MAX_ITEMS]

    def add(self, query: str) -> None:
        query = " ".join(query.split())
        if not query:
            return
        self.items = [
            value for value in self.items if value.casefold() != query.casefold()
        ]
        self.items.insert(0, query)
        self.items = self.items[: self.MAX_ITEMS]
        self.settings.setValue("recent_searches", self.items)
        self.settings.sync()
        self.changed.emit(list(self.items))

    def clear(self) -> None:
        self.items = []
        self.settings.remove("recent_searches")
        self.settings.sync()
        self.changed.emit([])
