"""검색어가 집어 적은 조문을 통합검색 목록에 올리는지 검증."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab
from utils.parsing import split_article_query


def _tab(tmp_path) -> ResourceSearchTab:
    QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "jo.ini"), QSettings.Format.IniFormat)
    return ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )


@pytest.mark.parametrize(
    ("query", "law_name", "jo", "hang", "ho"),
    [
        ("국토계획법 25조", "국토계획법", "002500", "", ""),
        ("국토계획법 제25조", "국토계획법", "002500", "", ""),
        ("건축법 제19조제2항", "건축법", "001900", "000200", ""),
        ("국토계획법 25조의2", "국토계획법", "002502", "", ""),
        ("농지법 제23조제1항9호", "농지법", "002300", "000100", "000900"),
        ("건축법 시행령 제25조", "건축법 시행령", "002500", "", ""),
    ],
)
def test_article_query_is_split_into_law_and_unit(
    query, law_name, jo, hang, ho
) -> None:
    request = split_article_query(query)

    assert request is not None
    assert request["law_name"] == law_name
    assert request["jo"] == jo
    assert request["hang"] == hang
    assert request["ho"] == ho


@pytest.mark.parametrize(
    "query",
    [
        "국토계획법",
        "제25조",
        "25조",
        # 조문 표기 뒤에 말이 이어지면 조문 지정이 아니다.
        "도로법 제2조의 정의",
        "관리계획 입안",
    ],
)
def test_plain_queries_are_not_treated_as_article_requests(query) -> None:
    assert split_article_query(query) is None


def test_article_hit_becomes_the_first_row(tmp_path) -> None:
    """그 조문 줄이 목록 맨 앞에 서고, 여는 길이 조문 단위를 알아본다."""
    tab = _tab(tmp_path)
    hit = {
        "row": {
            "id": "009294",
            "name": "국토의 계획 및 이용에 관한 법률",
            "organization": "국토교통부",
        },
        "unit": split_article_query("국토계획법 25조"),
        "payload": {
            "법령": {
                "조문": {
                    "조문단위": {
                        "조문번호": "25",
                        "조문제목": "도시ㆍ군관리계획의 입안",
                    }
                }
            }
        },
    }

    row = tab._article_hit_row(hit)

    assert row is not None
    assert row["label"] == "조문"
    assert row["article_direct"] is True
    assert row["display_name"] == "제25조 도시ㆍ군관리계획의 입안"
    # AI추천 줄과 같은 모양이라 조문 단위로 열고 즐겨찾기에 걸 수 있다.
    unit = ResourceSearchTab._keyword_article_unit(row)
    assert unit == {"jo": "002500", "hang": "", "ho": "", "mok": ""}

    # 정렬에서 다른 줄보다 앞선다.
    assert tab._article_hit_row({"row": {}, "unit": {}}) is None
    tab.close()
