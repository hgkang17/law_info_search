"""Claude CodeㆍCodex CLI가 남긴 영문 오류를 한글 설명으로 바꾼다.

두 CLI 모두 실패하면 종료 코드와 영문 stderr만 남긴다. 화면에 그대로
띄우면 무엇이 잘못됐는지, 무엇을 하면 되는지 알 수 없어서 여기서 한 번
사람 말로 풀어 준다.

두 CLI 다 성공은 0, 실패는 0이 아닌 값만 쓰고 값마다 뜻을 정해 두지
않았다. 그래서 종료 코드로는 운영체제가 정한 것(신호로 죽음, 명령 없음)
만 알아보고, 나머지는 stderr 문구로 가린다.
"""

from __future__ import annotations

import re


# 운영체제가 뜻을 정해 둔 종료 코드. 128 + 신호번호가 관례다.
_EXIT_CODES: dict[int, str] = {
    1: "일반 오류로 끝났습니다.",
    2: "명령을 잘못 불렀습니다(옵션ㆍ인자 오류).",
    126: "실행 권한이 없어 실행하지 못했습니다.",
    127: "명령을 찾지 못했습니다. 설치 여부와 PATH를 확인하세요.",
    130: "사용자가 중단했습니다(Ctrl+C).",
    137: "메모리 부족 등으로 강제 종료됐습니다(SIGKILL).",
    143: "종료 요청을 받고 끝났습니다(SIGTERM).",
    3221225477: "메모리 접근 위반으로 죽었습니다(Windows 0xC0000005).",
    3221225786: "사용자가 중단했습니다(Windows Ctrl+C).",
}


# 앞에 있는 것부터 맞춰 본다. 좁은 조건을 먼저 둔다.
_MESSAGE_RULES: tuple[tuple[str, str], ...] = (
    (
        r"credit balance|insufficient (funds|credit)|billing|payment required|402",
        "결제ㆍ크레딧 잔액 문제입니다. 계정의 결제 수단과 남은 크레딧을 "
        "확인하세요.",
    ),
    (
        r"rate limit|429|too many requests|usage limit|quota",
        "사용량 한도에 걸렸습니다. 잠시 뒤에 다시 시도하거나 요금제 한도를 "
        "확인하세요.",
    ),
    (
        r"not logged in|please run /login|/login|log ?in required",
        "로그인이 풀렸습니다. 터미널에서 CLI를 실행해 다시 로그인하세요.",
    ),
    (
        r"oauth|token (has )?expired|refresh token",
        "로그인 정보가 만료됐습니다. 터미널에서 CLI에 다시 로그인하세요.",
    ),
    (
        r"invalid api key|unauthorized|authentication|401|403|forbidden",
        "인증에 실패했습니다. API 키나 로그인 상태를 확인하세요.",
    ),
    (
        r"model .*(not found|not exist|unavailable)|invalid model|unknown model",
        "요청한 모델을 쓸 수 없습니다. 모델 이름과 계정 권한을 확인하세요.",
    ),
    (
        r"bad request|invalid request|malformed request|\b400\b",
        "요청 형식이 올바르지 않습니다. 입력 내용이나 CLI 설정을 확인하세요.",
    ),
    (
        r"request timeout|gateway timeout|\b408\b|\b504\b",
        "서버 응답 시간이 초과됐습니다. 잠시 뒤 다시 시도하세요.",
    ),
    (
        r"payload too large|request entity too large|\b413\b",
        "보낸 내용이 너무 큽니다. 첨부나 대화 내용을 줄여 다시 시도하세요.",
    ),
    (
        r"context (length|window)|too long|maximum.*tokens|prompt is too long",
        "대화가 너무 길어 한도를 넘었습니다. 새 대화를 시작하거나 질문을 "
        "줄여 주세요.",
    ),
    (
        r"self.?signed|unable_to_verify|cert(ificate)?_|sslv3|ssl error",
        "SSL 인증서 검증에 실패했습니다. 회사망의 보안 장비나 프록시 설정을 "
        "확인하세요.",
    ),
    (
        r"enotfound|eai_again|getaddrinfo",
        "서버 주소를 찾지 못했습니다. 인터넷 연결이나 DNS를 확인하세요.",
    ),
    (
        r"econnrefused|econnreset|etimedout|esockettimedout|socket hang up"
        r"|network|proxy",
        "서버에 연결하지 못했습니다. 인터넷 연결과 방화벽ㆍ프록시를 "
        "확인하세요.",
    ),
    (
        r"eacces|operation not permitted|permission denied",
        "파일이나 폴더에 접근할 권한이 없습니다.",
    ),
    (
        r"enospc|no space left",
        "디스크 여유 공간이 없습니다.",
    ),
    (
        r"is not recognized as an internal|command not found|enoent",
        "명령을 찾지 못했습니다. CLI가 설치돼 있고 PATH에 잡히는지 "
        "확인하세요.",
    ),
    (
        r"unsupported engine|requires node|node(js)? version",
        "Node.js 버전이 맞지 않습니다. CLI가 요구하는 버전으로 올리세요.",
    ),
    (
        r"mcp server|failed to (start|connect).*server",
        "MCP 서버를 띄우지 못했습니다. 법령검색 도구 없이 답할 수 있습니다.",
    ),
    (
        r"api error|internal server error|500|502|503|529|overloaded",
        "서버 쪽 오류이거나 사용자가 몰려 있습니다. 잠시 뒤 다시 "
        "시도하세요.",
    ),
)


_COMPILED = tuple(
    (re.compile(pattern, re.IGNORECASE), explanation)
    for pattern, explanation in _MESSAGE_RULES
)


def explain_stderr(text: str) -> str:
    """영문 오류 문구에서 알아볼 수 있는 것 하나를 한글로 돌려준다."""
    haystack = str(text or "")
    if not haystack.strip():
        return ""
    for pattern, explanation in _COMPILED:
        if pattern.search(haystack):
            return explanation
    return ""


def explain_exit_code(returncode: object) -> str:
    """운영체제가 뜻을 정해 둔 종료 코드만 한글로 돌려준다."""
    try:
        code = int(returncode)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    if code < 0:
        # POSIX에서 신호로 죽으면 음수로 온다. 128 + 신호번호로 맞춘다.
        code = 128 - code
    return _EXIT_CODES.get(code, "")


def describe_failure(returncode: object = None, stderr: str = "") -> str:
    """실패 사유 한 줄을 만든다. 알아보지 못하면 빈 문자열.

    stderr에서 알아본 것이 종료 코드보다 늘 구체적이라 그것을 먼저 쓴다.
    """
    return explain_stderr(stderr) or explain_exit_code(returncode)


def with_explanation(message: str, returncode: object = None, stderr: str = "") -> str:
    """알아본 오류는 한글 안내를 먼저 보여 주고 원문은 세부 정보로 둔다."""
    explanation = describe_failure(returncode, stderr)
    if not explanation:
        return message
    return f"{explanation}\n\n세부 정보: {message}"
