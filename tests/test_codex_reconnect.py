"""Codex 연결이 끊겨도 같은 질문을 스스로 다시 보내는지 검증."""

from __future__ import annotations

import pytest

from llm.base import LlmError, Progress
from llm.codex_app_server import CodexAppServerChat, CodexConnectionLost


class _Chat(CodexAppServerChat):
    """프로세스를 띄우지 않고 턴 동작만 흉내내는 시험용 대화."""

    def __init__(self, turns) -> None:
        # 실제 __init__은 CLI 경로와 작업 폴더를 요구하므로 부르지 않는다.
        self._turns = list(turns)
        self.closed = 0
        self.attempts: list[str] = []

    def close(self) -> None:
        self.closed += 1

    def _run_turn(self, message, produced):
        self.attempts.append(message)
        behaviour = self._turns.pop(0)
        yield from behaviour(produced)


def _drops_immediately(produced):
    raise CodexConnectionLost("Codex 연결이 예기치 않게 끝났습니다.")
    yield  # pragma: no cover - 제너레이터로 만들기 위한 줄


def _answers(text):
    def run(produced):
        produced[0] = True
        yield text

    return run


def _fails_for_another_reason(produced):
    raise LlmError("사용량 한도에 걸렸습니다.")
    yield  # pragma: no cover


def test_dead_connection_is_reopened_and_the_question_is_resent() -> None:
    chat = _Chat([_drops_immediately, _answers("답입니다")])

    pieces = list(chat.send("체육시설 조성기준"))

    # 사용자가 같은 질문을 손으로 다시 넣지 않아도 된다.
    assert chat.attempts == ["체육시설 조성기준", "체육시설 조성기준"]
    assert chat.closed == 1
    assert "답입니다" in pieces
    # 무슨 일이 있었는지는 진행줄로 알린다.
    assert any(
        isinstance(piece, Progress) and "다시 연결" in piece.text
        for piece in pieces
    )


def test_a_half_written_answer_is_not_asked_again() -> None:
    """글자가 나온 뒤 끊기면 다시 묻지 않는다. 같은 답이 두 번 쌓인다."""

    def drops_after_text(produced):
        produced[0] = True
        yield "앞부분"
        raise CodexConnectionLost("Codex 연결이 예기치 않게 끝났습니다.")

    chat = _Chat([drops_after_text, _answers("두 번째 답")])

    with pytest.raises(CodexConnectionLost):
        list(chat.send("질문"))

    assert chat.attempts == ["질문"]
    assert chat.closed == 0


def test_other_failures_are_not_retried() -> None:
    """한도ㆍ인증 실패는 다시 물어도 똑같이 실패한다."""
    chat = _Chat([_fails_for_another_reason, _answers("올 리 없는 답")])

    with pytest.raises(LlmError) as caught:
        list(chat.send("질문"))

    assert "사용량 한도" in str(caught.value)
    assert chat.attempts == ["질문"]
    assert chat.closed == 0


def test_reconnect_failing_again_surfaces_the_error() -> None:
    chat = _Chat([_drops_immediately, _drops_immediately])

    with pytest.raises(CodexConnectionLost):
        list(chat.send("질문"))

    assert chat.attempts == ["질문", "질문"]
    assert chat.closed == 1
