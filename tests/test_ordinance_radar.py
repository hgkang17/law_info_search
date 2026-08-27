"""조례 정비 레이더. 목적 조문 인용과 시행일 대조만 본다."""

from __future__ import annotations

import molit_cgm_expc_api as api
from llm.ordinance_radar import extract_basis_laws, months_between, run_ordinance_radar


def test_extract_basis_laws_uses_purpose_quotes_and_same_law() -> None:
    purpose = (
        "이 조례는 「주차장법」, 같은 법 시행령 및 시행규칙에서 "
        "위임한 사항과 그 시행에 필요한 사항을 규정함을 목적으로 한다."
    )
    names = extract_basis_laws(purpose, "서울특별시 광진구 주차장 설치 및 관리 조례")
    assert names == ["주차장법", "주차장법 시행령", "주차장법 시행규칙"]


def test_extract_basis_laws_skips_self_name() -> None:
    purpose = "이 조례는 「서울특별시 조례」와 「주차장법」을 따른다."
    names = extract_basis_laws(purpose, "서울특별시 조례")
    assert names == ["주차장법"]


def test_months_between_ignores_day() -> None:
    assert months_between("20200115", "20230101") == 36
    assert months_between("20230101", "20200101") == -36
    assert months_between("2020", "20230101") is None


def test_radar_flags_parent_amended_after_ordinance(
    monkeypatch,
) -> None:
    def fake_search_resource(oc, target, query, **kwargs):
        if target == "ordin":
            return {
                "OrdinSearch": {
                    "law": [
                        {
                            "자치법규명": "광진구 주차장 조례",
                            "자치법규일련번호": "12345",
                        }
                    ]
                }
            }
        assert query == "주차장법"
        return {
            "LawSearch": {
                "law": [
                    {
                        "법령명한글": "주차장법",
                        "법령ID": "001000",
                        "시행일자": "20230101",
                        "현행연혁코드": "현행",
                    }
                ]
            }
        }

    def fake_detail(oc, target, item_id, **kwargs):
        assert target == "ordin"
        assert item_id == "12345"
        assert kwargs.get("id_param") == "MST"
        return {
            "LawService": {
                "자치법규기본정보": {
                    "자치법규명": "광진구 주차장 조례",
                    "시행일자": "20200101",
                    "지자체기관명": "서울특별시 광진구",
                },
                "조문": {
                    "조": {
                        "조제목": "목적",
                        "조내용": "이 조례는 「주차장법」에서 위임한 사항을 규정한다.",
                    }
                },
            }
        }

    monkeypatch.setattr(api, "search_resource", fake_search_resource)
    monkeypatch.setattr(api, "get_resource_detail", fake_detail)
    text = run_ordinance_radar("dummy", query="광진구 주차장 조례")
    assert "[정비 검토]" in text
    assert "주차장법" in text
    assert "약 36개월 뒤" in text
    assert "단정하지 마세요" in text


def test_radar_does_not_use_unrelated_like_hit(monkeypatch) -> None:
    def fake_search_resource(oc, target, query, **kwargs):
        if target == "ordin":
            return {"OrdinSearch": {"law": [{"자치법규일련번호": "1"}]}}
        return {
            "LawSearch": {
                "law": [
                    {
                        "법령명한글": "난민법",
                        "법령ID": "999",
                        "시행일자": "20250101",
                        "현행연혁코드": "현행",
                    }
                ]
            }
        }

    def fake_detail(oc, target, item_id, **kwargs):
        return {
            "LawService": {
                "자치법규기본정보": {
                    "자치법규명": "테스트 조례",
                    "시행일자": "20200101",
                },
                "조문": {
                    "조": {
                        "조제목": "목적",
                        "조내용": "이 조례는 「민법」에서 위임한 사항을 규정한다.",
                    }
                },
            }
        }

    monkeypatch.setattr(api, "search_resource", fake_search_resource)
    monkeypatch.setattr(api, "get_resource_detail", fake_detail)
    text = run_ordinance_radar("dummy", item_id="1")
    assert "확인 불가" in text
    assert "[정비 검토]" not in text
    assert "난민법" not in text
