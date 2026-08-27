"""판례 생사 확인. 변경 문구 스캔과 사건번호 추출."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import molit_cgm_expc_api as api
from llm.cite_check import run_cite_check
from utils.case_numbers import extract_case_numbers, field_has_exact_case
from utils.precedent_scan import extract_holding, field_text, scan_treatment


def test_extract_case_numbers_keeps_real_codes_only() -> None:
    text = "대법원 2013다61381 및 96누4671. 1000억원2024, 제12조의2는 제외."
    assert extract_case_numbers(text) == ["2013다61381", "96누4671"]


def test_field_has_exact_case_rejects_prefix() -> None:
    assert field_has_exact_case("2013다61381", "2013다61381")
    assert not field_has_exact_case("2013다61381", "2013다6138")
    assert field_has_exact_case("2017다360, 2017다377", "2017다377")


def test_field_text_does_not_stringify_objects() -> None:
    assert field_text({"#text": "판시 요지"}) == "판시 요지"
    assert "[object Object]" not in field_text({"a": {"#text": "본문"}})
    assert "본문" in field_text({"a": {"#text": "본문"}})


def test_scan_treatment_finds_change_near_case_and_alias() -> None:
    body = (
        "대법원 2007다27670 전원합의체 판결(이하 '2008년 전원합의체 판결'이라 한다)의 "
        "견해를 변경하기로 한다. 2008년 전원합의체 판결은 더 이상 유지될 수 없다."
    )
    signals, context = scan_treatment(body, "2007다27670")
    assert "판례 변경 선언" in signals
    assert "선례 유지 불가 판시" in signals
    assert "변경하기로" in context


def test_extract_holding_prefers_issue_over_summary() -> None:
    holding = extract_holding(
        {"판시사항": "강제동원 손해배상", "판결요지": "긴 요지"}
    )
    assert holding == ("판시사항", "강제동원 손해배상")


def _prec_list(*cases: dict) -> ET.Element:
    root = ET.Element("PrecSearch")
    ET.SubElement(root, "totalCnt").text = str(len(cases))
    for case in cases:
        node = ET.SubElement(root, "prec")
        for tag, value in case.items():
            ET.SubElement(node, tag).text = value
    return root


def test_cite_check_reports_change_signal(monkeypatch) -> None:
    target = {
        "판례일련번호": "100",
        "사건명": "손해배상(기)",
        "사건번호": "2013다61381",
        "선고일자": "2018.10.30",
        "법원명": "대법원",
        "판결유형": "판결",
    }
    later = {
        "판례일련번호": "200",
        "사건명": "전원합의체 후속",
        "사건번호": "2018다248626",
        "선고일자": "2021.04.29",
        "법원명": "대법원",
        "판결유형": "전원합의체",
    }

    def fake_search_list(oc, query=None, search=1, display=20, page=1, **kwargs):
        if kwargs.get("nb") == "2013다61381":
            return _prec_list(target)
        assert search == 2
        return _prec_list(target, later)

    def fake_get_detail(oc, item_id, target="expc"):
        root = ET.Element("PrecService")
        if item_id == "100":
            ET.SubElement(root, "판시사항").text = "강제동원 손해배상 책임"
            ET.SubElement(root, "참조판례").text = "2007다27670"
            ET.SubElement(root, "판례내용").text = "대상 판결 본문"
            return root
        ET.SubElement(root, "판례내용").text = (
            "2013다61381 판결의 견해를 변경하기로 한다."
        )
        return root

    monkeypatch.setattr(api, "search_list", fake_search_list)
    monkeypatch.setattr(api, "get_detail", fake_get_detail)
    text = run_cite_check("dummy", "대법원 2013다61381")
    assert "변경·폐기 신호 감지" in text
    assert "2018다248626" in text
    assert "강제동원 손해배상 책임" in text
    assert "단정" in text or "한계" in text
