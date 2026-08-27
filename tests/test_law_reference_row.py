"""조문 팝업이 링크 ID와 법령명이 다를 때 이름을 따르는지."""

import pytest

from utils.parsing import (
    choose_law_reference_row,
    law_payload_has_body,
    resolve_law_reference_row,
    slice_law_detail_to_article,
)
from workers.search_worker import (
    load_law_reference_payload,
    named_law_reference_row,
)


def _row(item_id: str, name: str) -> dict[str, object]:
    return {
        "target": "law",
        "label": "법령",
        "id": item_id,
        "name": name,
        "related": "",
        "organization": "",
        "date": "",
        "number": "",
        "effective": "",
        "raw": {},
    }


def _search(laws: list[dict]) -> dict:
    return {"LawSearch": {"law": laws}}


def test_mismatched_law_id_follows_the_name() -> None:
    """「건축법」인데 시행령 ID가 붙어 있으면 건축법 ID로 연다."""
    named = _row("000000", "건축법")
    chosen = choose_law_reference_row(
        item_id="000572",
        law_name="건축법",
        named_row=named,
    )
    assert chosen["id"] == "000000"
    assert chosen["name"] == "건축법"


def test_matching_law_id_keeps_the_named_row() -> None:
    named = _row("000572", "건축법 시행령")
    chosen = choose_law_reference_row(
        item_id="000572",
        law_name="건축법 시행령",
        named_row=named,
    )
    assert chosen is named


def test_failed_name_search_keeps_linked_id() -> None:
    """약칭 검색이 실패해도 링크 ID는 유지한다."""
    chosen = choose_law_reference_row(
        item_id="001866",
        law_name="국토계획법",
        named_row=None,
    )
    assert chosen["id"] == "001866"
    assert chosen["name"] == "국토계획법"


def test_name_only_link_uses_search_row() -> None:
    named = _row("000000", "건축법")
    chosen = choose_law_reference_row(
        item_id="",
        law_name="건축법",
        named_row=named,
    )
    assert chosen["id"] == "000000"


def test_name_only_link_without_search_raises() -> None:
    with pytest.raises(ValueError, match="건축법"):
        choose_law_reference_row(
            item_id="",
            law_name="건축법",
            named_row=None,
        )


def test_resolve_ignores_whitespace_in_law_name() -> None:
    row = resolve_law_reference_row(
        _search(
            [
                {
                    "법령명한글": "2018평창동계올림픽대회및장애인동계올림픽대회지원등에관한특별법",
                    "법령ID": "012345",
                    "시행일자": "20180209",
                }
            ]
        ),
        "2018 평창 동계올림픽대회 및 장애인동계올림픽대회 지원 등에 관한 특별법",
    )
    assert row["id"] == "012345"


def test_resolve_prefers_last_living_version_over_repeal() -> None:
    row = resolve_law_reference_row(
        _search(
            [
                {
                    "법령명한글": "제14회 아시아경기대회 지원법",
                    "법령ID": "009999",
                    "법령일련번호": "1",
                    "시행일자": "20020101",
                    "제개정구분명": "제정",
                },
                {
                    "법령명한글": "제14회 아시아경기대회 지원법",
                    "법령ID": "009999",
                    "법령일련번호": "2",
                    "시행일자": "20031231",
                    "제개정구분명": "일부개정",
                },
                {
                    "법령명한글": "제14회 아시아경기대회 지원법",
                    "법령ID": "009999",
                    "법령일련번호": "3",
                    "시행일자": "20040101",
                    "제개정구분명": "폐지",
                },
            ]
        ),
        "제14회 아시아경기대회 지원법",
    )
    assert row["id"] == "009999"
    assert row["mst"] == "2"
    assert row["effective"] == "20031231"
    assert row["revision"] == "일부개정"


def test_named_row_falls_back_to_eflaw_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_search(oc, target, query, *, display=100, **kwargs):
        calls.append(target)
        if target == "law":
            return _search([])
        return _search(
            [
                {
                    "법령명한글": "제14회 아시아경기대회 지원법",
                    "법령ID": "009999",
                    "법령일련번호": "88",
                    "시행일자": "20031231",
                    "제개정구분명": "일부개정",
                }
            ]
        )

    monkeypatch.setattr("workers.search_worker.search_resource", fake_search)
    row = named_law_reference_row("oc", "제14회 아시아경기대회 지원법")
    assert calls == ["law", "eflaw"]
    assert row["id"] == "009999"
    assert row["from_history"] is True
    assert row["mst"] == "88"


def test_named_row_does_not_search_history_when_current_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_search(oc, target, query, *, display=100, **kwargs):
        calls.append(target)
        return _search(
            [{"법령명한글": "건축법", "법령ID": "000000", "시행일자": "20240101"}]
        )

    monkeypatch.setattr("workers.search_worker.search_resource", fake_search)
    row = named_law_reference_row("oc", "건축법")
    assert calls == ["law"]
    assert row["id"] == "000000"
    assert "from_history" not in row


def test_load_uses_historical_text_when_current_article_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    monkeypatch.setattr(
        "workers.search_worker.get_law_article",
        lambda *a, **k: {"법령": {"기본정보": {"법령명_한글": "폐지법"}}},
    )

    def fake_historical(oc, item_id, *, date, jo="", mst=""):
        seen.update({"id": item_id, "date": date, "jo": jo, "mst": mst})
        return {
            "법령": {
                "기본정보": {"법령명_한글": "폐지법"},
                "조문": {
                    "조문단위": [
                        {"조문번호": "1", "조문내용": "제1조 목적"},
                        {"조문번호": "2", "조문내용": "제2조 정의"},
                    ]
                },
            }
        }

    monkeypatch.setattr(
        "workers.search_worker.get_historical_law", fake_historical
    )
    payload = load_law_reference_payload(
        "oc",
        {
            "id": "009999",
            "effective": "20031231",
            "mst": "88",
            "from_history": True,
        },
        jo="000200",
    )
    assert seen == {
        "id": "009999",
        "date": "20031231",
        "jo": "000200",
        "mst": "88",
    }
    units = payload["법령"]["조문"]["조문단위"]
    assert len(units) == 1
    assert units[0]["조문내용"] == "제2조 정의"


def test_load_keeps_current_article_for_renamed_law(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_historical(*a, **k):
        raise AssertionError("제명변경 현행본이 있으면 연혁을 읽지 않는다")

    monkeypatch.setattr(
        "workers.search_worker.get_law_article",
        lambda *a, **k: {
            "법령": {
                "기본정보": {"법령명_한글": "신명칭 특별법"},
                "조문": {
                    "조문단위": [{"조문번호": "2", "조문내용": "제2조 현행"}]
                },
            }
        },
    )
    monkeypatch.setattr(
        "workers.search_worker.get_historical_law", fail_historical
    )
    payload = load_law_reference_payload(
        "oc",
        {
            "id": "012345",
            "effective": "20180209",
            "from_history": True,
        },
        jo="000200",
    )
    assert payload["법령"]["조문"]["조문단위"][0]["조문내용"] == "제2조 현행"


def test_missing_article_on_current_law_does_not_open_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_historical(*a, **k):
        raise AssertionError("현행 법령의 없는 조는 연혁으로 바꾸지 않는다")

    empty = {"법령": {"기본정보": {"법령명_한글": "건축법"}}}
    monkeypatch.setattr(
        "workers.search_worker.get_law_article", lambda *a, **k: empty
    )
    monkeypatch.setattr(
        "workers.search_worker.get_historical_law", fail_historical
    )
    payload = load_law_reference_payload(
        "oc",
        {"id": "000000", "effective": "20240101"},
        jo="009900",
    )
    assert payload == empty


def test_slice_keeps_requested_article_only() -> None:
    sliced = slice_law_detail_to_article(
        {
            "법령": {
                "조문": {
                    "조문단위": [
                        {"조문번호": "1", "조문내용": "제1조"},
                        {"조문번호": "2", "조문내용": "제2조"},
                    ]
                }
            }
        },
        "000200",
    )
    units = sliced["법령"]["조문"]["조문단위"]
    assert [unit["조문내용"] for unit in units] == ["제2조"]


def test_payload_has_body_when_text_is_only_in_paragraphs() -> None:
    assert law_payload_has_body(
        {
            "법령": {
                "조문": {
                    "조문단위": [
                        {"조문번호": "2", "항": [{"항내용": "① 정의"}]}
                    ]
                }
            }
        }
    )
    assert not law_payload_has_body(
        {"법령": {"기본정보": {"법령명_한글": "폐지법"}}}
    )
