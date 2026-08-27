from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTreeWidgetItem

from ui.main_window import LawSearchWindow
from ui.tabs.viewed_laws import ViewedLawsTab


class _Cache:
    def __init__(self, record: dict[str, object]) -> None:
        self.record = record

    def load(self, _path: str) -> dict[str, object]:
        return self.record


def _request(record: dict[str, object]) -> tuple[str, str] | None:
    app = QApplication.instance() or QApplication([])
    tab = SimpleNamespace(law_cache=_Cache(record))
    item = QTreeWidgetItem(("표시 이름",))
    item.setData(0, Qt.ItemDataRole.UserRole, "saved.json")
    result = ViewedLawsTab._favorite_search_request(tab, item)
    assert app is not None
    return result


def test_favorite_law_routes_to_law_search() -> None:
    assert _request(
        {
            "kind": "detail_snapshot",
            "row": {"target": "law", "name": "국토의 계획 및 이용에 관한 법률"},
        }
    ) == ("law", "국토의 계획 및 이용에 관한 법률")


def test_favorite_admin_rule_routes_to_admin_rule_search() -> None:
    assert _request(
        {
            "kind": "detail_snapshot",
            "row": {"target": "admrul", "title": "지구단위계획수립지침"},
        }
    ) == ("admrul", "지구단위계획수립지침")


def test_main_window_switches_to_resource_search() -> None:
    calls: list[tuple[str, str]] = []
    window = SimpleNamespace(
        navigation=SimpleNamespace(setCurrentRow=lambda row: calls.append(("row", str(row)))),
        resource_tab=SimpleNamespace(
            search_resource_name=lambda target, name: calls.append((target, name))
        ),
    )
    LawSearchWindow._search_favorite_in_resource_list(
        window, "admrul", "지구단위계획수립지침"
    )
    assert calls == [("row", "1"), ("admrul", "지구단위계획수립지침")]
