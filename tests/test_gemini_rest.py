"""SDK 없이 부르는 Gemini 검증.

Gemini는 CLI가 아니라 HTTPS API다. 예전에는 google-genai SDK가 함수
선언을 만들고 도구 호출을 대신 돌려 주었는데, 그 패키지가 없으면 아예
못 썼다(exe로 묶어 배포하면 늘 그랬다). 이제 그 두 가지를 직접 하므로
여기서 지킨다.
"""

from __future__ import annotations

import json

import pytest

from llm.base import LlmError, Progress
from llm.gemini import GeminiChat, GeminiProvider
from llm.gemini_rest import function_declarations


def search_law(query: str, category: str = "law", search_scope: int = 1) -> str:
    """법제처에서 이름으로 문서를 찾는다.

    두 번째 줄까지가 설명이다.

    Args:
        query: 찾을 법령 이름.
        category: "law"(기본값) | "admrul".
        search_scope: 1=문서명, 2=본문. 업무 용어로 찾을 때는
            2를 쓴다.
    """
    return f"{query}/{category}/{search_scope} 검색 결과"


def _text_chunk(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def _call_chunk(name: str, args: dict) -> dict:
    part = {"functionCall": {"name": name, "args": args}}
    return {"candidates": [{"content": {"parts": [part]}}]}


class FakeClient:
    """미리 정해 둔 응답을 차례로 돌려주는 가짜 Gemini."""

    def __init__(self, *turns: list[dict]) -> None:
        self.turns = [list(turn) for turn in turns]
        self.payloads: list[dict] = []
        self.closed = False

    def stream(self, model_id: str, payload: dict):
        # payload의 contents는 대화 기록 그 자체라 뒤에 계속 늘어난다.
        # 보낸 그 시점을 보려면 사본을 떠 둬야 한다.
        self.payloads.append(json.loads(json.dumps(payload)))
        return iter(self.turns.pop(0))

    def close(self) -> None:
        self.closed = True


def _chat(client: FakeClient, tools=(search_law,)) -> GeminiChat:
    return GeminiChat(client, "gemini-flash-latest", "지시문", tools)


# ------------------------------------------------------------------ 함수 선언
def test_function_declaration_is_built_from_the_tool_itself() -> None:
    """도구의 타입 힌트와 독스트링이 그대로 Gemini 함수 선언이 된다."""
    (declaration,) = function_declarations((search_law,))

    assert declaration["name"] == "search_law"
    assert declaration["description"].startswith("법제처에서 이름으로")
    assert "Args:" not in declaration["description"]

    parameters = declaration["parameters"]
    assert parameters["type"] == "OBJECT"
    assert parameters["properties"]["query"]["type"] == "STRING"
    assert parameters["properties"]["search_scope"]["type"] == "INTEGER"
    # 기본값이 없는 인자만 필수다.
    assert parameters["required"] == ["query"]


def test_multi_line_argument_description_is_kept() -> None:
    """여러 줄로 적은 인자 설명도 잘리지 않고 한 줄로 붙는다."""
    (declaration,) = function_declarations((search_law,))
    note = declaration["parameters"]["properties"]["search_scope"]["description"]

    assert "1=문서명" in note and "2를 쓴다" in note


def test_real_tools_all_become_declarations() -> None:
    """실제 도구 열다섯 개가 빠짐없이 선언으로 바뀐다."""
    from llm.tools import build_tools

    declarations = function_declarations(build_tools("테스트키"))
    names = [item["name"] for item in declarations]

    assert names == [
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
    ]
    assert all(item["description"] for item in declarations)


# ------------------------------------------------------------------ 도구 오가기
def test_chat_runs_the_tool_and_asks_again_with_the_result() -> None:
    """모델이 도구를 부르면 실제로 돌리고 그 결과를 붙여 다시 묻는다."""
    client = FakeClient(
        [_call_chunk("search_law", {"query": "농지법"})],
        [_text_chunk("농지법 제1조는"), _text_chunk(" 목적 규정입니다.")],
    )
    chat = _chat(client)

    pieces = list(chat.send("농지법을 알려 줘"))
    text = "".join(piece for piece in pieces if isinstance(piece, str))
    progress = [piece for piece in pieces if isinstance(piece, Progress)]

    assert text == "농지법 제1조는 목적 규정입니다."
    # 무엇을 하는 중인지 화면에 알려 준다. SDK를 쓸 때는 이 줄이 없었다.
    assert progress[0].text == "법제처에서 법령 검색하는 중: 농지법"
    assert progress[0].kind == "tool"

    # 두 번째 요청에는 도구 결과가 실려 나간다.
    second = client.payloads[1]["contents"]
    answer = second[-1]["parts"][0]["functionResponse"]
    assert answer["name"] == "search_law"
    assert answer["response"]["result"] == "농지법/law/1 검색 결과"


def test_body_search_progress_uses_a_different_label() -> None:
    """업무 용어 본문 검색은 제목 검색과 다른 진행 문구를 쓴다."""
    client = FakeClient(
        [_call_chunk("search_law", {"query": "준산업단지", "search_scope": 2})],
        [_text_chunk("준산업단지는")],
    )
    chat = _chat(client)
    progress = [
        piece
        for piece in chat.send("준산업단지에 대해 알려줘")
        if isinstance(piece, Progress)
    ]
    assert progress[0].text == "법제처에서 법령 본문 검색하는 중: 준산업단지"


def test_tool_declarations_ride_along_only_when_there_are_tools() -> None:
    client = FakeClient([_text_chunk("답")])
    list(_chat(client, tools=()).send("질문"))

    assert "tools" not in client.payloads[0]
    assert client.payloads[0]["systemInstruction"]["parts"][0]["text"] == "지시문"


def test_unknown_tool_is_answered_instead_of_crashing() -> None:
    """모델이 없는 도구를 부르면 대화를 끊지 않고 그렇다고 알려 준다."""
    client = FakeClient(
        [_call_chunk("찾아줘", {})],
        [_text_chunk("다시 찾겠습니다.")],
    )
    list(_chat(client).send("질문"))

    answer = client.payloads[1]["contents"][-1]["parts"][0]["functionResponse"]
    assert "없습니다" in answer["response"]["result"]


def test_history_carries_over_to_the_next_question() -> None:
    """이어 묻기가 되려면 앞의 문답을 우리가 들고 있어야 한다."""
    client = FakeClient([_text_chunk("첫 답")], [_text_chunk("둘째 답")])
    chat = _chat(client)

    list(chat.send("첫 질문"))
    list(chat.send("둘째 질문"))

    contents = client.payloads[1]["contents"]
    assert [item["role"] for item in contents] == ["user", "model", "user"]
    assert contents[0]["parts"][0]["text"] == "첫 질문"
    assert contents[1]["parts"][0]["text"] == "첫 답"


def test_streamed_pieces_are_merged_before_they_are_remembered() -> None:
    """흘러온 조각을 그대로 쌓으면 기록이 조각 수만큼 불어난다."""
    client = FakeClient(
        [_text_chunk("한 "), _text_chunk("문장"), _text_chunk("입니다.")],
        [_text_chunk("둘째 답")],
    )
    chat = _chat(client)
    list(chat.send("질문"))
    list(chat.send("또 질문"))

    remembered = client.payloads[1]["contents"][1]["parts"]
    assert remembered == [{"text": "한 문장입니다."}]


def test_empty_answer_is_reported_as_a_failure() -> None:
    """조용히 빈 말풍선만 남으면 멈춘 건지 알 수 없다."""
    client = FakeClient([])
    with pytest.raises(LlmError):
        list(_chat(client).send("질문"))


def test_safety_stop_says_why() -> None:
    client = FakeClient([{"candidates": [{"finishReason": "SAFETY"}]}])
    with pytest.raises(LlmError, match="안전 설정"):
        list(_chat(client).send("질문"))


def test_stopping_drops_the_unfinished_turn() -> None:
    """중간에 멈춘 턴을 기록에 남기면 다음 질문이 통째로 거부당한다."""
    client = FakeClient(
        [_call_chunk("search_law", {"query": "농지법"})],
        [_text_chunk("답")],
    )
    chat = _chat(client)

    stream = chat.send("질문")
    next(stream)  # 도구 진행 문구까지만 받고
    chat.cancel()
    stream.close()

    assert chat._history == []


# ------------------------------------------------------------------ 오류 문구
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("[404] NOT_FOUND model is not found for API version", "[갱신]"),
        ("[400] INVALID_ARGUMENT API key not valid", "API 키가 올바르지"),
        ("[403] PERMISSION_DENIED", "쓸 수 없습니다"),
        ("[429] RESOURCE_EXHAUSTED quota", "무료 한도"),
        ("[503] UNAVAILABLE overloaded", "사람이 몰려"),
        ("[500] INTERNAL", "구글 쪽에서 일시적인"),
        ("[400] FAILED_PRECONDITION billing", "이 지역이나 이 계정"),
        ("[400] input token count exceeds", "본문을 줄이거나"),
        (
            "[400] INVALID_ARGUMENT Function call is missing a "
            "thought_signature in functionCall parts",
            "프로그램 쪽 문제",
        ),
        ("연결하지 못했습니다: Max retries exceeded", "인터넷에 연결하지"),
        ("Read timed out", "응답이 너무 늦어"),
    ],
)
def test_api_failure_becomes_a_korean_sentence_the_user_can_act_on(
    raw: str, expected: str
) -> None:
    """Google이 돌려주는 사유는 전부 영어다. 그대로 두면 읽어도 모른다."""
    message = GeminiProvider._readable(RuntimeError(raw))
    assert expected in message
    # 우리말로 정해 둔 것은 영어 원문을 덧붙이지 않는다.
    assert "원문:" not in message


def test_unknown_failure_keeps_the_original_text() -> None:
    """아직 우리말로 정해 두지 않은 것은 원문이라도 보여 줘야 한다."""
    message = GeminiProvider._readable(RuntimeError("무언가 새로운 사유"))
    assert "무언가 새로운 사유" in message


def test_thought_signature_is_sent_back_with_the_tool_result() -> None:
    """서명을 빼고 다시 물으면 Gemini 3이 요청을 통째로 거부한다.

    실제로 "Function call is missing a thought_signature in functionCall
    parts"라는 400을 맞았다. 받은 그대로 돌려줘야 한다.
    """
    call = _call_chunk("search_law", {"query": "농지법"})
    call["candidates"][0]["content"]["parts"][0]["thoughtSignature"] = "서명값"
    client = FakeClient([call], [_text_chunk("답")])

    list(_chat(client).send("질문"))

    remembered = client.payloads[1]["contents"][1]["parts"][0]
    assert remembered["thoughtSignature"] == "서명값"
    assert remembered["functionCall"]["name"] == "search_law"


def test_signature_that_arrives_on_its_own_sticks_to_the_previous_piece() -> None:
    client = FakeClient(
        [_text_chunk("답"), {"candidates": [{"content": {"parts": [
            {"text": "", "thoughtSignature": "뒤늦은서명"}
        ]}}]}],
        [_text_chunk("둘째")],
    )
    chat = _chat(client)
    list(chat.send("질문"))
    list(chat.send("또 질문"))

    remembered = client.payloads[1]["contents"][1]["parts"][0]
    assert remembered == {"text": "답", "thoughtSignature": "뒤늦은서명"}
