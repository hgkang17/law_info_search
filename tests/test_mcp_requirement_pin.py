"""배포 EXE의 MCP 서버가 mcp 2.x로 깨지지 않게 막는 회귀 검증."""

from __future__ import annotations

import pathlib
import re

import pytest

REQUIREMENTS = pathlib.Path(__file__).resolve().parent.parent / "requirements.txt"


def test_mcp_dependency_keeps_a_major_version_ceiling() -> None:
    """상한이 없으면 빌드 기계가 2.x를 받아 배포본의 MCP 서버만 죽는다.

    mcp 2.x는 FastMCP를 MCPServer로 바꾸면서 mcp.server.fastmcp를 없앴다.
    로컬에 1.x가 깔려 있으면 개발 중에는 드러나지 않고, GitHub Actions가
    새로 받아 만든 EXE에서만 터진다.
    """
    text = REQUIREMENTS.read_text(encoding="utf-8")
    match = re.search(r"^mcp\[cli\].*$", text, re.MULTILINE)

    assert match is not None, "requirements.txt에서 mcp 항목을 찾지 못했습니다."
    assert "<2" in match.group(0), match.group(0)


def test_installed_mcp_still_exposes_fastmcp() -> None:
    """서버 코드가 쓰는 진입점이 살아 있는지 확인한다."""
    pytest.importorskip("mcp")
    from mcp.server.fastmcp import FastMCP

    assert callable(FastMCP)
