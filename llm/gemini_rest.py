"""SDK 없이 부르는 Gemini REST 호출.

Gemini는 Claudeㆍ Codex와 달리 CLI가 아니라 그냥 HTTPS API다. 그런데도
예전에는 google-genai SDK를 거쳤다. 그러면 이 프로그램을 받은 사람이
터미널에서 pip install을 먼저 해야 하고, exe로 묶어 배포하면 SDK가
안 들어가서 아예 못 쓴다(실제로 "google-genai 패키지가 없습니다"만
떴다). 법제처 API를 부를 때 이미 쓰는 requests로 직접 부르면 그런
준비가 필요 없다.

여기에는 HTTP를 주고받는 부분과, 파이썬 함수를 Gemini가 읽는 함수
선언으로 바꾸는 부분만 둔다. 대화를 어떻게 이어 갈지는 gemini.py가
정한다.
"""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Callable, Iterator

import requests

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

# 법령 본문을 통째로 넣고 답을 받는 데는 몇 분이 걸리기도 한다. 연결이
# 안 되는 것은 빨리 알려 주고, 답을 기다리는 시간은 넉넉히 준다.
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 300


class GeminiApiError(RuntimeError):
    """Gemini가 돌려준 실패.

    화면에 보일 문구로 바꾸는 일은 부르는 쪽(GeminiProvider._readable)이
    한다. 여기서는 상태 코드와 원문을 그대로 실어 보내, 그쪽이 404ㆍ429
    같은 것을 알아볼 수 있게 한다.
    """


def _error_message(response: requests.Response) -> str:
    """실패 응답에서 상태 코드와 사유를 한 줄로 뽑는다."""
    detail = ""
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            detail = " ".join(
                str(error.get(key) or "").strip()
                for key in ("status", "message")
                if error.get(key)
            )
    if not detail:
        detail = (response.text or "").strip()[:500]
    return f"[{response.status_code}] {detail}".strip()


class GeminiRestClient:
    """Gemini REST 끝점 하나하나를 감싼 얇은 층."""

    def __init__(self, api_key: str) -> None:
        self._session = requests.Session()
        # 키를 주소에 붙이면 오류 문구나 기록에 그대로 남는다. 헤더로 넣는다.
        self._session.headers.update(
            {
                "x-goog-api-key": api_key,
                "Content-Type": "application/json",
            }
        )

    def close(self) -> None:
        self._session.close()

    # ------------------------------------------------------------------ 조회
    def list_models(self) -> list[dict]:
        """이 키로 쓸 수 있는 모델을 모두 받아 온다."""
        models: list[dict] = []
        page_token = ""
        while True:
            params = {"pageSize": 200}
            if page_token:
                params["pageToken"] = page_token
            payload = self._request("GET", "/models", params=params)
            found = payload.get("models")
            if isinstance(found, list):
                models.extend(item for item in found if isinstance(item, dict))
            page_token = str(payload.get("nextPageToken") or "")
            if not page_token:
                return models

    def count_tokens(self, model: str, contents: list[dict]) -> int:
        payload = self._request(
            "POST",
            f"/models/{model}:countTokens",
            json={"contents": contents},
        )
        return int(payload.get("totalTokens") or 0)

    # ------------------------------------------------------------------ 생성
    def stream(self, model: str, payload: dict) -> Iterator[dict]:
        """답을 조각으로 받는다. SSE 한 줄이 곧 응답 조각 하나다."""
        url = f"{BASE_URL}/models/{model}:streamGenerateContent"
        try:
            with self._session.post(
                url,
                params={"alt": "sse"},
                json=payload,
                stream=True,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            ) as response:
                if response.status_code >= 400:
                    raise GeminiApiError(_error_message(response))
                # 헤더에 charset이 없으면 requests가 서유럽 문자로 읽어
                # 한글이 깨진다. 이 API는 언제나 UTF-8이다.
                response.encoding = "utf-8"
                for line in response.iter_lines(decode_unicode=True):
                    if not line or not line.startswith("data:"):
                        continue
                    body = line[len("data:") :].strip()
                    if not body or body == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(body)
                    except ValueError:
                        continue
                    if isinstance(chunk, dict):
                        yield chunk
        except requests.RequestException as error:
            raise GeminiApiError(f"연결하지 못했습니다: {error}") from error

    # ------------------------------------------------------------------ 공통
    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = self._session.request(
                method,
                f"{BASE_URL}{path}",
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                **kwargs,
            )
        except requests.RequestException as error:
            raise GeminiApiError(f"연결하지 못했습니다: {error}") from error
        if response.status_code >= 400:
            raise GeminiApiError(_error_message(response))
        try:
            payload = response.json()
        except ValueError as error:
            raise GeminiApiError("응답을 읽지 못했습니다.") from error
        return payload if isinstance(payload, dict) else {}


# ------------------------------------------------------------------ 함수 선언
# 파이썬 타입을 Gemini 스키마 타입으로. future import를 쓴 파일에서 온
# 함수는 힌트가 문자열이므로 이름으로도 찾을 수 있게 해 둔다.
_SCHEMA_TYPES = {
    "str": "STRING",
    "int": "INTEGER",
    "float": "NUMBER",
    "bool": "BOOLEAN",
}
_ARG_PATTERN = re.compile(r"^(\w+)\s*:\s*(.*)$")


def function_declarations(tools: tuple[Callable, ...]) -> list[dict]:
    """도구 함수들을 Gemini가 읽는 함수 선언 목록으로 바꾼다.

    예전에는 SDK가 함수의 시그니처와 독스트링을 읽어 이 일을 대신
    해 주었다. 하는 일은 같으므로 도구 쪽은 손대지 않는다 — 함수와
    설명은 한 군데(tools.py)에만 두고, 여기서는 읽기만 한다.
    """
    return [_declaration(tool) for tool in tools]


def _declaration(tool: Callable) -> dict:
    summary, arg_docs = _split_doc(inspect.getdoc(tool) or "")
    properties: dict[str, dict] = {}
    required: list[str] = []
    for name, parameter in inspect.signature(tool).parameters.items():
        if parameter.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        schema = {"type": _schema_type(parameter.annotation)}
        if arg_docs.get(name):
            schema["description"] = arg_docs[name]
        properties[name] = schema
        if parameter.default is inspect.Parameter.empty:
            required.append(name)
    declaration: dict = {"name": tool.__name__, "description": summary}
    if properties:
        declaration["parameters"] = {
            "type": "OBJECT",
            "properties": properties,
            "required": required,
        }
    return declaration


def _schema_type(annotation: object) -> str:
    name = getattr(annotation, "__name__", None) or str(annotation)
    return _SCHEMA_TYPES.get(name, "STRING")


def _split_doc(doc: str) -> tuple[str, dict[str, str]]:
    """독스트링을 설명과 인자 설명으로 가른다(Google 방식 Args:)."""
    lines = doc.splitlines()
    try:
        start = next(
            index
            for index, line in enumerate(lines)
            if line.strip() == "Args:"
        )
    except StopIteration:
        return doc.strip(), {}

    summary = "\n".join(lines[:start]).strip()
    arg_docs: dict[str, str] = {}
    current = ""
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip())
        match = _ARG_PATTERN.match(stripped) if indent <= 4 else None
        if match:
            current = match.group(1)
            arg_docs[current] = match.group(2).strip()
        elif current:
            # 여러 줄로 이어지는 설명. 한 줄로 붙인다.
            arg_docs[current] = f"{arg_docs[current]} {stripped}".strip()
    return summary, arg_docs
