"""중앙부처 질의회신 도구."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

import molit_cgm_expc_api as api
from llm import tools as llm_tools
from llm.inquiries import (
    is_inquiry_target,
    resolve_inquiry_agencies,
    split_doc_reference,
)
from molit_cgm_expc_api import AGENCIES


def test_resolve_inquiry_agencies_all_and_aliases() -> None:
    assert resolve_inquiry_agencies("") == tuple(AGENCIES)
    assert resolve_inquiry_agencies("전체") == tuple(AGENCIES)
    molit = resolve_inquiry_agencies("국토교통부")
    assert len(molit) == 1
    assert molit[0].target == "molitCgmExpc"
    assert resolve_inquiry_agencies("국토부")[0].target == "molitCgmExpc"
    assert resolve_inquiry_agencies("molitCgmExpc")[0].name == "국토교통부"


def test_resolve_inquiry_agencies_rejects_ambiguous() -> None:
    with pytest.raises(ValueError, match="여러 곳"):
        resolve_inquiry_agencies("moe")


def test_search_inquiries_filters_agency_and_reads_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = {}

    def fake_search_agencies(oc, agencies, *, query=None, search=1, display=100, page=1):
        seen["agencies"] = [item.target for item in agencies]
        seen["query"] = query
        seen["search"] = search
        root = ET.Element("LawSearch")
        item = ET.SubElement(root, "cgmexpc", id="1")
        ET.SubElement(item, "법령해석일련번호").text = "555"
        ET.SubElement(item, "안건명").text = "농지전용 질의"
        ET.SubElement(item, "안건번호").text = "MOLIT-1"
        ET.SubElement(item, "해석일자").text = "20240101"
        ET.SubElement(item, "질의기관명").text = "○○시"
        return ([(agencies[0], root)], [])

    def fake_get_detail(oc, item_id, target="molitCgmExpc"):
        seen["detail"] = (item_id, target)
        root = ET.Element("LawService")
        ET.SubElement(root, "안건명").text = "농지전용 질의"
        ET.SubElement(root, "질의요지").text = "전용 대상인지"
        ET.SubElement(root, "회답").text = "대상이 아니다"
        return root

    monkeypatch.setattr(api, "search_agencies", fake_search_agencies)
    monkeypatch.setattr(api, "get_detail", fake_get_detail)
    tools = llm_tools.build_tools("dummy-oc-key")
    names = [fn.__name__ for fn in tools]
    assert names[8] == "search_inquiries"
    assert names[9] == "get_inquiry"
    listed = tools[8]("농지전용", agency="국토부")
    assert seen["agencies"] == ["molitCgmExpc"]
    assert seen["search"] == 2
    assert "[중앙부처 질의회신]" in listed
    assert "id=555" in listed
    assert "target=molitCgmExpc" in listed
    assert "국토교통부" in listed
    assert "질의기관=○○시" in listed
    assert "(doc:molitCgmExpc:555)" in listed
    assert "[미리보기 1]" in listed
    assert "[회답]" in listed
    assert "대상이 아니다" in listed
    body = tools[9]("555", target="molitCgmExpc")
    assert seen["detail"] == ("555", "molitCgmExpc")
    assert "[회답]" in body
    assert "대상이 아니다" in body
    assert "(doc:molitCgmExpc:555)" in body


def test_search_inquiries_keeps_other_ministry_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    """앞 기관 결과가 채워져도 소관 부처 안건을 목록·미리보기에 남긴다."""

    def fake_search_agencies(oc, agencies, *, query=None, search=1, display=100, page=1):
        roots = []
        for agency in agencies:
            root = ET.Element("LawSearch")
            if agency.target == "moelCgmExpc":
                item = ET.SubElement(root, "cgmexpc")
                ET.SubElement(item, "법령해석일련번호").text = "1"
                ET.SubElement(item, "안건명").text = "근로시간 기초조사"
            elif agency.target == "molitCgmExpc":
                item = ET.SubElement(root, "cgmexpc")
                ET.SubElement(item, "법령해석일련번호").text = "360866"
                ET.SubElement(item, "안건명").text = (
                    "도시계획시설의 폐지 시 기초조사 등이 불필요한 경우의 의미"
                )
            else:
                continue
            roots.append((agency, root))
        return (roots, [])

    def fake_get_detail(oc, item_id, target="molitCgmExpc"):
        root = ET.Element("LawService")
        if item_id == "360866":
            ET.SubElement(root, "안건명").text = "도시계획시설 폐지"
            ET.SubElement(root, "회답").text = "일부 폐지에도 적용된다"
        else:
            ET.SubElement(root, "안건명").text = "근로시간"
            ET.SubElement(root, "회답").text = "노동 관련"
        return root

    monkeypatch.setattr(api, "search_agencies", fake_search_agencies)
    monkeypatch.setattr(api, "get_detail", fake_get_detail)
    search_inquiries = llm_tools.build_tools("dummy-oc-key")[8]
    listed = search_inquiries("기초조사 생략")
    assert "360866" in listed
    assert "도시계획시설의 폐지" in listed
    assert "일부 폐지에도 적용된다" in listed


def test_inquiry_title_score_prefers_more_query_tokens() -> None:
    from llm.inquiries import inquiry_title_score

    query = "기초조사 생략"
    weak = inquiry_title_score("근로시간 기초조사", query)
    strong = inquiry_title_score("기초조사 생략 관련 질의회신", query)
    assert strong > weak


def test_get_inquiry_skips_agency_without_detail() -> None:
    tools = llm_tools.build_tools("dummy-oc-key")
    result = tools[9]("1", target="ntsCgmExpc")
    assert "본문을 주지 않습니다" in result


def test_split_doc_reference_recovers_inquiry_from_admrul() -> None:
    assert split_doc_reference("doc:molitCgmExpc:360866") == (
        "molitCgmExpc",
        "360866",
    )
    assert split_doc_reference("doc:admrul:molitCgmExpc:360866") == (
        "molitCgmExpc",
        "360866",
    )
    assert split_doc_reference("doc:admrul:2100000282348") == (
        "admrul",
        "2100000282348",
    )
    assert is_inquiry_target("molitCgmExpc")
    assert not is_inquiry_target("admrul")
