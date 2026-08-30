"""저장 화면이 자기 신원을 달고 다니는지 확인한다.

3단비교 링크 보강은 법령 ID가 필요해서 조항호목 탭일 때 일부러 원본 법령
행으로 바꿔치기한다(`_three_stage_link_row`). 그래서 "링크를 붙일 화면"과
"저장할 파일"이 서로 다른 문서를 가리키게 되는데, 예전에는 그 둘이
어긋나는지 아무도 보지 않아 조문 하나짜리 화면이 법령 전문 파일을 덮었다.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from storage.cache import LawDocumentCache
from ui.tabs.resource_search import ResourceSearchTab


LAW_ROW = {
    "target": "law",
    "id": "009294",
    "name": "국토의 계획 및 이용에 관한 법률",
}
ARTICLE_ROW = {
    "target": "law_article",
    "id": "009294:006900::::",
    "label": "조항호목",
    "name": "국토의 계획 및 이용에 관한 법률 제69조",
    "source_row": dict(LAW_ROW),
}


def _snapshot(row: dict[str, object]) -> dict[str, object]:
    return ResourceSearchTab._law_render_snapshot_from_state(
        {"row": dict(row), "source_html": "<p>본문</p>", "plain_text": "본문"}
    )


def test_identity_uses_the_storage_addressing_rule() -> None:
    """규칙을 두 벌 두면 언젠가 어긋난다. 저장소 것을 그대로 빌린다."""
    assert ResourceSearchTab._document_identity(
        LAW_ROW
    ) == LawDocumentCache._cache_key(LAW_ROW)


def test_article_and_law_have_different_identities() -> None:
    assert ResourceSearchTab._document_identity(
        ARTICLE_ROW
    ) != ResourceSearchTab._document_identity(LAW_ROW)


def test_snapshot_records_the_document_it_came_from() -> None:
    assert _snapshot(ARTICLE_ROW)["rendered_for"] == (
        ResourceSearchTab._document_identity(ARTICLE_ROW)
    )


def test_article_snapshot_cannot_be_written_to_the_law_file() -> None:
    """실제로 났던 사고 그 자체."""
    assert (
        ResourceSearchTab._snapshot_belongs_to(_snapshot(ARTICLE_ROW), LAW_ROW)
        is False
    )


def test_law_snapshot_can_be_written_to_its_own_file() -> None:
    assert (
        ResourceSearchTab._snapshot_belongs_to(_snapshot(LAW_ROW), LAW_ROW)
        is True
    )


def test_article_snapshot_can_be_written_to_its_own_file() -> None:
    assert (
        ResourceSearchTab._snapshot_belongs_to(
            _snapshot(ARTICLE_ROW), ARTICLE_ROW
        )
        is True
    )


def test_snapshot_without_identity_is_not_blocked() -> None:
    """예전 판이 만든 저장 화면까지 버리면 멀쩡한 저장이 사라진다.

    그런 화면은 조문 수를 보는 ``_snapshot_covers_payload``가 받친다.
    """
    assert (
        ResourceSearchTab._snapshot_belongs_to(
            {"rendered_html": "<p>본문</p>"}, LAW_ROW
        )
        is True
    )


def test_state_without_a_row_reports_no_identity() -> None:
    assert ResourceSearchTab._document_identity(None) == ""
    assert ResourceSearchTab._document_identity({}) == ""
    assert _snapshot({})["rendered_for"] == ""
