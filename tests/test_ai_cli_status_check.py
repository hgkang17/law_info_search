"""켤 때 도는 CLI 상태 확인 경로 회귀 테스트.

``cli_version``을 가져오지 않아 확인 스레드가 늘 NameError로 끝나던 적이
있다. 예외를 ``except Exception``이 삼키고 "빈 결과"만 내보내서, 화면에는
멀쩡히 깔린 CLI가 계속 "미연결"로 보였다. 조용히 죽는 자리라 눈으로는
찾기 어려우므로 여기서 잡는다.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from llm.ai_cli_setup import CLAUDE_CLI
from ui.tabs import ai_chat_panel
from ui.tabs.ai_chat_panel import AiChatPanel, AiCliCheckWorker


class _Collector:
    """워커가 내보내는 신호를 대신 받는다."""

    def __init__(self) -> None:
        self.results: list[tuple] = []

    def emit(self, *values) -> None:
        self.results.append(values)


def _run_worker(monkeypatch, version, login) -> list[tuple]:
    monkeypatch.setattr(
        ai_chat_panel, "cli_version", lambda spec, cancelled=None: version
    )
    monkeypatch.setattr(
        ai_chat_panel, "cli_login_status", lambda spec, cancelled=None: login
    )
    worker = AiCliCheckWorker((CLAUDE_CLI,))
    checked = _Collector()
    worker.checked.connect(checked.emit)
    worker.run()
    return checked.results


def test_check_worker_reports_installed_cli(monkeypatch) -> None:
    """설치ㆍ로그인된 CLI는 그대로 전달된다(예외로 새지 않는다)."""
    results = _run_worker(
        monkeypatch, "claude 1.2.3", (True, "claude.ai 계정")
    )

    assert results == [(CLAUDE_CLI.label, "claude 1.2.3", True, "claude.ai 계정")]


def test_check_worker_reports_missing_cli(monkeypatch) -> None:
    """안 깔려 있으면 빈 버전으로 알리고 로그인 확인은 건너뛴다."""

    def fail(spec, cancelled=None):  # pragma: no cover - 불려서는 안 된다
        raise AssertionError("버전이 없으면 로그인을 확인하지 않는다")

    monkeypatch.setattr(
        ai_chat_panel, "cli_version", lambda spec, cancelled=None: None
    )
    monkeypatch.setattr(ai_chat_panel, "cli_login_status", fail)
    worker = AiCliCheckWorker((CLAUDE_CLI,))
    checked = _Collector()
    worker.checked.connect(checked.emit)
    worker.run()

    assert checked.results == [(CLAUDE_CLI.label, "", False, "")]


class _PanelStub:
    """``_auto_check_result``가 만지는 자리만 흉내 낸다."""

    def __init__(self) -> None:
        self._cli_statuses: dict[str, tuple[str, str]] = {}
        self.remembered: list[tuple] = []
        self.shown: list[tuple] = []

    def _remember_cli_connection(self, label, connected, tooltip) -> None:
        self.remembered.append((label, connected, tooltip))

    def _connection_spec(self):
        return None

    def _set_cli_status(self, *values) -> None:  # pragma: no cover - 미사용
        self.shown.append(values)


def test_connected_tooltip_puts_detail_on_a_new_line() -> None:
    """버전과 설명은 줄을 나눠 보여 준다."""
    panel = _PanelStub()
    AiChatPanel._auto_check_result(
        panel, CLAUDE_CLI.label, "claude 1.2.3", True, "claude.ai 계정"
    )

    assert panel._cli_statuses[CLAUDE_CLI.label] == ("CLI : 연결됨", "connected")
    assert panel.remembered == [
        (CLAUDE_CLI.label, True, "claude 1.2.3\nclaude.ai 계정")
    ]


def test_connected_tooltip_without_detail_is_version_only() -> None:
    """설명이 없으면 줄바꿈만 남기지 않는다."""
    panel = _PanelStub()
    AiChatPanel._auto_check_result(
        panel, CLAUDE_CLI.label, "claude 1.2.3", True, ""
    )

    assert panel.remembered == [(CLAUDE_CLI.label, True, "claude 1.2.3")]


def test_logged_out_tooltip_explains_login() -> None:
    panel = _PanelStub()
    AiChatPanel._auto_check_result(
        panel, CLAUDE_CLI.label, "claude 1.2.3", False, ""
    )

    assert panel._cli_statuses[CLAUDE_CLI.label] == ("CLI : 미연결", "disconnected")
    # 미연결이면 기억해 둘 툴팁을 비운다.
    assert panel.remembered == [(CLAUDE_CLI.label, False, "")]
