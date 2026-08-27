"""Claude Code와 Codex 데스크톱 연계의 로컬 프로토콜 회귀 테스트."""

from __future__ import annotations

import json
import subprocess
import sys
from collections import deque
from pathlib import Path

from llm import PROVIDERS, CodexAppServerProvider, Progress
from llm.claude_code import ClaudeCodeChat
from llm.codex_app_server import CodexAppServerChat
from llm.desktop_mcp import clean_child_environment, cli_argv, law_mcp_launch_spec


class _FakeStdout:
    def __init__(self, lines: deque[str]) -> None:
        self.lines = lines

    def readline(self) -> str:
        return self.lines.popleft() if self.lines else ""


class _FakeStdin:
    def __init__(self, process: _FakeCodexProcess) -> None:
        self.process = process
        self.buffer = ""

    def write(self, text: str) -> int:
        self.buffer += text
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line:
                self.process.receive(json.loads(line))
        return len(text)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


class _FakeCodexProcess:
    def __init__(self) -> None:
        self.lines: deque[str] = deque()
        self.stdout = _FakeStdout(self.lines)
        self.stdin = _FakeStdin(self)
        self.stderr: list[str] = []
        self.returncode: int | None = None
        self.requests: list[dict] = []
        self.turn_count = 0

    def queue(self, payload: dict) -> None:
        self.lines.append(json.dumps(payload, ensure_ascii=False) + "\n")

    def receive(self, payload: dict) -> None:
        self.requests.append(payload)
        method = payload.get("method")
        request_id = payload.get("id")
        if method == "initialize":
            self.queue({"id": request_id, "result": {"platformFamily": "windows"}})
        elif method == "thread/start":
            self.queue({"id": request_id, "result": {"thread": {"id": "thr-law"}}})
        elif method == "turn/start":
            self.turn_count += 1
            turn_id = f"turn-{self.turn_count}"
            self.queue({"id": request_id, "result": {"turn": {"id": turn_id}}})
            self.queue(
                {
                    "method": "item/agentMessage/delta",
                    "params": {"delta": "결론", "turnId": turn_id},
                }
            )
            self.queue(
                {
                    "method": "item/agentMessage/delta",
                    "params": {"delta": "입니다.", "turnId": turn_id},
                }
            )
            self.queue(
                {
                    "method": "item/completed",
                    "params": {
                        "item": {
                            "type": "agentMessage",
                            "id": "item-1",
                            "text": "결론입니다.",
                        }
                    },
                }
            )
            self.queue(
                {
                    "method": "turn/completed",
                    "params": {"turn": {"id": turn_id, "status": "completed"}},
                }
            )

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        self.returncode = self.returncode if self.returncode is not None else 0
        return self.returncode


def test_provider_list_contains_chatgpt_codex() -> None:
    assert CodexAppServerProvider in PROVIDERS
    assert CodexAppServerProvider.requires_api_key is False


def test_source_mcp_launch_uses_current_python_module() -> None:
    spec = law_mcp_launch_spec()
    assert spec.command == sys.executable
    assert spec.args == ("-m", "mcp_server.server")


def test_frozen_mcp_launch_reuses_the_exe(monkeypatch, tmp_path) -> None:
    exe = tmp_path / "국가법령정보 통합검색.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    spec = law_mcp_launch_spec()
    resolved = exe.resolve()
    assert spec.command == str(resolved)
    assert spec.args == ("--mcp-server",)
    assert spec.cwd == str(resolved.parent)


def test_clean_child_environment_drops_pyinstaller_worker_vars(monkeypatch) -> None:
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", r"C:\temp\_MEI123")
    monkeypatch.setenv("_MEIPASS2", r"C:\temp\_MEI123")
    env = clean_child_environment()
    assert "_PYI_APPLICATION_HOME_DIR" not in env
    assert "_MEIPASS2" not in env


def test_windows_batch_cli_uses_call_for_paths_with_spaces(monkeypatch) -> None:
    monkeypatch.setattr(
        "llm.desktop_mcp.shutil.which",
        lambda _name: r"C:\Program Files\nodejs\npm.cmd",
    )

    argv = cli_argv("npm")

    assert argv[-2:] == ["call", r"C:\Program Files\nodejs\npm.cmd"]


def test_codex_app_server_handshake_stream_and_thread_reuse() -> None:
    fake = _FakeCodexProcess()
    chat = CodexAppServerChat("", Path.cwd(), "법령만 검토", "secret-oc")
    chat._spawn_process = lambda: fake  # type: ignore[method-assign]

    assert "".join(chat.send("첫 질문")) == "결론입니다."
    assert "".join(chat.send("후속 질문")) == "결론입니다."

    methods = [request.get("method") for request in fake.requests]
    assert methods.count("initialize") == 1
    assert methods.count("thread/start") == 1
    assert methods.count("turn/start") == 2

    thread_request = next(r for r in fake.requests if r.get("method") == "thread/start")
    params = thread_request["params"]
    server = params["config"]["mcp_servers"]["law-search"]
    assert params["sandbox"] == "read-only"
    assert params["approvalPolicy"] == "never"
    assert server["env_vars"] == [
        "LAW_API_KEY",
        "PYINSTALLER_RESET_ENVIRONMENT",
    ]
    assert "secret-oc" not in json.dumps(thread_request, ensure_ascii=False)
    chat.close()


def _claude_stream(
    pieces: tuple[str, ...],
    tools: tuple[tuple[str, dict], ...] = (),
    result_text: str = "답변",
) -> list[str]:
    """claude --output-format stream-json이 흘리는 줄을 흉내낸다."""

    def dump(payload: dict) -> str:
        return json.dumps(payload, ensure_ascii=False) + "\n"

    lines = [dump({"type": "system", "subtype": "init", "session_id": "session-1"})]
    for name, argument in tools:
        lines.append(
            dump(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "tool_use", "name": name, "input": argument}
                        ]
                    },
                }
            )
        )
    for piece in pieces:
        lines.append(
            dump(
                {
                    "type": "stream_event",
                    "event": {
                        "type": "content_block_delta",
                        "delta": {"type": "text_delta", "text": piece},
                    },
                }
            )
        )
    lines.append(
        dump(
            {
                "type": "result",
                "subtype": "success",
                "session_id": "session-1",
                "is_error": False,
                "result": result_text,
                "num_turns": 3,
                "usage": {"input_tokens": 10, "output_tokens": 20},
            }
        )
    )
    return lines


class _FakeClaudeStdin:
    def __init__(self, captured: dict) -> None:
        self.captured = captured

    def write(self, text: str) -> int:
        self.captured["stdin"] = text
        return len(text)

    def close(self) -> None:
        pass


class _FakeClaudeProcess:
    def __init__(self, captured: dict, args: list[str], **kwargs) -> None:
        captured["args"] = args
        captured["kwargs"] = kwargs
        # 프롬프트 파일은 send()가 끝나면서 지우므로 지금 읽어 둔다.
        path = args[args.index("--append-system-prompt-file") + 1]
        captured["system_prompt"] = Path(path).read_text(encoding="utf-8")
        config_path = args[args.index("--mcp-config") + 1]
        captured["mcp_config"] = json.loads(
            Path(config_path).read_text(encoding="utf-8")
        )
        self.captured = captured
        self.stdin = _FakeClaudeStdin(captured)
        self.stdout = iter(captured.get("stream") or _claude_stream(("답변",)))
        self.stderr = iter(())
        self.returncode = 0

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode

    def poll(self) -> int | None:
        return self.returncode

    def kill(self) -> None:
        self.returncode = -9

    def terminate(self) -> None:
        self.returncode = -15


def test_claude_uses_local_mcp_config_without_key_on_command_line(monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr(
        "llm.claude_code.cli_argv",
        lambda _name: ["cmd.exe", "/d", "/s", "/c", "claude.cmd"],
    )
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda args, **kwargs: _FakeClaudeProcess(captured, args, **kwargs),
    )

    chat = ClaudeCodeChat("", Path.cwd(), "법령만 검토", "secret-oc")
    pieces = list(chat.send("질문"))
    assert "".join(p for p in pieces if isinstance(p, str)) == "답변"

    args = captured["args"]
    config = captured["mcp_config"]
    assert Path(args[args.index("--mcp-config") + 1]).suffix == ".json"
    assert config["mcpServers"]["law-search"]["env"]["LAW_API_KEY"] == (
        "${LAW_API_KEY}"
    )
    assert config["mcpServers"]["law-search"]["env"][
        "PYINSTALLER_RESET_ENVIRONMENT"
    ] == "1"
    assert "secret-oc" not in " ".join(args)
    assert captured["kwargs"]["env"]["LAW_API_KEY"] == "secret-oc"
    assert "--strict-mcp-config" in args


def test_claude_keeps_newline_values_off_the_command_line(monkeypatch) -> None:
    """줄바꿈이 있는 값은 명령줄에 실리면 안 된다.

    Windows에서 claude는 배치 파일이라 cmd.exe를 거치는데, cmd는 인자 안의
    줄바꿈을 명령의 끝으로 읽는다. 예전에 시스템 프롬프트를
    --append-system-prompt로 넘기다가 뒤따르던 --output-format과 --resume이
    통째로 잘려 나가, 응답이 평문으로 오고 대화도 이어지지 않았다.
    """
    captured: dict = {}
    system_prompt = "법령만 검토\n둘째 줄\n셋째 줄"
    question = "첫 줄 질문\n둘째 줄 질문"

    monkeypatch.setattr(
        "llm.claude_code.cli_argv",
        lambda _name: ["cmd.exe", "/d", "/s", "/c", "claude.cmd"],
    )
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda args, **kwargs: _FakeClaudeProcess(captured, args, **kwargs),
    )

    chat = ClaudeCodeChat("sonnet", Path.cwd(), system_prompt, "secret-oc")
    pieces = list(chat.send(question))
    assert "".join(p for p in pieces if isinstance(p, str)) == "답변"

    args = captured["args"]
    # 어떤 인자에도 줄바꿈이 없어야 cmd.exe가 명령을 끊지 않는다.
    assert not any("\n" in argument for argument in args)
    # 질문은 표준입력으로, 시스템 프롬프트는 파일로 넘어간다.
    assert captured["stdin"] == question
    assert captured["system_prompt"] == system_prompt
    assert "--append-system-prompt" not in args
    # 잘려 나가던 뒤쪽 인자가 그대로 남아 있어야 한다.
    assert args[args.index("--output-format") + 1] == "stream-json"
    assert args[args.index("--model") + 1] == "sonnet"


def test_claude_streams_answer_and_reports_tool_progress(monkeypatch) -> None:
    """답은 조각으로 흐르고, 도구를 오가는 동안 진행이 보여야 한다.

    법령을 여러 번 찾는 질문은 답이 나오기까지 몇 분이 걸린다. 예전처럼
    다 끝난 뒤 한 번에 받으면 그동안 화면에 "찾는 중…" 한 줄만 떠 있어
    멎은 것인지 알 수 없었다.
    """
    captured: dict = {
        "stream": _claude_stream(
            ("도시", "관리계획은"),
            tools=(
                ("mcp__law-search__search_law", {"query": "국토의 계획"}),
                ("mcp__law-search__get_article", {"law_id": "000479", "jo": "0018"}),
            ),
            result_text="도시관리계획은",
        )
    }

    monkeypatch.setattr("llm.claude_code.cli_argv", lambda _name: ["claude"])
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda args, **kwargs: _FakeClaudeProcess(captured, args, **kwargs),
    )

    chat = ClaudeCodeChat("", Path.cwd(), "법령만 검토", "secret-oc")
    pieces = list(chat.send("도시관리계획 입안서류"))

    assert [p for p in pieces if isinstance(p, str)] == ["도시", "관리계획은"]
    progress = [p for p in pieces if isinstance(p, Progress)]
    # 조문 조회는 어느 법의 제18조인지 화면이 이름을 붙일 수 있게
    # 문서 id를 앞에 남긴다. 숫자 id 자체는 화면에 그리지 않는다.
    assert [p.text for p in progress if p.kind == "tool"] == [
        "법제처에서 법령 검색하는 중: 국토의 계획",
        "법제처에서 조문 읽는 중: [문서 000479] 제18조",
    ]
    assert any(p.kind == "usage" for p in progress)
    # 이어 묻기가 붙도록 세션이 잡혀야 한다.
    assert chat._session_id == "session-1"
