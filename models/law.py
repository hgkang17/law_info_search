"""검색 대상 분류와 기관 설정. API 응답을 읽는 기준이 된다."""

from __future__ import annotations

from molit_cgm_expc_api import AgencyConfig


RESOURCE_ALL_TARGET = "__all__"


# 연관검색ㆍ직접검색은 법령검색 탭의 카테고리로 함께 보여 준다. 값은
# AiLawSearchTab의 service 이름과 같아야 저장내역ㆍ열람내역 복원이 그대로
# 이어진다.
KEYWORD_RELATED_TARGET = "ai_related"
KEYWORD_DIRECT_TARGET = "ai_search"
KEYWORD_CATEGORY_LABELS = {
    KEYWORD_RELATED_TARGET: "연관검색",
    # 화면에 보이는 이름. "직접검색"은 무엇을 곧바로 찾는다는 것인지
    # 알기 어려워, 실제로 찾는 대상인 조문을 그대로 쓴다.
    KEYWORD_DIRECT_TARGET: "조문검색",
}

# 카테고리 바의 캡슐 이름. 이 캡슐은 조문검색(직접) 하나만 맡는다.
# 연관검색은 따로 자리를 두지 않고 통합검색 결과 안에 "AI추천" 구분으로
# 섞어 보여 준다. 두 화면을 오가며 같은 키워드를 두 번 넣는 일이 잦았다.
KEYWORD_CATEGORY_LABEL = KEYWORD_CATEGORY_LABELS[KEYWORD_DIRECT_TARGET]

# 통합검색 목록에서 지능형 검색(연관ㆍ조문) 결과에 붙이는 구분 이름.
# 어느 API에서 왔는지가 아니라 "AI가 추천한 조문"이라는 성격을 밝힌다.
KEYWORD_INTEGRATED_LABEL = "AI추천"


# 별표ㆍ서식은 법령ㆍ행정규칙ㆍ자치법규 세 API로 나뉘어 있다. 카테고리
# 바에서는 하나로 묶고, 화면 안 대상 콤보로 고른다. ``__annex_all__``은
# 세 대상을 한 번에 부른 뒤 결과를 합쳐 보여 주는 자리다.
ANNEX_ALL_TARGET = "__annex_all__"
ANNEX_TARGETS = ("licbyl", "admbyl", "ordinbyl")
# 맨 위가 기본값이다. 어느 자료에 있는지 모르고 찾는 경우가 많아 전체를
# 앞에 두고 기본으로 삼는다.
ANNEX_TARGET_ITEMS = (
    ("전체", ANNEX_ALL_TARGET),
    ("법령", "licbyl"),
    ("행정규칙", "admbyl"),
    ("자치법규", "ordinbyl"),
)


# 분류 단추 아래에 작게 붙는 부제. 그 분류가 무엇을 포함하는지 알려 준다.
CATEGORY_SUBTITLES = {
    "law": "법률·대통령령·부령",
    "admrul": "훈령·예규·고시",
    "ordin": "조례·규칙",
}


RESOURCE_CATEGORIES = {
    "law": {
        "label": "법령",
        "group": "law",
        "root": "LawSearch",
        "item": "law",
        "id": "법령ID",
        "name": "법령명한글",
        "organization": "소관부처명",
        "date": "공포일자",
        "number": "공포번호",
        "effective": "시행일자",
        "detail_target": "eflaw",
        "id_param": "ID",
    },
    "licbyl": {
        "label": "법령 별표·서식",
        "tab_label": "별표·서식",
        "group": "law",
        "root": "licBylSearch",
        "item": "licbyl",
        "id": "별표일련번호",
        "name": "별표명",
        "related": "관련법령명",
        "organization": "소관부처명",
        "date": "공포일자",
        "number": "공포번호",
        "effective": "",
    },
    "admrul": {
        "label": "행정규칙",
        "group": "admrul",
        "root": "AdmRulSearch",
        "item": "admrul",
        "id": "행정규칙일련번호",
        "name": "행정규칙명",
        "organization": "소관부처명",
        "date": "발령일자",
        "number": "발령번호",
        "effective": "시행일자",
        "detail_target": "admrul",
        "id_param": "ID",
    },
    "admbyl": {
        "label": "행정규칙 별표·서식",
        "tab_label": "별표·서식",
        "group": "admrul",
        "root": "admRulBylSearch",
        "item": "admrulbyl",
        "id": "별표일련번호",
        "name": "별표명",
        "related": "관련행정규칙명",
        "organization": "소관부처명",
        "date": "발령일자",
        "number": "발령번호",
        "effective": "",
    },
    "ordin": {
        "label": "자치법규",
        "group": "ordin",
        "root": "OrdinSearch",
        "item": "law",
        "id": "자치법규일련번호",
        "name": "자치법규명",
        "organization": "지자체기관명",
        "date": "공포일자",
        "number": "공포번호",
        "effective": "시행일자",
        "detail_target": "ordin",
        "id_param": "MST",
    },
    "ordinbyl": {
        "label": "자치법규 별표·서식",
        "tab_label": "별표·서식",
        "group": "ordin",
        "root": "licBylSearch",
        "item": "ordinbyl",
        "id": "별표일련번호",
        "name": "별표명",
        "related": "관련자치법규명",
        "organization": "지자체기관명",
        "date": "공포일자",
        "number": "공포번호",
        "effective": "",
    },
}


# 목록 조회 API의 ``search`` 값. 법령ㆍ행정규칙ㆍ자치법규는 1이 이름,
# 2가 본문검색이다(법제처 OPEN API 가이드 lsEfYdListGuide·admrulListGuide·
# ordinListGuide에서 확인). 별표ㆍ서식만 2가 해당 법령명, 3이 별표 본문이라
# 구성이 다르다. 여기 없는 분류는 범위를 고르지 않고 항상 1로 부른다.
SEARCH_SCOPE_ITEMS = {
    "law": (("법령명", 1), ("본문검색", 2)),
    "admrul": (("행정규칙명", 1), ("본문검색", 2)),
    "ordin": (("자치법규명", 1), ("본문검색", 2)),
    "licbyl": (("별표·서식명", 1), ("해당 법령명", 2), ("별표 본문", 3)),
    "admbyl": (("별표·서식명", 1), ("해당 행정규칙명", 2), ("별표 본문", 3)),
    "ordinbyl": (("별표·서식명", 1), ("해당 자치법규명", 2), ("별표 본문", 3)),
    ANNEX_ALL_TARGET: (
        ("별표·서식명", 1),
        ("해당 법령·규칙명", 2),
        ("별표 본문", 3),
    ),
}


# 고른 검색범위에 맞춰 입력칸에 띄우는 안내.
SEARCH_SCOPE_PLACEHOLDERS = {
    "law": {
        1: "검색할 법령명을 입력하세요",
        2: "법령 본문에서 찾을 단어를 입력하세요",
    },
    "admrul": {
        1: "검색할 행정규칙명을 입력하세요",
        2: "행정규칙 본문에서 찾을 단어를 입력하세요",
    },
    "ordin": {
        1: "검색할 자치법규명을 입력하세요",
        2: "자치법규 본문에서 찾을 단어를 입력하세요",
    },
    "licbyl": {
        1: "검색할 별표·서식명을 입력하세요",
        2: "별표·서식을 찾을 법령명을 입력하세요",
        3: "별표 본문에서 찾을 단어를 입력하세요",
    },
    "admbyl": {
        1: "검색할 별표·서식명을 입력하세요",
        2: "별표·서식을 찾을 행정규칙명을 입력하세요",
        3: "별표 본문에서 찾을 단어를 입력하세요",
    },
    "ordinbyl": {
        1: "검색할 별표·서식명을 입력하세요",
        2: "별표·서식을 찾을 자치법규명을 입력하세요",
        3: "별표 본문에서 찾을 단어를 입력하세요",
    },
    ANNEX_ALL_TARGET: {
        1: "검색할 별표·서식명을 입력하세요",
        2: "별표·서식을 찾을 법령·행정규칙·자치법규명을 입력하세요",
        3: "별표 본문에서 찾을 단어를 입력하세요",
    },
}


EXPC_AGENCY = AgencyConfig("법령해석례", "expc")


PREC_AGENCY = AgencyConfig("판례", "prec")


AI_SEARCH_AGENCY = AgencyConfig("지능형 법령검색", "aiSearch", False)


AI_RELATED_AGENCY = AgencyConfig("연관법령", "aiRltLs", False)
