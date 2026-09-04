"""화면을 오갈 때 검색칸이 위아래로 흔들리지 않는지 보는 회귀 테스트.

법령검색에는 분류 바가, 중앙부처 질의회신ㆍ법령해석례ㆍ판례에는 화면 이름
띠가 검색칸 위에 온다. 두 자리의 높이가 어긋나면 화면을 바꿀 때마다
검색칸이 2px씩 움직여 눈에 거슬린다.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QFrame

from ui.main_window import LawSearchWindow


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def test_every_search_screen_starts_its_search_row_at_one_height(
    qt_app,
) -> None:
    window = LawSearchWindow()
    try:
        window.resize(1300, 850)
        window.show()
        qt_app.processEvents()

        starts: dict[str, int] = {}
        stack = window.tabs
        for index in range(stack.count()):
            page = stack.widget(index)
            # 검색줄을 가진 화면만 견준다. 즐겨찾기ㆍ저장내역은 검색칸이
            # 아니라 목록 카드로 시작하므로 대상이 아니다.
            if type(page).__name__ not in (
                "ResourceSearchTab",
                "LawSearchTab",
            ):
                continue
            stack.setCurrentIndex(index)
            qt_app.processEvents()
            cards = [
                card
                for card in page.findChildren(QFrame)
                if card.objectName() == "card" and card.isVisible()
            ]
            if not cards:
                continue
            top = min(
                card.mapTo(page, card.rect().topLeft()).y() for card in cards
            )
            name = f"{type(page).__name__}:{getattr(page, 'service', '-')}"
            starts[name] = top

        assert starts, "검색칸을 가진 화면을 찾지 못했다"
        assert len(set(starts.values())) == 1, (
            f"화면마다 검색칸 시작 높이가 다르다: {starts}"
        )
    finally:
        window.close()
