"""
법제처 OPEN API 활용가이드(guideResult.do) 응답 확인용 단독 스크립트

https://open.law.go.kr/LSO/openApi/guideResult.do 가 어떤 식으로 내려오는지,
그리고 그 가이드에 적힌 요청 URL로 실제 API를 부르면 응답이 어떤 모양인지를
한 파일에서 확인하기 위한 테스트 코드다. 프로그램 본체와는 무관하며 아무것도
import 하지 않는다.

확인된 사실(실제 호출로 검증)
  - 가이드 목록 : https://open.law.go.kr/LSO/openApi/guideList.do
    페이지 안의 JS 함수 openApiGuide('htmlName') 호출로 각 API 가이드가 열린다.
    링크에 URL이 안 박혀 있어서 htmlName 값을 정규식으로 긁어와야 한다.
  - 가이드 본문 : guideResult.do?htmlName=<htmlName>
    원래는 POST(form)로 넘기지만 GET 쿼리스트링으로도 동일하게 200/HTML이 온다.
    htmlName 없이 부르면 "현행법령 목록 조회 API" 가이드가 기본으로 나온다.
  - 응답은 HTML(UTF-8). 응답 헤더의 charset 추정이 부실해서 utf-8로 고정 디코딩한다.
    본문은 <div class="guide_area"> 안에 h3(API 이름) / dt(섹션 제목) /
    table.blist.guide(요청변수·출력필드 표) 구조로 들어 있다.
  - 섹션 구성은 API마다 다르다. 표 개수도 다르고 "샘플 URL"은 dt 제목 없이
    표 안에 들어있는 API도 있어서, dt/table을 나온 순서대로 훑는 방식으로 뽑는다.

사용법
    python test_open_api_guide.py                    # 대화형(목록 -> 선택)
    python test_open_api_guide.py list               # 가이드 전체 목록
    python test_open_api_guide.py list 행정규칙       # 제목 키워드로 필터
    python test_open_api_guide.py guide admrulListGuide
    python test_open_api_guide.py raw  admrulListGuide --out guide.html
    python test_open_api_guide.py call admrulListGuide query=주차 display=3
    python test_open_api_guide.py call admrulListGuide --type XML

옵션
    --oc <인증키>   기본값은 환경변수 LAW_API_OC, 없으면 "test"(샘플 계정)
    --type <형식>   JSON(기본) / XML / HTML
    --out <파일>    raw / call 결과를 파일로 저장
    --full          응답을 자르지 않고 전부 출력

준비물
    pip install requests
"""

import html
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

import requests

BASE = "https://open.law.go.kr/LSO/openApi"
GUIDE_LIST_URL = BASE + "/guideList.do"
GUIDE_URL = BASE + "/guideResult.do"

# 법제처는 Referer/User-Agent 없는 요청을 막는 경우가 있어 항상 같이 보낸다.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Python requests",
    "Referer": "https://open.law.go.kr/LSO/openApi/guideList.do",
}

PREVIEW_LIMIT = 4000  # --full 이 없을 때 응답 본문 출력 상한(문자)


# ---------------------------------------------------------------- 공통 유틸


def _get_html(url, params=None):
    res = requests.get(url, params=params, headers=HEADERS, timeout=20)
    res.raise_for_status()
    # 응답 헤더의 charset을 신뢰할 수 없어(EUC-KR로 잘못 추정됨) 실제 바이트에 맞춰 고정.
    res.encoding = "utf-8"
    return res.text


def _strip_tags(fragment):
    """HTML 조각을 한 줄 텍스트로. <br>은 ' / '로 살려둔다."""
    text = re.sub(r"(?is)<br\s*/?>", " / ", fragment)
    text = re.sub(r"(?is)<script.*?</script>", "", text)
    text = re.sub(r"(?is)<style.*?</style>", "", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _cut(text, limit):
    if limit is None or len(text) <= limit:
        return text
    return text[:limit] + "\n... (이하 {:,}자 생략, --full 로 전체 출력)".format(len(text) - limit)


# ---------------------------------------------------------- 가이드 목록/본문


def fetch_guide_list():
    """guideList.do 에서 (htmlName, 제목) 목록을 뽑는다."""
    page = _get_html(GUIDE_LIST_URL)
    items = []
    seen = set()
    pattern = r"openApiGuide\(\s*['\"]([^'\"]+)['\"]\s*\)[^>]*>(.*?)</a>"
    for match in re.finditer(pattern, page, re.S):
        name = match.group(1).strip()
        title = _strip_tags(match.group(2))
        if name and name not in seen:
            seen.add(name)
            items.append((name, title))
    return items


def fetch_guide_html(html_name=None):
    """guideResult.do 원본 HTML. html_name 이 None이면 기본 가이드."""
    params = {"htmlName": html_name} if html_name else None
    return _get_html(GUIDE_URL, params)


def _parse_table(table_html):
    """table 조각을 (헤더 리스트, 행 리스트)로."""
    headers = [_strip_tags(c) for c in re.findall(r"(?is)<th[^>]*>(.*?)</th>", table_html)]
    rows = []
    for row_html in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", table_html):
        cells = [_strip_tags(c) for c in re.findall(r"(?is)<td[^>]*>(.*?)</td>", row_html)]
        if cells:
            rows.append(cells)
    return headers, rows


def parse_guide(page):
    """guideResult.do HTML을 구조화한다.

    반환: {"title", "request_url", "sections": [{"title", "tables", "urls"}]}
    섹션 구성이 API마다 달라서 dt(제목)와 표를 나온 순서 그대로 담는다.
    """
    start = page.find('<div class="guide_area"')
    body = page[start:] if start >= 0 else page

    title_match = re.search(r"(?is)<h3[^>]*>(.*?)</h3>", body)
    title = _strip_tags(title_match.group(1)) if title_match else "(제목 없음)"

    request_url = ""
    url_match = re.search(r"요청\s*URL\s*[:：]\s*([^\s<]+)", _strip_tags(body[:4000]))
    if url_match:
        request_url = url_match.group(1)

    sections = []
    current = None
    token = re.compile(
        r"(?is)<dt[^>]*>(.*?)</dt>"
        r"|<table[^>]*class=\"[^\"]*guide[^\"]*\"[^>]*>(.*?)</table>"
    )
    for match in token.finditer(body):
        if match.group(1) is not None:
            text = _strip_tags(match.group(1))
            if not text or text.startswith("- 요청 URL"):
                continue
            current = {"title": text, "tables": [], "urls": []}
            sections.append(current)
        else:
            headers, rows = _parse_table(match.group(2))
            if current is None:
                current = {"title": "(표)", "tables": [], "urls": []}
                sections.append(current)
            current["tables"].append((headers, rows))

    # 샘플 URL은 표가 아니라 <dd> 안 평문으로 들어있어서 따로 긁는다.
    for dd_html in re.findall(r"(?is)<dd[^>]*>(.*?)</dd>", body):
        if "<table" in dd_html.lower():
            continue
        urls = re.findall(r"https?://[^\s<\"']+", html.unescape(dd_html))
        if not urls or not sections:
            continue
        for section in reversed(sections):
            if not section["tables"]:
                section["urls"].extend(urls)
                break
        else:
            sections[-1]["urls"].extend(urls)

    return {"title": title, "request_url": request_url, "sections": sections}


def _print_table(headers, rows):
    if not rows:
        return
    width = max(len(headers), max(len(r) for r in rows))
    norm = [(headers + [""] * width)[:width]] if headers else []
    norm += [(r + [""] * width)[:width] for r in rows]
    widths = [min(60, max(len(r[i]) for r in norm)) for i in range(width)]

    def line(cells):
        # 정렬용으로만 폭을 맞추고, 샘플 URL처럼 긴 값은 잘라내지 않는다.
        return " | ".join(c.ljust(widths[i]) for i, c in enumerate(cells)).rstrip()

    if headers:
        print("    " + line(norm[0]))
        print("    " + "-+-".join("-" * w for w in widths))
        norm = norm[1:]
    for row in norm:
        print("    " + line(row))


def print_guide(guide, html_name):
    print("=" * 78)
    print("[가이드] " + guide["title"])
    print("  htmlName    : " + (html_name or "(기본값 - 현행법령 목록 조회)"))
    print("  가이드 주소 : {}?htmlName={}".format(GUIDE_URL, html_name or ""))
    if guide["request_url"]:
        print("  요청 URL    : " + guide["request_url"])
    print("=" * 78)
    for section in guide["sections"]:
        print("\n[{}]".format(section["title"]))
        for headers, rows in section["tables"]:
            _print_table(headers, rows)
            print()
        for url in section["urls"]:
            print("    " + url)


# ------------------------------------------------------------- 실제 API 호출


def _summarize_json(data, indent=0, depth=0, max_depth=4):
    pad = "  " * indent
    if depth >= max_depth:
        print(pad + "...")
        return
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, dict):
                print("{}{}: dict({}키)".format(pad, key, len(value)))
                _summarize_json(value, indent + 1, depth + 1, max_depth)
            elif isinstance(value, list):
                print("{}{}: list({}건)".format(pad, key, len(value)))
                if value:
                    _summarize_json(value[0], indent + 1, depth + 1, max_depth)
            else:
                shown = str(value).replace("\n", " ")
                print("{}{}: {}".format(pad, key, shown[:70]))
    elif isinstance(data, list):
        print("{}list({}건)".format(pad, len(data)))
        if data:
            _summarize_json(data[0], indent + 1, depth + 1, max_depth)
    else:
        print(pad + str(data)[:70])


def _summarize_xml(text):
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        print("  XML 파싱 실패: {}".format(exc))
        return

    def walk(node, indent=0, depth=0):
        if depth > 3:
            return
        pad = "  " * indent
        value = (node.text or "").strip().replace("\n", " ")
        print("{}<{}>{}".format(pad, node.tag, (" " + value[:60]) if value else ""))
        seen = {}
        for child in node:
            seen[child.tag] = seen.get(child.tag, 0) + 1
            if seen[child.tag] <= 1:  # 같은 태그 반복은 첫 건만 펼친다
                walk(child, indent + 1, depth + 1)
        for tag, count in seen.items():
            if count > 1:
                print("{}  <{}> x {}건".format(pad, tag, count))

    walk(root)


def call_api(request_url, extra, oc, out_type, out_path=None, full=False):
    """가이드에 적힌 요청 URL을 그대로 호출해서 응답 모양을 보여준다."""
    if not request_url:
        print("요청 URL을 가이드에서 찾지 못했습니다.")
        return

    # 가이드의 요청 URL에는 target=... 이 이미 붙어 있다. 그걸 살리고 나머지를 합친다.
    base, _, query = request_url.partition("?")
    base = base.replace("http://", "https://")
    params = {}
    for pair in query.split("&"):
        if "=" in pair:
            key, value = pair.split("=", 1)
            params[key] = value
    params["OC"] = oc
    params["type"] = out_type
    params.update(extra)

    print("=" * 78)
    print("[실제 호출]")
    print("  URL    : " + base)
    print("  params : {}".format(params))
    try:
        res = requests.get(base, params=params, headers=HEADERS, timeout=20)
    except requests.RequestException as exc:
        print("  요청 실패: {}".format(exc))
        return
    print("  최종 URL     : " + res.url)
    print("  status       : {}".format(res.status_code))
    print("  Content-Type : {}".format(res.headers.get("Content-Type")))
    print("  응답 크기    : {:,} bytes".format(len(res.content)))
    print("=" * 78)

    text = res.text
    ctype = (res.headers.get("Content-Type") or "").lower()
    upper = out_type.upper()

    if upper == "JSON" or "json" in ctype:
        try:
            data = res.json()
        except ValueError:
            print("!! type=JSON 으로 요청했지만 JSON이 아닌 응답이 왔습니다"
                  " (인증키 오류이거나 해당 API가 JSON 미지원일 수 있음).")
            print(_cut(text, None if full else PREVIEW_LIMIT))
        else:
            print("\n[응답 구조 요약]")
            _summarize_json(data)
            print("\n[응답 본문]")
            pretty = json.dumps(data, ensure_ascii=False, indent=2)
            print(_cut(pretty, None if full else PREVIEW_LIMIT))
            text = pretty
    elif upper == "XML" or "xml" in ctype:
        print("\n[응답 구조 요약]")
        _summarize_xml(text)
        print("\n[응답 본문]")
        print(_cut(text, None if full else PREVIEW_LIMIT))
    else:
        print("\n[응답 본문(HTML)]")
        print(_cut(text, None if full else PREVIEW_LIMIT))

    if out_path:
        with open(out_path, "w", encoding="utf-8") as fp:
            fp.write(text)
        print("\n저장: " + out_path)


# ----------------------------------------------------------------- CLI 처리


def _parse_argv(argv):
    """[명령, 인자], --옵션, key=value 추가 파라미터로 나눈다."""
    positional, options, extra = [], {}, {}
    index = 0
    while index < len(argv):
        token = argv[index]
        if token.startswith("--"):
            key = token[2:]
            if key == "full":
                options["full"] = True
            else:
                index += 1
                options[key] = argv[index] if index < len(argv) else ""
        elif "=" in token and not token.startswith("-"):
            key, value = token.split("=", 1)
            extra[key] = value
        else:
            positional.append(token)
        index += 1
    return positional, options, extra


def _print_list(items, keyword=""):
    for number, (name, title) in enumerate(items, 1):
        if keyword and keyword not in title and keyword not in name:
            continue
        print("{:3d}. {}".format(number, title))
        print("     htmlName = " + name)


def _resolve(items, token):
    """번호 또는 htmlName 으로 항목을 찾는다."""
    if token.isdigit():
        index = int(token) - 1
        if 0 <= index < len(items):
            return items[index][0]
        return None
    return token


def interactive():
    items = fetch_guide_list()
    print("가이드 {}건\n".format(len(items)))
    _print_list(items)
    print()
    token = input("번호 또는 htmlName (엔터=기본 가이드): ").strip()
    html_name = None  # 엔터만 치면 기본 가이드(현행법령 목록 조회)
    if token:
        html_name = _resolve(items, token)
        if html_name is None:
            print("목록에서 찾지 못했습니다.")
            return
    guide = parse_guide(fetch_guide_html(html_name))
    print()
    print_guide(guide, html_name)

    if not guide["request_url"]:
        return
    print()
    if input("이 API를 실제로 호출해볼까요? (y/N): ").strip().lower() != "y":
        return
    oc = os.environ.get("LAW_API_OC", "").strip()
    if not oc:
        oc = input("OC 인증키(엔터=test): ").strip() or "test"
    out_type = input("type (기본 JSON): ").strip().upper() or "JSON"
    raw_extra = input("추가 파라미터 (예: query=주차 display=3): ").strip()
    extra = dict(pair.split("=", 1) for pair in raw_extra.split() if "=" in pair)
    print()
    call_api(guide["request_url"], extra, oc, out_type)


def main(argv):
    positional, options, extra = _parse_argv(argv)
    command = positional[0] if positional else ""
    target = positional[1] if len(positional) > 1 else ""
    oc = options.get("oc") or os.environ.get("LAW_API_OC", "").strip() or "test"
    out_type = (options.get("type") or "JSON").upper()
    out_path = options.get("out")
    full = bool(options.get("full"))

    if not command:
        interactive()
        return 0

    if command == "list":
        items = fetch_guide_list()
        print("가이드 {}건 (guideList.do)\n".format(len(items)))
        _print_list(items, target)
        return 0

    if command in ("guide", "raw", "call"):
        items = fetch_guide_list() if target.isdigit() else []
        html_name = _resolve(items, target) if target else None
        if target and html_name is None:
            print("목록에서 {} 번을 찾지 못했습니다.".format(target))
            return 1

        page = fetch_guide_html(html_name)

        if command == "raw":
            if out_path:
                with open(out_path, "w", encoding="utf-8") as fp:
                    fp.write(page)
                print("저장: {} ({:,}자)".format(out_path, len(page)))
            else:
                print(_cut(page, None if full else PREVIEW_LIMIT))
            return 0

        guide = parse_guide(page)
        print_guide(guide, html_name)

        if command == "call":
            print()
            call_api(guide["request_url"], extra, oc, out_type, out_path, full)
        return 0

    print(__doc__)
    return 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        print("\n중단")
    except requests.RequestException as error:
        print("요청 실패: {}".format(error))
        sys.exit(1)
