"""search_cases/get_case가 쓰는 결정례 출처 목록."""

from __future__ import annotations

from molit_cgm_expc_api import AgencyConfig
from models.law import EXPC_AGENCY, PREC_AGENCY

_CUSTOMS_AGENCY = AgencyConfig("관세청 법령해석", "kcsCgmExpc")
_CONSTITUTIONAL = AgencyConfig("헌재 결정례", "detc")
_ADMIN_APPEAL = AgencyConfig("행정심판례", "decc")
_TAX_TRIBUNAL = AgencyConfig("조세심판원 재결례", "ttSpecialDecc")
_FTC = AgencyConfig("공정위 결정문", "ftc")
_PIPC = AgencyConfig("개인정보위 결정문", "ppc")
_NLRC = AgencyConfig("노동위 결정문", "nlrc")
_ACR = AgencyConfig("권익위 결정문", "acr")

CASE_SOURCES = {
    "expc": {
        "label": "법령해석례",
        "item": "expc",
        "id": "법령해석례일련번호",
        "title": "안건명",
        "number": "안건번호",
        "date": "회신일자",
        "agency": EXPC_AGENCY,
        "fields": ("질의요지", "회답", "이유", "관련법령"),
    },
    "prec": {
        "label": "판례",
        "item": "prec",
        "id": "판례일련번호",
        "title": "사건명",
        "number": "사건번호",
        "date": "선고일자",
        "agency": PREC_AGENCY,
        "fields": ("판시사항", "판결요지", "참조조문", "참조판례", "판례내용"),
    },
    "central": {
        "label": "중앙부처 질의회신",
        "item": "cgmexpc",
        "id": "법령해석일련번호",
        "title": "안건명",
        "number": "안건번호",
        "date": "해석일자",
        "agency": None,
        "fields": ("질의요지", "회답", "이유", "관련법령"),
    },
    "customs": {
        "label": "관세청 법령해석",
        "item": "cgmexpc",
        "id": "법령해석일련번호",
        "title": "안건명",
        "number": "안건번호",
        "date": "해석일자",
        "agency": _CUSTOMS_AGENCY,
        "fields": ("질의요지", "회답", "이유", "관련법령"),
    },
    "detc": {
        "label": "헌재 결정례",
        "item": "detc",
        "id": "헌재결정례일련번호",
        "title": "사건명",
        "number": "사건번호",
        "date": "종국일자",
        "agency": _CONSTITUTIONAL,
        "fields": ("주문", "이유", "결정요지", "참조조문", "참조판례"),
        "aliases": ("constitutional", "헌재"),
    },
    "decc": {
        "label": "행정심판례",
        "item": "decc",
        "id": "행정심판재결례일련번호",
        "title": "사건명",
        "number": "사건번호",
        "date": "의결일자",
        "agency": _ADMIN_APPEAL,
        "fields": ("주문", "이유", "청구취지", "처분내용"),
        "aliases": ("admin_appeal", "행심"),
    },
    "tax": {
        "label": "조세심판원 재결례",
        "item": "ttspecialdecc",
        "id": "특별행정심판재결례일련번호",
        "title": "사건명",
        "number": "청구번호",
        "date": "의결일자",
        "agency": _TAX_TRIBUNAL,
        "fields": ("주문", "이유", "청구취지", "처분내용"),
        "aliases": ("ttSpecialDecc", "조세심판"),
    },
    "ftc": {
        "label": "공정위 결정문",
        "item": "ftc",
        "id": "결정문일련번호",
        "title": "사건명",
        "number": "사건번호",
        "date": "결정일자",
        "agency": _FTC,
        "fields": ("결정요지", "결정내용", "주문", "이유"),
    },
    "ppc": {
        "label": "개인정보위 결정문",
        "item": "ppc",
        "id": "결정문일련번호",
        "title": "사건명",
        "number": "사건번호",
        "date": "결정일자",
        "agency": _PIPC,
        "fields": ("결정요지", "결정내용", "주문", "이유"),
        "aliases": ("pipc",),
    },
    "nlrc": {
        "label": "노동위 결정문",
        "item": "nlrc",
        "id": "결정문일련번호",
        "title": "사건명",
        "number": "사건번호",
        "date": "결정일자",
        "agency": _NLRC,
        "fields": ("결정요지", "결정내용", "주문", "이유"),
    },
    "acr": {
        "label": "권익위 결정문",
        "item": "acr",
        "id": "결정문일련번호",
        "title": "사건명",
        "number": "사건번호",
        "date": "결정일자",
        "agency": _ACR,
        "fields": ("결정요지", "결정내용", "주문", "이유"),
    },
}

_ALIAS_TO_SOURCE = {}
for _key, _meta in CASE_SOURCES.items():
    _ALIAS_TO_SOURCE[_key] = _key
    for _alias in _meta.get("aliases", ()):
        _ALIAS_TO_SOURCE[str(_alias).casefold()] = _key

SOURCE_CHOICES = (
    "expc(법령해석례), prec(판례), central(중앙부처 질의회신), "
    "customs(관세청), detc(헌재), decc(행정심판), tax(조세심판), "
    "ftc(공정위), ppc(개인정보위), nlrc(노동위), acr(권익위)"
)


def resolve_case_source(source: str) -> dict:
    key = str(source or "expc").strip().casefold()
    resolved = _ALIAS_TO_SOURCE.get(key)
    if resolved is None:
        raise ValueError(f"source는 {SOURCE_CHOICES} 중 하나여야 합니다.")
    return CASE_SOURCES[resolved]
