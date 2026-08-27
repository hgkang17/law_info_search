"""ClaudeㆍCodex CLI가 남긴 영문 오류를 한글로 풀어 주는지 검증."""

from __future__ import annotations

import pytest

from llm.cli_errors import describe_failure, explain_exit_code, explain_stderr, with_explanation


@pytest.mark.parametrize(
    "stderr, expected",
    [
        ("Error: Invalid API key · Please run /login", "로그인"),
        ("OAuth token has expired", "만료"),
        ("API Error: 429 rate_limit_error", "사용량 한도"),
        ("Your credit balance is too low", "크레딧"),
        ("getaddrinfo ENOTFOUND api.anthropic.com", "DNS"),
        ("connect ECONNREFUSED 127.0.0.1:443", "방화벽"),
        ("prompt is too long: 250000 tokens > 200000 maximum", "대화가 너무 길어"),
        ("SELF_SIGNED_CERT_IN_CHAIN", "인증서"),
        ("EACCES: permission denied", "권한"),
        ("ENOSPC: no space left on device", "디스크"),
        ("'claude' is not recognized as an internal or external command", "PATH"),
        ("Unsupported engine: requires Node >=18", "Node.js"),
        ("529 overloaded_error", "서버 쪽 오류"),
    ],
)
def test_common_english_errors_get_a_korean_explanation(stderr, expected) -> None:
    assert expected in explain_stderr(stderr)


def test_unknown_error_text_gets_no_guess() -> None:
    assert explain_stderr("something we have never seen") == ""
    assert explain_stderr("") == ""


@pytest.mark.parametrize(
    "code, expected",
    [
        (127, "찾지 못했습니다"),
        (130, "Ctrl+C"),
        (137, "강제 종료"),
        (126, "실행 권한"),
        (1, "일반 오류"),
    ],
)
def test_operating_system_exit_codes_are_named(code, expected) -> None:
    assert expected in explain_exit_code(code)


def test_signal_exit_codes_arrive_negative_on_posix() -> None:
    # POSIX에서 신호로 죽으면 음수로 온다. 128 + 신호번호로 맞춘다.
    assert "Ctrl+C" in explain_exit_code(-2)
    assert "SIGKILL" in explain_exit_code(-9)


def test_unknown_exit_code_is_silent() -> None:
    assert explain_exit_code(77) == ""
    assert explain_exit_code(None) == ""
    assert explain_exit_code("이상한 값") == ""


def test_stderr_beats_exit_code_because_it_is_more_specific() -> None:
    explanation = describe_failure(1, "API Error: 429 rate_limit_error")

    assert "사용량 한도" in explanation
    assert "일반 오류" not in explanation


def test_message_is_returned_untouched_when_nothing_is_recognized() -> None:
    message = "claude 실행이 실패했습니다: 종료 코드 77"

    assert with_explanation(message, 77, "알 수 없는 오류") == message


def test_explanation_is_appended_below_the_original_message() -> None:
    result = with_explanation("실패했습니다", 1, "429 rate limit")

    assert result.startswith("실패했습니다")
    assert "사용량 한도" in result
