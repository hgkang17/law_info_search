"""AI 답 인용 검증. 조항호목 API만 쓰고 전문은 부르지 않는다."""

from __future__ import annotations

import pytest

import molit_cgm_expc_api as api
from llm.verify_citations import (
    STATUS_MISSING,
    STATUS_MISMATCH,
    STATUS_UNCHECKED,
    STATUS_VERIFIED,
    collect_citations,
    display_citation_label,
    verification_html,
    verify_answer_citations,
)


def test_display_citation_label_quotes_law_titles() -> None:
    assert display_citation_label("농지법") == "「농지법」"
    assert display_citation_label("농지법 제1조") == "「농지법」 제1조"
    assert (
        display_citation_label("국토의 계획 및 이용에 관한 법률 제27조")
        == "「국토의 계획 및 이용에 관한 법률」 제27조"
    )
    assert (
        display_citation_label("도시·군관리계획수립지침")
        == "「도시·군관리계획수립지침」"
    )
    assert display_citation_label("기초조사 생략") == "기초조사 생략"
    assert display_citation_label("준산업단지") == "준산업단지"
    assert display_citation_label("제27조") == "제27조"
    assert display_citation_label("「농지법」") == "「농지법」"


def _forbid_full_law_fetch(*_args, **_kwargs):
    raise AssertionError("인용 확인에 법령 전문 API를 부르면 안 된다")


def test_collect_linked_and_bare_articles() -> None:
    text = (
        "[농지법 제1조](law:000479:000100)에 따르면 목적이다. "
        "제999조도 있다고 한다."
    )
    checks = collect_citations(text)
    assert checks[0].law_id == "000479"
    assert checks[0].jo == "000100"
    assert "lawref://open?" in checks[0].href
    # 링크 없이 적힌 제999조도 앞에 나온 「농지법」을 물려받아 열 수 있게
    # 한다. 다만 물려받은 법령은 추측이라 실존 판정까지는 하지 않는다.
    bare = next(item for item in checks if item.label.endswith("제999조"))
    assert bare.label == "농지법 제999조"
    assert bare.status == STATUS_UNCHECKED
    assert "lawref://open?" in bare.href


def test_verify_uses_josub_and_marks_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, str]] = []

    def fake_get_law_article(oc, law_id, jo, *, hang="", ho="", mok=""):
        seen.append((law_id, jo))
        if jo == "000100":
            return {
                "법령": {
                    "조문": {
                        "조문단위": [{"조문내용": "제1조(목적) 이 법은..."}]
                    }
                }
            }
        return {"법령": {"조문": {"조문단위": []}}}

    monkeypatch.setattr(api, "get_resource_detail", _forbid_full_law_fetch)
    monkeypatch.setattr(api, "get_law_article", fake_get_law_article)
    text = (
        "[농지법 제1조](law:000479:000100)와 "
        "[농지법 제999조](law:000479:099900)와 제8조"
    )
    checks = verify_answer_citations("dummy-oc-key", text)
    assert seen == [("000479", "000100"), ("000479", "099900")]
    by_label = {item.label: item.status for item in checks}
    assert by_label["농지법 제1조"] == STATUS_VERIFIED
    assert by_label["농지법 제999조"] == STATUS_MISSING
    assert by_label["농지법 제8조"] == STATUS_UNCHECKED
    html = verification_html(checks)
    assert "사용한 법령 조문" in html
    assert "확인됨" not in html
    assert "확인 필요" not in html
    assert "「농지법」 제1조" in html
    assert "제8조" in html
    assert "lawref://open?" in html
    assert "get_resource_detail" not in html


def test_annex_citation_opens_annex_not_the_referring_article() -> None:
    text = "[건축법 시행령 별표 1](law:002118:000305)"
    checks = collect_citations(text)
    assert len(checks) == 1
    assert checks[0].href.startswith("annexref://open?")
    assert "category=licbyl" in checks[0].href
    assert "related=" in checks[0].href
    assert "lawref://open?" not in checks[0].href
    html = verification_html(checks)
    assert "annexref://open?" in html
    assert "lawref://open?" not in html


def test_bare_annex_citation_inherits_preceding_law_name() -> None:
    text = (
        "[건축법 시행령 제3조의5](law:000572:000305) "
        "[별표 1](law:000572:000100)"
    )
    checks = collect_citations(text)
    annex = next(item for item in checks if "별표" in item.label)
    assert annex.href.startswith("annexref://open?")
    assert "related=" in annex.href


def test_verify_marks_content_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get_law_article(oc, law_id, jo, *, hang="", ho="", mok=""):
        return {
            "법령": {
                "조문": {
                    "조문단위": [
                        {"조문내용": "제1조(목적) 이 법은 농지의 이용을 위하여"}
                    ]
                }
            }
        }

    monkeypatch.setattr(api, "get_resource_detail", _forbid_full_law_fetch)
    monkeypatch.setattr(api, "get_law_article", fake_get_law_article)
    text = (
        "[농지법 제1조](law:000479:000100)"
        "「이 법은 해상운송인의 책임 한도와 선하증권 기재사항을 정한다.」"
    )
    checks = verify_answer_citations("dummy-oc-key", text)
    assert checks[0].status == STATUS_MISMATCH
    assert "본문과 다름" in checks[0].detail
