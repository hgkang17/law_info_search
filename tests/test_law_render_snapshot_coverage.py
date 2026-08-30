"""저장 화면이 법령 전문인지 확인하는 회귀 테스트.

즐겨찾기에서 국토계획법을 열면 제1조만 뜨는 일이 있었다. 3단비교 링크
보강이 조문 하나짜리 화면을 법령 전문 저장 파일에 덮어썼고, 되살리는 쪽은
첫 줄이 법령 이름과 맞는지만 봤다. 첫 줄은 여전히 법령 이름이라 검사를
통과했고, 한 번 망가지면 스스로 낫지 않았다.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from ui.tabs.resource_search import ResourceSearchTab


def _payload(article_count: int) -> dict[str, object]:
    return {
        "법령": {
            "조문": {
                "조문단위": [
                    {"조문내용": f"제{number}조(제목) 본문입니다."}
                    for number in range(1, article_count + 1)
                ]
            }
        }
    }


def _plain(article_count: int, name: str = "국토의 계획 및 이용에 관한 법률") -> str:
    lines = [name, ""]
    lines += [f"제{number}조(제목) 본문입니다." for number in range(1, article_count + 1)]
    return "\n".join(lines)


def test_single_article_snapshot_is_rejected() -> None:
    """실제로 겪은 모양 — 원문 202조인데 저장 화면은 제1조 하나뿐."""
    assert (
        ResourceSearchTab._snapshot_covers_payload(_plain(1), _payload(202))
        is False
    )


def test_full_snapshot_is_accepted() -> None:
    assert (
        ResourceSearchTab._snapshot_covers_payload(_plain(202), _payload(202))
        is True
    )


def test_snapshot_missing_a_few_articles_is_still_accepted() -> None:
    """조문 몇 개가 비어도 버리지 않는다. 멀쩡한 화면을 잘못 버리면
    켤 때마다 원문에서 다시 그려 오히려 느려진다."""
    assert (
        ResourceSearchTab._snapshot_covers_payload(_plain(180), _payload(202))
        is True
    )


def test_short_law_is_not_judged() -> None:
    """조문이 서너 개뿐인 법령은 비교가 의미 없어 통과시킨다."""
    assert (
        ResourceSearchTab._snapshot_covers_payload(_plain(1), _payload(3))
        is True
    )


def test_branch_article_numbers_are_distinguished() -> None:
    """제3조와 제3조의2는 다른 조문이다."""
    labels = ResourceSearchTab._article_labels(
        "제3조(정의) ... 제3조의2(적용례) ..."
    )
    assert labels == {"제3조", "제3조의2"}


def test_empty_payload_is_not_judged() -> None:
    """원문을 못 읽으면 저장 화면을 버릴 근거도 없다."""
    assert ResourceSearchTab._snapshot_covers_payload(_plain(1), None) is True
    assert ResourceSearchTab._snapshot_covers_payload(_plain(1), {}) is True


def test_first_line_check_alone_would_have_passed() -> None:
    """예전 검사만으로는 잘린 화면을 걸러내지 못했음을 남겨 둔다."""
    row = {"name": "국토의 계획 및 이용에 관한 법률"}
    truncated = _plain(1)

    assert ResourceSearchTab._snapshot_matches_row(row, truncated) is True
    assert (
        ResourceSearchTab._snapshot_covers_payload(truncated, _payload(202))
        is False
    )
