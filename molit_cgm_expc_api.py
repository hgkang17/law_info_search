"""
국가법령정보 공동활용 API 조회 모듈

law.go.kr DRF Open API를 이용해
  1) 목록 조회 (lawSearch.do?target=molitCgmExpc)
  2) 본문 조회 (lawService.do?target=molitCgmExpc)
를 순서대로 호출하는 예제입니다.

사용 전 준비물
---------------
1. https://open.law.go.kr 에서 발급받은 OC 인증키 (본인이 이미 발급받아 사용 중인 그 키)
2. pip install requests

주의
----
- 이 스크립트는 data.go.kr에 게시된 "법제처_국토교통부 법령해석 목록/본문 조회 API" 설명(캡처로 공유해주신
  요청 URL·파라미터 표)을 근거로 작성했습니다.
- 본문 조회 API(lawService.do)의 정확한 파라미터명(ID vs itmno 등)과 응답 필드는 목록 조회처럼
  화면으로 직접 확인하지 못했습니다(law.go.kr/data.go.kr가 이 환경의 웹 조회 도구로는 robots.txt에
  막혀 접근이 안 됐습니다). 같은 계열의 다른 target(예: expc)이 lawService.do?target=xxx&ID=일련번호
  패턴을 쓰는 것을 참고해 동일한 패턴으로 구현해 두었으니, 실제 호출 결과가 다르면 아래
  DETAIL_ID_PARAM 값을 데이터포털 API 문서(15140240)에 나온 실제 파라미터명으로 바꿔주세요.
- type은 XML로 고정해서 파싱합니다. JSON을 원하면 type="JSON"으로 바꾸고 파싱부만 json.loads로
  교체하면 됩니다.
"""

import base64
import html
import re
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Iterable, Optional

import requests

BASE_URL = "https://www.law.go.kr/DRF"
LIST_ENDPOINT = f"{BASE_URL}/lawSearch.do"
DETAIL_ENDPOINT = f"{BASE_URL}/lawService.do"
FILE_DOWNLOAD_ENDPOINT = "https://www.law.go.kr/LSW/flDownload.do"
TARGET = "molitCgmExpc"  # 국토교통부 법령해석(중앙부처 1차해석)


@dataclass(frozen=True)
class AgencyConfig:
    """중앙부처 1차 법령해석 API 대상 기관."""

    name: str
    target: str
    detail_available: bool = True


AGENCIES = (
    AgencyConfig("고용노동부", "moelCgmExpc"),
    AgencyConfig("국토교통부", "molitCgmExpc"),
    AgencyConfig("재정경제부", "moefCgmExpc", False),
    AgencyConfig("해양수산부", "mofCgmExpc"),
    AgencyConfig("행정안전부", "moisCgmExpc"),
    AgencyConfig("기후에너지환경부", "meCgmExpc"),
    AgencyConfig("관세청", "kcsCgmExpc"),
    AgencyConfig("국세청", "ntsCgmExpc", False),
    AgencyConfig("교육부", "moeCgmExpc"),
    AgencyConfig("과학기술정보통신부", "msitCgmExpc"),
    AgencyConfig("국가보훈부", "mpvaCgmExpc"),
    AgencyConfig("국방부", "mndCgmExpc"),
    AgencyConfig("농림축산식품부", "mafraCgmExpc"),
    AgencyConfig("문화체육관광부", "mcstCgmExpc"),
    AgencyConfig("법무부", "mojCgmExpc"),
    AgencyConfig("보건복지부", "mohwCgmExpc"),
    AgencyConfig("산업통상부", "motieCgmExpc"),
    AgencyConfig("성평등가족부", "mogefCgmExpc"),
    AgencyConfig("외교부", "mofaCgmExpc"),
    AgencyConfig("중소벤처기업부", "mssCgmExpc"),
    AgencyConfig("통일부", "mouCgmExpc"),
    AgencyConfig("법제처", "molegCgmExpc"),
    AgencyConfig("식품의약품안전처", "mfdsCgmExpc"),
    AgencyConfig("인사혁신처", "mpmCgmExpc"),
    AgencyConfig("기상청", "kmaCgmExpc"),
    AgencyConfig("국가유산청", "khsCgmExpc"),
    AgencyConfig("농촌진흥청", "rdaCgmExpc"),
    AgencyConfig("경찰청", "npaCgmExpc"),
    AgencyConfig("방위사업청", "dapaCgmExpc"),
    AgencyConfig("병무청", "mmaCgmExpc"),
    AgencyConfig("산림청", "kfsCgmExpc"),
    AgencyConfig("소방청", "nfaCgmExpc"),
    AgencyConfig("재외동포청", "okaCgmExpc"),
    AgencyConfig("조달청", "ppsCgmExpc"),
    AgencyConfig("질병관리청", "kdcaCgmExpc"),
    AgencyConfig("국가데이터처", "kostatCgmExpc"),
    AgencyConfig("지식재산처", "kipoCgmExpc"),
    AgencyConfig("해양경찰청", "kcgCgmExpc"),
    AgencyConfig("행정중심복합도시건설청", "naaccCgmExpc"),
)
AGENCY_BY_TARGET = {agency.target: agency for agency in AGENCIES}

# 법제처 API는 Referer가 없는 요청을 사용자 검증 실패로 처리할 수 있습니다.
REQUEST_HEADERS = {
    "Referer": "https://www.law.go.kr/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Python requests",
}

# 본문 조회 API가 실제로 요구하는 ID 파라미터명. 문서 확인 후 다르면 이 값만 바꾸면 됩니다.
DETAIL_ID_PARAM = "ID"

_RETRY_STATUSES = {404, 429, 503, 504}
_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 0.3

# 행정규칙 본문에는 표가 이미지 ID만 가진 태그로 섞여 내려온다.
# 예: ``<img id="158685505"></img>``. 국가법령정보센터 본문 화면도
# 이 ID를 ``flDownload.do?flSeq=...``로 바꿔 표시한다.
_ADMIN_RULE_IMAGE_PATTERN = re.compile(
    r"(?is)<img\b[^>]*\bid\s*=\s*[\"']?(\d+)[\"']?[^>]*>\s*(?:</img\s*>)?"
)
ADMIN_RULE_IMAGES_KEY = "_law_go_kr_images"
_MAX_ADMIN_RULE_IMAGE_BYTES = 10 * 1024 * 1024


def _looks_like_html_error(text: str) -> bool:
    head = (text or "").lstrip()[:180].casefold()
    return head.startswith("<!doctype html") or head.startswith("<html")


def _request(
    url: str,
    params: dict,
    *,
    timeout: int,
    expect_json: bool = False,
) -> requests.Response:
    """법제처 DRF 호출. 잠깐의 404·빈 본문·HTML 오류 페이지는 재시도한다.

    재시도가 끝난 뒤에도 HTML이면 장애로 보고, 빈 JSON `{}`는 호출 쪽이
    '없음'으로 읽게 그대로 돌려준다.
    """
    last_error: Exception | None = None
    for attempt in range(_RETRY_ATTEMPTS + 1):
        try:
            response = requests.get(
                url,
                params=params,
                headers=REQUEST_HEADERS,
                timeout=timeout,
            )
            if response.status_code in _RETRY_STATUSES and attempt < _RETRY_ATTEMPTS:
                time.sleep(_RETRY_BASE_DELAY * (2 ** attempt))
                continue
            response.raise_for_status()
            response.encoding = "utf-8"
            body = response.text or ""
            if (not body.strip() or (expect_json and _looks_like_html_error(body))) and (
                attempt < _RETRY_ATTEMPTS
            ):
                time.sleep(_RETRY_BASE_DELAY * (2 ** attempt))
                continue
            if expect_json and _looks_like_html_error(body):
                raise ValueError(
                    "법제처가 HTML 오류 페이지를 돌려줬습니다. 잠시 후 다시 시도하세요."
                )
            return response
        except (requests.RequestException, ValueError) as error:
            last_error = error
            if attempt < _RETRY_ATTEMPTS:
                time.sleep(_RETRY_BASE_DELAY * (2 ** attempt))
                continue
            raise
    if last_error:
        raise last_error
    raise RuntimeError("법제처 요청이 비어 있습니다.")

# ===== 아래 두 값을 본인 것으로 직접 채워 넣으세요 =====
OC_KEY = ""  # GUI의 API 인증값 입력칸 또는 실행 인자로 입력
# ====================================================


def search_list(
    oc: str,
    query: Optional[str] = None,
    search: int = 1,
    display: int = 20,
    page: int = 1,
    inq: Optional[int] = None,
    rpl: Optional[int] = None,
    gana: Optional[str] = None,
    itmno: Optional[int] = None,
    expl_yd: Optional[str] = None,
    sort: Optional[str] = None,
    nb: Optional[str] = None,
    target: str = TARGET,
) -> ET.Element:
    """지정 기관의 법령해석 목록 조회.

    Parameters
    ----------
    oc : str
        발급받은 OC 인증값
    query : str
        검색할 문자열
    search : int
        검색범위. 1=법령해석명(기본), 2=본문검색
    display : int
        결과 개수 (기본 20, 최대 100)
    page : int
        결과 페이지 (기본 1)
    inq : int
        질의기관코드
    rpl : int
        해석기관코드
    gana : str
        사전식 검색 (ga, na, da ... 등)
    itmno : int
        안건번호 (지정 시 query는 무시됨)
    expl_yd : str
        해석일자 검색 범위, "20090101~20090130" 형식
    sort : str
        정렬옵션 (lasc/ldes/dasc/ddes/nasc/ndes)
    nb : str
        사건번호 전방 일치 검색 (판례 target=prec). 지정 시 query와 함께 쓸 수 있다.

    Returns
    -------
    xml.etree.ElementTree.Element
        파싱된 XML 루트 엘리먼트
    """
    params = {
        "OC": oc,
        "target": target,
        "type": "XML",
        "search": search,
        "display": display,
        "page": page,
    }
    if query:
        params["query"] = query
    if inq is not None:
        params["inq"] = inq
    if rpl is not None:
        params["rpl"] = rpl
    if gana:
        params["gana"] = gana
    if itmno is not None:
        params["itmno"] = itmno
        params.pop("query", None)  # 안건번호 지정 시 query 무시된다고 문서에 명시됨
    if expl_yd:
        params["explYd"] = expl_yd
    if sort:
        params["sort"] = sort
    if nb:
        params["nb"] = nb

    resp = _request(LIST_ENDPOINT, params, timeout=10)
    return ET.fromstring(resp.text)


def search_agencies(
    oc: str,
    agencies: Iterable[AgencyConfig],
    *,
    query: Optional[str] = None,
    search: int = 1,
    display: int = 100,
    page: int = 1,
) -> tuple[
    list[tuple[AgencyConfig, ET.Element]],
    list[tuple[AgencyConfig, str]],
]:
    """여러 기관을 병렬 조회하고 기관 순서대로 결과와 오류를 반환."""
    agency_list = tuple(agencies)
    if not agency_list:
        return [], []

    roots: dict[str, ET.Element] = {}
    errors: dict[str, str] = {}

    def fetch(agency: AgencyConfig) -> ET.Element:
        return search_list(
            oc,
            query=query,
            search=search,
            display=display,
            page=page,
            target=agency.target,
        )

    with ThreadPoolExecutor(max_workers=min(12, len(agency_list))) as executor:
        futures = {executor.submit(fetch, agency): agency for agency in agency_list}
        for future in as_completed(futures):
            agency = futures[future]
            try:
                roots[agency.target] = future.result()
            except Exception as exc:
                errors[agency.target] = str(exc)

    return (
        [(agency, roots[agency.target]) for agency in agency_list if agency.target in roots],
        [(agency, errors[agency.target]) for agency in agency_list if agency.target in errors],
    )


def search_agency_scopes(
    oc: str,
    requests: Iterable[tuple[AgencyConfig, int]],
    *,
    query: Optional[str] = None,
    display: int = 100,
    page: int = 1,
) -> tuple[
    list[tuple[AgencyConfig, ET.Element]],
    list[tuple[AgencyConfig, str]],
]:
    """같은 기관의 여러 검색 범위를 병렬 조회한다.

    ``search_agencies``는 기관 target을 결과 키로 사용하므로 같은 기관을
    ``search=0``과 ``search=1``로 동시에 조회하면 한쪽이 덮인다. 통합검색의
    연관법령처럼 동일 target의 여러 범위를 모두 보존해야 할 때 사용한다.
    """
    request_list = tuple(requests)
    if not request_list:
        return [], []

    roots: dict[int, ET.Element] = {}
    errors: dict[int, str] = {}

    def fetch(agency: AgencyConfig, search: int) -> ET.Element:
        return search_list(
            oc,
            query=query,
            search=search,
            display=display,
            page=page,
            target=agency.target,
        )

    with ThreadPoolExecutor(max_workers=min(12, len(request_list))) as executor:
        futures = {
            executor.submit(fetch, agency, search): (index, agency)
            for index, (agency, search) in enumerate(request_list)
        }
        for future in as_completed(futures):
            index, _agency = futures[future]
            try:
                roots[index] = future.result()
            except Exception as exc:
                errors[index] = str(exc)

    return (
        [
            (agency, roots[index])
            for index, (agency, _search) in enumerate(request_list)
            if index in roots
        ],
        [
            (agency, errors[index])
            for index, (agency, _search) in enumerate(request_list)
            if index in errors
        ],
    )


def search_resource(
    oc: str,
    target: str,
    query: str,
    *,
    search_scope: int = 1,
    display: int = 100,
    page: int = 1,
    nw: str = "",
) -> dict:
    """법령·행정규칙·자치법규 및 별표·서식 목록을 JSON으로 조회."""
    params = {
        "OC": oc,
        "target": target,
        "type": "JSON",
        "search": search_scope,
        "query": query,
        "display": display,
        "page": page,
    }
    if nw:
        params["nw"] = nw
    resp = _request(
        LIST_ENDPOINT,
        params,
        timeout=15,
        expect_json=True,
    )
    return resp.json()


def get_resource_detail(
    oc: str,
    target: str,
    item_id: str,
    *,
    id_param: str = "ID",
) -> dict:
    """법령·행정규칙·자치법규 본문을 JSON으로 조회."""
    resp = _request(
        DETAIL_ENDPOINT,
        {
            "OC": oc,
            "target": target,
            "type": "JSON",
            id_param: item_id,
        },
        timeout=20,
        expect_json=True,
    )
    return resp.json()


def attach_admin_rule_images(payload: dict) -> dict:
    """행정규칙 본문의 이미지 ID를 검증된 data URI로 붙인다.

    화면 렌더링용 조회에서만 호출한다. 이미지 하나가 일시적으로 실패해도
    본문 전체를 막지 않고, 받은 이미지만 붙여 텍스트는 계속 표시한다.
    """
    service = payload.get("AdmRulService")
    if not isinstance(service, dict):
        return payload

    def text_values(value: object):
        if isinstance(value, str):
            yield value
        elif isinstance(value, list):
            for item in value:
                yield from text_values(item)
        elif isinstance(value, dict):
            for item in value.values():
                yield from text_values(item)

    image_ids: list[str] = []
    for field in ("조문내용", "조문", "부칙"):
        for value in text_values(service.get(field)):
            for image_id in _ADMIN_RULE_IMAGE_PATTERN.findall(
                html.unescape(value)
            ):
                if image_id not in image_ids:
                    image_ids.append(image_id)
    if not image_ids:
        return payload

    def download(image_id: str) -> tuple[str, str]:
        response = _request(
            FILE_DOWNLOAD_ENDPOINT,
            {"flSeq": image_id},
            timeout=20,
        )
        content = response.content
        content_type = str(response.headers.get("Content-Type") or "")
        mime_type = content_type.split(";", 1)[0].strip().casefold()
        if not mime_type.startswith("image/"):
            raise ValueError("법제처 이미지 응답 형식이 올바르지 않습니다.")
        if not content or len(content) > _MAX_ADMIN_RULE_IMAGE_BYTES:
            raise ValueError("법제처 이미지 크기가 허용 범위를 벗어났습니다.")
        encoded = base64.b64encode(content).decode("ascii")
        return image_id, f"data:{mime_type};base64,{encoded}"

    embedded: dict[str, str] = {}
    worker_count = min(4, len(image_ids))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(download, image_id): image_id
            for image_id in image_ids
        }
        for future in as_completed(futures):
            try:
                image_id, data_uri = future.result()
            except (OSError, ValueError, requests.RequestException):
                continue
            embedded[image_id] = data_uri
    if embedded:
        payload[ADMIN_RULE_IMAGES_KEY] = embedded
    return payload


def get_law_article(
    oc: str,
    item_id: str,
    jo: str,
    *,
    hang: str = "",
    ho: str = "",
    mok: str = "",
) -> dict:
    """현행법령(시행일 기준)의 특정 조·항·호·목을 JSON으로 조회."""
    params = {
        "OC": oc,
        "target": "eflawjosub",
        "type": "JSON",
        "ID": item_id,
        "JO": jo,
    }
    for key, value in (("HANG", hang), ("HO", ho), ("MOK", mok)):
        if value:
            params[key] = value
    resp = _request(DETAIL_ENDPOINT, params, timeout=20, expect_json=True)
    return resp.json()


def get_three_stage_comparison(
    oc: str,
    item_id: str,
    *,
    comparison_kind: int = 2,
) -> dict:
    """법률·시행령·시행규칙 3단비교 자료를 JSON으로 조회.

    comparison_kind는 법제처 API 정의에 따라 1=인용조문,
    2=위임조문이며 본문의 3단비교 버튼은 위임조문을 사용한다.
    """
    resp = _request(
        DETAIL_ENDPOINT,
        {
            "OC": oc,
            "target": "thdCmp",
            "type": "JSON",
            "knd": comparison_kind,
            "ID": item_id,
        },
        timeout=30,
        expect_json=True,
    )
    return resp.json()


def _has_law_node(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    if isinstance(payload.get("법령"), dict):
        return True
    return any(
        isinstance(value, dict) and "법령" in value for value in payload.values()
    )


def get_historical_law(
    oc: str,
    item_id: str,
    *,
    date: str,
    jo: str = "",
    mst: str = "",
) -> dict:
    """지정한 시행일의 법령 본문을 JSON으로 조회한다(행위시법).

    eflaw는 날짜(efYd) 없이 MST만 주면 빈 응답이 오는 경우가 있어
    시행일을 반드시 붙인다. 빈 본문을 현행본으로 바꾸지 않는다.
    연혁 버전은 법령ID보다 법령일련번호(MST)가 그 공포본을 가리킨다.
    """
    params = {
        "OC": oc,
        "target": "eflaw",
        "type": "JSON",
        "efYd": date,
    }
    if mst:
        params["MST"] = mst
    else:
        params["ID"] = item_id
    if jo:
        params["JO"] = jo
    resp = _request(DETAIL_ENDPOINT, params, timeout=20, expect_json=True)
    payload = resp.json()
    return payload if isinstance(payload, dict) else {}


def get_old_and_new(oc: str, item_id: str) -> ET.Element:
    """신구법 대조표를 XML로 조회한다."""
    resp = _request(
        DETAIL_ENDPOINT,
        {
            "OC": oc,
            "target": "oldAndNew",
            "type": "XML",
            "ID": item_id,
        },
        timeout=30,
    )
    return ET.fromstring(resp.text)


def get_article_history(
    oc: str,
    item_id: str,
    jo: str,
    *,
    display: int = 20,
) -> dict:
    """특정 조의 일자별 개정 이력을 JSON으로 조회한다."""
    resp = _request(
        LIST_ENDPOINT,
        {
            "OC": oc,
            "target": "lsJoHstInf",
            "type": "JSON",
            "ID": item_id,
            "JO": jo,
            "display": display,
        },
        timeout=20,
        expect_json=True,
    )
    payload = resp.json()
    return payload if isinstance(payload, dict) else {}


def print_list(root: ET.Element) -> list:
    """목록 조회 결과를 출력하고, (법령해석일련번호, 안건명) 리스트를 반환."""
    items = []

    result_code = (root.findtext("resultCode") or "").strip()
    result_msg = (root.findtext("resultMsg") or "").strip()
    total_count = (root.findtext("totalCnt") or "0").strip()
    if result_code and result_code != "00":
        print(f"조회 실패: {result_code} {result_msg}")
        return items

    print(f"총 {total_count}건 중 현재 페이지 결과:\n")

    for node in root.iter():
        if node.tag.lower() != "cgmexpc" or "id" not in node.attrib:
            continue

        item_id = (node.findtext("법령해석일련번호") or "").strip()
        title = (node.findtext("안건명") or "").strip()
        case_number = (node.findtext("안건번호") or "").strip()
        explanation_date = (node.findtext("해석일자") or "").strip()

        if item_id or title:
            items.append((item_id, title))
            metadata = " / ".join(
                value for value in (case_number, explanation_date) if value
            )
            suffix = f" ({metadata})" if metadata else ""
            print(f"[{item_id}] {title}{suffix}")

    if not items:
        print("결과를 찾지 못했거나, 응답 태그 구조가 예상과 달라 파싱하지 못했습니다.")
        print("아래 raw XML을 직접 확인해 print_list()의 태그 매칭 부분을 수정해 주세요:\n")
        print(ET.tostring(root, encoding="unicode")[:3000])
    return items


def get_detail(oc: str, item_id: str, target: str = TARGET) -> ET.Element:
    """법령해석일련번호로 지정 기관의 법령해석 본문 XML을 조회."""
    params = {
        "OC": oc,
        "target": target,
        "type": "XML",
        DETAIL_ID_PARAM: item_id,
    }
    resp = _request(DETAIL_ENDPOINT, params, timeout=10)
    return ET.fromstring(resp.text)


def _clean_text(value: str) -> str:
    """응답에 포함된 HTML 조각과 불필요한 공백을 정리."""
    value = html.unescape(value or "")
    value = re.sub(r"(?i)<br\s*/?>", "\n", value)
    value = re.sub(r"(?i)</(?:p|div|li|tr|h[1-6])>", "\n", value)
    value = re.sub(r"<[^>]+>", "", value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _find_text(root: ET.Element, tag: str) -> str:
    node = root.find(f".//{tag}")
    if node is None:
        return ""
    return _clean_text("".join(node.itertext()))


def iter_xml_items(root: ET.Element, item_tag: str):
    """목록 XML에서 항목 태그(prec, expc 등)만 고른다."""
    wanted = str(item_tag or "").rsplit("}", 1)[-1].lower()
    for node in root.iter():
        if str(node.tag).rsplit("}", 1)[-1].lower() == wanted:
            yield node


def xml_total_count(root: ET.Element) -> int:
    """검색 XML의 총건수. 없으면 0."""
    for tag in ("totalCnt", "totalcnt", "총건수"):
        text = _find_text(root, tag)
        if text.isdigit():
            return int(text)
    return 0


def print_detail(root: ET.Element) -> None:
    """본문 조회 XML을 사람이 읽기 쉬운 형식으로 출력."""
    result_code = _find_text(root, "resultCode")
    result_msg = _find_text(root, "resultMsg")
    if result_code and result_code != "00":
        print(f"본문 조회 실패: {result_code} {result_msg}")
        return

    item_id = _find_text(root, "법령해석일련번호")
    title = _find_text(root, "안건명")
    if not item_id and not title:
        message = _clean_text("".join(root.itertext()))
        print(f"본문 응답을 파싱하지 못했습니다: {message or '응답 내용 없음'}")
        return

    print("\n" + "=" * 72)
    print(f"{title or '국토교통부 법령해석'}")
    print("=" * 72)

    metadata_fields = (
        "법령해석일련번호",
        "안건번호",
        "해석일자",
        "해석기관명",
        "질의기관명",
        "대분류",
        "중분류",
        "소분류",
    )
    for field in metadata_fields:
        value = _find_text(root, field)
        if value:
            print(f"{field}: {value}")

    for field in ("질의요지", "회답", "이유", "관련법령"):
        value = _find_text(root, field)
        if value:
            print(f"\n[{field}]\n{value}")


def main():
    # CLI 실행 시 첫 번째 인자로 OC 인증값을 받는다.
    oc = sys.argv[1] if len(sys.argv) >= 2 else OC_KEY
    query = sys.argv[2].strip() if len(sys.argv) >= 3 else ""

    if not oc or oc == "여기에_발급받은_OC_인증키_입력":
        print("OC 인증값이 없습니다. 첫 번째 실행 인자로 입력해 주세요.")
        sys.exit(1)
    if not query:
        print("검색어가 없습니다. 두 번째 실행 인자로 입력해 주세요.")
        sys.exit(1)

    print(f"'{query}' 검색 중 (국토교통부 법령해석)...\n")
    root = search_list(oc, query=query, display=100)
    items = print_list(root)

    if not items:
        return

    valid_ids = {item_id for item_id, _ in items if item_id}
    while True:
        selected_id = input(
            "\n본문을 조회할 법령해석일련번호를 입력하세요 "
            "(Enter: 종료): "
        ).strip()
        if not selected_id:
            return
        if selected_id not in valid_ids:
            print("목록의 대괄호 안에 표시된 ID를 입력해 주세요.")
            continue

        detail_root = get_detail(oc, selected_id)
        print_detail(detail_root)


if __name__ == "__main__":
    main()
