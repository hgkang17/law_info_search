"""llm/tools.py 검증. 실제 법제처 API는 부르지 않고 흉내만 낸다."""

from __future__ import annotations

import inspect

import pytest

import molit_cgm_expc_api as api
from llm import tools as llm_tools
from utils.parsing import article_jo_label, extract_law_article, normalize_article_jo


def test_normalize_article_jo_codes() -> None:
    assert normalize_article_jo("8") == "000800"
    assert normalize_article_jo("0008") == "000800"
    assert normalize_article_jo("000800") == "000800"
    assert normalize_article_jo("12의2") == "001202"
    assert normalize_article_jo("제12조의2") == "001202"
    assert article_jo_label("001202") == "제12조의2"
    assert article_jo_label("0001") == "제1조"


def test_tools_module_keeps_real_type_objects() -> None:
    """Gemini에 넘기는 함수의 타입 힌트가 문자열로 바뀌면 안 된다.

    llm/tools.py에 `from __future__ import annotations`를 넣었다가 실제로
    겪은 문제다. 그 상태에서는 타입 힌트가 전부 "str" 같은 문자열이 되고,
    Gemini SDK가 도구 호출 스키마를 만들다가
    "isinstance() arg 2 must be a type"로 죽는다. 화면에는 오류가 안 뜨고
    모델이 같은 검색만 반복하다 포기하는 것처럼 보여서 원인을 알아채기
    어려웠다. 이 테스트가 그 상태로 되돌아가는 것을 막는다.
    """
    tools = llm_tools.build_tools("dummy-oc-key")
    search_law = tools[0]
    signature = inspect.signature(search_law)
    query_annotation = signature.parameters["query"].annotation
    assert query_annotation is str, (
        f"query 인자의 타입이 실제 str 객체가 아니라 {query_annotation!r} "
        "입니다. tools.py 맨 위에 `from __future__ import annotations`가 "
        "다시 들어갔는지 확인하세요."
    )


def test_category_meta_rejects_unknown_category() -> None:
    tools = llm_tools.build_tools("dummy-oc-key")
    search_law = tools[0]
    result = search_law("아무거나", category="byl")
    assert "도구 실행 중 오류" in result
    assert "law, admrul, ordin" in result


def test_search_law_maps_result_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_search_resource(oc, target, query, *, display=100, page=1, search_scope=1, nw="", **kwargs):
        assert target == "law"
        assert query == "농지법"
        return {
            "LawSearch": {
                "law": [
                    {
                        "법령명한글": "농지법",
                        "법령ID": "000479",
                        "법령약칭명": "농지법",
                        "시행일자": "20240101",
                    }
                ]
            }
        }

    monkeypatch.setattr(api, "search_resource", fake_search_resource)
    search_law = llm_tools.build_tools("dummy-oc-key")[0]
    result = search_law("농지법")

    assert "농지법" in result
    assert "id=000479" in result
    assert "시행일=20240101" in result
    # 검색으로 끝나지 않고 바로 조문 조회로 넘어가라는 지시가 붙어야 한다.
    # 이게 없으면 약한 모델이 같은 검색을 반복하다 답을 못 낸다.
    assert "get_article" in result


def test_search_law_keeps_official_short_name_for_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """진행줄이 약칭을 쓰려면 검색 결과에 법령약칭명이 남아 있어야 한다."""
    from llm import document_labels

    monkeypatch.setattr(document_labels, "_NAME_INDEX_PATH", tmp_path / "id_names.json")
    monkeypatch.setattr(
        document_labels, "AI_TOOL_SEARCH_CACHE_DIR", tmp_path
    )

    def fake_search_resource(oc, target, query, *, display=100, page=1, search_scope=1, nw="", **kwargs):
        return {
            "LawSearch": {
                "law": [
                    {
                        "법령명한글": "산업입지 및 개발에 관한 법률",
                        "법령ID": "001839",
                        "법령약칭명": "산업입지법",
                    }
                ]
            }
        }

    monkeypatch.setattr(api, "search_resource", fake_search_resource)
    search_law = llm_tools.build_tools("dummy-oc-key")[0]
    result = search_law("산업입지법")

    assert "약칭=산업입지법" in result
    assert (
        document_labels.lookup_cached_document_label("001839")
        == "산업입지 및 개발에 관한 법률"
    )


def test_search_law_expands_alias_and_rejects_unrelated_hits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queries: list[str] = []

    def fake_search_resource(oc, target, query, *, display=100, page=1, search_scope=1, nw="", **kwargs):
        queries.append(query)
        if query == "국토계획법":
            return {
                "LawSearch": {
                    "law": [
                        {
                            "법령명한글": "공간정보의 구축 및 관리 등에 관한 법률",
                            "법령ID": "000001",
                        }
                    ]
                }
            }
        return {
            "LawSearch": {
                "law": [
                    {
                        "법령명한글": "국토의 계획 및 이용에 관한 법률",
                        "법령ID": "009294",
                        "현행연혁코드": "현행",
                        "시행일자": "20240101",
                    }
                ]
            }
        }

    monkeypatch.setattr(api, "search_resource", fake_search_resource)
    search_law = llm_tools.build_tools("dummy-oc-key")[0]
    result = search_law("국토계획법")
    assert "국토의 계획 및 이용에 관한 법률" in result
    assert "id=009294" in result
    assert "[현행]" in result
    assert "공간정보" not in result
    assert any("계획 및 이용" in item for item in queries)


def test_body_search_keeps_hits_whose_title_does_not_match_the_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """본문 검색은 법령명에 없는 낱말로 찾는다. 이름 필터를 걸면 결과가 사라진다."""

    def fake_search_resource(oc, target, query, *, display=100, page=1, search_scope=1, nw="", **kwargs):
        assert query == "준산업단지"
        return {
            "LawSearch": {
                "law": [
                    {
                        "법령명한글": "산업입지 및 개발에 관한 법률",
                        "법령ID": "001839",
                        "법령약칭명": "산업입지법",
                    }
                ]
            }
        }

    monkeypatch.setattr(api, "search_resource", fake_search_resource)
    search_law = llm_tools.build_tools("dummy-oc-key")[0]

    title_search = search_law("준산업단지", search_scope=1)
    assert "[NOT_FOUND]" in title_search
    assert "001839" not in title_search

    body_search = search_law("준산업단지", search_scope=2)
    assert "산업입지 및 개발에 관한 법률" in body_search
    assert "id=001839" in body_search
    assert "[NOT_FOUND]" not in body_search


def test_body_search_asks_for_a_hundred_hits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """본문 검색은 가나다순 앞 20건에 안 들어오는 법령도 받아야 한다."""
    seen: list[tuple[int, int]] = []

    def fake_search_resource(oc, target, query, *, display=100, page=1, search_scope=1, nw="", **kwargs):
        seen.append((search_scope, display))
        return {
            "LawSearch": {
                "law": [
                    {
                        "법령명한글": "산업입지 및 개발에 관한 법률",
                        "법령ID": "001839",
                    }
                ]
            }
        }

    monkeypatch.setattr(api, "search_resource", fake_search_resource)
    search_law = llm_tools.build_tools("dummy-oc-key")[0]
    search_law("준산업단지", search_scope=1)
    search_law("준산업단지", search_scope=2)

    assert (1, 20) in seen
    assert (2, 100) in seen


def test_legal_research_appends_three_stage_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_search_resource(oc, target, query, *, display=100, page=1, search_scope=1, nw="", **kwargs):
        return {
            "LawSearch": {
                "law": [
                    {
                        "법령명한글": "국토의 계획 및 이용에 관한 법률",
                        "법령ID": "009294",
                    }
                ]
            },
            "AdmRulSearch": {"admrul": []},
            "licBylSearch": {"licbyl": []},
            "admRulBylSearch": {"admrulbyl": []},
        }

    def fake_three_stage(oc, item_id, *, comparison_kind=2):
        assert item_id == "009294"
        return {
            "LawService": {
                "위임조문삼단비교": {
                    "법률조문": {
                        "조번호": "2",
                        "시행령조문": {
                            "법령명": "국토의 계획 및 이용에 관한 법률 시행령",
                            "조번호": "4",
                            "조제목": "도시·군관리계획",
                        },
                    }
                }
            }
        }

    monkeypatch.setattr(api, "search_resource", fake_search_resource)
    monkeypatch.setattr(api, "get_three_stage_comparison", fake_three_stage)
    legal_research = llm_tools.build_tools("dummy-oc-key")[5]
    result = legal_research("국토계획법")
    assert "[3단비교 위임]" in result
    assert "시행령 제4조" in result
    assert "get_article" in result


def test_search_law_reports_no_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        api, "search_resource", lambda *a, **k: {"LawSearch": {"law": []}}
    )
    search_law = llm_tools.build_tools("dummy-oc-key")[0]
    result = search_law("존재하지않는법령이름")
    assert "[NOT_FOUND]" in result
    assert "추측하지 마세요" in result


def _forbid_full_law_fetch(*_args, **_kwargs):
    raise AssertionError("조 하나 읽는데 법령 전문 API를 부르면 안 된다")


def test_get_article_reads_one_article_via_josub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get_law_article(oc, law_id, jo, *, hang="", ho="", mok=""):
        assert law_id == "000479"
        assert jo == "000100"
        return {
            "법령": {
                "조문": {
                    "조문단위": [
                        {"조문번호": "1", "조문여부": "전문"},
                        {"조문번호": "1", "조문내용": "제1조(목적) 이 법은..."},
                    ]
                }
            }
        }

    monkeypatch.setattr(api, "get_resource_detail", _forbid_full_law_fetch)
    monkeypatch.setattr(api, "get_law_article", fake_get_law_article)
    get_article = llm_tools.build_tools("dummy-oc-key")[1]
    result = get_article("000479", "0001")
    assert result == "제1조(목적) 이 법은..."


def test_get_article_missing_reports_plainly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "get_resource_detail", _forbid_full_law_fetch)
    monkeypatch.setattr(
        api,
        "get_law_article",
        lambda *a, **k: {"법령": {"조문": {"조문단위": []}}},
    )
    get_article = llm_tools.build_tools("dummy-oc-key")[1]
    result = get_article("000479", "9999")
    assert "찾지 못했습니다" in result


def test_get_article_uses_josub_for_article_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = {}

    def fake_get_law_article(oc, law_id, jo, *, hang="", ho="", mok=""):
        seen["id"] = law_id
        seen["jo"] = jo
        return {
            "법령": {
                "조문": {
                    "조문단위": [{"조문내용": "제30조(결정) 도시·군관리계획은"}]
                }
            }
        }

    monkeypatch.setattr(api, "get_resource_detail", _forbid_full_law_fetch)
    monkeypatch.setattr(api, "get_law_article", fake_get_law_article)
    get_article = llm_tools.build_tools("dummy-oc-key")[1]
    result = get_article("009294", "30")
    assert seen == {"id": "009294", "jo": "003000"}
    assert "제30조(결정)" in result


def test_tool_failure_becomes_text_not_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """도구가 죽으면 대화 전체가 끊긴다. 실패도 문자열로 돌려줘야 한다."""

    def boom(*args, **kwargs):
        raise ConnectionError("네트워크 끊김")

    monkeypatch.setattr(api, "search_resource", boom)
    search_law = llm_tools.build_tools("dummy-oc-key")[0]
    result = search_law("아무 법령")
    assert "오류" in result
    assert "네트워크 끊김" in result


def test_oc_key_is_hidden_from_tool_signature() -> None:
    """모델이 볼 수 있는 인자에 인증키가 섞이면 안 된다."""
    search_law = llm_tools.build_tools("secret-oc-key")[0]
    params = inspect.signature(search_law).parameters
    assert "oc" not in params
    assert "oc_key" not in params


def test_result_is_truncated_for_long_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    huge = "가" * (llm_tools._MAX_RESULT_CHARS + 500)
    monkeypatch.setattr(
        api,
        "get_resource_detail",
        lambda *a, **k: {"법령": huge},
    )
    get_document = llm_tools.build_tools("dummy-oc-key")[2]
    result = get_document("000479", category="law")
    assert len(result) < len(huge)
    assert "잘림" in result


def test_get_article_notifies_touched_document(monkeypatch: pytest.MonkeyPatch) -> None:
    """즐겨찾기 단추는 실제로 읽은 문서만 알아야 한다.

    검색 후보는 여러 개일 수 있어 신호로 약하다. get_article을 불러
    실제로 조문을 읽었을 때만 콜백이 와야, 화면에 모델이 훑어보기만 한
    법령까지 단추로 걸리지 않는다.
    """
    monkeypatch.setattr(
        api,
        "search_resource",
        lambda *a, **k: {
            "LawSearch": {
                "law": [{"법령명한글": "농지법", "법령ID": "000479"}]
            }
        },
    )
    monkeypatch.setattr(api, "get_resource_detail", _forbid_full_law_fetch)
    monkeypatch.setattr(
        api,
        "get_law_article",
        lambda *a, **k: {
            "법령": {
                "조문": {
                    "조문단위": [{"조문내용": "제1조(목적) ..."}]
                }
            }
        },
    )
    notified: list[tuple[str, str, str]] = []
    search_law, get_article, *_ = llm_tools.build_tools(
        "dummy-oc-key", on_document_used=lambda *args: notified.append(args)
    )

    search_law("농지법")
    assert notified == [], "검색만으로는 아직 통보하지 않는다"

    get_article("000479", "0001")
    assert notified == [("law", "000479", "농지법")]


def test_notify_callback_failure_does_not_break_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """단추를 만드는 콜백이 죽어도 답변 자체는 끊기면 안 된다."""
    monkeypatch.setattr(api, "get_resource_detail", _forbid_full_law_fetch)
    monkeypatch.setattr(
        api,
        "get_law_article",
        lambda *a, **k: {
            "법령": {"조문": {"조문단위": [{"조문내용": "제1조 본문"}]}}
        },
    )

    def boom(*args):
        raise RuntimeError("화면 쪽 콜백 오류")

    _, get_article, *_ = llm_tools.build_tools(
        "dummy-oc-key", on_document_used=boom
    )
    result = get_article("000479", "0001")
    assert result == "제1조 본문"


def test_get_annexes_searches_related_law_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = {}

    def fake_search_resource(
        oc, target, query, *, display=100, page=1, search_scope=1, nw="", **kwargs
    ):
        seen.update(oc=oc, target=target, query=query, search_scope=search_scope)
        return {
            "licBylSearch": {
                "licbyl": [
                    {
                        "별표일련번호": "123",
                        "별표명": "별지 제1호서식",
                        "관련법령명": "도시계획법 시행규칙",
                        "소관부처명": "국토교통부",
                    }
                ]
            }
        }

    monkeypatch.setattr(api, "search_resource", fake_search_resource)
    get_annexes = llm_tools.build_tools("dummy-oc-key")[4]
    result = get_annexes("도시계획법 시행규칙", category="licbyl")

    assert seen == {
        "oc": "dummy-oc-key",
        "target": "licbyl",
        "query": "도시계획법 시행규칙",
        "search_scope": 2,
    }
    assert "별지 제1호서식" in result
    assert "관련=도시계획법 시행규칙" in result
    assert "[별지 제1호서식](doc:licbyl:123)" in result


def test_legal_research_searches_law_admin_rules_and_annexes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, int]] = []

    def fake_search_resource(
        oc, target, query, *, display=100, page=1, search_scope=1, nw="", **kwargs
    ):
        calls.append((target, query, search_scope))
        return {
            "LawSearch": {
                "law": [{"법령명한글": "국토계획법", "법령ID": "1"}]
            },
            "AdmRulSearch": {
                "admrul": [
                    {"행정규칙명": "도시·군관리계획수립지침", "행정규칙일련번호": "2"}
                ]
            },
            "licBylSearch": {
                "licbyl": [{"별표명": "별지서식", "별표일련번호": "3"}]
            },
            "admRulBylSearch": {
                "admrulbyl": [{"별표명": "계획조서", "별표일련번호": "4"}]
            },
        }

    monkeypatch.setattr(api, "search_resource", fake_search_resource)
    monkeypatch.setattr(
        api, "get_three_stage_comparison", lambda *a, **k: {}
    )
    legal_research = llm_tools.build_tools("dummy-oc-key")[5]
    result = legal_research("도시관리계획 입안서류좀 찾아주라")

    assert any(target == "law" and scope == 1 for target, _, scope in calls)
    assert any(target == "admrul" and scope == 1 for target, _, scope in calls)
    assert any(target == "law" and scope == 2 for target, _, scope in calls)
    assert any(target == "licbyl" and scope == 2 for target, _, scope in calls)
    assert any(target == "admbyl" and scope == 2 for target, _, scope in calls)
    assert "도시·군관리계획수립지침" in result
    assert "계획조서" in result
    assert "[다음 행동]" in result


def test_get_article_normalizes_branch_article_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = {}

    def fake_get_law_article(oc, law_id, jo, *, hang="", ho="", mok=""):
        seen["id"] = law_id
        seen["jo"] = jo
        return {
            "법령": {
                "조문": {
                    "조문단위": [{"조문내용": "제12조의2(특례) 본문"}]
                }
            }
        }

    monkeypatch.setattr(api, "get_resource_detail", _forbid_full_law_fetch)
    monkeypatch.setattr(api, "get_law_article", fake_get_law_article)
    get_article = llm_tools.build_tools("dummy-oc-key")[1]
    result = get_article("001866", "12의2")
    assert seen == {"id": "001866", "jo": "001202"}
    assert "제12조의2" in result


def test_get_document_returns_plain_article_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        api,
        "get_resource_detail",
        lambda *a, **k: {
            "법령": {
                "기본정보": {"법령명_한글": "농지법", "시행일자": "20240101"},
                "조문": {
                    "조문단위": [
                        {"조문내용": "제1조(목적) 이 법은 농지를 위하여"},
                        {
                            "조문내용": "제2조(정의)",
                            "항": [{"항내용": "① 농지란 다음을 말한다."}],
                        },
                    ]
                },
            }
        },
    )
    get_document = llm_tools.build_tools("dummy-oc-key")[2]
    result = get_document("000479", category="law")
    assert "제1조(목적)" in result
    assert "제2조(정의)" in result
    assert "get_article" in result
    assert "{'조문'" not in result


def test_get_document_keyword_uses_readable_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        api,
        "get_resource_detail",
        lambda *a, **k: {
            "AdmRulService": {
                "행정규칙기본정보": {"행정규칙명": "도시·군관리계획수립지침"},
                "조문내용": "3-1-1. 입안서류는 계획설명서와 계획도면을 포함한다.",
            }
        },
    )
    get_document = llm_tools.build_tools("dummy-oc-key")[2]
    result = get_document("2", category="admrul", keyword="입안서류")
    assert "입안서류는 계획설명서" in result
    assert "AdmRulService" not in result


def test_search_cases_and_get_case(monkeypatch: pytest.MonkeyPatch) -> None:
    import xml.etree.ElementTree as ET
    from models.law import EXPC_AGENCY

    def fake_search_agencies(oc, agencies, *, query=None, search=1, display=100, page=1):
        root = ET.Element("LawSearch")
        item = ET.SubElement(root, "expc", id="1")
        ET.SubElement(item, "법령해석례일련번호").text = "100"
        ET.SubElement(item, "안건명").text = "농지전용 질의"
        ET.SubElement(item, "안건번호").text = "12-1"
        return ([(EXPC_AGENCY, root)], [])

    def fake_get_detail(oc, item_id, target="expc"):
        root = ET.Element("LawService")
        ET.SubElement(root, "안건명").text = "농지전용 질의"
        ET.SubElement(root, "질의요지").text = "전용 대상인지"
        ET.SubElement(root, "회답").text = "대상이 아니다"
        return root

    monkeypatch.setattr(api, "search_agencies", fake_search_agencies)
    monkeypatch.setattr(api, "get_detail", fake_get_detail)
    tools = llm_tools.build_tools("dummy-oc-key")
    listed = tools[6]("농지전용")
    assert "농지전용 질의" in listed
    assert "id=100" in listed
    body = tools[7]("100", source="expc")
    assert "대상이 아니다" in body
    assert "[회답]" in body


def test_get_document_reads_saved_body_without_api(
    isolate_saved_documents, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolate_saved_documents.save(
        {"target": "law", "id": "000479", "name": "농지법"},
        {
            "법령": {
                "기본정보": {"법령명_한글": "농지법"},
                "조문": {
                    "조문단위": [
                        {"조문내용": "제1조(목적) 저장된 본문이다"}
                    ]
                },
            }
        },
    )

    def boom(*args, **kwargs):
        raise AssertionError("저장본이 있으면 본문 API를 부르면 안 된다")

    monkeypatch.setattr(api, "get_resource_detail", boom)
    get_document = llm_tools.build_tools(
        "dummy-oc-key", law_cache=isolate_saved_documents
    )[2]
    result = get_document("000479", category="law", keyword="목적")
    assert "저장된 본문이다" in result


def test_get_article_uses_saved_payload_without_api(
    isolate_saved_documents, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolate_saved_documents.save(
        {"target": "law", "id": "000479", "name": "농지법"},
        {
            "법령": {
                "조문": {
                    "조문단위": [{"조문번호": "1", "조문내용": "제1조 저장본"}]
                }
            }
        },
    )
    monkeypatch.setattr(api, "get_resource_detail", _forbid_full_law_fetch)

    def boom_josub(*_args, **_kwargs):
        raise AssertionError("저장본에 조가 있으면 조항호목 API도 부르면 안 된다")

    monkeypatch.setattr(api, "get_law_article", boom_josub)
    get_article = llm_tools.build_tools(
        "dummy-oc-key", law_cache=isolate_saved_documents
    )[1]
    result = get_article("000479", "0001")
    assert result == "제1조 저장본"


def test_get_document_saves_admin_rule_snapshot(
    isolate_saved_documents, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {
        "AdmRulService": {
            "행정규칙기본정보": {"행정규칙명": "도시·군관리계획수립지침"},
            "조문내용": "3-1-1. 입안서류는 계획설명서와 계획도면을 포함한다.",
        }
    }
    monkeypatch.setattr(api, "get_resource_detail", lambda *a, **k: payload)
    get_document = llm_tools.build_tools(
        "dummy-oc-key", law_cache=isolate_saved_documents
    )[2]
    result = get_document("2", category="admrul", keyword="입안서류")
    assert "입안서류는 계획설명서" in result
    saved = isolate_saved_documents.load_snapshot({"target": "admrul", "id": "2"})
    assert saved is not None
    assert saved["detail_payload"] == payload
    assert saved["administrative_rule_sections"]


def test_extract_law_article_from_saved_payload() -> None:
    payload = {
        "법령": {
            "조문": {
                "조문단위": [
                    {"조문번호": "1", "조문내용": "제1조(목적) 이 법은"},
                    {
                        "조문번호": "2",
                        "조문내용": "제2조(정의)",
                        "항": [{"항번호": "1", "항내용": "① 농지란 다음을 말한다."}],
                    },
                ]
            }
        }
    }
    assert extract_law_article(payload, "000100") == "제1조(목적) 이 법은"
    assert "① 농지란" in extract_law_article(payload, "2")


def test_extract_law_article_ignores_date_suffix_on_unit_key() -> None:
    payload = {
        "법령": {
            "조문": {
                "조문단위": [
                    {
                        "조문키": "00300020210701",
                        "조문내용": "제30조(도시·군관리계획의 결정)",
                    }
                ]
            }
        }
    }
    assert "제30조" in extract_law_article(payload, "003000")
    assert "제30조" in extract_law_article(payload, "30")


def test_search_law_ranks_exact_name_ahead_of_partial_hit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_search_resource(oc, target, query, *, display=100, page=1, search_scope=1, nw="", **kwargs):
        return {
            "LawSearch": {
                "law": [
                    {
                        "법령명한글": "난민법",
                        "법령ID": "1",
                        "현행연혁코드": "현행",
                    },
                    {
                        "법령명한글": "민법",
                        "법령ID": "2",
                        "현행연혁코드": "현행",
                    },
                ]
            }
        }

    monkeypatch.setattr(api, "search_resource", fake_search_resource)
    result = llm_tools.build_tools("dummy-oc-key")[0]("민법")
    assert result.index("민법") < result.index("난민법")


def test_get_annexes_parses_single_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_search_resource(oc, target, query, *, display=100, page=1, search_scope=1, nw="", **kwargs):
        return {
            "licBylSearch": {
                "licbyl": [
                    {
                        "별표일련번호": "9",
                        "별표번호": "000400",
                        "별표명": "별표 4 과태료",
                        "별표서식파일링크": "/LSW/flDownload.do?flSeq=1",
                    }
                ]
            }
        }

    monkeypatch.setattr(api, "search_resource", fake_search_resource)
    from utils.annex_parse import AnnexParseResult

    monkeypatch.setattr(llm_tools, "download_law_file", lambda url: b"hwp-bytes")
    monkeypatch.setattr(
        llm_tools,
        "parse_annex_bytes",
        lambda data: AnnexParseResult(
            success=True,
            markdown="| 위반 | 과태료 |\n| 무단전용 | 500만원 |",
            file_type="hwp",
        ),
    )
    result = llm_tools.build_tools("dummy-oc-key")[4]("농지법 별표 4", category="licbyl")
    assert "무단전용" in result
    assert "별표 4 과태료" in result


def test_get_historical_law_uses_effective_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = {}

    def fake_historical(oc, law_id, *, date, jo=""):
        seen["id"] = law_id
        seen["date"] = date
        seen["jo"] = jo
        return {
            "법령": {
                "조문": {
                    "조문단위": [{"조문번호": "1", "조문내용": "제1조 당시 본문"}]
                }
            }
        }

    monkeypatch.setattr(api, "get_historical_law", fake_historical)
    monkeypatch.setattr(
        api,
        "get_resource_detail",
        lambda *a, **k: {
            "법령": {
                "부칙": {
                    "부칙단위": [
                        {
                            "부칙공포번호": "19158",
                            "부칙공포일자": "20230103",
                            "부칙내용": (
                                "부칙 <제19158호, 2023.1.3.>\n"
                                "제2조(적용례) 이 법 시행 당시의 행위에 대하여는 "
                                "종전의 규정에 따른다."
                            ),
                        }
                    ]
                }
            }
        },
    )
    tools = llm_tools.build_tools("dummy-oc-key")
    result = tools[10]("000479", date="2024-01-01", jo="1")
    assert seen == {"id": "000479", "date": "20240101", "jo": "000100"}
    assert "당시 본문" in result
    assert "20240101" in result
    assert "적용례·경과조치" in result
    assert "종전의 규정" in result


def test_compare_old_new_compacts_xml(monkeypatch: pytest.MonkeyPatch) -> None:
    import xml.etree.ElementTree as ET

    root = ET.fromstring(
        """
        <LawService>
          <법령명>농지법</법령명>
          <구조문_기본정보><공포일자>20200101</공포일자></구조문_기본정보>
          <신조문_기본정보>
            <공포일자>20240101</공포일자>
            <제개정구분명>일부개정</제개정구분명>
          </신조문_기본정보>
          <구조문목록><조문><조문키>제1조</조문키>구 목적</조문></구조문목록>
          <신조문목록><조문><조문키>제1조</조문키>신 목적</조문></신조문목록>
        </LawService>
        """
    )
    monkeypatch.setattr(api, "get_old_and_new", lambda *a, **k: root)
    result = llm_tools.build_tools("dummy-oc-key")[11]("000479")
    assert "[신구대조] 농지법" in result
    assert "신 목적" in result
    assert "일부개정" in result


def test_build_tools_includes_radar_cite_and_impact() -> None:
    names = [fn.__name__ for fn in llm_tools.build_tools("dummy-oc-key")]
    assert names[-3:] == ["ordinance_radar", "cite_check", "impact_map"]
    assert names[8] == "search_inquiries"
    assert names[9] == "get_inquiry"
    assert names[10] == "get_historical_law"
    assert names[11] == "compare_old_new"
