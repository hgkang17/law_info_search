"""부칙 경과조치 발췌와 폐지 후속 안내."""

from __future__ import annotations

from llm.addendum import extract_transition_excerpts
from llm.abolished import (
    detect_abolished_admin_rule,
    extract_successor_names,
    format_abolished_admin_rule,
    format_abolished_law_note,
    parse_abolished_laws,
    parse_admin_rule_history,
)
import molit_cgm_expc_api as api
from llm import tools as llm_tools


def test_extract_transition_prefers_article_and_signal_lines() -> None:
    payload = {
        "법령": {
            "부칙": {
                "부칙단위": [
                    {
                        "부칙공포번호": "19158",
                        "부칙공포일자": "20230103",
                        "부칙내용": (
                            "부칙 <제19158호, 2023.1.3.>\n"
                            "제1조(시행일) 이 법은 공포한 날부터 시행한다.\n"
                            "제2조(적용례) 제44조 개정 규정은 이 법 시행 이후 "
                            "행위에 대하여 적용한다.\n"
                            "제3조 이 법 시행 당시의 사건에 대하여는 종전의 규정에 "
                            "따른다."
                        ),
                    }
                ]
            }
        }
    }
    excerpts = extract_transition_excerpts(payload, "제44조")
    assert excerpts
    header, lines = excerpts[0]
    assert "19158" in header
    assert any("제44조" in line for line in lines)
    assert any("종전의 규정" in line for line in lines)


def test_parse_abolished_laws_keeps_latest_repealed_only() -> None:
    data = {
        "LawSearch": {
            "law": [
                {
                    "법령명한글": "사법시험법",
                    "법령ID": "009198",
                    "법령일련번호": "1",
                    "시행일자": "20060324",
                    "제개정구분명": "일부개정",
                    "법령구분명": "법률",
                },
                {
                    "법령명한글": "사법시험법",
                    "법령ID": "009198",
                    "법령일련번호": "2",
                    "시행일자": "20171231",
                    "제개정구분명": "타법폐지",
                    "법령구분명": "법률",
                },
                {
                    "법령명한글": "민사소송법",
                    "법령ID": "001265",
                    "법령일련번호": "3",
                    "시행일자": "20171231",
                    "제개정구분명": "타법폐지",
                    "법령구분명": "법률",
                },
                {
                    "법령명한글": "변호사시험법",
                    "법령ID": "010225",
                    "법령일련번호": "4",
                    "시행일자": "20250101",
                    "제개정구분명": "일부개정",
                    "법령구분명": "법률",
                },
            ]
        }
    }
    found = parse_abolished_laws(data, "사법시험법")
    assert [item["law_id"] for item in found] == ["009198"]
    assert found[0]["revision"] == "타법폐지"
    note = format_abolished_law_note("사법시험법", found)
    assert "[폐지]" in note
    assert "get_historical_law" in note
    assert "현행 기준으로 인용하지 마세요" in note


def test_extract_successor_names_from_merger_reason() -> None:
    reason = (
        "유사 분야 7개 훈령을 「징수업무 처리에 관한 고시」로 통ㆍ폐합하여 "
        "접근성 제고"
    )
    names = extract_successor_names(reason, ["월별납부제도 운영에 관한 고시"])
    assert names == ["징수업무 처리에 관한 고시"]


def test_detect_abolished_admin_rule_from_history() -> None:
    data = {
        "AdmRulSearch": {
            "admrul": [
                {
                    "행정규칙일련번호": "1",
                    "행정규칙명": "월별납부제도 운영에 관한 고시",
                    "행정규칙ID": "37446",
                    "발령일자": "20240402",
                    "제개정구분명": "일부개정",
                    "현행연혁구분": "연혁",
                    "행정규칙종류": "고시",
                    "소관부처명": "관세청",
                },
                {
                    "행정규칙일련번호": "2",
                    "행정규칙명": "월별납부제도 운영에 관한 고시",
                    "행정규칙ID": "37446",
                    "발령일자": "20241211",
                    "제개정구분명": "폐지",
                    "현행연혁구분": "연혁",
                    "행정규칙종류": "고시",
                    "소관부처명": "관세청",
                },
            ]
        }
    }
    hits = parse_admin_rule_history(data)
    detected = detect_abolished_admin_rule("월별납부제도 운영에 관한 고시", hits)
    assert detected is not None
    kind, group = detected
    assert kind == "abolished"
    note = format_abolished_admin_rule(
        "월별납부제도 운영에 관한 고시",
        group,
        "7개 훈령을 「징수업무 처리에 관한 고시」로 통ㆍ폐합하여 접근성 제고",
    )
    assert "징수업무 처리에 관한 고시" in note
    assert "후속(통합) 규정" in note


def test_search_law_reports_abolished_instead_of_missing(
    monkeypatch,
) -> None:
    def fake_search_resource(oc, target, query, **kwargs):
        if target == "eflaw":
            return {
                "LawSearch": {
                    "law": [
                        {
                            "법령명한글": "사법시험법",
                            "법령ID": "009198",
                            "시행일자": "20171231",
                            "제개정구분명": "타법폐지",
                            "법령구분명": "법률",
                        }
                    ]
                }
            }
        return {"LawSearch": {"law": []}}

    monkeypatch.setattr(api, "search_resource", fake_search_resource)
    result = llm_tools.build_tools("dummy-oc-key")[0]("사법시험법")
    assert "[폐지]" in result
    assert "사법시험법" in result
    assert "[NOT_FOUND]" not in result


def test_search_law_keeps_not_found_when_history_is_unrelated(
    monkeypatch,
) -> None:
    def fake_search_resource(oc, target, query, **kwargs):
        if target == "eflaw":
            return {
                "LawSearch": {
                    "law": [
                        {
                            "법령명한글": "민사소송법",
                            "법령ID": "001265",
                            "시행일자": "20171231",
                            "제개정구분명": "타법폐지",
                            "법령구분명": "법률",
                        }
                    ]
                }
            }
        return {"LawSearch": {"law": []}}

    monkeypatch.setattr(api, "search_resource", fake_search_resource)
    result = llm_tools.build_tools("dummy-oc-key")[0]("사법시험법")
    assert "[NOT_FOUND]" in result
    assert "[폐지]" not in result


def test_search_admin_rule_reports_successor(monkeypatch) -> None:
    def fake_search_resource(oc, target, query, **kwargs):
        if kwargs.get("nw") == "2":
            return {
                "AdmRulSearch": {
                    "admrul": [
                        {
                            "행정규칙일련번호": "100",
                            "행정규칙명": "월별납부제도 운영에 관한 고시",
                            "행정규칙ID": "37446",
                            "발령일자": "20240402",
                            "제개정구분명": "일부개정",
                            "현행연혁구분": "연혁",
                            "행정규칙종류": "고시",
                            "소관부처명": "관세청",
                        },
                        {
                            "행정규칙일련번호": "200",
                            "행정규칙명": "월별납부제도 운영에 관한 고시",
                            "행정규칙ID": "37446",
                            "발령일자": "20241211",
                            "제개정구분명": "폐지",
                            "현행연혁구분": "연혁",
                            "행정규칙종류": "고시",
                            "소관부처명": "관세청",
                        },
                    ]
                }
            }
        return {"AdmRulSearch": {"admrul": []}}

    def fake_detail(oc, target, item_id, **kwargs):
        assert item_id == "200"
        return {
            "제개정이유": (
                "유사 분야를 「징수업무 처리에 관한 고시」로 통ㆍ폐합하여 "
                "접근성 제고"
            )
        }

    monkeypatch.setattr(api, "search_resource", fake_search_resource)
    monkeypatch.setattr(api, "get_resource_detail", fake_detail)
    result = llm_tools.build_tools("dummy-oc-key")[3]("월별납부제도 운영에 관한 고시")
    assert "[폐지]" in result
    assert "징수업무 처리에 관한 고시" in result
