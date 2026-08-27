"""인용 문구와 조문 본문 일치 판정."""

from __future__ import annotations

from utils.citation_match import match_citation_content, normalize_legal_text


def test_normalize_replaces_circled_and_quotes() -> None:
    assert "(1)" in normalize_legal_text("① 목적")
    assert "관세법" in normalize_legal_text("「관세법」")


def test_short_claim_contained_in_article_matches() -> None:
    actual = "제1조(목적) 이 법은 농지의 효율적 이용을 위하여 필요한 사항을 규정한다."
    result = match_citation_content("농지의 효율적 이용", actual)
    assert result.matched is True
    assert result.method == "exact"


def test_unrelated_claim_is_mismatch() -> None:
    actual = "제1조(목적) 이 법은 농지의 효율적 이용을 위하여 필요한 사항을 규정한다."
    result = match_citation_content(
        "이 법은 해상운송인의 책임 한도와 선하증권 기재사항을 정한다.",
        actual,
    )
    assert result.matched is False
