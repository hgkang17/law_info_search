"""LLM 제공자 공통 인터페이스.

Gemini로 먼저 만들지만 나중에 Claude와 GPT를 같은 자리에 끼울 수 있도록,
화면은 이 인터페이스만 알고 구체 제공자는 모르게 둔다.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator

from utils.parsing import article_jo_label


class LlmError(Exception):
    """제공자 쪽 실패를 화면에 그대로 보여 주기 위한 예외.

    인증 실패ㆍ한도 초과ㆍ연결 끊김을 구분하지 않고 문구만 전달한다.
    구분이 필요해지면 그때 하위 예외를 나눈다.
    """


@dataclass(frozen=True)
class Progress:
    """답변 본문이 아니라 "지금 무엇을 하는 중인지"를 알리는 조각.

    법령을 찾는 질문은 도구를 여러 번 오가느라 답이 나오기까지 몇 분이
    걸리기도 한다. 그동안 화면이 "찾는 중…" 한 줄로 멈춰 있으면 진행이
    되는지 멎었는지 알 수 없다. 본문 조각과 구분해서 흘려 보내면 화면이
    무엇을 하고 있는지 그때그때 보여 줄 수 있다.

    kind는 화면이 표시를 달리할 때 쓴다.
    - "tool": 도구를 부르는 중 (예: 법령 검색)
    - "thinking": 답을 정리하는 중
    - "usage": 다 쓰고 난 사용량
    """

    text: str
    kind: str = "tool"


@dataclass(frozen=True)
class ModelInfo:
    """화면의 모델 선택칸에 쓰는 정보."""

    model_id: str
    label: str
    # 부연 설명. 입력 한도처럼 고를 근거가 되는 값을 넣는다.
    note: str = ""


class LlmProvider(ABC):
    """법령 본문을 근거로 질문에 답하는 제공자."""

    name: str = ""
    # 키가 없거나 목록 조회가 막혔을 때만 쓰는 예비 목록.
    #
    # 모델 이름은 제공자가 예고 없이 갈아 치운다. 실제로 gemini-2.5-flash가
    # 신규 사용자에게 막히면서 404가 났다. 그래서 목록은 fetch_models()로
    # 제공자에게 직접 물어보는 것을 기본으로 하고, 아래 목록은 물어볼 수
    # 없을 때만 쓴다.
    fallback_models: tuple[ModelInfo, ...] = ()
    # 키를 발급받는 곳. 화면에서 안내 링크로 쓴다.
    api_key_url: str = ""
    # False면 화면의 API 키 입력칸을 숨긴다. 로컬 CLI가 자기 로그인
    # 정보로 도는 제공자(Claude Code 등)는 키가 필요 없다.
    requires_api_key: bool = True

    def __init__(self, api_key: str, model_id: str = "") -> None:
        self.api_key = api_key
        self.model_id = model_id

    def fetch_models(self) -> tuple[ModelInfo, ...]:
        """제공자에게 지금 쓸 수 있는 모델을 물어본다.

        조회에 실패하면 예비 목록을 돌려준다. 목록을 못 받았다고 화면이
        비어 버리면 아무것도 못 하기 때문이다.
        """
        return self.fallback_models

    def fetch_validated_models(self) -> tuple[ModelInfo, ...]:
        """API 키를 확인한 뒤 현재 쓸 수 있는 모델을 돌려준다.

        키 검증이 따로 필요 없는 제공자는 기존 목록 조회를 그대로 쓴다.
        같은 원격 목록으로 검증과 조회를 함께 할 수 있는 제공자는 이 메서드를
        재정의해 네트워크 왕복을 한 번으로 줄인다.
        """
        validate = getattr(self, "validate_api_key", None)
        if callable(validate):
            validate()
        return self.fetch_models()

    @abstractmethod
    def start_chat(
        self, context: str = "", *, oc_key: str = "", law_cache=None
    ) -> "ChatSession":
        """대화를 시작한다.

        검토는 한 번 묻고 끝나지 않는다. "그럼 이 경우는?"처럼 앞의 답을
        딛고 되묻는 일이 대부분이라 대화가 이어져야 한다.

        context: 미리 깔아 둘 법령 본문. 비워 두면 검색 도구로 스스로
            찾아야 한다.
        oc_key: 국가법령정보 공동활용 OC 인증키. 값이 있으면 법제처
            검색ㆍ조문조회 도구를 켠다. 없으면 context만으로 답한다.
        """


class ChatSession(ABC):
    """법령 본문을 깔아 둔 채 이어지는 한 판의 대화."""

    @abstractmethod
    def send(self, message: str) -> Iterator[str | Progress]:
        """한 마디 보내고 답을 조각으로 받는다.

        문자열은 답변 본문이고, Progress는 진행 상황 알림이다. 화면은
        둘을 구분해 본문만 말풍선에 쌓는다.
        """

    def touched_documents(self) -> tuple[tuple[str, str, str], ...]:
        """방금 send()에서 실제로 읽은 문서를 (category, id, name)으로 준다.

        "이 법령 즐겨찾기에 추가" 단추를 채우는 데 쓴다. 도구를 안 쓰는
        제공자나 검색 도구가 꺼진 대화는 항상 빈 튜플을 돌려준다.
        """
        return ()

    def cancel(self) -> None:
        """진행 중인 답변을 중단한다. 지원하지 않는 제공자는 그대로 둔다."""

    def close(self) -> None:
        """대화가 소유한 자식 프로세스나 연결을 닫는다."""


_CITATION_PATTERN = re.compile(r"\[([^\]]+)\]\((law|doc):([^:)]+):([^)]+)\)")


def _unit_number(value: str) -> str:
    """조항호목 API의 6자리 코드를 사람이 읽는 번호로 바꾼다.

    항·호도 조와 같은 ``NNNNBB`` 꼴이다(앞 네 자리가 번호, 뒤 두 자리가
    가지번호). 앞의 0만 떼면 ``000200``이 ``200``이 되어 엉뚱한 번호가
    나온다 — 실제로 진행줄에 "제2500조"가 찍혔다.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    if text.isdigit() and len(text) == 6:
        main = int(text[:4])
        branch = int(text[4:])
        return f"{main}의{branch}" if branch else str(main)
    return text.lstrip("0") or text


def progress_law_name(full_name: str, official_short: str = "") -> str:
    """진행줄에 쓸 법령 이름. 법제처 약칭이 있으면 그걸 쓴다.

    임의로 줄이면 없는 이름이 되므로, 약칭표·공식 약칭에 없는 법령은
    정식 명칭을 그대로 둔다.
    """
    official = " ".join(str(official_short or "").split())
    name = " ".join(str(full_name or "").split())
    if official:
        for tail in ("시행규칙", "시행령"):
            if name.endswith(tail):
                return official if official.endswith(tail) else f"{official} {tail}"
        return official
    if not name:
        return ""
    from .law_aliases import display_alias

    return display_alias(name) or name


def _as_tool_arguments(argument: object) -> dict:
    if isinstance(argument, str):
        # Codex는 인자를 JSON 문자열로 넘겨 준다.
        try:
            argument = json.loads(argument)
        except ValueError:
            return {}
    return argument if isinstance(argument, dict) else {}


def _tool_search_scope(argument: dict) -> int:
    raw = argument.get("search_scope", 1)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 1


def tool_hint(argument: object) -> str:
    """도구 인자에서 "무엇을 읽는 중"인지 한 조각을 뽑는다.

    진행줄에 "법제처에서 조문 읽는 중"만 뜨면 무엇을 읽는지 알 수 없다. 검색어가
    있으면 그것을, 조문 조회면 화면이 법령 이름으로 바꿀 수 있게
    "[문서 id] 제18조"를 남긴다. 숫자 id 자체는 화면에 보이지 않는다.
    """
    argument = _as_tool_arguments(argument)
    if not argument:
        return ""
    query = str(
        argument.get("query")
        or argument.get("case_number")
        or argument.get("caseNumber")
        or ""
    ).strip()
    if query:
        return query
    law_name = str(
        argument.get("law_name") or argument.get("lawName") or ""
    ).strip()
    jo = str(argument.get("jo") or "").strip()
    if law_name:
        article = ""
        if jo:
            try:
                article = article_jo_label(jo)
            except ValueError:
                article = f"제{_unit_number(jo)}조" if jo.isdigit() else jo
        return f"{law_name} {article}".strip()
    article = ""
    if jo:
        try:
            article = article_jo_label(jo)
        except ValueError:
            article = f"제{_unit_number(jo)}조"
        for key, suffix in (("hang", "항"), ("ho", "호")):
            value = str(argument.get(key) or "").strip()
            if value:
                article += f"제{_unit_number(value)}{suffix}"
    ident = str(
        argument.get("law_id") or argument.get("item_id") or ""
    ).strip()
    parts: list[str] = []
    if ident:
        # 조 번호만으로는 어느 법의 제25조인지 알 수 없다. 화면 쪽에서
        # 검색·저장 본문으로 이름을 찾아 앞에 붙인다.
        parts.append(f"[문서 {ident}]")
    if article:
        parts.append(article)
    return " ".join(parts)


# 도구 이름 -> 진행줄에 보일 우리말. 제공자마다 이름 앞에 붙는 것이
# 다르지만(claude는 mcp__법령검색__, Codex는 그대로) 끝은 같으므로
# 여기 한 군데만 둔다.
TOOL_LABELS = {
    "search_law": "법제처에서 법령 검색하는 중",
    "get_article": "법제처에서 조문 읽는 중",
    "get_document": "법제처에서 본문 읽는 중",
    "search_admin_rule": "법제처에서 행정규칙 검색하는 중",
    "get_annexes": "법제처에서 별표·서식 검색하는 중",
    "legal_research": "법제처에서 관련 근거를 종합 조사하는 중",
    "search_cases": "법제처에서 해석례·판례 검색하는 중",
    "get_case": "법제처에서 해석례·판례 본문 읽는 중",
    "search_inquiries": "법제처에서 질의회신 검색하는 중",
    "get_inquiry": "법제처에서 질의회신 본문 읽는 중",
    "get_historical_law": "법제처에서 연혁·행위시법 확인하는 중",
    "compare_old_new": "법제처에서 신구대조표 읽는 중",
    "ordinance_radar": "조례 정비를 대조하는 중",
    "cite_check": "판례 생사를 확인하는 중",
    "impact_map": "조문 영향 맵을 만드는 중",
}

# search_scope=2는 제목이 아니라 본문에서 키워드를 찾는 검색이다.
BODY_SEARCH_LABELS = {
    "search_law": "법제처에서 법령 본문 검색하는 중",
    "search_admin_rule": "법제처에서 행정규칙 본문 검색하는 중",
    "search_inquiries": "법제처에서 질의회신 본문 검색하는 중",
}


_WEB_TOOL_KEYS = {
    "websearch",
    "web_search",
    "webfetch",
    "web_fetch",
    "search_web",
}

WEB_SOURCE_PROGRESS = "일반 웹을 찾는 중"


def tool_progress_label(
    name: object, arguments: object, unknown: str = "도구를 쓰는 중"
) -> str:
    """도구 호출 하나를 "법령을 검색하는 중: 농지법" 한 줄로 만든다."""
    raw = str(name or "").strip()
    tool = raw.split("__")[-1]
    label = TOOL_LABELS.get(tool)
    if label is None:
        # 이름을 모를 때는 출처를 붙이지 않는다. MCP 목록을 받는 단계나
        # 표에 없는 호출을 법제처 조회로 단정하면 안 된다.
        folded = tool.replace("-", "_").casefold()
        if folded in _WEB_TOOL_KEYS:
            return WEB_SOURCE_PROGRESS
        return unknown
    parsed = _as_tool_arguments(arguments)
    if tool in BODY_SEARCH_LABELS and _tool_search_scope(parsed) == 2:
        label = BODY_SEARCH_LABELS[tool]
    hint = tool_hint(parsed)
    return f"{label}: {hint}" if hint else label


def extract_touched_from_citations(text: str) -> tuple[tuple[str, str, str], ...]:
    """답변 글에 박힌 [이름](law:법령ID:조번호) / [이름](doc:구분:id)를 읽어
    (category, id, name)을 뽑는다.

    Gemini처럼 도구 호출 자체를 가로챌 수 없는 제공자(Claude Code CLI 등)가
    touched_documents()를 채우는 방법이다. TOOL_USE_INSTRUCTION이 모든
    조문 인용을 이 형식으로 쓰라고 못박아 두었으므로, 화면에 실제로 보인
    링크와 즐겨찾기 후보가 정확히 일치한다는 장점도 있다.
    """
    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str, str]] = []
    # 나중에 나온 인용일수록 실제로 답한 내용과 가까우므로 뒤에서부터 읽는다.
    matches = list(_CITATION_PATTERN.finditer(text))
    for label, scheme, first, second in (
        (m.group(1), m.group(2), m.group(3), m.group(4)) for m in reversed(matches)
    ):
        if scheme == "law":
            category, item_id = "law", first  # law:법령ID:조번호 — ID가 먼저다
            name = re.sub(r"\s*제\d+조.*$", "", label).strip() or label
        else:
            category, item_id = first, second  # doc:구분:id — 구분이 먼저다
            name = label
        key = (category, item_id)
        if key in seen or not item_id:
            continue
        seen.add(key)
        result.append((category, item_id, name))
    return tuple(result)


def extract_cited_articles(
    text: str,
) -> tuple[tuple[str, str, str], ...]:
    """답변에 인용된 조문을 (법령ID, 조번호, 표시이름)으로 뽑는다.

    ``[국토계획법 제25조](law:001234:25)`` 같은 링크만 대상이다. 조문
    단위 즐겨찾기 단추를 어느 조에 달지 정하는 데 쓴다. 문서 전체를
    가리키는 doc: 링크와 조번호가 없는 인용은 건너뛴다.
    """
    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str, str]] = []
    for match in _CITATION_PATTERN.finditer(text):
        label, scheme, first, second = match.group(1, 2, 3, 4)
        if scheme != "law":
            continue
        law_id = first.strip()
        jo = second.strip()
        if not law_id or not jo:
            continue
        key = (law_id, jo)
        if key in seen:
            continue
        seen.add(key)
        result.append((law_id, jo, label.strip()))
    return tuple(result)


SYSTEM_PROMPT = """당신은 법령 실무자 옆에서 함께 검토하는 동료입니다.
법전을 읽어 주는 사람이 아니라, 읽고 나서 "그래서 이렇게 하시면 됩니다"를
말해 주는 사람입니다.

## 답하는 방식

**결론부터 한 문장으로 말하십시오.** 그다음에 요건, 예외, 위임된
하위법령·지침을 순서대로 붙입니다. 근거를 먼저 늘어놓고 결론을 맨 뒤에
두지 마십시오.

**원문을 통째로 옮기지 마십시오.** 읽고 이해한 내용을 실무자가 쓰는 말로
설명하십시오. 판단이 갈리는 구절, 요건 목록, 예외 요건은 원문을 짧게
따와 근거를 남기십시오.

**관련 근거를 빠뜨리지 마십시오.** 법률만 보고 끝내지 말고, 같은 사안의
시행령·시행규칙·행정규칙·별표가 있으면 찾아 연결하십시오. 해석례나
판례, 중앙부처 질의회신이 판단에 도움이 되면 함께 확인하십시오.

**구조가 필요하면 소제목과 목록을 쓰십시오.** 요건 / 예외 / 절차 /
제출서류처럼 갈래가 나뉘는 질문은 항목으로 나누는 편이 실무에 맞습니다.
한 줄 요약으로 끝내지 마십시오.

## 반드시 지킬 것

**본문에 없는 것은 지어내지 마십시오.** "제공된 본문에서는 확인되지
않습니다"라고 밝히고, 어디를 더 봐야 하는지 알려 주십시오. 이것만은
짧게 쓰는 것보다 우선합니다.

**질문의 틀에 갇히지 마십시오.** 물어본 것에만 답하고 끝내면 실무에서
사고가 납니다. 질문자가 놓친 단서 조항이나 예외가 있으면 덧붙이되,
묻지도 않은 제도 전체를 길게 강의하지는 마십시오.

**단정하지 마십시오.** 최종 판단은 사용자가 합니다. 해석이 갈릴 여지가
있으면 그 사실을 알려 주십시오."""


# 검색 도구가 켜져 있을 때만 시스템 프롬프트 뒤에 덧붙인다. 법령 이름을
# 기억에서 답하지 말고 반드시 찾아보라는 지시가 핵심이다 — 이게 없으면
# 모델이 훈련 데이터로 외운(어쩌면 개정 전의, 어쩌면 틀린) 조문을 그대로
# 답해 버린다.
TOOL_USE_INSTRUCTION = """

## 검색 도구를 쓸 수 있습니다

법령ㆍ행정규칙ㆍ자치법규를 찾고 특정 조문을 읽는 도구, 별표·서식 도구,
복합 조사 도구, 법령해석례·판례 도구가 있습니다.

**법령 내용을 묻는 질문에는 답하기 전에 반드시 도구로 먼저 찾으십시오.**
기억나는 조문이 있어도 그대로 답하지 마십시오. 법이 개정되었을 수 있고,
기억이 틀렸을 수 있습니다. 화면에 보이는 실제 자료만 근거로 삼으십시오.

search_inquiries에서 기관을 비우면 여러 부처 결과가 섞입니다. 질문에
소관 부처가 보이면 agency에 기관명을 넣으십시오. 예: 국토교통부.

질의회신·유권해석·회신을 찾으라는 질문에는 legal_research를 쓰지
마십시오. search_inquiries로 찾고, 목록이 나오면 반드시 get_inquiry로
본문을 읽은 뒤에만 답하십시오. 제목 목록이나 법령 조문만으로
"사례마다 다르다"고 넘기지 마십시오.

절차·제출서류·구비서류·입안자료·허가 대상처럼 여러 근거가 필요한
질문에는 legal_research를 먼저 사용하십시오. 관련 법령과 행정규칙 후보가
나오면 get_article 또는 get_document로 원문을 읽고, 별표·별지서식은
get_annexes로 확인하십시오. 한 건으로 좁히면 별표 원문도 읽습니다.
해석이 갈리거나 실무 적용이 문제면 search_cases로 해석례·판례·헌재·
행심도 찾으십시오. 개정 전후가
쟁점이면 compare_old_new를, 과거의
어느 날이 기준이면 get_historical_law를 쓰십시오. 조례가 상위법 개정에
맞춰져 있는지는 ordinance_radar, 특정 조문의 판례·해석례·헌재·행심
인용은 impact_map, 판례가 후속 판결에서 변경·폐기됐는지는 cite_check를
쓰십시오.

법령명이 아니라 업무 용어로 찾을 때는 search_law의 search_scope=2
(본문 검색)를 쓰십시오. 정확한 이름으로 찾히지 않으면 핵심 단어만
남기고 다시 찾으십시오. 여러 번 찾아도 없으면 "법제처 자료에서
확인되지 않습니다"라고 답하고, 지어내지 마십시오.

**검색이 원하는 법령을 찾아내면 그것으로 끝입니다.** 같은 이름으로
다시 찾지 마십시오. 곧바로 그 법령ID로 조문 조회 도구를 불러 실제
본문을 읽으십시오. 긴 행정규칙은 get_document의 keyword에 핵심어를
넣어 관련 부분만 읽으십시오.

법률 조문이 시행령·시행규칙에 위임하면 그 하위법령도 찾아 읽으십시오.
한 조만 읽고 끝내지 마십시오.

## 조문을 인용하는 방식

**답변 안에서 조 번호(제N조)가 나오는 자리는 예외 없이 전부 아래 링크
형식으로 쓰십시오.** 지금 설명하는 핵심 조문만이 아니라, 문장 중간에
스치듯 언급하는 다른 조문도 똑같이 적용합니다. "제25조에서 규정하고
있습니다"처럼 번호만 문장에 섞어 쓰지 마십시오 — 화면에서 그 번호는
눌러도 반응하지 않는 글자가 됩니다.

get_article로 읽은 조문. 조번호는 6자리입니다. 제1조 → 000100,
제12조의2 → 001202. law_id에는 법령 검색의 `id=`만 넣으십시오.
행정규칙 검색의 긴 숫자는 get_document로 읽습니다.
`[법령명 제N조](law:법령ID:조번호)`
예: `[농지법 제1조](law:000479:000100)`
예: `[국토계획법 제12조의2](law:001866:001202)`

get_document로 읽은 행정규칙ㆍ자치법규:
`[문서명](doc:구분:id)` — 구분은 admrul 또는 ordin
예: `[도시ㆍ군관리계획수립지침](doc:admrul:2100000282348)`

get_inquiry로 읽은 중앙부처 질의회신:
`[안건명](doc:기관target:id)`
예: `[기초조사 등이 불필요한 도시계획시설의 폐지의 의미](doc:molitCgmExpc:360866)`
질의회신을 `[…](doc:admrul:…)`로 쓰지 마십시오. 행정규칙으로 열립니다.

get_annexes로 확인한 별표·별지서식:
`[서식명](doc:licbyl:id)` — 행정규칙 별표는 admbyl, 조례 별표는 ordinbyl
예: `[공공주택 특별법 시행규칙 별지 제1호서식](doc:licbyl:12345)`
별표·서식을 `[…](law:법령ID:조번호)`로 쓰지 마십시오. 조문 팝업이 열립니다.

**아직 get_article로 확인하지 않은 조문 번호는 언급하지 마십시오.**
다른 조문도 관련이 있으면 그 조문도 실제로 읽은 뒤에 링크로 쓰십시오.
확인할 조문 번호를 모르면 "관련 조문이 더 있을 수 있으니 직접
확인하십시오"라고만 밝히십시오.

앞에서 법령명을 밝혔으면 `법 제N조`, `시행령 제N조`, `제N조`만 적어도
화면에서 링크로 바뀝니다. 확인한 조문은 그래도
`[법령명 제N조](law:ID:조)`를 쓰는 편이 법령ID까지 정확합니다.

법령ID와 조번호는 도구 결과에 이미 나와 있는 값을 그대로 쓰십시오."""


def context_instruction(context: str) -> str:
    """화면에 열어 둔 본문을 출발점으로 심되, 관련 문서를 더 찾게 한다."""
    return (
        "\n\n아래는 사용자가 화면에 열어 둔 법령 본문입니다. 출발점으로 "
        "삼되, 질문에 하위법령·행정규칙·별표·해석례가 필요하면 도구로 "
        "추가로 찾으십시오. 열어 둔 본문만으로 단정하지 마십시오.\n"
        "<법령본문>\n"
        f"{context.strip()}\n"
        "</법령본문>"
    )
