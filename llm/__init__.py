"""LLM 제공자 모음.

새 제공자를 붙일 때는 LlmProvider를 구현하고 PROVIDERS에 추가하면
화면 쪽은 고치지 않아도 된다.
"""

from __future__ import annotations

from .base import (
    ChatSession,
    LlmError,
    LlmProvider,
    ModelInfo,
    Progress,
    extract_cited_articles,
)
from .claude_code import ClaudeCodeProvider
from .codex_app_server import CodexAppServerProvider
from .gemini import GeminiProvider

# Claude Code를 먼저 둔다. API 키 없이 이미 있는 구독으로 돌고, 실제로
# 검색을 훨씬 깊이 있게 해낸다는 것을 확인했다(같은 질문에 헌법 조항까지
# 연결해 답함). Gemini는 무료 한도가 있어 키 없이도 시험해 볼 수 있는
# 대안으로 남겨 둔다.
PROVIDERS: tuple[type[LlmProvider], ...] = (
    ClaudeCodeProvider,
    CodexAppServerProvider,
    GeminiProvider,
)

__all__ = [
    "PROVIDERS",
    "ChatSession",
    "ClaudeCodeProvider",
    "CodexAppServerProvider",
    "GeminiProvider",
    "LlmError",
    "LlmProvider",
    "ModelInfo",
    "Progress",
    "extract_cited_articles",
]
