"""ChatGPT 로그인으로 동작하는 Codex app-server 제공자.

Codex 데스크톱/CLI가 쓰는 공식 app-server JSONL 프로토콜을 사용한다.
API 키를 받지 않고 이 컴퓨터의 Codex 로그인과 ChatGPT 요금제 사용량을
그대로 쓴다. 법령검색 MCP 서버는 전역 설정을 바꾸지 않고 이 대화에만
주입한다.
"""

from __future__ import annotations

import json
import subprocess
import threading
from collections import deque
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .cli_errors import with_explanation
from .base import (
    SYSTEM_PROMPT,
    TOOL_USE_INSTRUCTION,
    ChatSession,
    LlmError,
    LlmProvider,
    ModelInfo,
    Progress,
    context_instruction,
    extract_touched_from_citations,
    tool_progress_label,
)
from .desktop_mcp import (
    clean_child_environment,
    cli_argv,
    law_mcp_launch_spec,
    mcp_server_child_env,
    no_window_creation_flags,
)

_MCP_SERVER_NAME = "law-search"

_TOOL_INSTRUCTION = f"""

도구 이름에는 mcp__{_MCP_SERVER_NAME}__ 접두사가 붙을 수 있습니다.
`search_law`, `get_article`, `get_document`, `search_admin_rule`,
`get_annexes`, `legal_research`, `search_cases`, `get_case`,
`search_inquiries`, `get_inquiry`,
`get_historical_law`, `compare_old_new`, `ordinance_radar`,
`cite_check`, `impact_map`로 대한민국
법제처 국가법령정보를 직접 찾고 읽을 수 있습니다.

이 대화는 법령 검토용 읽기 전용 대화입니다. 파일을 만들거나 고치거나
명령을 실행하지 마십시오. 제공된 본문과 법령검색 MCP 도구만 사용하십시오.

웹 검색으로 법령을 찾지 마십시오. 법제처 원문을 그대로 읽는 위 도구가
정본이며, 웹 문서는 개정 전 내용이거나 요약본일 수 있습니다. law.go.kr
주소를 답변에 붙이지 말고 `law:법령ID:조번호` 링크 형식을 쓰십시오.
그래야 사용자가 프로그램 안에서 원문을 바로 열 수 있습니다.
""" + TOOL_USE_INSTRUCTION


def _item_progress(item: object) -> Progress | None:
    """Codex가 시작한 작업 하나를 화면에 보일 진행 문구로 바꾼다."""
    if not isinstance(item, dict):
        return None
    kind = str(item.get("type") or "")
    if kind == "reasoning":
        return Progress("답을 정리하는 중…", "thinking")
    if kind == "webSearch":
        # web_search를 꺼 두었지만 설정이 바뀌면 다시 나올 수 있다.
        # 법제처 조회와 섞이면 안 되므로 출처를 따로 적는다.
        return Progress(tool_progress_label("webSearch", {}), "tool")
    if kind not in ("mcpToolCall", "toolCall", "functionCall"):
        return None
    name = str(item.get("tool") or item.get("name") or "")
    arguments = item.get("arguments") or item.get("input")
    return Progress(tool_progress_label(name, arguments), "tool")


def _codex_usage_label(usage: object) -> str:
    """Codex가 알려 주는 사용량을 한 줄로 만든다."""
    if not isinstance(usage, dict):
        return ""
    total = usage.get("total")
    if not isinstance(total, dict):
        return ""
    entered = total.get("inputTokens")
    produced = total.get("outputTokens")
    if not isinstance(entered, int) or not isinstance(produced, int):
        return ""
    return f"토큰 {entered:,} 넣고 {produced:,} 받음"


class CodexConnectionLost(LlmError):
    """app-server 프로세스가 사라져 이번 대화를 이어 갈 수 없다.

    다른 실패와 나눠 두어야 한다. 이 경우에만 새로 연결해 다시 물어볼 수
    있고, 인증ㆍ한도 같은 실패는 다시 물어도 똑같이 실패하기 때문이다.
    """


class CodexAppServerChat(ChatSession):
    """하나의 app-server 프로세스와 thread를 유지하는 대화."""

    def __init__(
        self,
        model: str,
        working_dir: Path,
        system_prompt: str,
        oc_key: str,
    ) -> None:
        self._model = model
        self._working_dir = working_dir
        self._system_prompt = system_prompt
        self._oc_key = oc_key
        self._process: subprocess.Popen[str] | None = None
        self._request_id = 0
        self._thread_id: str | None = None
        self._active_turn_id: str | None = None
        self._pending: deque[dict[str, Any]] = deque()
        self._stderr_tail: deque[str] = deque(maxlen=20)
        self._write_lock = threading.Lock()
        self._touched: tuple[tuple[str, str, str], ...] = ()

    def touched_documents(self) -> tuple[tuple[str, str, str], ...]:
        return self._touched

    def _spawn_process(self) -> subprocess.Popen[str]:
        env = clean_child_environment()
        # Codex의 env_vars 설정으로만 MCP 자식에게 전달한다. thread 설정이나
        # 명령줄에 인증키 값을 직접 넣지 않는다.
        env["LAW_API_KEY"] = self._oc_key
        env.update(mcp_server_child_env())
        argv = cli_argv("codex") + ["app-server"]
        try:
            return subprocess.Popen(
                argv,
                cwd=str(self._working_dir),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
                creationflags=no_window_creation_flags(),
            )
        except FileNotFoundError as error:
            raise LlmError(
                "codex 명령을 찾지 못했습니다. ChatGPT/Codex 데스크톱 앱이나 "
                "Codex CLI를 설치하고 로그인한 뒤 다시 시도하세요."
            ) from error

    def _collect_stderr(self, process: subprocess.Popen[str]) -> None:
        if process.stderr is None:
            return
        for line in process.stderr:
            self._stderr_tail.append(line.rstrip())

    def _ensure_started(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        self._pending.clear()
        self._stderr_tail.clear()
        self._thread_id = None
        self._process = self._spawn_process()
        threading.Thread(
            target=self._collect_stderr,
            args=(self._process,),
            daemon=True,
        ).start()

        self._request(
            "initialize",
            {
                "clientInfo": {
                    "name": "central_law_search",
                    "title": "국가법령정보 통합검색",
                    "version": "1.0",
                }
            },
        )
        self._notify("initialized", {})

        spec = law_mcp_launch_spec()
        params: dict[str, Any] = {
            "cwd": str(self._working_dir),
            "ephemeral": False,
            "approvalPolicy": "never",
            "sandbox": "read-only",
            "developerInstructions": self._system_prompt,
            "config": {
                # 웹 검색을 열어 두면 법령검색 도구를 놔두고 그쪽으로 답한다.
                # 실측으로 "농지법 제1조" 질문에 law-search가 ready였는데도
                # webSearch만 쓰고 law.go.kr 링크를 붙여 답했다. 그러면 조문
                # 링크 형식이 깨져 팝업도 즐겨찾기도 걸리지 않는다.
                "tools": {"web_search": False},
                "mcp_servers": {
                    _MCP_SERVER_NAME: {
                        "command": spec.command,
                        "args": list(spec.args),
                        "cwd": spec.cwd,
                        "env_vars": [
                            "LAW_API_KEY",
                            "PYINSTALLER_RESET_ENVIRONMENT",
                        ],
                        "required": True,
                        "enabled_tools": [
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
                        ],
                        "default_tools_approval_mode": "approve",
                    }
                }
            },
        }
        if self._model:
            params["model"] = self._model
        result = self._request("thread/start", params)
        thread = result.get("thread") if isinstance(result, dict) else None
        thread_id = thread.get("id") if isinstance(thread, dict) else None
        if not thread_id:
            self.close()
            raise LlmError("Codex가 새 대화 ID를 돌려주지 않았습니다.")
        self._thread_id = str(thread_id)

    def _write(self, payload: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None or process.poll() is not None:
            raise CodexConnectionLost(
                self._process_error("Codex 연결이 종료되었습니다.")
            )
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        try:
            with self._write_lock:
                process.stdin.write(line + "\n")
                process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise CodexConnectionLost(
                self._process_error("Codex에 메시지를 보내지 못했습니다.")
            ) from error

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"method": method, "params": params})

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _read_message(self) -> dict[str, Any]:
        process = self._process
        if process is None or process.stdout is None:
            raise LlmError("Codex 연결이 열리지 않았습니다.")
        while True:
            line = process.stdout.readline()
            if not line:
                raise CodexConnectionLost(
                    self._process_error("Codex 연결이 예기치 않게 끝났습니다.")
                )
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict):
                return message

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id()
        self._write({"method": method, "id": request_id, "params": params})
        while True:
            message = self._read_message()
            if message.get("id") == request_id and "method" not in message:
                error = message.get("error")
                if isinstance(error, dict):
                    raise LlmError(str(error.get("message") or "Codex 요청이 실패했습니다."))
                result = message.get("result")
                return result if isinstance(result, dict) else {}
            if "id" in message and "method" in message:
                self._deny_server_request(message)
            else:
                self._pending.append(message)

    def _deny_server_request(self, message: dict[str, Any]) -> None:
        """읽기 전용 채팅에서 들어온 실행·수정 승인을 안전하게 거절한다."""
        method = str(message.get("method") or "")
        request_id = message.get("id")
        if method in {
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval",
        }:
            result: dict[str, Any] = {"decision": "decline"}
        elif method in {"execCommandApproval", "applyPatchApproval"}:
            result = {"decision": "abort"}
        elif method == "item/permissions/requestApproval":
            result = {"permissions": {}}
        elif method == "mcpServer/elicitation/request":
            result = {"action": "decline", "content": None}
        else:
            self._write(
                {
                    "id": request_id,
                    "error": {"code": -32601, "message": "지원하지 않는 요청입니다."},
                }
            )
            return
        self._write({"id": request_id, "result": result})

    def _process_error(self, message: str) -> str:
        details = chr(10).join(line for line in self._stderr_tail if line).strip()
        process = self._process
        returncode = process.returncode if process is not None else None
        if details:
            return with_explanation(
                f"{message} {details[-500:]}", returncode, details
            )
        return with_explanation(message, returncode, details)

    @staticmethod
    def _completed_message(message: dict[str, Any]) -> str:
        params = message.get("params")
        item = params.get("item") if isinstance(params, dict) else None
        if isinstance(item, dict) and item.get("type") == "agentMessage":
            return str(item.get("text") or "")
        return ""

    def send(self, message: str) -> Iterator[str | Progress]:
        """한 번 물어본다. 연결이 끊겨 있으면 새로 열어 한 번만 다시 묻는다.

        app-server는 대화를 쉬는 동안에도 사라질 수 있다. 다른 AI 탭을
        보다가 돌아와 물으면 그 자리에서 "연결이 예기치 않게 끝났습니다"만
        나와, 사용자는 같은 질문을 손으로 다시 넣어야 했다.

        답 글자가 한 자라도 나온 뒤에 끊긴 것은 다시 묻지 않는다. 화면에
        같은 답이 두 번 쌓이기 때문이다.
        """
        produced: list[bool] = [False]
        try:
            yield from self._run_turn(message, produced)
            return
        except CodexConnectionLost:
            if produced[0]:
                raise
        # 남은 파이프와 프로세스를 확실히 정리한 뒤 새로 연다.
        self.close()
        yield Progress("Codex 연결이 끊겨 다시 연결하는 중…", "tool")
        yield from self._run_turn(message, produced)

    def _run_turn(
        self, message: str, produced: list[bool]
    ) -> Iterator[str | Progress]:
        self._ensure_started()
        if not self._thread_id:
            raise LlmError("Codex 대화가 시작되지 않았습니다.")

        result = self._request(
            "turn/start",
            {
                "threadId": self._thread_id,
                "input": [{"type": "text", "text": message}],
            },
        )
        turn = result.get("turn") if isinstance(result, dict) else None
        self._active_turn_id = str(turn.get("id") or "") if isinstance(turn, dict) else None
        if not self._active_turn_id:
            raise LlmError("Codex가 응답 작업 ID를 돌려주지 않았습니다.")
        full_text = ""
        completed_text = ""

        try:
            while True:
                if self._pending:
                    event = self._pending.popleft()
                else:
                    event = self._read_message()

                if "id" in event and "method" in event:
                    self._deny_server_request(event)
                    continue
                method = event.get("method")
                params = event.get("params")
                params = params if isinstance(params, dict) else {}
                event_turn_id = params.get("turnId")
                if method == "turn/completed":
                    event_turn = params.get("turn")
                    if isinstance(event_turn, dict):
                        event_turn_id = event_turn.get("id")
                if event_turn_id and str(event_turn_id) != self._active_turn_id:
                    continue
                if method == "item/agentMessage/delta":
                    delta = str(params.get("delta") or "")
                    if delta:
                        full_text += delta
                        produced[0] = True
                        yield delta
                elif method == "item/started":
                    started = _item_progress(params.get("item"))
                    if started is not None:
                        yield started
                elif method == "thread/tokenUsage/updated":
                    usage_label = _codex_usage_label(params.get("tokenUsage"))
                    if usage_label:
                        yield Progress(usage_label, "usage")
                elif method == "item/completed":
                    text = self._completed_message(event)
                    if text:
                        completed_text = text
                elif method == "turn/completed":
                    turn_data = params.get("turn")
                    turn_data = turn_data if isinstance(turn_data, dict) else {}
                    status = str(turn_data.get("status") or "")
                    if status == "failed":
                        error = turn_data.get("error")
                        detail = error.get("message") if isinstance(error, dict) else ""
                        raise LlmError(str(detail or "Codex가 답변을 만들지 못했습니다."))
                    if status == "interrupted":
                        return
                    break
        finally:
            self._active_turn_id = None

        if not full_text and completed_text:
            full_text = completed_text
            produced[0] = True
            yield completed_text
        if not full_text.strip():
            raise LlmError("Codex가 빈 답변을 돌려주었습니다.")
        self._touched = extract_touched_from_citations(full_text)

    def cancel(self) -> None:
        # stdout을 읽는 작업 스레드와 별개로 안전하게 즉시 빠져나오게 하려면
        # 프로세스를 닫는 편이 확실하다. 다음 send()가 새 연결을 만든다.
        self.close()

    def close(self) -> None:
        process = self._process
        self._process = None
        self._thread_id = None
        self._active_turn_id = None
        self._pending.clear()
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()


class CodexAppServerProvider(LlmProvider):
    name = "ChatGPT (Codex)"
    requires_api_key = False
    fallback_models = (
        ModelInfo("", "기본 모델 (Codex 설정값)"),
        ModelInfo("gpt-5.6-sol", "GPT-5.6 Sol — 가장 어려운 검토"),
        ModelInfo("gpt-5.6-terra", "GPT-5.6 Terra — 균형"),
        ModelInfo("gpt-5.6-luna", "GPT-5.6 Luna — 빠른 검토"),
    )

    def __init__(self, api_key: str = "", model_id: str = "") -> None:
        super().__init__(api_key, model_id)

    def start_chat(
        self, context: str = "", *, oc_key: str = "", law_cache=None
    ) -> CodexAppServerChat:
        instruction = SYSTEM_PROMPT + _TOOL_INSTRUCTION
        if context.strip():
            instruction += context_instruction(context)
        return CodexAppServerChat(
            self.model_id,
            Path(__file__).resolve().parent.parent,
            instruction,
            oc_key,
        )
