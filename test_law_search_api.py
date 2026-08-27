"""
국가법령정보 Open API 테스트 스크립트 (법령 / 행정규칙 / 자치법규)

law.go.kr Open API 가이드(https://open.law.go.kr/LSO/openApi/guideResult.do)의
목록조회·본문조회 설명을 참고해 작성한 최소 테스트 코드입니다.
실행 시 조회 대상(법령/행정규칙/자치법규)과 검색어를 입력하면
목록을 보여주고, 번호를 선택하면 해당 문서의 본문을 조회합니다.

공통
  - OC     : API 인증키(이메일 아이디). LAW_API_OC 환경변수 또는 실행 시 입력.
  - type   : 응답 형식(JSON 고정)
  - 법제처 API는 Referer/User-Agent가 없는 요청을 사용자 검증 실패로 처리하는
    경우가 있어 REQUEST_HEADERS를 항상 같이 보냄.

[1] 법령
  목록: lawSearch.do?target=law        (query, display, page)
  본문: lawService.do?target=eflaw     (ID=법령ID. ID 입력 시 efYd는 무시되므로 생략)
  본문 응답: 법령>조문>조문단위 리스트, 조문 하위에 항->호->목이 중첩될 수 있음.

[2] 행정규칙
  목록: lawSearch.do?target=admrul     (query, display, page)
  본문: lawService.do?target=admrul    (ID=행정규칙일련번호)
  본문 응답: AdmRulService>조문내용 이 통 텍스트 하나로 내려오며 항목 구분에
            전각공백(\\u3000)이 쓰이는 것으로 실제 호출 결과에서 확인됨.

[3] 자치법규
  목록: lawSearch.do?target=ordin      (query, display, page)
  본문: lawService.do?target=ordin     (MST=자치법규일련번호)
  본문 응답: LawService>조문>조 리스트, 각 조는 조내용 하나에 항목이 모두
            포함되어 내려옴(조문여부 "N"=장/절 제목, "Y"=조문).

[4/5/6] 별표서식 (법령/행정규칙/자치법규)
  목록: lawSearch.do?target=licbyl|admbyl|ordinbyl  (query, display, page)
  별표서식은 이미지/HWP/PDF 형태의 첨부파일이라 lawService.do가 JSON을 지원하지
  않고(type=JSON을 줘도 HTML이 내려오는 것을 실제 호출로 확인) 별도 "본문 조회"가
  없음. 대신 목록 응답에 첨부파일 다운로드 링크와 상세페이지(HTML) 링크가 같이
  내려오므로, 번호 선택 시 그 링크들을 출력함.

[7] 법령정보지식베이스 법령용어
  목록: lawSearch.do?target=lstrmAI    (query, display, page)
  이것도 별도 "본문 조회"가 없는 목록형 API. 응답의 각 법령용어 항목에
  "용어간관계링크"(target=lstrmRlt)·"조문간관계링크"(target=lstrmRltJo)라는
  관련 API 링크가 같이 내려오길래, 번호 선택 시 동음이의어 여부·비고와 함께
  그 링크들을 보여줌(관련 API 자체를 호출해서 파싱하는 것까지는 구현하지 않음).
  총 결과 개수 필드명이 다른 target들과 달리 "totalCnt"가 아니라
  "검색결과개수"인 것도 실제 호출로 확인됨.

사용 전 준비물
  pip install requests
"""

import sys
import json
import re
import html
import os

import requests

SEARCH_URL = "https://www.law.go.kr/DRF/lawSearch.do"
DETAIL_URL = "https://www.law.go.kr/DRF/lawService.do"
OC = os.environ.get("LAW_API_OC", "").strip()

REQUEST_HEADERS = {
    "Referer": "https://www.law.go.kr/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Python requests",
}


def _request(url: str, params: dict) -> dict:
    res = requests.get(url, params=params, headers=REQUEST_HEADERS, timeout=10)
    res.raise_for_status()
    return res.json()


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _clean_text(text: str) -> str:
    """행정규칙/자치법규 본문에 섞인 HTML 태그·전각공백을 정리."""
    text = html.unescape(text or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("　", "\n")
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def _strip_tags(text: str) -> str:
    """검색어 강조용으로 붙는 <strong> 등의 태그를 제목류 문자열에서 제거."""
    return re.sub(r"<[^>]+>", "", html.unescape(text or "")).strip()


def _full_url(path: str) -> str:
    if path and path.startswith("/"):
        return f"https://www.law.go.kr{path}"
    return path


# ===================== 1) 법령 =====================

def search_law(query: str, display: int = 20, page: int = 1) -> dict:
    return _request(SEARCH_URL, {
        "OC": OC, "target": "law", "type": "JSON",
        "query": query, "display": display, "page": page,
    })


def get_law_detail(law_id: str) -> dict:
    return _request(DETAIL_URL, {
        "OC": OC, "target": "eflaw", "type": "JSON", "ID": law_id,
    })


def print_law_list(data: dict) -> list:
    search = data.get("LawSearch")
    if search is None:
        print("응답에 LawSearch 항목이 없습니다. 원본 응답:")
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return []

    print(f"\n총 검색 결과: {search.get('totalCnt', '?')}건\n")
    laws = _as_list(search.get("law"))
    if not laws:
        print("검색 결과가 없습니다.")
        return []

    items = []
    for i, law in enumerate(laws, start=1):
        name = law.get("법령명한글", "")
        law_id = law.get("법령ID", "")
        print(f"[{i}] {name}")
        print(f"    법령ID: {law_id} | 공포일자: {law.get('공포일자', '')} "
              f"(제{law.get('공포번호', '')}호) | 시행일자: {law.get('시행일자', '')} | "
              f"소관부처: {law.get('소관부처명', '')} | 구분: {law.get('제개정구분명', '')}")
        items.append((name, law_id, law))
    return items


def _print_hang_ho_mok(node: dict, indent: int) -> None:
    content = node.get("항내용") or node.get("호내용") or node.get("목내용")
    if content:
        print("    " * indent + content)
    for key in ("호", "목"):
        for child in _as_list(node.get(key)):
            _print_hang_ho_mok(child, indent + 1)


def print_law_detail(data: dict) -> None:
    law = data.get("법령")
    if law is None:
        print("응답에 법령 항목이 없습니다. 원본 응답:")
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    basic = law.get("기본정보", {})
    dept = basic.get("소관부처", {})
    dept_name = dept.get("content", "") if isinstance(dept, dict) else dept

    print("\n" + "=" * 72)
    print(basic.get("법령명_한글", ""))
    print("=" * 72)
    print(f"공포일자: {basic.get('공포일자', '')} (제{basic.get('공포번호', '')}호) | "
          f"시행일자: {basic.get('시행일자', '')} | 소관부처: {dept_name}")

    units = _as_list(law.get("조문", {}).get("조문단위"))
    if not units:
        print("\n조문 내용을 찾지 못했습니다.")
        return

    print()
    for unit in units:
        if unit.get("조문여부") == "전문":  # 장/절 표제
            print(f"\n  {(unit.get('조문내용') or '').strip()}")
            continue
        print("\n" + (unit.get("조문내용") or "").strip())
        for hang in _as_list(unit.get("항")):
            _print_hang_ho_mok(hang, 1)


# ===================== 2) 행정규칙 =====================

def search_admrul(query: str, display: int = 20, page: int = 1) -> dict:
    return _request(SEARCH_URL, {
        "OC": OC, "target": "admrul", "type": "JSON",
        "query": query, "display": display, "page": page,
    })


def get_admrul_detail(admrul_sn: str) -> dict:
    return _request(DETAIL_URL, {
        "OC": OC, "target": "admrul", "type": "JSON", "ID": admrul_sn,
    })


def print_admrul_list(data: dict) -> list:
    search = data.get("AdmRulSearch")
    if search is None:
        print("응답에 AdmRulSearch 항목이 없습니다. 원본 응답:")
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return []

    print(f"\n총 검색 결과: {search.get('totalCnt', '?')}건\n")
    rules = _as_list(search.get("admrul"))
    if not rules:
        print("검색 결과가 없습니다.")
        return []

    items = []
    for i, rule in enumerate(rules, start=1):
        name = rule.get("행정규칙명", "")
        rule_sn = rule.get("행정규칙일련번호", "")
        print(f"[{i}] {name}")
        print(f"    발령일자: {rule.get('발령일자', '')} (제{rule.get('발령번호', '')}호) | "
              f"시행일자: {rule.get('시행일자', '')} | 소관부처: {rule.get('소관부처명', '')} | "
              f"종류: {rule.get('행정규칙종류', '')} | 구분: {rule.get('제개정구분명', '')}")
        items.append((name, rule_sn, rule))
    return items


def print_admrul_detail(data: dict) -> None:
    svc = data.get("AdmRulService")
    if svc is None:
        print("응답에 AdmRulService 항목이 없습니다. 원본 응답:")
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    info = svc.get("행정규칙기본정보", {})
    print("\n" + "=" * 72)
    print(info.get("행정규칙명", ""))
    print("=" * 72)
    print(f"발령일자: {info.get('발령일자', '')} (제{info.get('발령번호', '')}호) | "
          f"시행일자: {info.get('시행일자', '')} | 소관부처: {info.get('소관부처명', '')} | "
          f"종류: {info.get('행정규칙종류', '')}")

    body = _clean_text(svc.get("조문내용", ""))
    print(f"\n{body}" if body else "\n본문 내용을 찾지 못했습니다.")

    appendix = _clean_text(svc.get("부칙", ""))
    if appendix:
        print(f"\n[부칙]\n{appendix}")


# ===================== 3) 자치법규 =====================

def search_ordin(query: str, display: int = 20, page: int = 1) -> dict:
    return _request(SEARCH_URL, {
        "OC": OC, "target": "ordin", "type": "JSON",
        "query": query, "display": display, "page": page,
    })


def get_ordin_detail(ordin_mst: str) -> dict:
    return _request(DETAIL_URL, {
        "OC": OC, "target": "ordin", "type": "JSON", "MST": ordin_mst,
    })


def print_ordin_list(data: dict) -> list:
    search = data.get("OrdinSearch")
    if search is None:
        print("응답에 OrdinSearch 항목이 없습니다. 원본 응답:")
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return []

    print(f"\n총 검색 결과: {search.get('totalCnt', '?')}건\n")
    ordins = _as_list(search.get("law"))
    if not ordins:
        print("검색 결과가 없습니다.")
        return []

    items = []
    for i, ordin in enumerate(ordins, start=1):
        name = ordin.get("자치법규명", "")
        mst = ordin.get("자치법규일련번호", "")
        print(f"[{i}] {name}")
        print(f"    지자체: {ordin.get('지자체기관명', '')} | 공포일자: {ordin.get('공포일자', '')} "
              f"(제{ordin.get('공포번호', '')}호) | 시행일자: {ordin.get('시행일자', '')} | "
              f"종류: {ordin.get('자치법규종류', '')} | 구분: {ordin.get('제개정구분명', '')}")
        items.append((name, mst, ordin))
    return items


def print_ordin_detail(data: dict) -> None:
    svc = data.get("LawService")
    if svc is None:
        print("응답에 LawService 항목이 없습니다. 원본 응답:")
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    info = svc.get("자치법규기본정보", {})
    print("\n" + "=" * 72)
    print(info.get("자치법규명", ""))
    print("=" * 72)
    print(f"지자체: {info.get('지자체기관명', '')} | 공포일자: {info.get('공포일자', '')} "
          f"(제{info.get('공포번호', '')}호) | 시행일자: {info.get('시행일자', '')}")

    articles = _as_list(svc.get("조문", {}).get("조"))
    if not articles:
        print("\n조문 내용을 찾지 못했습니다.")
        return

    print()
    for article in articles:
        content = _clean_text(article.get("조내용", ""))
        if not content:
            continue
        if article.get("조문여부") == "N":  # 장/절 표제
            print(f"\n  {content}")
        else:
            print(f"\n{content}")


# ===================== 4) 법령 별표서식 =====================

def search_licbyl(query: str, display: int = 20, page: int = 1) -> dict:
    return _request(SEARCH_URL, {
        "OC": OC, "target": "licbyl", "type": "JSON",
        "query": query, "display": display, "page": page,
    })


def print_licbyl_list(data: dict) -> list:
    search = data.get("licBylSearch")
    if search is None:
        print("응답에 licBylSearch 항목이 없습니다. 원본 응답:")
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return []

    print(f"\n총 검색 결과: {search.get('totalCnt', '?')}건\n")
    forms = _as_list(search.get("licbyl"))
    if not forms:
        print("검색 결과가 없습니다.")
        return []

    items = []
    for i, form in enumerate(forms, start=1):
        name = _strip_tags(form.get("별표명", ""))
        law_name = _strip_tags(form.get("관련법령명", ""))
        print(f"[{i}] {name}")
        print(f"    관련법령: {law_name} | 별표종류: {form.get('별표종류', '')} | "
              f"공포일자: {form.get('공포일자', '')} (제{form.get('공포번호', '')}호) | "
              f"소관부처: {form.get('소관부처명', '')}")
        items.append((name, form.get("별표일련번호", ""), form))
    return items


# ===================== 5) 행정규칙 별표서식 =====================

def search_admbyl(query: str, display: int = 20, page: int = 1) -> dict:
    return _request(SEARCH_URL, {
        "OC": OC, "target": "admbyl", "type": "JSON",
        "query": query, "display": display, "page": page,
    })


def print_admbyl_list(data: dict) -> list:
    search = data.get("admRulBylSearch")
    if search is None:
        print("응답에 admRulBylSearch 항목이 없습니다. 원본 응답:")
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return []

    print(f"\n총 검색 결과: {search.get('totalCnt', '?')}건\n")
    forms = _as_list(search.get("admrulbyl"))
    if not forms:
        print("검색 결과가 없습니다.")
        return []

    items = []
    for i, form in enumerate(forms, start=1):
        name = _strip_tags(form.get("별표명", ""))
        rule_name = _strip_tags(form.get("관련행정규칙명", ""))
        print(f"[{i}] {name}")
        print(f"    관련행정규칙: {rule_name} | 별표종류: {form.get('별표종류', '')} | "
              f"발령일자: {form.get('발령일자', '')} (제{form.get('발령번호', '')}호) | "
              f"소관부처: {form.get('소관부처명', '')}")
        items.append((name, form.get("별표일련번호", ""), form))
    return items


# ===================== 6) 자치법규 별표서식 =====================

def search_ordinbyl(query: str, display: int = 20, page: int = 1) -> dict:
    return _request(SEARCH_URL, {
        "OC": OC, "target": "ordinbyl", "type": "JSON",
        "query": query, "display": display, "page": page,
    })


def print_ordinbyl_list(data: dict) -> list:
    # 이 API는 목록 응답의 최상위 키를 licbyl과 동일하게 "licBylSearch"로 내려줌
    # (law.go.kr 실제 호출 결과로 확인됨. 문서에는 안내되지 않은 부분).
    search = data.get("licBylSearch")
    if search is None:
        print("응답에 licBylSearch 항목이 없습니다. 원본 응답:")
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return []

    print(f"\n총 검색 결과: {search.get('totalCnt', '?')}건\n")
    forms = _as_list(search.get("ordinbyl"))
    if not forms:
        print("검색 결과가 없습니다.")
        return []

    items = []
    for i, form in enumerate(forms, start=1):
        name = _strip_tags(form.get("별표명", ""))
        ordin_name = _strip_tags(form.get("관련자치법규명", ""))
        print(f"[{i}] {name}")
        print(f"    관련자치법규: {ordin_name} | 지자체: {form.get('지자체기관명', '')} | "
              f"별표종류: {form.get('별표종류', '')} | 공포일자: {form.get('공포일자', '')} "
              f"(제{form.get('공포번호', '')}호)")
        items.append((name, form.get("별표일련번호", ""), form))
    return items


def print_byl_links(item: dict) -> None:
    """별표서식은 JSON 본문 API가 없어, 목록 응답에 같이 내려오는
    첨부파일·상세페이지 링크를 그대로 보여준다."""
    detail_link = (
        item.get("별표법령상세링크")
        or item.get("별표행정규칙상세링크")
        or item.get("별표자치법규상세링크")
        or ""
    )
    file_link = item.get("별표서식파일링크", "")
    pdf_link = item.get("별표서식PDF파일링크", "")

    print()
    if detail_link:
        print(f"상세보기(웹): {_full_url(detail_link)}")
    if file_link:
        print(f"첨부파일 다운로드: {_full_url(file_link)}")
    if pdf_link:
        print(f"PDF 다운로드: {_full_url(pdf_link)}")
    if not (detail_link or file_link or pdf_link):
        print("다운로드/상세 링크를 찾지 못했습니다.")


# ===================== 7) 법령정보지식베이스 법령용어 =====================

def search_lstrmai(query: str, display: int = 20, page: int = 1) -> dict:
    return _request(SEARCH_URL, {
        "OC": OC, "target": "lstrmAI", "type": "JSON",
        "query": query, "display": display, "page": page,
    })


def print_lstrmai_list(data: dict) -> list:
    search = data.get("lstrmAISearch")
    if search is None:
        print("응답에 lstrmAISearch 항목이 없습니다. 원본 응답:")
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return []

    # 이 target은 다른 target들과 달리 총 개수 필드명이 "검색결과개수"임(실제 호출로 확인).
    print(f"\n총 검색 결과: {search.get('검색결과개수', '?')}건\n")
    terms = _as_list(search.get("법령용어"))
    if not terms:
        print("검색 결과가 없습니다.")
        return []

    items = []
    for i, term in enumerate(terms, start=1):
        name = term.get("법령용어명", "")
        homonym = "있음" if term.get("동음이의어존재여부") == "Y" else "없음"
        note = term.get("비고", "")
        print(f"[{i}] {name}  (동음이의어: {homonym}{f' | 비고: {note}' if note else ''})")
        items.append((name, "", term))
    return items


_MST_RE = re.compile(r"[?&]MST=(\d+)")


def _extract_mst(link: str) -> str:
    m = _MST_RE.search(link or "")
    return m.group(1) if m else ""


def get_lstrm_rlt(mst: str) -> dict:
    return _request(DETAIL_URL, {"OC": OC, "target": "lstrmRlt", "type": "JSON", "MST": mst})


def get_lstrm_rlt_jo(mst: str) -> dict:
    return _request(DETAIL_URL, {"OC": OC, "target": "lstrmRltJo", "type": "JSON", "MST": mst})


def print_lstrmai_links(item: dict) -> None:
    """법령용어 조회는 별도 본문 API가 없는 대신, 목록 응답의 관계링크에 담긴
    MST 값으로 용어간/조문간 관계 조회 API(lstrmRlt/lstrmRltJo)를 직접 호출해서
    보여준다. (링크를 브라우저로 직접 열면 law.go.kr가 요구하는 Referer 헤더가
    없어 '사용자 정보 검증 실패' 에러가 나므로, 스크립트가 헤더를 붙여 대신 호출함)"""
    print()
    print(f"법령용어명: {item.get('법령용어명', '')}")
    print(f"동음이의어 존재여부: {item.get('동음이의어존재여부', '')}")
    if item.get("비고"):
        print(f"비고: {item.get('비고')}")

    mst = _extract_mst(item.get("용어간관계링크", "")) or _extract_mst(item.get("조문간관계링크", ""))
    if not mst:
        print("관계 조회에 필요한 MST 값을 찾지 못했습니다.")
        return

    try:
        rlt = get_lstrm_rlt(mst)
    except requests.RequestException as e:
        print(f"\n용어간 관계 조회 실패: {e}")
    else:
        related = _as_list(rlt.get("lstrmRltService", {}).get("법령용어", {}).get("연계용어"))
        print("\n[연계 일상용어]")
        if related:
            for rel in related:
                print(f"  - {rel.get('일상용어명', '')} ({rel.get('용어관계', '')})")
        else:
            print("  없음")

    try:
        rlt_jo = get_lstrm_rlt_jo(mst)
    except requests.RequestException as e:
        print(f"\n조문간 관계 조회 실패: {e}")
    else:
        laws = _as_list(rlt_jo.get("lstrmRltJoService", {}).get("법령용어", {}).get("연계법령"))
        print("\n[연계 조문]")
        if laws:
            for law in laws:
                jo_no = law.get("조번호", "").lstrip("0") or "0"
                content = _clean_text(law.get("조문내용", "")).split("\n")[0]
                if len(content) > 80:
                    content = content[:80] + "..."
                print(f"  - {law.get('법령명', '')} 제{jo_no}조: {content}")
        else:
            print("  없음")


# ===================== 공통 실행부 =====================
# mode="api"   : get_detail(id) 로 본문을 조회한 뒤 print_detail(data)로 출력
# mode="links" : 별도 API 호출 없이 목록에 포함된 raw 항목을 print_links(item)로 출력
#                (별표서식은 JSON 본문 API가 없기 때문)

CATEGORIES = {
    "1": {"label": "법령", "search": search_law, "print_list": print_law_list,
          "mode": "api", "get_detail": get_law_detail, "print_detail": print_law_detail},
    "2": {"label": "행정규칙", "search": search_admrul, "print_list": print_admrul_list,
          "mode": "api", "get_detail": get_admrul_detail, "print_detail": print_admrul_detail},
    "3": {"label": "자치법규", "search": search_ordin, "print_list": print_ordin_list,
          "mode": "api", "get_detail": get_ordin_detail, "print_detail": print_ordin_detail},
    "4": {"label": "법령 별표서식", "search": search_licbyl, "print_list": print_licbyl_list,
          "mode": "links", "print_links": print_byl_links},
    "5": {"label": "행정규칙 별표서식", "search": search_admbyl, "print_list": print_admbyl_list,
          "mode": "links", "print_links": print_byl_links},
    "6": {"label": "자치법규 별표서식", "search": search_ordinbyl, "print_list": print_ordinbyl_list,
          "mode": "links", "print_links": print_byl_links},
    "7": {"label": "법령용어", "search": search_lstrmai, "print_list": print_lstrmai_list,
          "mode": "links", "print_links": print_lstrmai_links},
}


def _read_input(prompt: str) -> str:
    # 일부 터미널(PowerShell 파이프 등)이 표준입력 맨 앞에 BOM을 붙이는 경우가 있어 제거.
    return input(prompt).strip().lstrip("﻿")


def main() -> None:
    global OC
    if not OC:
        OC = _read_input("API 인증값(OC)을 입력하세요: ")
    if not OC:
        print("API 인증값이 입력되지 않았습니다.")
        sys.exit(1)

    print("조회할 대상을 선택하세요")
    for key, cat in CATEGORIES.items():
        print(f"  {key}. {cat['label']}")
    choice = _read_input("번호 입력 (Enter: 1. 법령): ") or "1"
    if choice not in CATEGORIES:
        print("잘못된 선택입니다.")
        sys.exit(1)

    cat = CATEGORIES[choice]
    label = cat["label"]

    query = _read_input(f"{label} 검색어를 입력하세요: ")
    if not query:
        print("검색어가 입력되지 않았습니다.")
        sys.exit(1)

    try:
        data = cat["search"](query)
    except requests.RequestException as e:
        print(f"API 요청 중 오류가 발생했습니다: {e}")
        sys.exit(1)

    items = cat["print_list"](data)
    if not items:
        return

    result_label = "링크를" if cat["mode"] == "links" else "본문을"
    while True:
        selected = _read_input(
            f"\n{result_label} 조회할 {label}의 번호를 입력하세요 (Enter: 종료): "
        )
        if not selected:
            return
        if not selected.isdigit() or not (1 <= int(selected) <= len(items)):
            print(f"1~{len(items)} 사이의 번호를 입력해 주세요.")
            continue

        name, item_id, raw = items[int(selected) - 1]

        if cat["mode"] == "links":
            cat["print_links"](raw)
            continue

        if not item_id:
            print(f"'{name}'의 식별자를 확인할 수 없습니다.")
            continue

        try:
            detail = cat["get_detail"](item_id)
        except requests.RequestException as e:
            print(f"본문 조회 중 오류가 발생했습니다: {e}")
            continue

        cat["print_detail"](detail)


if __name__ == "__main__":
    main()
