"""Claude Code CLI 제공자.

이 컴퓨터에 설치된 claude CLI(Claude Code)를 별도 프로세스로 불러
대화한다. API 키가 없다 — claude CLI가 이미 로그인해 둔 Claude 구독
(Pro/Max)의 사용량으로 그대로 돈다. 대신 다음 두 가지가 미리 되어
있어야 한다.

1. claude CLI 설치와 로그인 (`claude auth login` 또는 터미널에서 한 번
   `claude`를 실행해 로그인).
2. 프로그램 위쪽 "API 인증키" 칸에 국가법령정보 OC 인증키 입력.

법령검색 MCP 설정은 매 요청에 프로그램이 직접 넘긴다. Claude Desktop이나
Claude Code의 사용자 MCP 설정을 고치지 않으며, 인증키도 명령줄에 노출하지
않는다.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
from collections import deque
from collections.abc import Iterator
from pathlib import Path
from typing import IO

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
    write_mcp_config_file,
)

# --mcp-config로 넘기는 서버 이름. 도구 이름이 mcp__<이름>__<도구>로
# 만들어지므로 아래 _TOOL_INSTRUCTION과 --allowedTools가 이 값을 함께 쓴다.
# 사용자의 claude mcp 등록 목록과는 무관하다(--strict-mcp-config로 막는다).
_MCP_SERVER_NAME = "law-search"

# 도구를 찾지 못하는 질문에서 몇 분씩 붙들고 있지 않도록 상한을 둔다.
# 실측으로 도구를 여러 번 쓰는 질문은 2분 넘게 걸리기도 했다.
_TIMEOUT_SECONDS = 300

_TOOL_INSTRUCTION = f"""

도구 이름에는 mcp__{_MCP_SERVER_NAME}__ 접두사가 붙습니다.
예: mcp__{_MCP_SERVER_NAME}__search_law, mcp__{_MCP_SERVER_NAME}__get_article,
mcp__{_MCP_SERVER_NAME}__get_document, mcp__{_MCP_SERVER_NAME}__search_admin_rule,
mcp__{_MCP_SERVER_NAME}__get_annexes, mcp__{_MCP_SERVER_NAME}__legal_research,
mcp__{_MCP_SERVER_NAME}__search_cases, mcp__{_MCP_SERVER_NAME}__get_case,
mcp__{_MCP_SERVER_NAME}__search_inquiries, mcp__{_MCP_SERVER_NAME}__get_inquiry,
mcp__{_MCP_SERVER_NAME}__get_historical_law, mcp__{_MCP_SERVER_NAME}__compare_old_new,
mcp__{_MCP_SERVER_NAME}__ordinance_radar, mcp__{_MCP_SERVER_NAME}__cite_check,
mcp__{_MCP_SERVER_NAME}__impact_map.
이 도구들 밖의 파일ㆍ폴더에는 접근할 수 없으니 시도하지 마십시오.
""" + TOOL_USE_INSTRUCTION


# 도구 이름을 화면에 그대로 내보내면 mcp__law-search__search_law처럼 보인다.
# 무엇을 하는 중인지 사람 말로 바꿔서 보여 준다.
def _drain(stream: IO[str] | None, sink: deque[str]) -> None:
    """stderr를 따로 비워 준다. 안 읽으면 버퍼가 차서 자식이 멎는다."""
    if stream is None:
        return
    for line in stream:
        text = line.rstrip()
        if text:
            sink.append(text)


def _tool_label(block: dict) -> str:
    """도구 호출 하나를 "법령을 검색하는 중: 농지법" 같은 한 줄로 만든다."""
    # claude가 MCP 도구를 실제로 부르기 전에 목록을 먼저 받아 가는
    # 단계가 있다. 그 이름까지 그대로 보이면 어수선하고, 법제처 조회라고
    # 단정할 수도 없다.
    return tool_progress_label(
        block.get("name"), block.get("input"), "도구를 준비하는 중"
    )


def _usage_label(usage: object, turns: object) -> str:
    """다 쓰고 난 사용량을 한 줄로 만든다. 값이 없으면 빈 문자열."""
    if not isinstance(usage, dict):
        return ""
    output = usage.get("output_tokens")
    if not isinstance(output, int):
        return ""
    entered = sum(
        value
        for key in (
            "input_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        )
        if isinstance(value := usage.get(key), int)
    )
    parts = [f"토큰 {entered:,} 넣고 {output:,} 받음"]
    if isinstance(turns, int) and turns > 0:
        parts.append(f"{turns}차례 오감")
    return " · ".join(parts)


class ClaudeCodeChat(ChatSession):
    """claude -p를 --resume으로 이어 붙이는 한 판의 대화."""

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
        self._session_id: str | None = None
        self._touched: tuple[tuple[str, str, str], ...] = ()
        self._process: subprocess.Popen[str] | None = None
        self._process_lock = threading.Lock()

    def touched_documents(self) -> tuple[tuple[str, str, str], ...]:
        return self._touched

    def send(self, message: str) -> Iterator[str | Progress]:
        spec = law_mcp_launch_spec()
        # LAW_API_KEY 값은 자식 환경으로만 넘기고 명령줄에는 남기지 않는다.
        # Claude가 ${LAW_API_KEY}를 MCP 서버 환경으로 확장한다.
        mcp_config_path = write_mcp_config_file(
            {
                "mcpServers": {
                    _MCP_SERVER_NAME: {
                        "command": spec.command,
                        "args": list(spec.args),
                        "cwd": spec.cwd,
                        "env": {
                            "LAW_API_KEY": "${LAW_API_KEY}",
                            **mcp_server_child_env(),
                        },
                    }
                }
            }
        )
        # 줄바꿈이 들어가는 값은 명령줄에 싣지 않는다. Windows에서 claude는
        # 배치 파일(claude.CMD)이라 cmd.exe를 거쳐 실행되는데, cmd는 인자
        # 안의 줄바꿈을 명령의 끝으로 읽는다. 그러면 그 뒤에 붙인
        # --output-format, --model, --resume이 통째로 사라져서 응답이 JSON이
        # 아닌 평문으로 오고, 고른 모델도 이어지던 대화도 무시된다. 실제로
        # 겪은 문제라 시스템 프롬프트는 파일로, 질문은 표준입력으로 넘긴다.
        prompt_file = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            suffix=".txt",
            prefix="law_prompt_",
            delete=False,
        )
        try:
            prompt_file.write(self._system_prompt)
        finally:
            prompt_file.close()

        args = cli_argv("claude") + [
            "-p",
            "--allowedTools",
            f"mcp__{_MCP_SERVER_NAME}__*",
            "--mcp-config",
            mcp_config_path,
            "--strict-mcp-config",
            "--append-system-prompt-file",
            prompt_file.name,
            # 조각으로 받아야 화면이 답을 타자기처럼 풀어 줄 수 있고, 도구를
            # 오가는 동안에도 무엇을 하는 중인지 보여 줄 수 있다. json으로
            # 한 번에 받으면 법령을 여러 번 찾는 질문에서 몇 분 동안 화면에
            # "찾는 중…" 한 줄만 떠 있게 된다.
            "--output-format",
            "stream-json",
            "--include-partial-messages",
            "--verbose",
        ]
        if self._model:
            args += ["--model", self._model]
        if self._session_id:
            args += ["--resume", self._session_id]

        env = clean_child_environment()
        env["LAW_API_KEY"] = self._oc_key
        process = None
        killer: threading.Timer | None = None
        stderr_tail: deque[str] = deque(maxlen=20)
        streamed: list[str] = []
        final_text = ""
        got_result = False
        last_kind = ""
        try:
            try:
                process = subprocess.Popen(
                    args,
                    cwd=str(self._working_dir),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                    bufsize=1,
                    creationflags=no_window_creation_flags(),
                )
            except FileNotFoundError as error:
                raise LlmError(
                    "claude 명령을 찾지 못했습니다. Claude Code CLI를 설치하고 "
                    "터미널에서 claude로 로그인했는지 확인하세요."
                ) from error

            with self._process_lock:
                self._process = process
            threading.Thread(
                target=_drain, args=(process.stderr, stderr_tail), daemon=True
            ).start()
            if process.stdin is not None:
                process.stdin.write(message)
                process.stdin.close()

            # 조각을 하나씩 읽는 동안에는 communicate의 timeout을 쓸 수 없다.
            # 상한을 넘기면 프로세스를 닫아 읽기 루프가 자연히 끝나게 한다.
            timed_out = threading.Event()

            def _stop_waiting() -> None:
                timed_out.set()
                process.kill()

            killer = threading.Timer(_TIMEOUT_SECONDS, _stop_waiting)
            killer.start()

            for line in process.stdout or ():
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                for piece in self._read_event(event):
                    if isinstance(piece, Progress):
                        # 생각 조각은 수백 개가 쏟아진다. 같은 종류가 이어질
                        # 때는 한 번만 알려 화면이 요동치지 않게 한다.
                        if piece.kind == "thinking" and last_kind == "thinking":
                            continue
                        last_kind = piece.kind
                    else:
                        streamed.append(piece)
                        last_kind = ""
                    yield piece
                if event.get("type") == "result":
                    # 여기까지 왔으면 claude가 이번 턴을 제대로 끝냈다는
                    # 뜻이다(오류 결과는 _read_event가 이미 걸러 냈다).
                    got_result = True
                    final_text = str(event.get("result") or "").strip()

            process.wait()
            if timed_out.is_set():
                raise LlmError(
                    f"{_TIMEOUT_SECONDS}초 안에 응답이 오지 않아 중단했습니다. "
                    "질문을 더 구체적으로 줄여서 다시 시도하세요."
                )
            if process.returncode != 0 and not got_result:
                # 답을 다 받은 뒤에 CLI가 뒷정리하다 0이 아닌 값으로 끝나는
                # 일이 있다. 답은 멀쩡히 화면에 있는데 그 밑에 "실행이
                # 실패했습니다"가 붙어 무엇이 잘못됐는지 알 수 없었다.
                # 답을 못 받았을 때만 실패로 다룬다.
                details = " ".join(stderr_tail).strip()[:300]
                if streamed:
                    raise LlmError(
                        with_explanation(
                            "답이 끝나기 전에 claude가 멈췄습니다. 다시 물어보세요."
                            + (f"\n{details}" if details else ""),
                            process.returncode,
                            details,
                        )
                    )
                raise LlmError(
                    with_explanation(
                        "claude 실행이 실패했습니다: "
                        f"{details or f'종료 코드 {process.returncode}'}",
                        process.returncode,
                        details,
                    )
                )
        finally:
            if killer is not None:
                killer.cancel()
            with self._process_lock:
                self._process = None
            # 자식이 다 읽고 끝난 뒤에 지운다.
            try:
                os.unlink(prompt_file.name)
            except OSError:
                pass
            try:
                os.unlink(mcp_config_path)
            except OSError:
                pass

        # 조각으로 흘린 것이 완성본과 어긋날 수 있다. 마지막 결과가 더 길면
        # 모자란 뒤끝만 마저 보내 답이 잘려 보이지 않게 한다.
        shown = "".join(streamed)
        if final_text and final_text != shown.strip():
            if not shown.strip():
                streamed.append(final_text)
                yield final_text
            elif final_text.startswith(shown):
                tail = final_text[len(shown) :]
                streamed.append(tail)
                yield tail

        text = "".join(streamed).strip()
        if not text:
            raise LlmError("답을 만들지 못했습니다. 다시 물어보세요.")
        self._touched = extract_touched_from_citations(text)

    def _read_event(self, event: dict) -> Iterator[str | Progress]:
        """claude가 흘리는 이벤트 하나를 화면에 보일 조각으로 바꾼다."""
        kind = event.get("type")
        if kind == "stream_event":
            inner = event.get("event") or {}
            if inner.get("type") != "content_block_delta":
                return
            delta = inner.get("delta") or {}
            if delta.get("type") == "text_delta":
                text = str(delta.get("text") or "")
                if text:
                    yield text
            elif delta.get("type") == "thinking_delta":
                yield Progress("답을 정리하는 중…", "thinking")
            return

        if kind == "assistant":
            message = event.get("message") or {}
            for block in message.get("content") or ():
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    yield Progress(_tool_label(block), "tool")
            return

        if kind == "system" and event.get("subtype") == "init":
            # 이어 묻기는 이 값으로 붙는다. 중간에 끊겨도 남도록 먼저 잡는다.
            self._session_id = (
                str(event.get("session_id") or "") or self._session_id
            )
            return

        if kind == "result":
            self._session_id = (
                str(event.get("session_id") or "") or self._session_id
            )
            if event.get("is_error"):
                raise LlmError(
                    str(event.get("result") or "claude 요청이 실패했습니다.")
                )
            label = _usage_label(event.get("usage"), event.get("num_turns"))
            if label:
                yield Progress(label, "usage")

    def cancel(self) -> None:
        with self._process_lock:
            process = self._process
        if process is not None and process.poll() is None:
            process.terminate()

    def close(self) -> None:
        self.cancel()


class ClaudeCodeProvider(LlmProvider):
    name = "Claude Code"
    requires_api_key = False
    # claude -p --model에 그대로 넘길 수 있는 별칭.
    fallback_models = (
        ModelInfo("", "기본 모델 (claude CLI 설정값)"),
        ModelInfo("opus", "Opus — 가장 정확, 가장 느림"),
        ModelInfo("sonnet", "Sonnet — 균형"),
        ModelInfo("haiku", "Haiku — 가장 빠름"),
    )

    def __init__(self, api_key: str = "", model_id: str = "") -> None:
        # api_key는 이 제공자에서 쓰지 않는다. 인터페이스를 맞추기 위해
        # 받기만 하고 무시한다.
        super().__init__(api_key, model_id)

    def start_chat(
        self, context: str = "", *, oc_key: str = "", law_cache=None
    ) -> ClaudeCodeChat:
        instruction = SYSTEM_PROMPT + _TOOL_INSTRUCTION
        if context.strip():
            instruction += context_instruction(context)
        working_dir = Path(__file__).resolve().parent.parent
        return ClaudeCodeChat(self.model_id, working_dir, instruction, oc_key)
