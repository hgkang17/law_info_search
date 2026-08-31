"""Gemini 제공자.

무료 한도가 있어서 받는 사람이 카드 없이 키만 받아 쓸 수 있다. 그래서
세 제공자 가운데 이것을 먼저 붙였다.

Claudeㆍ Codex는 이미 깔린 CLI를 띄워 쓰지만 Gemini는 HTTPS API다.
그래서 SDK(google-genai) 없이 gemini_rest.py로 직접 부른다 — 받은
사람이 터미널에서 pip install을 하지 않아도 되고, exe로 묶어 배포해도
그대로 돈다. 대신 도구를 부르고 그 결과를 다시 물어보는 오가기는
여기서 직접 돌린다(예전에는 SDK의 자동 함수 호출이 대신 했다).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator

from .base import (
    SYSTEM_PROMPT,
    TOOL_USE_INSTRUCTION,
    ChatSession,
    LlmError,
    LlmProvider,
    ModelInfo,
    Progress,
    context_instruction,
    tool_progress_label,
)
from .gemini_rest import GeminiApiError, GeminiRestClient, function_declarations
from .tools import MAX_TOOL_CALLS_PER_TURN, build_tools


def _content(role: str, parts: list[dict]) -> dict:
    return {"role": role, "parts": parts}


def _answer_parts(chunk: dict) -> list[dict]:
    """응답 조각 하나에서 실제 내용 조각들만 꺼낸다."""
    candidates = chunk.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return []
    first = candidates[0]
    content = first.get("content") if isinstance(first, dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        return []
    return [part for part in parts if isinstance(part, dict)]


def _finish_reason(chunk: dict) -> str:
    candidates = chunk.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    first = candidates[0]
    return str(first.get("finishReason") or "") if isinstance(first, dict) else ""


def _visible_text(part: dict) -> str:
    """화면에 쌓을 글. 생각 조각은 답이 아니므로 뺀다."""
    if part.get("thought"):
        return ""
    text = part.get("text")
    return text if isinstance(text, str) else ""


def _merge_parts(parts: list[dict]) -> list[dict]:
    """흘러온 조각을 대화 기록에 남길 꼴로 합친다.

    스트리밍은 한 문장도 여러 조각으로 쪼개 보낸다. 그대로 쌓으면
    기록이 조각 수만큼 불어나고, 다음 질문에 그 부피가 그대로 실린다.

    thoughtSignature는 반드시 받은 그대로 돌려줘야 한다. Gemini 3부터는
    도구를 부른 조각에 이 서명이 함께 오고, 도구 결과를 붙여 다시 물을
    때 그것이 빠져 있으면 요청 전체가 거부된다("Function call is missing
    a thought_signature in functionCall parts").
    """
    merged: list[dict] = []
    for part in parts:
        signature = part.get("thoughtSignature")
        call = part.get("functionCall")
        if isinstance(call, dict):
            piece: dict = {"functionCall": call}
            if signature:
                piece["thoughtSignature"] = signature
            merged.append(piece)
            continue
        text = _visible_text(part)
        if not text:
            # 글자는 없고 서명만 실려 오는 조각도 있다. 그 서명은
            # 바로 앞 조각의 것이므로 거기에 붙여 둔다.
            if signature and merged:
                merged[-1].setdefault("thoughtSignature", signature)
            continue
        if merged and isinstance(merged[-1].get("text"), str):
            merged[-1]["text"] += text
        else:
            merged.append({"text": text})
        if signature:
            merged[-1]["thoughtSignature"] = signature
    return merged


def _usage_label(usage: dict) -> str:
    """다 쓰고 난 사용량을 한 줄로 만든다. 값이 없으면 빈 문자열."""
    entered = int(usage.get("promptTokenCount") or 0)
    output = int(usage.get("candidatesTokenCount") or 0)
    total = int(usage.get("totalTokenCount") or 0)
    if not (entered or output or total):
        return ""
    detail = f"토큰 {entered:,} 넣고 {output:,} 받음"
    if total and total != entered + output:
        detail += f" · 총 {total:,}"
    return detail


# Gemini 3은 시키지 않으면 오래 생각한다. 우리 지시문(법령을 함부로
# 지어내지 말고 도구로 확인하라는 긴 글)을 받으면 "안녕"에도 60초 넘게
# 생각만 하다가 답했다 — 실측값이다. 도구를 오가는 질문은 그 한 턴마다
# 그만큼 붙으므로 몇 분이 된다. 낮은 수준에서도 답의 질은 그대로였다.
# 이 값은 Gemini REST 요청에만 실린다. Claudeㆍ Codex는 각자 CLI가
# 자기 방식으로 도니 아무 영향이 없다.
THINKING_LEVEL = "low"


# 답이 한 글자도 안 왔을 때, 왜 그런지 아는 만큼 알려 준다.
_FINISH_REASONS = {
    "SAFETY": "안전 설정에 걸려 답을 만들지 못했습니다. 질문을 바꿔 보세요.",
    "RECITATION": "인용이 너무 길어 답이 막혔습니다. 범위를 좁혀 물어보세요.",
    "MAX_TOKENS": "답이 한도에 걸려 잘렸습니다. 질문을 나누어 물어보세요.",
}


class GeminiChat(ChatSession):
    """법령 본문을 지시문에 깔아 두고 이어 가는 대화.

    본문을 첫 질문에 실어 보내면 두 번째 질문부터는 모델이 본문을 잊는다.
    지시문에 두면 대화 내내 남는다.
    """

    def __init__(
        self,
        client: GeminiRestClient,
        model_id: str,
        instruction: str,
        tools: tuple[Callable, ...] = (),
        on_error: Callable[[Exception], str] = str,
        touched: list[tuple[str, str, str]] | None = None,
        thinking_level: str = THINKING_LEVEL,
    ) -> None:
        self._client = client
        self._model_id = model_id
        self._instruction = instruction
        self._tools = {tool.__name__: tool for tool in tools}
        self._declarations = function_declarations(tools)
        self._on_error = on_error
        self._thinking_level = thinking_level
        # 주고받은 말. 이어 묻기가 되려면 우리가 직접 들고 있어야 한다.
        self._history: list[dict] = []
        # tools.build_tools의 on_document_used 콜백이 여기에 쌓는다.
        # start_chat에서 만든 도구 함수의 클로저와 이 리스트를 공유한다.
        self._touched: list[tuple[str, str, str]] = (
            touched if touched is not None else []
        )
        self._cancelled = False

    def touched_documents(self) -> tuple[tuple[str, str, str], ...]:
        # 나중에 읽은 문서일수록 실제로 답한 내용과 가까우므로 앞에 둔다.
        seen: set[tuple[str, str]] = set()
        result: list[tuple[str, str, str]] = []
        for category, item_id, name in reversed(self._touched):
            key = (category, item_id)
            if key in seen:
                continue
            seen.add(key)
            result.append((category, item_id, name))
        return tuple(result)

    def cancel(self) -> None:
        self._cancelled = True

    def close(self) -> None:
        self._client.close()

    def send(self, message: str) -> Iterator[str | Progress]:
        self._touched.clear()
        self._cancelled = False
        # 멈추면 이 자리까지 걷어 낸다. 도구 결과만 남고 모델의 답이 없는
        # 기록을 들고 다음 질문을 보내면 그 요청이 통째로 거부당한다.
        mark = len(self._history)
        self._history.append(_content("user", [{"text": message}]))
        got_text = False
        usage: dict = {}
        reason = ""
        finished = False
        try:
            # 도구를 부르면 그 결과를 붙여 다시 물어야 한다. 한 질문에
            # 몇 번이고 오갈 수 있으므로 한도를 두고 반복한다.
            for _ in range(MAX_TOOL_CALLS_PER_TURN + 1):
                collected: list[dict] = []
                for chunk in self._stream():
                    if self._cancelled:
                        return
                    chunk_usage = chunk.get("usageMetadata")
                    if isinstance(chunk_usage, dict):
                        usage = chunk_usage
                    reason = _finish_reason(chunk) or reason
                    for part in _answer_parts(chunk):
                        text = _visible_text(part)
                        if text:
                            got_text = True
                            yield text
                        collected.append(part)
                merged = _merge_parts(collected)
                if merged:
                    self._history.append(_content("model", merged))
                calls = [
                    part["functionCall"]
                    for part in merged
                    if isinstance(part.get("functionCall"), dict)
                ]
                if not calls:
                    finished = True
                    break
                answers: list[dict] = []
                for call in calls:
                    if self._cancelled:
                        return
                    name = str(call.get("name") or "")
                    arguments = call.get("args")
                    arguments = arguments if isinstance(arguments, dict) else {}
                    yield Progress(tool_progress_label(name, arguments), "tool")
                    answers.append(self._run_tool(name, arguments))
                self._history.append(_content("user", answers))
        finally:
            if self._cancelled:
                del self._history[mark:]

        if not finished:
            raise LlmError(
                f"법령을 {MAX_TOOL_CALLS_PER_TURN}번 넘게 찾고도 답을 "
                "만들지 못했습니다. 질문을 좁혀 다시 물어보세요."
            )
        if not got_text:
            # 도구를 여러 번 부르고도 답을 못 만들면 예외 없이 조용히
            # 끝난다 — 화면에는 성공한 요청처럼 보이지만 말풍선이 비어
            # 있어서, 실제로 겪어 보니 "멈춘 건지 답하는 중인지" 구분이
            # 안 됐다. 이걸 실패로 취급해 사용자가 알 수 있게 한다.
            raise LlmError(
                _FINISH_REASONS.get(reason)
                or (
                    "검색을 여러 번 시도했지만 답을 만들지 못했습니다. "
                    "법령 이름이나 조문 번호를 더 정확히 넣어 다시 물어보세요."
                )
            )
        detail = _usage_label(usage)
        if detail:
            yield Progress(detail, "usage")

    # ------------------------------------------------------------------ 내부
    def _payload(self) -> dict:
        payload: dict = {
            "contents": self._history,
            "systemInstruction": {"parts": [{"text": self._instruction}]},
        }
        if self._declarations:
            payload["tools"] = [{"functionDeclarations": self._declarations}]
        if self._thinking_level:
            payload["generationConfig"] = {
                "thinkingConfig": {"thinkingLevel": self._thinking_level}
            }
        return payload

    def _stream(self) -> Iterator[dict]:
        for attempt in (0, 1):
            started = False
            try:
                for chunk in self._client.stream(self._model_id, self._payload()):
                    started = True
                    yield chunk
                return
            except GeminiApiError as error:
                # 생각 수준을 못 받는 모델도 있을 수 있다. 아직 아무것도
                # 못 받았을 때만, 그것을 빼고 딱 한 번 다시 보낸다.
                if (
                    attempt == 0
                    and not started
                    and self._thinking_level
                    and "thinking" in str(error).lower()
                ):
                    self._thinking_level = ""
                    continue
                raise LlmError(self._on_error(error)) from error

    def _run_tool(self, name: str, arguments: dict) -> dict:
        """모델이 부른 도구를 실제로 돌리고 그 결과를 답신으로 만든다."""
        tool = self._tools.get(name)
        if tool is None:
            result = f"'{name}' 도구는 없습니다. 주어진 도구만 쓰세요."
        else:
            # build_tools가 이미 예외를 글로 바꿔 돌려주도록 감싸 두었다.
            result = tool(**arguments)
        return {
            "functionResponse": {
                "name": name,
                "response": {"result": result},
            }
        }


class GeminiProvider(LlmProvider):
    name = "Gemini"
    api_key_url = "https://aistudio.google.com/apikey"
    # 고를 수 있는 모델을 이름 그대로 적는다. "최신"처럼 어느 판인지
    # 알 수 없는 별칭은 쓰지 않는다 — 무료 한도가 모델마다 다른데
    # 별칭만 보고는 지금 무엇을 쓰는지도, 얼마나 쓸 수 있는지도 알 수
    # 없다. 여기 적힌 것 가운데 API가 "있다"고 확인해 준 것만 목록에
    # 뜨므로(fetch_models), 구글이 하나를 내리거나 새로 올려도 화면은
    # 조용히 따라간다.
    #
    # 괄호 안 한도는 구글이 수시로 바꾼다. 고를 때 감을 잡는 값이고
    # 정확한 값은 AI Studio의 사용량 화면이 기준이다.
    # 숫자를 고치면 확인한 날짜도 같이 고친다.
    FREE_QUOTA_AS_OF = "2026년 8월 26일"
    FREE_QUOTA_MENU_NOTE = (
        "구글이 무료 사용량 수시로 바꿈. 아래 무료량은 "
        + FREE_QUOTA_AS_OF
        + " 확인완료"
    )
    fallback_models = (
        ModelInfo(
            "gemini-3.1-flash-lite",
            "Gemini 3.1 Flash Lite - 가볍고 저렴함(1분당 15회요청, 분당 25만 토큰, 하루 500회)",
        ),
        ModelInfo(
            "gemini-3.5-flash-lite",
            "Gemini 3.5 Flash Lite - 가장 빠른답변(1분당 15회요청, 분당 25만 토큰, 하루 500회)",
        ),
        ModelInfo(
            "gemini-3.5-flash",
            "Gemini 3.5 Flash - 일상적(1분당 5회요청, 분당 25만 토큰, 하루 20회)",
        ),
        ModelInfo(
            "gemini-3.6-flash",
            "Gemini 3.6 Flash - 일상적(1분당 5회요청, 분당 25만 토큰, 하루 20회)",
        ),
        ModelInfo(
            "gemini-3.7-flash",
            "Gemini 3.7 Flash - 복잡한 문제 해결(1분당 5회요청, 분당 25만 토큰, 하루 20회)",
        ),
        ModelInfo(
            "gemini-3.1-pro",
            "Gemini 3.1 Pro - 고급추론(무료제공 X)",
        ),
    )

    # 글을 주고받는 용도가 아닌 모델은 목록에서 뺀다. 그림ㆍ음성ㆍ로봇용이
    # 섞이면 고르기만 어려워진다.
    _EXCLUDED_KEYWORDS = (
        "image",
        "tts",
        "audio",
        "robotics",
        "computer-use",
        "embedding",
        "lyria",
        "nano-banana",
        "veo",
        "imagen",
        "gemma",
    )
    # 법령 본문은 길다. 입력 한도가 작은 모델은 조문 몇 개도 못 받는다.
    _MIN_INPUT_TOKENS = 200_000

    def fetch_models(self) -> tuple[ModelInfo, ...]:
        """지금 이 키로 쓸 수 있는 모델을 Google에 직접 물어본다."""
        client = None
        try:
            client = self._client()
            available: set[str] = set()
            for model in client.list_models():
                info = self._model_info(model)
                if info is not None:
                    available.add(info[1].model_id)
            # 우리가 적어 둔 것 가운데 실제로 쓸 수 있는 것만 남긴다.
            # 하나도 확인되지 않으면(조회가 막혔거나 이름이 다 바뀌었으면)
            # 적어 둔 목록을 그대로 보인다 — 목록이 비면 아무것도 못 한다.
            selected = tuple(
                model
                for model in self.fallback_models
                if model.model_id in available
            )
            return selected or self.fallback_models
        except Exception:
            # 조회가 막혀도 화면은 떠야 한다. 별칭만으로도 대화는 된다.
            return self.fallback_models
        finally:
            if client is not None:
                client.close()

    def fetch_validated_models(self) -> tuple[ModelInfo, ...]:
        """키 검증과 모델 목록 갱신을 같은 API 응답으로 끝낸다."""
        client = self._client()
        try:
            available: set[str] = set()
            for model in client.list_models():
                info = self._model_info(model)
                if info is not None:
                    available.add(info[1].model_id)
            selected = tuple(
                model
                for model in self.fallback_models
                if model.model_id in available
            )
            return selected or self.fallback_models
        except GeminiApiError as error:
            raise LlmError(self._readable(error)) from error
        finally:
            client.close()

    def validate_api_key(self) -> None:
        """모델 목록 조회로 키를 인증한다. 생성 요청은 소비하지 않는다."""
        client = self._client()
        try:
            client.list_models()
        except GeminiApiError as error:
            raise LlmError(self._readable(error)) from error
        finally:
            client.close()

    def _model_info(self, model: dict) -> tuple[float, ModelInfo] | None:
        name = str(model.get("name") or "").replace("models/", "")
        if not name or not name.startswith("gemini"):
            return None
        lowered = name.lower()
        if any(word in lowered for word in self._EXCLUDED_KEYWORDS):
            return None
        actions = model.get("supportedGenerationMethods") or []
        if actions and "generateContent" not in actions:
            return None
        try:
            limit = int(model.get("inputTokenLimit") or 0)
        except (TypeError, ValueError):
            limit = 0
        if limit and limit < self._MIN_INPUT_TOKENS:
            return None

        display = str(model.get("displayName") or name)
        # 정렬용 세대 번호. "gemini-3.7-flash" → 3.7
        generation = 0.0
        match = re.search(r"gemini-(\d+(?:\.\d+)?)", lowered)
        if match:
            generation = float(match.group(1))
        elif lowered.endswith("-latest"):
            # 별칭은 항상 최신이므로 맨 위에 둔다.
            generation = 999.0
        return generation, ModelInfo(name, display)

    def _client(self) -> GeminiRestClient:
        if not self.api_key.strip():
            raise LlmError("API 키를 먼저 입력하세요.")
        return GeminiRestClient(self.api_key.strip())

    def _contents(self, context: str, question: str) -> str:
        # 본문과 질문의 경계를 뚜렷이 해서, 본문 안의 문장이 지시로 읽히지
        # 않게 한다. 법령 본문에는 "~하여야 한다" 같은 명령문이 많다.
        return (
            "다음은 검토 대상 법령 본문입니다.\n"
            "<법령본문>\n"
            f"{context.strip()}\n"
            "</법령본문>\n\n"
            "위 본문에 근거해 아래 질문에 답하십시오.\n"
            "<질문>\n"
            f"{question.strip()}\n"
            "</질문>"
        )

    def stream_answer(self, context: str, question: str) -> Iterator[str]:
        client = self._client()
        payload = {
            "contents": [
                _content("user", [{"text": self._contents(context, question)}])
            ],
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "generationConfig": {
                "thinkingConfig": {"thinkingLevel": THINKING_LEVEL}
            },
        }
        try:
            for chunk in client.stream(self.model_id, payload):
                for part in _answer_parts(chunk):
                    text = _visible_text(part)
                    if text:
                        yield text
        except GeminiApiError as error:
            raise LlmError(self._readable(error)) from error
        finally:
            client.close()

    def start_chat(
        self, context: str = "", *, oc_key: str = "", law_cache=None
    ) -> GeminiChat:
        if not str(self.model_id or "").strip():
            raise LlmError("쓸 모델을 먼저 고르세요.")
        instruction = SYSTEM_PROMPT
        if context.strip():
            # 본문의 명령문("~하여야 한다")이 지시로 읽히지 않도록 태그로
            # 감싼다. 열어 둔 본문만 보고 하위법령을 놓치지 않게 한다.
            instruction += context_instruction(context)

        tools: tuple[Callable, ...] = ()
        touched: list[tuple[str, str, str]] = []
        if oc_key.strip():
            instruction += TOOL_USE_INSTRUCTION
            tools = build_tools(
                oc_key.strip(),
                on_document_used=lambda category, item_id, name: touched.append(
                    (category, item_id, name)
                ),
                law_cache=law_cache,
            )
        return GeminiChat(
            self._client(),
            self.model_id,
            instruction,
            tools,
            self._readable,
            touched,
        )

    def count_tokens(self, context: str, question: str) -> int:
        client = self._client()
        try:
            return client.count_tokens(
                self.model_id,
                [_content("user", [{"text": self._contents(context, question)}])],
            )
        except GeminiApiError as error:
            raise LlmError(self._readable(error)) from error
        finally:
            client.close()

    @staticmethod
    def _readable(error: Exception) -> str:
        """실패를 사용자가 무엇을 해야 하는지 아는 문구로 바꾼다.

        Google이 돌려주는 사유는 모두 영어다. 그대로 상태줄에 찍으면
        읽는 사람은 자기가 뭘 해야 하는지 알 수 없다. 실제로 겪은 것부터
        하나씩 우리말로 정해 두고, 아직 모르는 것만 원문을 붙인다.
        """
        text = str(error)
        lowered = text.lower()

        def has(*words: str) -> bool:
            return any(word in lowered for word in words)

        if has("thought_signature", "thoughtsignature"):
            # 도구 호출에 딸려 온 서명을 되돌려 보내지 않으면 난다.
            # 프로그램이 고쳐야 할 몫이지 사용자가 할 일이 아니다.
            return (
                "도구를 부르는 중에 프로그램 쪽 문제로 요청이 거부됐습니다. "
                "다시 물어보고, 계속 그러면 알려 주세요."
            )
        if has("not_found", "404", "is not found for api version"):
            # 모델 이름은 제공자가 예고 없이 갈아 치운다. 사용자가 스스로
            # 고칠 수 있도록 무엇을 누르면 되는지 알려 준다.
            return (
                "이 모델은 지금 쓸 수 없습니다. 제공자가 모델을 바꾼 것이니 "
                "[갱신]을 눌러 쓸 수 있는 모델을 다시 받아 오세요."
            )
        if has("api key not valid", "api_key_invalid", "invalid api key"):
            return "API 키가 올바르지 않습니다. 키를 다시 확인하세요."
        if has("401", "403", "permission_denied", "unauthenticated"):
            return (
                "이 키로는 이 모델을 쓸 수 없습니다. AI Studio에서 키와 "
                "프로젝트 설정을 확인하세요."
            )
        if has("quota", "resource_exhausted", "429", "rate limit"):
            return (
                "무료 한도를 넘었습니다. 잠시 뒤에 다시 시도하거나 "
                "한도가 더 넉넉한 모델(Flash Lite)로 바꿔 보세요."
            )
        if has("failed_precondition", "billing", "not available in your country"):
            return (
                "이 지역이나 이 계정에서는 무료로 쓸 수 없는 모델입니다. "
                "다른 모델을 골라 보세요."
            )
        if has(
            "exceeds the maximum number of tokens",
            "input token count",
            "too many tokens",
            "request payload size",
            "413",
        ):
            return (
                "보낸 본문이 이 모델이 받을 수 있는 양을 넘었습니다. "
                "본문을 줄이거나 조문을 나누어 물어보세요."
            )
        if has("unavailable", "503", "overloaded"):
            # 우리 쪽 잘못이 아니라 제공자가 붐비는 것이다. 사용자가
            # 키나 본문을 의심하며 헤매지 않도록 그대로 알려 준다.
            return (
                "지금 이 모델에 사람이 몰려 잠시 응답하지 못합니다. "
                "잠시 뒤 다시 보내거나 다른 모델을 골라 보세요."
            )
        if has("internal", "500"):
            return (
                "구글 쪽에서 일시적인 오류가 났습니다. 잠시 뒤 다시 "
                "보내 보세요."
            )
        if has("deadline", "timeout", "timed out"):
            return "응답이 너무 늦어 끊겼습니다. 본문을 줄여서 다시 시도하세요."
        if "연결하지 못했습니다" in text:
            return (
                "인터넷에 연결하지 못했습니다. 연결 상태를 확인하고 다시 "
                "보내 보세요."
            )
        if has("invalid_argument", "400"):
            # 여기까지 왔으면 우리가 아직 우리말로 정해 두지 않은
            # 형식 오류다. 무엇인지 알 수 있게 원문을 함께 남긴다.
            return f"요청 형식이 잘못돼 거부됐습니다.\n\n원문: {text}"
        return f"요청이 실패했습니다.\n\n원문: {text}"
