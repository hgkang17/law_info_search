"""AI 연결 버튼에서 사용하는 CLI 설치 경로 단위 테스트."""

from __future__ import annotations

import subprocess

import pytest

from llm import ai_cli_setup as setup


def _completed(args, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args, returncode, stdout, stderr)


def test_existing_cli_skips_npm_install(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(setup.shutil, "which", lambda name: f"C:/{name}.cmd")

    def fake_run(command, *args, timeout):
        calls.append((command, *args))
        return _completed(args, stdout="codex-cli 1.2.3\n")

    monkeypatch.setattr(setup, "_run_cli", fake_run)

    version, installed = setup.ensure_cli(setup.CODEX_CLI)

    assert version == "codex-cli 1.2.3"
    assert installed is False
    assert calls == [("codex", "--version")]


def test_vscode_bundled_codex_is_not_global_install(monkeypatch) -> None:
    bundled = (
        "C:/Users/User/.vscode/extensions/"
        "openai.chatgpt-1.2.3/bin/windows-x86_64/codex.exe"
    )
    monkeypatch.setattr(setup.shutil, "which", lambda _name: bundled)

    assert setup.cli_version(setup.CODEX_CLI) is None


def test_claude_login_status_reads_json(monkeypatch) -> None:
    monkeypatch.setattr(
        setup,
        "_run_cli",
        lambda command, *args, timeout: _completed(
            args,
            stdout=(
                '{"loggedIn":true,"authMethod":"claude.ai",'
                '"subscriptionType":"pro"}'
            ),
        ),
    )

    logged_in, detail = setup.cli_login_status(setup.CLAUDE_CLI)

    assert logged_in is True
    assert detail == "claude.ai · Claude Pro"


def test_codex_login_status_reports_chatgpt(monkeypatch) -> None:
    monkeypatch.setattr(
        setup,
        "_run_cli",
        lambda command, *args, timeout: _completed(
            args, stdout="Logged in using ChatGPT\n"
        ),
    )

    logged_in, detail = setup.cli_login_status(setup.CODEX_CLI)

    assert logged_in is True
    assert detail == "ChatGPT"


@pytest.mark.parametrize("spec", [setup.CLAUDE_CLI, setup.CODEX_CLI])
def test_cli_login_status_detects_logged_out(monkeypatch, spec) -> None:
    monkeypatch.setattr(
        setup,
        "_run_cli",
        lambda command, *args, timeout: _completed(
            args, returncode=1, stderr="Not logged in"
        ),
    )

    assert setup.cli_login_status(spec) == (False, "")


@pytest.mark.parametrize(
    ("spec", "login_args"),
    [
        (setup.CLAUDE_CLI, ("auth", "login")),
        (setup.CODEX_CLI, ("login",)),
    ],
)
def test_logged_out_cli_launches_official_browser_login(
    monkeypatch, spec, login_args
) -> None:
    calls: list[list[str]] = []

    def fake_popen(args, **_kwargs):
        calls.append(args)
        return object()

    monkeypatch.setattr(setup, "cli_argv", lambda command: [command])
    monkeypatch.setattr(setup.subprocess, "Popen", fake_popen)

    setup.launch_cli_login(spec)

    assert calls == [[spec.command, *login_args]]


@pytest.mark.parametrize(
    ("spec", "version"),
    [
        (setup.CLAUDE_CLI, "2.1.0 (Claude Code)"),
        (setup.CODEX_CLI, "codex-cli 2.0.0"),
    ],
)
def test_missing_cli_installs_expected_npm_package(
    monkeypatch, spec, version
) -> None:
    cli_checks = 0
    calls: list[tuple[str, ...]] = []

    def fake_which(name):
        nonlocal cli_checks
        if name == "npm":
            return "C:/node/npm.cmd"
        if name == spec.command:
            cli_checks += 1
            return None if cli_checks == 1 else f"C:/npm/{name}.cmd"
        return None

    def fake_run(command, *args, timeout):
        calls.append((command, *args))
        if command == spec.command:
            return _completed(args, stdout=f"{version}\n")
        return _completed(args, stdout="10.9.0\n")

    monkeypatch.setattr(setup.shutil, "which", fake_which)
    monkeypatch.setattr(setup, "_run_cli", fake_run)

    actual_version, installed = setup.ensure_cli(spec)

    assert actual_version == version
    assert installed is True
    assert ("npm", "install", "-g", spec.npm_package) in calls


@pytest.mark.parametrize(
    "spec",
    [setup.CLAUDE_CLI, setup.CODEX_CLI],
)
def test_missing_npm_gives_node_guidance(monkeypatch, spec) -> None:
    monkeypatch.setattr(setup.shutil, "which", lambda _name: None)

    with pytest.raises(setup.AiCliSetupError, match="Node.js"):
        setup.ensure_cli(spec)

