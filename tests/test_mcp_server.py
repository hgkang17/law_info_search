"""mcp_server/server.py 검증. 실제 법제처 API도, 실제 stdio도 쓰지 않는다.

이 서버는 Claude/ChatGPT Desktop이 별도 프로세스로 띄우는 것을 전제로
동작한다. 여기서는 FastMCP의 도구 등록ㆍ호출 경로가 llm/tools.py의
함수를 그대로 받아도 깨지지 않는지, 그리고 인증키가 도구 스키마에
새지 않는지만 확인한다.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import sys

import pytest

import molit_cgm_expc_api as api


@pytest.fixture()
def server_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LAW_API_KEY", "dummy-oc-key")
    sys.modules.pop("mcp_server.server", None)
    sys.modules.pop("mcp_server", None)
    return importlib.import_module("mcp_server.server")


def test_server_module_imports_from_any_working_directory(
    server_module, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Claude/ChatGPT Desktop은 프로젝트 폴더가 아닌 곳에서 이 파일을 띄운다.

    server.py가 sys.path에 프로젝트 루트를 직접 넣지 않으면
    molit_cgm_expc_api를 못 찾는다.
    """
    monkeypatch.chdir(tmp_path)
    sys.modules.pop("mcp_server.server", None)
    sys.modules.pop("mcp_server", None)
    module = importlib.import_module("mcp_server.server")
    assert module.mcp.name == "법령검색"


def test_all_tools_are_registered(server_module) -> None:
    tools = asyncio.run(server_module.mcp.list_tools())
    names = {tool.name for tool in tools}
    assert names == {
        "search_law",
        "get_article",
        "get_document",
        "search_admin_rule",
        "get_annexes",
        "legal_research",
        "search_cases",
        "get_case",
        "search_inquiries",
        "get_inquiry",
        "get_historical_law",
        "compare_old_new",
        "ordinance_radar",
        "cite_check",
        "impact_map",
    }


def test_oc_key_never_appears_in_tool_schema(server_module) -> None:
    """인증키는 클로저 안에만 있어야 한다. 모델이 볼 스키마에 새면 안 된다."""
    tools = asyncio.run(server_module.mcp.list_tools())
    for tool in tools:
        params = set(tool.inputSchema.get("properties", {}))
        assert "oc_key" not in params
        assert "oc" not in params
        assert "dummy-oc-key" not in str(tool.inputSchema)


def test_search_law_tool_call_reaches_real_api_wrapper(
    server_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FastMCP를 거쳐도 실제로는 molit_cgm_expc_api를 부르는지 확인한다."""
    seen = {}

    def fake_search_resource(oc, target, query, *, display=100, page=1, search_scope=1, nw="", **kwargs):
        seen["oc"] = oc
        seen["target"] = target
        seen["query"] = query
        return {"LawSearch": {"law": [{"법령명한글": "농지법", "법령ID": "000479"}]}}

    monkeypatch.setattr(api, "search_resource", fake_search_resource)
    content, structured = asyncio.run(
        server_module.mcp.call_tool("search_law", {"query": "농지법"})
    )
    assert seen == {"oc": "dummy-oc-key", "target": "law", "query": "농지법"}
    assert "농지법" in content[0].text
    assert "id=000479" in content[0].text


def test_missing_api_key_warns_but_still_starts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """키를 안 넣었다고 서버 자체가 죽으면 원인을 알 길이 없다.

    도구 목록은 뜨고, 실제 호출에서만 자연스럽게 실패해야 한다.
    """
    monkeypatch.delenv("LAW_API_KEY", raising=False)
    sys.modules.pop("mcp_server.server", None)
    sys.modules.pop("mcp_server", None)
    module = importlib.import_module("mcp_server.server")
    assert "LAW_API_KEY" in capsys.readouterr().err
    tools = asyncio.run(module.mcp.list_tools())
    assert len(tools) == 15


@pytest.fixture(autouse=True)
def _cleanup_module():
    yield
    sys.modules.pop("mcp_server.server", None)
    sys.modules.pop("mcp_server", None)
