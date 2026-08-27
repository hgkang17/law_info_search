"""검색 대상 분류와 기관 설정. API 응답을 읽는 기준이 된다."""

from __future__ import annotations

from molit_cgm_expc_api import AgencyConfig


RESOURCE_ALL_TARGET = "__all__"


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


EXPC_AGENCY = AgencyConfig("법령해석례", "expc")


PREC_AGENCY = AgencyConfig("판례", "prec")


AI_SEARCH_AGENCY = AgencyConfig("지능형 법령검색", "aiSearch", False)


AI_RELATED_AGENCY = AgencyConfig("연관법령", "aiRltLs", False)
