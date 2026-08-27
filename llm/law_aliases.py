"""법령 약칭을 정식 명칭으로 풀어 검색한다.

법제처 목록 검색은 정식 제명에 강하고 `국토계획법` 같은 실무 약칭에는
약하다. 약칭표를 두고 재검색하되, 풀네임으로 물어봤는데 쿼리와 무관한
법령만 잔뜩 오면 그 결과는 버린다. 없는 법을 있는 것처럼 보여 주는
편이 더 나쁘다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 가운뎃점 표기 차이. 법제처 제명은 ㆍ, 실무·모델 출력은 · 가 흔하다.
_INTERPUNCT = str.maketrans(
    {
        "·": "",
        "ㆍ": "",
        "‧": "",
        "•": "",
        "・": "",
        " ": "",
    }
)

# 업무 용어 → 실제 법령·지침명. 약칭표와 달리 "이 말이 그 문서"라는
# 대응이 확실한 것만 둔다.
RESEARCH_QUERY_ALIASES: dict[str, tuple[str, ...]] = {
    "도시관리계획": (
        "국토의 계획 및 이용에 관한 법률",
        "도시·군관리계획수립지침",
    ),
    "도시군관리계획": (
        "국토의 계획 및 이용에 관한 법률",
        "도시·군관리계획수립지침",
    ),
    "농지전용": ("농지법",),
    "산지전용": ("산지관리법",),
    "개발행위": ("국토의 계획 및 이용에 관한 법률",),
    "도시계획시설": (
        "국토의 계획 및 이용에 관한 법률",
        "도시·군관리계획수립지침",
    ),
}


@dataclass(frozen=True)
class LawAliasEntry:
    canonical: str
    aliases: tuple[str, ...]
    alternatives: tuple[str, ...] = ()


# 실무에서 자주 쓰는 약칭. 정식 제명과 약칭만 적고, 오탈자 추정은 넣지
# 않는다. 짧은 접미사(`법`)는 넣지 않는다 — 아무 법령이나 물어온다.
LAW_ALIAS_ENTRIES: tuple[LawAliasEntry, ...] = (
    LawAliasEntry("대한민국헌법", ("헌법", "헌 법")),
    LawAliasEntry(
        "상법",
        ("상 법", "상사법"),
        ("상법 시행령",),
    ),
    LawAliasEntry(
        "민법",
        ("민 법",),
        ("민법 시행령", "민사소송법", "민사집행법"),
    ),
    LawAliasEntry(
        "형법",
        ("형 법",),
        ("형사소송법",),
    ),
    LawAliasEntry("어음법", ("어 음법",)),
    LawAliasEntry("수표법", ("수 표법",)),
    LawAliasEntry("관세법", ("관세 법",)),
    LawAliasEntry(
        "자유무역협정의 이행을 위한 관세법의 특례에 관한 법률",
        ("fta특례법", "fta 특례법", "fta특례", "에프티에이특례법"),
        ("관세법",),
    ),
    LawAliasEntry(
        "화학물질관리법",
        ("화관법", "화관 법", "화학물질 관리법"),
        ("화학물질관리법 시행령", "화학물질관리법 시행규칙"),
    ),
    LawAliasEntry(
        "행정기본법",
        ("행정법", "행정 법"),
        ("행정절차법", "행정조사기본법", "행정규제기본법"),
    ),
    LawAliasEntry(
        "대외무역법",
        ("무역법",),
        ("관세법",),
    ),
    LawAliasEntry("원산지표시법", ("원산지 표시법", "원산지표시")),
    LawAliasEntry("관세법 시행령", ("관시령", "관세시행령", "관세법시행령")),
    LawAliasEntry(
        "관세법 시행규칙", ("관시규", "관세시행규칙", "관세법시행규칙")
    ),
    LawAliasEntry(
        "지방공무원법",
        ("지공법", "지방공무원 법"),
        ("지방공무원 임용령", "지방공무원 보수규정"),
    ),
    LawAliasEntry("지방공무원 임용령", ("지방공무원임용령", "지공임용령")),
    LawAliasEntry(
        "지방공무원 보수규정", ("지방공무원보수규정", "지공보수규정")
    ),
    LawAliasEntry(
        "산업안전보건법",
        ("산안법",),
        ("산업안전보건법 시행령", "산업안전보건법 시행규칙"),
    ),
    LawAliasEntry(
        "산업안전보건기준에 관한 규칙",
        ("산안기준규칙", "산안규칙", "안전보건기준규칙"),
        ("산업안전보건법",),
    ),
    LawAliasEntry(
        "중대재해 처벌 등에 관한 법률",
        ("중대재해처벌법", "중처법", "중대재해법"),
        ("산업안전보건법",),
    ),
    LawAliasEntry("근로기준법", ("근기법", "근로법")),
    LawAliasEntry(
        "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률",
        ("남녀고용평등법", "고평법"),
    ),
    LawAliasEntry(
        "개인정보 보호법", ("개보법", "개인정보법", "개인정보보호법")
    ),
    LawAliasEntry(
        "정보통신망 이용촉진 및 정보보호 등에 관한 법률",
        ("정보통신망법", "정통망법"),
    ),
    LawAliasEntry(
        "인공지능 발전과 신뢰 기반 조성 등에 관한 기본법",
        ("인공지능기본법", "인공지능법", "ai기본법", "ai법"),
    ),
    LawAliasEntry(
        "부정청탁 및 금품등 수수의 금지에 관한 법률",
        ("청탁금지법", "김영란법"),
    ),
    LawAliasEntry(
        "공직자의 이해충돌 방지법",
        ("이해충돌방지법", "공직자이해충돌방지법"),
    ),
    LawAliasEntry(
        "국가를 당사자로 하는 계약에 관한 법률",
        ("국가계약법",),
    ),
    LawAliasEntry(
        "지방자치단체를 당사자로 하는 계약에 관한 법률",
        ("지방계약법",),
    ),
    LawAliasEntry("공공기관의 정보공개에 관한 법률", ("정보공개법",)),
    LawAliasEntry(
        "부동산 거래신고 등에 관한 법률",
        ("부동산거래신고법", "부거법"),
    ),
    LawAliasEntry("주택임대차보호법", ("주임법",)),
    LawAliasEntry("상가건물 임대차보호법", ("상임법", "상가임대차법")),
    LawAliasEntry("소방시설 설치 및 관리에 관한 법률", ("소방시설법",)),
    LawAliasEntry("국세기본법", ("국기법",)),
    LawAliasEntry("부가가치세법", ("부가세법",)),
    LawAliasEntry(
        "독점규제 및 공정거래에 관한 법률",
        ("공정거래법", "공거법", "독점규제법"),
    ),
    LawAliasEntry("하도급거래 공정화에 관한 법률", ("하도급법",)),
    LawAliasEntry("약관의 규제에 관한 법률", ("약관법", "약관규제법")),
    LawAliasEntry("표시ㆍ광고의 공정화에 관한 법률", ("표시광고법",)),
    LawAliasEntry(
        "가맹사업거래의 공정화에 관한 법률", ("가맹사업법", "가맹법")
    ),
    LawAliasEntry(
        "전자상거래 등에서의 소비자보호에 관한 법률",
        ("전자상거래법", "전상법"),
    ),
    LawAliasEntry(
        "신용정보의 이용 및 보호에 관한 법률", ("신용정보법", "신정법")
    ),
    LawAliasEntry(
        "자본시장과 금융투자업에 관한 법률", ("자본시장법", "자시법")
    ),
    LawAliasEntry(
        "특정 금융거래정보의 보고 및 이용 등에 관한 법률",
        ("특정금융정보법", "특금법"),
    ),
    LawAliasEntry("전자금융거래법", ("전금법",)),
    LawAliasEntry(
        "국토의 계획 및 이용에 관한 법률",
        ("국토계획법", "국계법", "국토이용법"),
        ("국토의 계획 및 이용에 관한 법률 시행령",),
    ),
    LawAliasEntry("도시 및 주거환경정비법", ("도시정비법", "도정법")),
    LawAliasEntry(
        "감염병의 예방 및 관리에 관한 법률", ("감염병예방법", "감염병법")
    ),
    LawAliasEntry("대기환경보전법", ("대기환경법", "대기법")),
    LawAliasEntry(
        "도로교통법",
        ("도교법", "도로교통 법"),
        ("도로교통법 시행령", "도로교통법 시행규칙"),
    ),
    LawAliasEntry("여객자동차 운수사업법", ("여객운수법", "여객자동차법")),
    LawAliasEntry("화물자동차 운수사업법", ("화물운수법", "화운법")),
    LawAliasEntry("민사소송법", ("민소법",)),
    LawAliasEntry("형사소송법", ("형소법",)),
    LawAliasEntry("민사집행법", ("민집법",)),
    LawAliasEntry("국민건강보험법", ("국건법", "건보법")),
    LawAliasEntry("산업재해보상보험법", ("산재보험법", "산재법")),
    LawAliasEntry("고용보험법", ("고보법",)),
    LawAliasEntry("전기통신사업법", ("전기통신법", "전사법")),
    LawAliasEntry("산지관리법", ("산지법",)),
    LawAliasEntry(
        "개발제한구역의 지정 및 관리에 관한 특별조치법",
        ("개발제한구역법", "그린벨트법"),
    ),
    LawAliasEntry(
        "산업입지 및 개발에 관한 법률",
        ("산업입지법",),
        ("산업입지 및 개발에 관한 법률 시행령",),
    ),
    LawAliasEntry("건축법", ("건축 법",)),
)


def compact_law_key(value: str) -> str:
    """비교용으로 공백·가운뎃점을 없앤다."""
    return str(value or "").translate(_INTERPUNCT).casefold()


def display_alias(law_name: str) -> str:
    """정식 명칭이면 실무 약칭을 돌려준다. 이미 짧은 이름이면 비운다.

    공백만 다른 표기(`건축 법`)는 약칭이 아니므로 건너뛴다.
    """
    name = " ".join(str(law_name or "").split())
    if not name:
        return ""
    entry = _ALIAS_LOOKUP.get(compact_law_key(name))
    if entry is not None:
        for alias in entry.aliases:
            if compact_law_key(alias) != compact_law_key(name):
                return alias
        return ""
    for tail in ("시행규칙", "시행령"):
        if not name.endswith(tail):
            continue
        base = name[: -len(tail)].strip()
        base_entry = _ALIAS_LOOKUP.get(compact_law_key(base))
        if base_entry is None:
            continue
        for alias in base_entry.aliases:
            if compact_law_key(alias) != compact_law_key(base):
                return f"{alias} {tail}"
    return ""


def _alias_lookup() -> dict[str, LawAliasEntry]:
    table: dict[str, LawAliasEntry] = {}
    for entry in LAW_ALIAS_ENTRIES:
        table[compact_law_key(entry.canonical)] = entry
        for alias in entry.aliases:
            table[compact_law_key(alias)] = entry
    return table


_ALIAS_LOOKUP = _alias_lookup()


@dataclass(frozen=True)
class AliasResolution:
    canonical: str
    matched_alias: str = ""
    alternatives: tuple[str, ...] = ()


def resolve_law_alias(query: str) -> AliasResolution:
    """쿼리 전체가 약칭이면 정식 명칭을 돌려준다."""
    cleaned = " ".join(str(query or "").split()).strip()
    if not cleaned:
        return AliasResolution(canonical="")
    entry = _ALIAS_LOOKUP.get(compact_law_key(cleaned))
    if entry is None:
        return AliasResolution(canonical=cleaned)
    matched = ""
    for alias in entry.aliases:
        if compact_law_key(alias) == compact_law_key(cleaned):
            matched = alias
            break
    return AliasResolution(
        canonical=entry.canonical,
        matched_alias=matched,
        alternatives=entry.alternatives,
    )


def expand_search_queries(query: str) -> list[str]:
    """원문 다음에 약칭·업무용어로 풀어 쓴 검색어를 붙인다."""
    cleaned = " ".join(str(query or "").split()).strip()
    seen: list[str] = []

    def add(value: str) -> None:
        text = " ".join(str(value or "").split()).strip()
        if text and text not in seen:
            seen.append(text)

    add(cleaned)
    resolved = resolve_law_alias(cleaned)
    add(resolved.canonical)
    for alternative in resolved.alternatives:
        add(alternative)

    compact_query = compact_law_key(cleaned)
    candidates: list[tuple[str, LawAliasEntry]] = []
    for entry in LAW_ALIAS_ENTRIES:
        for alias in entry.aliases:
            key = compact_law_key(alias)
            if len(key) < 2:
                continue
            candidates.append((key, entry))
    candidates.sort(key=lambda item: len(item[0]), reverse=True)
    used_canonicals: set[str] = set()
    for key, entry in candidates:
        if entry.canonical in used_canonicals:
            continue
        if compact_query == key:
            continue
        if key not in compact_query:
            continue
        used_canonicals.add(entry.canonical)
        add(cleaned.replace(key, entry.canonical))
        # 붙여 쓴 약칭(`국토계획법`)은 원문에 공백이 없어 replace가
        # 실패할 수 있다. 그때는 정식 명칭만 추가로 넣는다.
        add(entry.canonical)

    compact_core = compact_query
    for phrase, replacements in RESEARCH_QUERY_ALIASES.items():
        if compact_law_key(phrase) in compact_core:
            for replacement in replacements:
                add(replacement)
    return seen


def name_matches_query(query: str, name: str, short_name: str = "") -> bool:
    """검색어와 결과 법령명이 서로 포함 관계이거나 약칭이 같은지."""
    query_key = compact_law_key(query)
    name_key = compact_law_key(name)
    short_key = compact_law_key(short_name)
    if not query_key or not name_key:
        return False
    if query_key in name_key or name_key in query_key:
        return True
    if short_key and (query_key == short_key or query_key in short_key):
        return True
    canonical = compact_law_key(resolve_law_alias(query).canonical)
    if canonical and (canonical in name_key or name_key in canonical):
        return True
    if short_key and canonical and canonical == short_key:
        return True
    return False


def _loose_law_name(requested: str, official: str) -> bool:
    """공백·가운뎃점을 접은 뒤 같거나 접두인지만 본다.

    `민법` ⊂ `난민법` 같은 LIKE 부분문자열은 여기서 거절한다. 조례
    정비·영향 맵이 무관 법령의 시행일로 단정하지 않게 하는 가드다.
    """
    target = compact_law_key(requested)
    official_key = compact_law_key(official)
    if not target or not official_key:
        return False
    if official_key == target or official_key.startswith(target):
        return True
    stripped = official_key
    if stripped.endswith("법률"):
        stripped = stripped[:-2] + "법"
    return bool(stripped) and target.startswith(stripped)


def resolved_law_matches(
    requested: str, official_name: str, short_name: str = ""
) -> bool:
    """검색 1위가 요청한 법령과 실제로 같은지.

    정확 일치가 없을 때 LIKE 1위를 그대로 쓰지 않는다.
    """
    if _loose_law_name(requested, official_name):
        return True
    if short_name and _loose_law_name(requested, short_name):
        return True
    canonical = resolve_law_alias(requested).canonical
    if compact_law_key(canonical) == compact_law_key(requested):
        return False
    if _loose_law_name(canonical, official_name):
        return True
    return bool(short_name) and _loose_law_name(canonical, short_name)


def has_related_hit(
    query: str, names: list[tuple[str, str]]
) -> bool:
    """풀네임 재검색 결과가 쿼리와 무관한 상위 건만이면 채택하지 않는다."""
    return any(name_matches_query(query, name, short) for name, short in names)


def score_law_relevance(law_name: str, query: str) -> int:
    """법제처 LIKE 결과에서 요청한 법령명을 앞으로 보낸다.

    '민법'이 '난민법'보다 뒤에 오는 일을 막기 위한 점수다. 현행/연혁
    정렬과 따로 매겨 첫 결과를 덜 엉뚱하게 고른다.
    """
    name_key = compact_law_key(law_name)
    query_key = compact_law_key(query)
    canonical = compact_law_key(resolve_law_alias(query).canonical)
    score = 0
    if name_key and query_key:
        if name_key == query_key or name_key == canonical:
            score += 120
        elif query_key in name_key:
            score += 80
        elif name_key in query_key:
            score += 70
        else:
            for word in str(query or "").split():
                if compact_law_key(word) and compact_law_key(word) in name_key:
                    score += 10
    if not re.search(r"시행령|시행규칙", law_name or ""):
        score += 5
    return score
